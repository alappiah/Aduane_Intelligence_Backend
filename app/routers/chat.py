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
from .recipes import recommend_recipes

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
                    "content": "You are a routing bot. Reply ONLY with 1 (Food Request) or 2 (Medical Question)."
                },
                {
                    "role": "user", 
                    "content": f"""Categorize: '{request.query}'
                    
                    1 = User is asking for a menu, recipes, or 'what should I eat'.
                    2 = User is asking 'Why', 'How', or for health/medical explanations.
                    
                    Reply ONLY with the number."""
                }
            ],
            max_tokens=1
        )

        intent = intent_response.choices[0].message.content.strip()
        print(f"🎯 Intent Detected: {intent}")

        if "2" in intent:
            return await ask_medical_question(request, db)
        else:
            recipe_request = RecipeRequest(
                query=request.query,
                health_condition=request.health_condition,
                current_calories=request.current_calories,
                calorie_goal=request.calorie_goal
            )
            return await recommend_recipes(recipe_request, db)

    except Exception as e:
        print(f"❌ Router Error: {e}. Falling back to recipes.")
        # 🌟 FIX: Added 'db' here to prevent a TypeError crash
        fallback_request = RecipeRequest(query=request.query, health_condition=request.health_condition)
        return await recommend_recipes(fallback_request, db)