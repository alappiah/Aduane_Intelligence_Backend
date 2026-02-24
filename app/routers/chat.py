from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import chromadb
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
from ollama import AsyncClient

# Import your database and crud logic
from .. import crud, schemas
from ..database import get_db

# Import BOTH request types to fix the mismatch!
from ..schemas import ChatRequest, RecipeRequest 
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
    
    if med_collection is None:
        return {"ai_message": "My medical database is currently offline.", "results": [], "count": 0}
    
    # Retrieve the relevant PDF paragraphs from ChromaDB
    results = med_collection.query(
        query_texts=[request.query],
        n_results=3 # Get the top 3 most relevant chunks
    )
    
    context = "\n\n".join(results['documents'][0]) if results['documents'] else "No specific medical guidelines found."
    
    # Build the strict prompt
    prompt = f"""
    You are Aduane Intelligence, an expert Ghanaian Nutritionist.
    The user has {request.health_condition}.
    
    Use the following official medical guidelines to answer the user's question. 
    If the answer is not in the guidelines, say you do not know. Do NOT make up medical advice.
    
    MEDICAL GUIDELINES:
    {context}
    
    USER QUESTION:
    {request.query}
    """
    
    # Generate the answer using your medical model
    try:
        response = await AsyncClient().chat(model='thewindmom/llama3-med42-8b', messages=[
            {'role': 'user', 'content': prompt},
        ])
        
        return {
            "ai_message": response['message']['content'],
            "results": [], # No recipes for a medical question
            "count": 0
        }
    except Exception as e:
        print(f"❌ RAG Error: {e}")
        return {"ai_message": "I'm having trouble accessing my medical guidelines right now.", "results": [], "count": 0}


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
        intent_response = await AsyncClient().chat(model='phi3:mini', messages=[
            {'role': 'user', 'content': classification_prompt},
        ])
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
            
    except Exception as e:
        print(f"❌ Router Error: {e}")
        recipe_request = RecipeRequest(query=request.query, health_condition=request.health_condition)
        return await recommend_recipes(recipe_request)