from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
import chromadb, json, asyncio, os
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
from ollama import AsyncClient
from dotenv import load_dotenv

# Import your database, models, and crud logic
from .. import crud, schemas, models # 🌟 Added models here!
from ..database import get_db

# Import BOTH request types
from ..schemas import ChatRequest, RecipeRequest, UpdateMessageRequest 
from .recipes import recommend_recipes

load_dotenv()

router = APIRouter(
    prefix="/chat",
    tags=["Chat & Assistant"]
)

# ==========================================
# 🌟 1. CENTRALIZED AI CONFIGURATION
# ==========================================
# Change this Ngrok URL in ONE place when your Colab restarts!
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "https://unjudging-unsystematically-delsie.ngrok-free.dev")
LOCAL_EMBED_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "mxbai-embed-large"
DB_PATH = "./ghana_recipe_db"

try:
    chroma_client = chromadb.PersistentClient(path=DB_PATH)
    ollama_ef = OllamaEmbeddingFunction(model_name=EMBED_MODEL, url=LOCAL_EMBED_URL)
    med_collection = chroma_client.get_or_create_collection(name="medical_guidelines", embedding_function=ollama_ef)
    print("✅ ChromaDB connected in chat router!")
except Exception as e:
    print(f"⚠️ Warning: Could not connect to ChromaDB. RAG will not work. Error: {e}")
    med_collection = None


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
    """Save a new message to the database."""
    print(f"💾 Saving new {message.sender} message for User ID: {user_id}")
    return crud.create_user_message(db=db, message=message, user_id=user_id)

@router.delete("/history/{user_id}")
def delete_chat_history(user_id: int, db: Session = Depends(get_db)):
    """Permanently deletes all chat history for a specific user."""
    try:
        # 🌟 REFACTOR: Using secure SQLAlchemy ORM instead of raw text SQL
        db.query(models.Message).filter(models.Message.owner_id == user_id).delete()
        db.commit()
        
        print(f"🗑️ Database Wipe: History for User {user_id} deleted.")
        return {"status": "success", "message": "Chat history cleared"}
        
    except Exception as e:
        db.rollback()
        print(f"🚨 SQL Error during history deletion: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete history")

@router.put("/update/{message_id}")
def update_message(message_id: int, request: UpdateMessageRequest, db: Session = Depends(get_db)):
    try:
        # 🌟 REFACTOR: Using secure SQLAlchemy ORM instead of raw text SQL
        db_msg = db.query(models.Message).filter(models.Message.id == message_id).first()
        
        if not db_msg:
            raise HTTPException(status_code=404, detail="Message not found")
            
        db_msg.content = request.content # type: ignore
        db_msg.recipes = json.dumps(request.recipes) # type: ignore
        db.commit()
        
        print(f"✅ Database Update: Row {message_id} updated successfully.")
        return {"status": "success", "message": f"Message {message_id} updated"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback() 
        print(f"🚨 SQL Error during update: {e}")
        raise HTTPException(status_code=500, detail="Database update failed")


# ==========================================
# 3. AI TRAFFIC COP & RAG LOGIC
# ==========================================
async def ask_medical_question(request: ChatRequest):
    print(f"🩺 RAG Pipeline Triggered for: {request.query}")
    
    if med_collection is None:
        async def offline_stream():
            yield f"data: {json.dumps({'type': 'text', 'content': 'My medical database is currently offline.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(offline_stream(), media_type="text/event-stream")
    
    # Retrieve the relevant PDF paragraphs from ChromaDB
    results = med_collection.query(
        query_texts=[request.query],
        n_results=3 
    )
    
    context = "\n\n".join(results['documents'][0]) if results['documents'] else "No specific medical guidelines found."
    
    async def rag_stream_generator():
        prompt = f"""
        You are an expert Ghanaian medical nutritionist. 
        The user asking this question has the following health profile: {request.health_condition}.
        Please tailor your medical advice specifically to be safe and relevant for someone with this condition.
        
        Answer this question: {request.query}
        Use this context: {context} 
        """

        try:
            # 🌟 REFACTOR: Uses the centralized variable!
            client = AsyncClient(host=OLLAMA_HOST)
            
            async for chunk in await client.chat(
                model='thewindmom/llama3-med42-8b', 
                messages=[{'role': 'user', 'content': prompt}], 
                stream=True
            ):
                text_piece = chunk['message']['content']
                if text_piece:
                    packet = json.dumps({"type": "text", "content": text_piece})
                    yield f"data: {packet}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except asyncio.CancelledError:
            print("🛑 [Intent 2] User pressed Stop! Terminating stream.")
            yield f"data: {json.dumps({'type': 'text', 'content': ' ... [Stopped]'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return 
            
        except Exception as e:
            print(f"❌ RAG Stream Error: {e}")
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(rag_stream_generator(), media_type="text/event-stream")


@router.post("/message")
async def handle_user_message(request: ChatRequest):
    print(f"🚦 Routing Message: '{request.query}'")
    
    classification_prompt = f"""
    You are a strict routing bot. Categorize the following message:
    Message: "{request.query}"
    
    If the user is hungry, thirsty, or wants food/drinks, reply with the number: 1
    If the user is asking a medical, health, or dietary question, reply with the number: 2
    
    Output ONLY the number. No words. No punctuation.
    """
    
    try:
        # 🌟 REFACTOR: Uses the centralized variable!
        client = AsyncClient(host=OLLAMA_HOST)
        
        intent_response = await client.chat(
            model='llama3.1:8b', 
            messages=[{'role': 'user', 'content': classification_prompt}], 
            stream=False 
        )
        
        # 🌟 REFACTOR: Cleaned up the duplicate intent definition
        intent = intent_response['message']['content'].strip()
        print(f"🎯 Intent Detected: {intent}")
        
        if "2" in intent:
            return await ask_medical_question(request)
        else:
            recipe_request = RecipeRequest(query=request.query, health_condition=request.health_condition)
            return await recommend_recipes(recipe_request)

    except Exception as e:
        print(f"❌ Router Error: {e}")
        # Default fallback if the LLM fails to classify
        recipe_request = RecipeRequest(query=request.query, health_condition=request.health_condition)
        return await recommend_recipes(recipe_request)