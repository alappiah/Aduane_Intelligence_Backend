from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
import chromadb, json, asyncio
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
from ollama import AsyncClient
from sqlalchemy import text

# Import your database and crud logic
from .. import crud, schemas
from ..database import get_db

# Import BOTH request types to fix the mismatch!
from ..schemas import ChatRequest, RecipeRequest, UpdateMessageRequest 
from .recipes import recommend_recipes

router = APIRouter(
    prefix="/chat",
    tags=["Chat & Assistant"]
)

# ==========================================
# 1. FIX: INITIALIZE THE VECTOR DATABASE
# ==========================================
DB_PATH = "./ghana_recipe_db"
EMBED_MODEL = "mxbai-embed-large"

try:
    chroma_client = chromadb.PersistentClient(path=DB_PATH)
    ollama_ef = OllamaEmbeddingFunction(model_name=EMBED_MODEL, url="http://localhost:11434/api/embeddings")
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
    messages = crud.get_user_messages(db, user_id=user_id)
    return messages

@router.post("/save/{user_id}", response_model=schemas.Message)
def save_message(user_id: int, message: schemas.MessageCreate, db: Session = Depends(get_db)):
    """Save a new message to the database."""
    print(f"💾 Saving new {message.sender} message for User ID: {user_id}")
    return crud.create_user_message(db=db, message=message, user_id=user_id)


# ==========================================
# 3. AI TRAFFIC COP & RAG LOGIC
# ==========================================
async def ask_medical_question(request: ChatRequest):
    print(f"🩺 RAG Pipeline Triggered for: {request.query}")
    
    # THE FIX: Return the offline message as a stream!
    if med_collection is None:
        async def offline_stream():
            yield f"data: {json.dumps({'type': 'text', 'content': 'My medical database is currently offline.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(offline_stream(), media_type="text/event-stream")
    
    # Retrieve the relevant PDF paragraphs from ChromaDB
    results = med_collection.query(
        query_texts=[request.query],
        n_results=3 # Get the top 3 most relevant chunks
    )
    
    context = "\n\n".join(results['documents'][0]) if results['documents'] else "No specific medical guidelines found."
    
    # Build the strict prompt
    async def rag_stream_generator():
        prompt = f"""
        You are a Ghanaian medical nutritionist. 
        Answer this question: {request.query}
        Use this context: {context} 
        """

        try:
           # Point this to your active Colab Ngrok URL
            client = AsyncClient(host='https://unjudging-unsystematically-delsie.ngrok-free.dev')
            
            async for chunk in await client.chat(
                model='thewindmom/llama3-med42-8b', # Your medical model
                messages=[{'role': 'user', 'content': prompt}], 
                stream=True
            ):
                
                text_piece = chunk['message']['content']
                if text_piece:
                    packet = json.dumps({"type": "text", "content": text_piece})
                    yield f"data: {packet}\n\n"

            # 2. TELL FLUTTER WE ARE DONE (No recipes for medical answers)
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as e:
            print(f"❌ RAG Stream Error: {e}")
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    # Return the open stream!
    return StreamingResponse(rag_stream_generator(), media_type="text/event-stream")


@router.post("/message")
async def handle_user_message(request: ChatRequest):
    print(f"🚦 Routing Message: '{request.query}'")
    
    # 1. THE BULLETPROOF PROMPT
    classification_prompt = f"""
    You are a strict routing bot. Categorize the following message:
    Message: "{request.query}"
    
    If the user is hungry, thirsty, or wants food/drinks, reply with the number: 1
    If the user is asking a medical, health, or dietary question, reply with the number: 2
    
    Output ONLY the number. No words. No punctuation.
    """
    
    try:
        # Point to your Colab Ngrok URL
        client = AsyncClient(host='https://unjudging-unsystematically-delsie.ngrok-free.dev')
        
        # Call the model normally (NO streaming for intent detection)
        intent_response = await client.chat(
            model='llama3.1:8b', # Usually best to use the standard model for routing
            messages=[{'role': 'user', 'content': classification_prompt}], 
            stream=False # <-- Set this to False!
        )
        
        # Extract the text
        intent = intent_response['message']['content'].strip()
        intent = intent_response['message']['content'].strip()
        
        print(f"🎯 Intent Detected: {intent}")
        
        # 2. THE BULLETPROOF LOGIC
        if "2" in intent:
            # If it outputs a 2, send to the Medical RAG model!
            return await ask_medical_question(request)
        else:
            # Default to Recipes for 1, or if it hallucinates anything else
            recipe_request = RecipeRequest(query=request.query, health_condition=request.health_condition)
            return await recommend_recipes(recipe_request)

    except asyncio.CancelledError:
            print("🛑 User disconnected. Stopping Ollama generation.")
            return # Exiting the generator cuts the connection to Colab instantly
            
    except Exception as e:
        print(f"❌ Router Error: {e}")
        recipe_request = RecipeRequest(query=request.query, health_condition=request.health_condition)
        return await recommend_recipes(recipe_request)

@router.put("/update/{message_id}")
def update_message(message_id: int, request: UpdateMessageRequest, db: Session = Depends(get_db)):
    try:
        # We target the exact row using the message_id, preserving the Primary Key
        query = text("""
            UPDATE messages 
            SET content = :content, recipes = :recipes 
            WHERE id = :id
        """)
        
        db.execute(
            query, 
            {
                "content": request.content, 
                # json.dumps ensures the list formats correctly for PostgreSQL JSON/JSONB columns
                "recipes": json.dumps(request.recipes), 
                "id": message_id
            }
        )
        db.commit()
        
        print(f"✅ Database Update: Row {message_id} updated successfully.")
        return {"status": "success", "message": f"Message {message_id} updated"}
        
    except Exception as e:
        db.rollback() # Protects the database if something crashes
        print(f"🚨 SQL Error during update: {e}")
        raise HTTPException(status_code=500, detail="Database update failed")

@router.delete("/history/{user_id}")
def delete_chat_history(user_id: int, db: Session = Depends(get_db)):
    """Permanently deletes all chat history for a specific user."""
    try:
        # We target all messages where owner_id matches the user
        query = text("DELETE FROM chat_messages WHERE owner_id = :u_id")
        db.execute(query, {"u_id": user_id})
        db.commit()
        
        print(f"🗑️ Database Wipe: History for User {user_id} deleted.")
        return {"status": "success", "message": "Chat history cleared"}
        
    except Exception as e:
        db.rollback()
        print(f"🚨 SQL Error during history deletion: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete history")