from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import pandas as pd
import joblib
import chromadb
from sentence_transformers import SentenceTransformer
import ollama
import os
import random

router = APIRouter(prefix="/recipes", tags=["Recipes"])

print("⏳ Loading AI Systems...")

# 1. Load ML Guardrails
try:
    ml_predictors = {
        "Diabetes": joblib.load('ml_models/diabetes_model.pkl'),
        "Hypertension": joblib.load('ml_models/hypertension_model.pkl'),
        "Cholesterol": joblib.load('ml_models/cholesterol_model.pkl')
    }
    encoder = joblib.load('ml_models/encoder.pkl')
    model_columns = joblib.load('ml_models/model_columns.pkl')
except:
    print("❌ Critical: ML Models missing.")

# 2. Load Vector DB
chroma_client = chromadb.PersistentClient(path="./ghana_recipe_db")
collection = chroma_client.get_collection("ghana_recipes")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

# 3. Load Data
csv_path = "./data/final_recipes.csv"
# Check for the version with images first
if os.path.exists("./data/ghana_recipes_v3.csv"):
    csv_path = "./data/ghana_recipes_v3.csv"
elif not os.path.exists(csv_path): 
    csv_path = "./data/ghana_recipes_v2.csv"

data = pd.read_csv(csv_path)
print(f"✅ System Ready! Loaded data from {csv_path}")

# --- DATA MODELS ---
class RecipeRequest(BaseModel):
    query: str
    health_condition: str
    current_reading: float = None

# --- HELPER: SAFETY CHECKER ---
def check_safety(recipe_row, condition):
    condition = condition.title()
    if condition not in ml_predictors: return 0 # Default to Unsafe if model missing
    
    features = ['sodium_mg', 'sugar_g', 'fiber_g', 'fat_total_g', 'fat_saturated_g', 'potassium_mg', 'iron_mg', 'meal_type', 'tags']
    try:
        df_clean = pd.DataFrame([recipe_row])[features]
        df_cat = df_clean.select_dtypes(include=['object'])
        df_num = df_clean.select_dtypes(exclude=['object'])
        
        encoded = encoder.transform(df_cat)
        df_encoded = pd.DataFrame(encoded, columns=encoder.get_feature_names_out(df_cat.columns))
        
        df_final = pd.concat([df_num, df_encoded], axis=1)
        df_final = df_final.reindex(columns=model_columns, fill_value=0)
        return int(ml_predictors[condition].predict(df_final)[0])
    except:
        return 0

# --- HELPER: GENERATE MENU SUMMARY ---
def generate_menu_summary(recipe_names, condition, query):
    names_str = ", ".join(recipe_names)
    prompt = f"""
    You are a Ghanaian Nutritionist.
    User Condition: {condition}
    User Request: "{query}"
    
    We have selected 3 options: {names_str}.
    
    Write a SHORT (1 sentence) friendly intro recommending these three choices for their variety and safety. 
    Do not list them again. Just say something nice about the selection.
    """
    try:
        response = ollama.chat(model='llama3.1:8b', messages=[
            {'role': 'user', 'content': prompt},
        ])
        return response['message']['content'].replace('"', '')
    except Exception as e:
        print(f"❌ OLLAMA ERROR: {e}")
        return "Here are three delicious and safe options I selected for you."
    

@router.post("/recommend")
def recommend_recipes(request: RecipeRequest):
    print(f"🔍 Menu Request: '{request.query}' for {request.health_condition}")
    
    # 1. SEARCH (Fetch more candidates to ensure variety)
    query_embed = embedding_model.encode([request.query]).tolist()
    results = collection.query(query_embeddings=query_embed, n_results=20) # Get top 20

    if not results['metadatas'] or not results['metadatas'][0]:
        return {"count": 0, "results": [], "message": "No recipes found."}

    found_ids = [int(str(m['recipe_id'])) for m in results['metadatas'][0]]
    # Filter unique IDs to avoid duplicates
    found_ids = list(set(found_ids))
    candidates = data.loc[found_ids].copy()
    
    safe_pool = []
    
    # 2. FILTER (Collect ALL safe options)
    for idx, row in candidates.iterrows():
        # A. Clinical Safety Check (Random Forest)
        safety_score = check_safety(row, request.health_condition)
        
        if safety_score == 1:
            # We add it to the pool
            safe_pool.append(row)
    
    # 3. RANDOMIZE (The Shuffle)
    if not safe_pool:
        return {"count": 0, "results": [], "message": "No safe options found for this specific query."}

    # Shuffle the list to make it random each time
    random.shuffle(safe_pool)
    
    # Pick top 3
    selected_recipes = safe_pool[:3]
    
    # 4. PREPARE OUTPUT
    output_list = []
    recipe_names = []

    for row in selected_recipes:
        recipe_names.append(row['name'])
        output_list.append({
            "id": int(str(row.name)),
            "name": row['name'],
            "description": row.get('description', 'Authentic Ghanaian Dish'),
            "meal_type": str(row.get('meal_type', 'General')).upper(),
            "tags": str(row.get('tags', 'Local')).split(','),
            "nutrition": {
                "sugar": f"{row['sugar_g']}g",
                "sodium": f"{row['sodium_mg']}mg",
                "fat": f"{row['fat_saturated_g']}g"
            },
            "image_url": row.get('image_url', 'https://placehold.co/600x400')
        })

    # 5. GENERATE AI SUMMARY
    ai_message = generate_menu_summary(recipe_names, request.health_condition, request.query)

    return {
        "count": len(output_list),
        "ai_message": ai_message, # The intro text
        "results": output_list    # The 3 recipes for your cards
    }