from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
from sentence_transformers import SentenceTransformer
from groq import AsyncGroq
import json, asyncio, os
from dotenv import load_dotenv

from .. import crud, schemas, models
from ..database import get_db
from ..schemas import ChatRequest, RecipeRequest, UpdateMessageRequest
from .recipes import get_cached_recipes, recommend_recipes

load_dotenv()

router = APIRouter(
    prefix="/chat",
    tags=["Chat & Assistant"]
)

# ==========================================
# 1. AI & CLOUD CONFIGURATION
# ==========================================
# Groq handles the "Brain" (LLM)
groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

# SentenceTransformer handles local embedding (384-dimensions)
# This model is lightweight and runs efficiently on Render's CPU
embed_model = SentenceTransformer("all-MiniLM-L6-v2")

print("✅ Aduane Intelligence: Groq + SQLAlchemy pgvector Ready!")


# ==========================================
# 2. CHAT HISTORY ENDPOINTS
# ==========================================
@router.get("/history/{user_id}", response_model=List[schemas.Message])
def get_history(user_id: int, db: Session = Depends(get_db)):
    """Fetch all previous messages for a specific user."""
    print(f"📬 Fetching chat history for User ID: {user_id}")
    return crud.get_user_messages(db, user_id=user_id)

@router.post("/save/{user_id}", response_model=schemas.Message)
def save_message(user_id: int, message: schemas.MessageCreate, db: Session = Depends(get_db)):
    """Save a new user or AI message to the database."""
    print(f"💾 Saving new {message.sender} message for User ID: {user_id}")
    return crud.create_user_message(db=db, message=message, user_id=user_id)

@router.delete("/history/{user_id}")
def delete_chat_history(user_id: int, db: Session = Depends(get_db)):
    """Permanently delete all chat history for a specific user."""
    print(f"🗑️ Clearing chat history for User ID: {user_id}")
    try:
        db.query(models.Message).filter(models.Message.owner_id == user_id).delete()
        db.commit()
        return {"status": "success", "message": "Chat history cleared"}
    except Exception as e:
        db.rollback()
        print(f"🚨 Error deleting history: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete history")

@router.put("/update/{message_id}")
def update_message(message_id: int, request: UpdateMessageRequest, db: Session = Depends(get_db)):
    """Update the content or associated recipes of an existing message."""
    print(f"🔄 Updating message ID: {message_id}")
    try:
        db_msg = db.query(models.Message).filter(models.Message.id == message_id).first()
        if not db_msg:
            raise HTTPException(status_code=404, detail="Message not found")
        db_msg.content = request.content
        db_msg.recipes = json.dumps(request.recipes)
        db.commit()
        return {"status": "success", "message": f"Message {message_id} updated"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"🚨 Error updating message: {e}")
        raise HTTPException(status_code=500, detail="Database update failed")


# ==========================================
# 3. MEDICAL RAG LOGIC
# ==========================================
async def ask_medical_question(request: ChatRequest, db: Session):
    """Generate a medical response using RAG with pgvector search and Groq."""
    print(f"🩺 RAG Pipeline Triggered for: {request.query}")

    # Step 1 — Generate embedding locally (384-dimensions)
    query_embedding = embed_model.encode(request.query).tolist()

    # Step 2 — Search Supabase using pgvector via SQLAlchemy
    # We use cosine_distance to find the top 3 most relevant medical guidelines
    try:
        results = db.query(models.MedicalGuideline).order_by(
            models.MedicalGuideline.embedding.cosine_distance(query_embedding)
        ).limit(3).all()

        context = "\n\n".join(
            [r.content for r in results]
        ) if results else "No specific medical guidelines found."
    except Exception as e:
        print(f"⚠️ Vector Search Error: {e}")
        context = "Medical guidelines are currently unavailable."

    # Step 3 — Stream response from Groq (Llama 3.1)
    async def rag_stream_generator():
        prompt = f"""
You are 'Aduane Intelligence', a blunt but supportive Ghanaian Nutrition Coach. 
Avoid generic greetings like 'Hello my dear friend' or 'I am happy to help.'

STYLE GUIDELINES:
1. Use analogies (e.g., 'Sodium is a sponge').
2. Be direct: Tell the user exactly why their profile ({request.health_condition}) makes the query risky.
3. Ghanaian Context: Always pivot to local high-volume, low-calorie foods (Kontomire, Garden Eggs, Okra).
4. Goal Focus: Mention their {request.calorie_goal} kcal limit and {request.goal_weight_kg}kg target as the 'Why' behind your advice.
5. NO FLUFF: Max 3-4 punchy sentences.

USER PROFILE: {request.health_condition} | {request.current_weight_kg}kg -> {request.goal_weight_kg}kg
CONTEXT: {context}
QUESTION: {request.query}
"""

        try:
            chat_completion = await groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {
                        "role": "system", 
                        "content": "You are a supportive Ghanaian medical nutritionist. Keep answers concise, safe, and culturally relevant."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,        # Lower for medical safety
                max_tokens=512,         # Keeps responses "smaller"
                top_p=1,
                stream=True
            )

            async for chunk in chat_completion:
                text_piece = chunk.choices[0].delta.content or ""
                if text_piece:
                    packet = json.dumps({"type": "text", "content": text_piece})
                    yield f"data: {packet}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except asyncio.CancelledError:
            print("🛑 Medical stream cancelled by user.")
        except Exception as e:
            print(f"❌ Groq Medical Stream Error: {e}")
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(rag_stream_generator(), media_type="text/event-stream")

