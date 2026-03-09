from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from ollama import AsyncClient
import os, json, asyncio, joblib
from ..schemas import RecipeRequest

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
except Exception as e:
    print(f"❌ Critical: ML Models missing. Error: {e}")


# 2. Load Data
csv_path = "./data/final_recipes.csv"
if os.path.exists("./data/ghana_recipes_v3.csv"):
    csv_path = "./data/ghana_recipes_v3.csv"
elif not os.path.exists(csv_path): 
    csv_path = "./data/ghana_recipes_v2.csv"

data = pd.read_csv(csv_path)

# Clean text columns for the TF-IDF vectorizer
text_cols = ['name', 'ingredients', 'tags', 'meal_type']
for col in text_cols:
    if col in data.columns:
        data[col] = data[col].fillna('')

print(f"✅ System Ready! Loaded data from {csv_path}")


# --- HELPER: SAFETY CHECKER ---
def check_safety(recipe_row, condition):
    condition = condition.title()
    if condition not in ml_predictors or condition == "None": 
        return 1 # Default to Safe if no condition is provided
    
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
    except Exception as e:
        print(f"⚠️ ML Prediction Error for {condition}: {e}")
        return 0


# --- MAIN ROUTE: RECOMMEND & STREAM ---
@router.post("/recommend")
async def recommend_recipes(request: RecipeRequest):
    print(f"🔍 Menu Request: '{request.query}' for {request.health_condition}")
    
    # 1. HARD FILTER LAYER 
    safe_indices = []
    for idx, row in data.iterrows():
        if check_safety(row, request.health_condition) == 1:
            safe_indices.append(idx)
            
    safe_df = data.loc[safe_indices].copy()
    
    if safe_df.empty:
        # If no recipes are safe, return an empty stream
        async def empty_stream():
            yield f"data: {json.dumps({'type': 'text', 'content': 'I could not find any medically safe options for that.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")
        
    safe_df = safe_df.reset_index(drop=True)

    # 2. FEATURE ENGINEERING
    ingredients_col = safe_df['ingredients'] if 'ingredients' in safe_df.columns else ""
    safe_df['combined_features'] = safe_df['name'] + " " + \
                                   ingredients_col + " " + \
                                   safe_df['tags'] + " " + \
                                   safe_df['meal_type']
                                   
    all_text_data = safe_df['combined_features'].tolist()
    all_text_data.append(request.query)

    # 3. VECTORIZATION & SIMILARITY SCORING
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(all_text_data)
    cosine_sim = cosine_similarity(tfidf_matrix[-1], tfidf_matrix[:-1])[0]
    
    top_n = min(3, len(safe_df))
    top_indices = cosine_sim.argsort()[-top_n:][::-1]

    # 4. PREPARE OUTPUT DATA
    output_list = []
    recipe_names = []
    results_df = safe_df.iloc[top_indices]

    for _, row in results_df.iterrows():
        recipe_names.append(row['name'])
        recipe_id = row['recipe_id'] if 'recipe_id' in row else _ 
        
        output_list.append({
            "id": int(recipe_id),
            "name": row['name'],
            "description": row.get('description', 'Authentic Ghanaian Dish'),
            "meal_type": str(row.get('meal_type', 'General')).upper(),
            "tags": str(row.get('tags', 'Local')).split(','),
            "nutrition": {
                "sugar": f"{row.get('sugar_g', 0)}g",
                "sodium": f"{row.get('sodium_mg', 0)}mg",
                "fat": f"{row.get('fat_saturated_g', 0)}g"
            },
            "image_url": row.get('image_url', 'https://placehold.co/600x400')
        })

    # 5. GENERATE THE STREAM 
    async def recipe_stream_generator():
        prompt = f"""
        You are a friendly Ghanaian Nutritionist. 
        The user has {request.health_condition} and asked for "{request.query}". 
        You are recommending these exact dishes: {', '.join(recipe_names)}.
        
        Write EXACTLY ONE short, friendly sentence introducing these dishes. 
        Do NOT write a guide. Do NOT give medical advice. STOP writing after the first sentence.
        """

        try:
            # Point this to your active Colab Ngrok URL
            client = AsyncClient(host='https://unjudging-unsystematically-delsie.ngrok-free.dev')
            
            async for chunk in await client.chat(
                model='llama3.1:8b',  # Use the standard model you pulled
                messages=[{'role': 'user', 'content': prompt}], 
                stream=True
            ):
                
                text_piece = chunk['message']['content']
                if text_piece:
                    packet = json.dumps({"type": "text", "content": text_piece})
                    yield f"data: {packet}\n\n"

            # B. STREAM RECIPE CARDS
            for recipe in output_list:
                await asyncio.sleep(0.4) # Pause for visual effect
                packet = json.dumps({"type": "recipe", "content": recipe})
                yield f"data: {packet}\n\n"

            # C. END THE STREAM
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        # 1. ADD THIS BLOCK: Catch the user pressing Stop!
        except asyncio.CancelledError:
            print("🛑 User disconnected. Stopping Ollama generation.")
            return # Exiting the generator cuts the connection to Colab instantly
            
        except Exception as e:
            print(f"❌ Stream Error: {e}")
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    # 6. RETURN THE OPEN PIPELINE TO FLUTTER
    return StreamingResponse(recipe_stream_generator(), media_type="text/event-stream")