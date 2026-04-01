from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from groq import AsyncGroq # ⚡ High-speed cloud AI
import os, json, asyncio, joblib
from dotenv import load_dotenv

from ..database import get_db
from .. import models, schemas
from ..schemas import RecipeRequest

load_dotenv()

router = APIRouter(prefix="/recipes", tags=["Recipes"])

# ==========================================
# 1. AI & ML CONFIGURATION
# ==========================================
# Groq handles the "Coach" logic
groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

print("⏳ Loading ML Safety Predictors...")
try:
    ml_predictors = {
        "Diabetes": joblib.load('ml_models/diabetes_model.pkl'),
        "Hypertension": joblib.load('ml_models/hypertension_model.pkl'),
        "Cholesterol": joblib.load('ml_models/cholesterol_model.pkl')
    }
    encoder = joblib.load('ml_models/encoder.pkl')
    model_columns = joblib.load('ml_models/model_columns.pkl')
    print("✅ ML Models loaded successfully.")
except Exception as e:
    print(f"❌ Warning: ML Models missing. Safety checks will be restricted. Error: {e}")
    ml_predictors = {}


# ==========================================
# 2. HELPER: ML SAFETY CHECKER
# ==========================================
def check_safety(recipe_row, condition: str):
    """Uses pre-trained ML models to determine if a recipe is safe for a condition."""
    condition = condition.title()
    if condition not in ml_predictors or condition == "None": 
        return 1 # Default to Safe
    
    features = [
        'sodium_mg', 
        'sugar_g', 
        'fat_total_g', 
        'meal_type', 
        'tags'
    ]
    try:
        # Convert row to DataFrame for the predictor
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


# ==========================================
# 3. MAIN ROUTE: RECOMMEND & STREAM
# ==========================================
@router.post("/recommend")
async def recommend_recipes(request: RecipeRequest, db: Session = Depends(get_db)):
    """Fetches safe Ghanaian recipes from Supabase and provides AI coaching via Groq."""
    print(f"🔍 Recommendation Request: '{request.query}' for {request.health_condition}")
    
    # 1. Fetch ALL recipes from Supabase (Fresh from the DB)
    try:
        db_recipes = db.query(models.Recipe).all()
        # Convert SQLAlchemy objects to a list of dicts for Pandas processing
        recipe_data = [
            {column.name: getattr(recipe, column.name) for column in recipe.__table__.columns} 
            for recipe in db_recipes
        ]
        data = pd.DataFrame(recipe_data)
    except Exception as e:
        print(f"🚨 Database Error: {e}")
        raise HTTPException(status_code=500, detail="Could not fetch recipes from database.")

    if data.empty:
        raise HTTPException(status_code=404, detail="No recipes found in database.")

    # 2. HARD FILTER LAYER (ML Safety Models)
    safe_indices = []
    for idx, row in data.iterrows():
        if check_safety(row, request.health_condition) == 1:
            safe_indices.append(idx)
            
    safe_df = data.loc[safe_indices].copy()
    
    if safe_df.empty:
        async def empty_stream():
            yield f"data: {json.dumps({'type': 'text', 'content': 'I could not find any medically safe options for that.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    # 3. DYNAMIC CALORIE FILTERING
    safe_goal = request.calorie_goal if request.calorie_goal else 2000
    safe_current = request.current_calories if request.current_calories else 0
    remaining_calories = safe_goal - safe_current
    ai_system_warning = "" 

    if remaining_calories < 0:
        over_limit = abs(remaining_calories)
        ai_system_warning = f"USER ALERT: User is {over_limit}kcal OVER their limit. Only suggest very light snacks (<150kcal)."
        safe_df = safe_df[safe_df['calories'] <= 150]
    elif remaining_calories < 500:
        ai_system_warning = f"USER ALERT: Only {remaining_calories}kcal left. Suggest light options."
        safe_df = safe_df[safe_df['calories'] <= (remaining_calories + 50)]

    # Safety Fallback: ensure we always have at least 3 items
    if safe_df.empty:
        safe_df = data.loc[safe_indices].copy().sort_values(by='calories').head(3) 

    safe_df = safe_df.reset_index(drop=True)

    # 4. VECTOR SIMILARITY (TF-IDF Search)
    safe_df['combined_features'] = (
        safe_df['name'].fillna('') + " " + 
        safe_df['ingredients'].fillna('') + " " + 
        safe_df['tags'].fillna('') + " " + 
        safe_df['meal_type'].fillna('')
    )
    
    all_text = safe_df['combined_features'].tolist()
    all_text.append(request.query)

    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(all_text)
    cosine_sim = cosine_similarity(tfidf_matrix[-1], tfidf_matrix[:-1])[0]
    
    top_n = min(3, len(safe_df))
    top_indices = cosine_sim.argsort()[-top_n:][::-1]
    results_df = safe_df.iloc[top_indices]

    # 5. PREPARE JSON FOR FLUTTER
    output_list = []
    recipe_names = []
    for _, row in results_df.iterrows():
        recipe_names.append(row['name'])
        output_list.append({
            "id": int(row.get('id', 0)),
            "name": row['name'],
            "calories": int(row.get('calories', 0)),
            "carbs": int(row.get('carbs_g', 0)),
            "protein": int(row.get('protein_g', 0)),
            "description": row.get('description', 'Authentic Ghanaian Dish'),
            "meal_type": str(row.get('meal_type', 'General')).upper(),
            "tags": str(row.get('tags', 'Local')).split(','),
            "nutrition": {
                "sugar": f"{row.get('sugar_g', 0)}g",
                "sodium": f"{row.get('sodium_mg', 0)}mg",
                "fat": f"{row.get('fat_saturated_g', 0)}g"
            },
            "image_url": row.get('image_url', 'https://placehold.co/600x400'),
            "ingredients": str(row.get('ingredients', '')),   
            "instructions": str(row.get('instructions', ''))
        })

    # 6. STREAM GENERATOR (Groq Logic)
    async def recipe_stream_generator():
        prompt = f"""
CONTEXT: You are 'Aduane Intelligence', a witty Ghanaian Nutrition Coach.
USER DATA: 
- Aiming for {request.goal_weight_kg}kg (Current: {request.current_weight_kg}kg)
- Health: {request.health_condition} 
- {ai_system_warning}

OPTIONS TO PITCH: {recipe_names}

INSTRUCTIONS:
1. Acknowledge the craving briefly.
2. Explain why these specific Ghanaian options help them reach their {request.goal_weight_kg}kg goal while managing {request.health_condition}.
3. Keep it to 3 sentences. Be supportive and insightful.
"""

        try:
            stream = await groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                stream=True
            )

            async for chunk in stream:
                text_piece = chunk.choices[0].delta.content or ""
                if text_piece:
                    yield f"data: {json.dumps({'type': 'text', 'content': text_piece})}\n\n"

            # Add delay before cards for smooth UI in Flutter
            for recipe in output_list:
                await asyncio.sleep(0.4)
                yield f"data: {json.dumps({'type': 'recipe', 'content': recipe})}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        # 🌟 ADD THIS BLOCK HERE
        except asyncio.CancelledError:
            print("🛑 User disconnected. Stopping generation.")
            return 

        except Exception as e:
            print(f"❌ Groq Stream Error: {e}")
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(recipe_stream_generator(), media_type="text/event-stream")