def find_food_in_db(food_name: str, db: Session):
    """
    Performs a fuzzy, case-insensitive search using the RAM cache instead of the DB.
    """
    print(f"🔍 Searching RAM cache for: '{food_name}'")
    
    try:
        # 1. Grab the cached DataFrame (Instant!)
        df = get_cached_recipes(db)
        
        if df.empty:
            return None

        # 2. Pandas fuzzy search (case-insensitive 'contains')
        # This is the Pandas equivalent of SQL's ILIKE '%food_name%'
        matches = df[df['name'].str.contains(food_name, case=False, na=False)]

        # 3. If we found a match, return the first one as a dictionary
        if not matches.empty:
            result = matches.iloc[0] # Grab the first matched row
            print(f"✅ Found match in Cache: {result['name']}")
            return {
                "id": int(result.get('id', 0)),
                "name": str(result.get('name', 'Unknown')),
                "calories": int(result.get('calories', 0))
            }
        else:
            print(f"❌ No match found in cache for '{food_name}'")
            return None
            
    except Exception as e:
        print(f"🚨 Cache Search Error: {e}")
        return None


async def handle_food_logging(request: ChatRequest, db: Session):
    """Path 3: Handles statements like 'I ate Waakye' and streams the response."""
    print(f"📝 Logging Intent Triggered for: {request.query}")
    
    # 1. SILENT AI EXTRACTOR: Get the food name for the DB lookup (No stream)
    try:
        extract_response = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "Extract ONLY the name of the food from the user's sentence. Nothing else."},
                {"role": "user", "content": request.query}
            ],
            max_tokens=10,
            temperature=0.0
        )
        food_name = extract_response.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ Extraction failed: {e}")
        food_name = request.query # Fallback
        
    # 2. SEARCH DATABASE
    # (Replace this with your actual DB search logic/function)
    food_item = find_food_in_db(food_name, db) 
    
    # 3. STREAM GENERATOR (Talking to the user)
    async def logging_stream_generator():
        # Tell the AI what happened in the database so it can talk to the user about it
        if food_item:
            calories = food_item.get('calories', 0)
            food_id = food_item.get('id', 0)
            system_prompt = f"The user just ate '{food_item['name']}', which is {calories} calories. In 2 short sentences, enthusiastically acknowledge this, tell them the calories, and ask if they want you to log it to their daily tracker."
        else:
            system_prompt = f"The user said they ate '{food_name}', but you don't have the exact nutrition facts for that right now. In 2 short sentences, apologize and ask if they would like to enter the calories manually."

        try:
            stream = await groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "You are Aduane Intelligence, a helpful Ghanaian nutrition assistant."},
                    {"role": "user", "content": system_prompt}
                ],
                stream=True,
                temperature=0.6
            )

            # Stream the conversational text to Flutter
            async for chunk in stream:
                text_piece = chunk.choices[0].delta.content or ""
                if text_piece:
                    yield f"data: {json.dumps({'type': 'text', 'content': text_piece})}\n\n"

            # 🌟 PRO-TIP FOR FLUTTER: Send a hidden UI trigger packet!
            if food_item:
                # We send a special packet at the end that the UI can catch to display the Yes/No buttons
                action_packet = {
                    "type": "log_action",
                    "food_name": food_item['name'],
                    "food_id": food_id,
                    "calories": calories
                }
                yield f"data: {json.dumps(action_packet)}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except asyncio.CancelledError:
            print("🛑 Logging stream cancelled by user.")
        except Exception as e:
            print(f"❌ Groq Logging Stream Error: {e}")
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(logging_stream_generator(), media_type="text/event-stream")

async def handle_general_chat(request: ChatRequest):
    """Path 4: Handles greetings, small talk, and off-topic queries."""
    print(f"👋 General Chat Triggered for: {request.query}")

    async def chat_stream_generator():
        # The Persona: Friendly, but highly focused on bringing them back to the app's purpose
        system_prompt = """
        You are 'Aduane Intelligence', a friendly, witty, and helpful Ghanaian Nutrition Coach.
        The user has just said something conversational, a greeting, or something completely off-topic.
        
        INSTRUCTIONS:
        1. Reply naturally and warmly in 1 to 2 short sentences.
        2. Briefly introduce yourself if they ask who you are.
        3. Gently steer the conversation back to your core capabilities: recommending healthy Ghanaian meals, tracking calories, or answering health/nutrition questions.
        """

        try:
            stream = await groq_client.chat.completions.create(
                model="llama-3.1-8b-instant", # The 8B model is perfect (and fast) for general chat
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": request.query}
                ],
                stream=True,
                temperature=0.7 # A little higher temperature makes the AI sound more natural and conversational
            )

            # Stream the conversational text to Flutter
            async for chunk in stream:
                text_piece = chunk.choices[0].delta.content or ""
                if text_piece:
                    yield f"data: {json.dumps({'type': 'text', 'content': text_piece})}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except asyncio.CancelledError:
            print("🛑 General chat stream cancelled by user.")
            return
        except Exception as e:
            print(f"❌ Groq General Chat Error: {e}")
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(chat_stream_generator(), media_type="text/event-stream")


# ==========================================
# 4. INTENT ROUTER
# ==========================================
@router.post("/message")
async def handle_user_message(request: ChatRequest, db: Session = Depends(get_db)):
    """Route the incoming message to either the recipe recommender or medical assistant."""
    print(f"🚦 Routing Message: '{request.query}'")

    try:
        # We sharpen the prompt to ensure 'Why' and 'How' questions go to Path 2
        intent_response = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system", 
                    "content": "You are a strict intent classification engine. You must output EXACTLY ONE DIGIT (1, 2, 3, or 4). Do not output any other text, punctuation, or explanation."
                },
                {
                    "role": "user", 
                    "content": f"""Categorize the following user message: '{request.query}'
                    
                    Choose the best fit:
                    1 = RECOMMENDATION (User wants food suggestions, a menu, or asks 'what should I eat?').
                    2 = FACTUAL/MEDICAL (User asks 'How many calories?', 'Why?', or asks a health/nutrition question).
                    3 = LOGGING/CONSUMPTION (User states they ate something, e.g., 'I ate Waakye', 'I just had lunch').
                    4 = GENERAL/CHIT-CHAT (Greetings, small talk, or unclear/random statements).
                    
                    Output ONLY the number:"""
                }
            ],
            max_tokens=1,
            temperature=0.0 # 🌟 CRITICAL: Set to 0.0 so it never guesses or hallucinates!
        )

        intent = intent_response.choices[0].message.content.strip()
        print(f"🎯 Intent Detected: {intent}")

        # Path 1: Recommendations (Your original function)
        if intent == "1":
            recipe_request = RecipeRequest(
                query=request.query,
                health_condition=request.health_condition,
                current_calories=request.current_calories,
                calorie_goal=request.calorie_goal
            )
            return await recommend_recipes(recipe_request, db)

        # Path 2: Factual / Medical (Your original function)
        elif intent == "2":
            return await ask_medical_question(request, db)

        # Path 3: Logging ("I ate Waakye")
        elif intent == "3":
            # Create a new function for this!
            return await handle_food_logging(request, db)

        # Path 4 & Fallback: General Chat
        else:
            # Handle greetings or weird prompts gracefully
            return await handle_general_chat(request)

    except Exception as e:
        print(f"❌ Router Error: {e}. Falling back to recipes.")
        # 🌟 FIX: Added 'db' here to prevent a TypeError crash
        fallback_request = RecipeRequest(query=request.query, health_condition=request.health_condition)
        return await recommend_recipes(fallback_request, db)