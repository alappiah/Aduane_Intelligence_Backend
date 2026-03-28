from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from ollama import AsyncClient
import os, json, asyncio, joblib
from dotenv import load_dotenv

from ..schemas import RecipeRequest

load_dotenv()

router = APIRouter(prefix="/recipes", tags=["Recipes"])

# ==========================================
# 🌟 1. CENTRALIZED AI CONFIGURATION
# ==========================================
# Change this Ngrok URL in ONE place when your Colab restarts!
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "https://unjudging-unsystematically-delsie.ngrok-free.dev")

print("⏳ Loading AI Systems & ML Models...")

# ==========================================
# 2. LOAD ML MODELS & DATA ON STARTUP
# ==========================================
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
    ml_predictors = {} # Fallback so the app doesn't crash completely

# Load and clean Recipe Data
csv_path = "./data/final_recipes.csv"
if os.path.exists("./data/ghana_recipes_v3.csv"):
    csv_path = "./data/ghana_recipes_v3.csv"
elif not os.path.exists(csv_path): 
    csv_path = "./data/ghana_recipes_v2.csv"

try:
    data = pd.read_csv(csv_path)
    # Clean text columns for the TF-IDF vectorizer
    text_cols = ['name', 'ingredients', 'tags', 'meal_type']
    for col in text_cols:
        if col in data.columns:
            data[col] = data[col].fillna('')
    print(f"✅ System Ready! Loaded data from {csv_path}")
except Exception as e:
    print(f"❌ Critical: Recipe CSV missing or corrupted. Error: {e}")
    data = pd.DataFrame() # Fallback


# ==========================================
# 3. HELPER: ML SAFETY CHECKER
# ==========================================
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


# ==========================================
# 4. MAIN ROUTE: RECOMMEND & STREAM
# ==========================================
@router.post("/recommend")
async def recommend_recipes(request: RecipeRequest):
    print(f"📊 DATA CHECK -> Goal: {request.calorie_goal} | Eaten: {request.current_calories}")

    print(f"🔍 Menu Request: '{request.query}' for {request.health_condition}")
    
    # 1. HARD FILTER LAYER (Using the ML Models)
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
    
        
    safe_df = safe_df.reset_index(drop=True)

    # ==========================================
    # 🌟 NEW: 1.5 DYNAMIC CONTEXT FILTERING
    # ==========================================
    safe_goal = request.calorie_goal if request.calorie_goal is not None else 2000
    safe_current = request.current_calories if request.current_calories is not None else 0
    
    remaining_calories = safe_goal - safe_current
    
    # 🟢 NEW: System Prompt Injection variable to pass to DeepSeek later
    ai_system_warning = "" 

    # SCENARIO A: User is OVER their limit!
    if remaining_calories < 0:
        over_limit_amount = abs(remaining_calories)
        print(f"🚨 User OVER limit by {over_limit_amount} kcal! Filtering strict...")
        
        # 🌟 FIX: Make it sound like a coach, not a doctor!
        ai_system_warning = f"NUTRITION ALERT: The user is OVER their daily calorie limit by {over_limit_amount} calories. Acknowledge their craving, but firmly and warmly remind them that a heavy meal isn't safe right now due to their limit and hypertension. Advise them to hydrate and ONLY pitch the light recipes listed below."
        
        safe_df = safe_df[safe_df['calories'] <= 150]
        
    # SCENARIO B: User is NEARING their limit (less than 500 left)
    elif remaining_calories < 500 and safe_current > 0:
        print(f"⚠️ User nearing limit. Only {remaining_calories} kcal left.")
        
        ai_system_warning = f"CRITICAL: The user only has {remaining_calories} calories left today. Explain that you specifically chose these light options to help them stay safely under their limit."
        
        safe_df = safe_df[safe_df['calories'] <= (remaining_calories + 50)]

    # 🟢 SAFETY FALLBACK: If the filters wiped out EVERYTHING, grab the 3 lightest items
    if safe_df.empty:
        safe_df = data.loc[safe_indices].copy() 
        safe_df = safe_df.sort_values(by='calories').head(3) 

    safe_df = safe_df.reset_index(drop=True)

    # 2. FEATURE ENGINEERING (For similarity search)
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
        recipe_id = row['recipe_id'] if 'recipe_id' in row else 0 
        
        output_list.append({
            "id": int(recipe_id),
            "name": row['name'],
            "calories": int(row.get('calories', 0)), # 🌟 Add this later!
            "carbs": int(row.get('carbs_g', 0)),     # 🌟 Add this later!
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

    # 5. GENERATE THE STREAM 
    async def recipe_stream_generator():
        # 5. THE GEMINI/CLAUDE STYLE REFINEMENT
        prompt = f"""
    CONTEXT: You are 'Aduane Intelligence', a sophisticated and insightful Nutrition Coach specialized in Ghanaian cuisine and {request.health_condition} management. 
    
    USER INPUT: "{request.query}"
    BIOMETRIC DATA: {ai_system_warning}
    AVAILABLE OPTIONS: {recipe_names}
    
    GUIDELINES FOR YOUR RESPONSE:
    1. RELATE & VALIDATE: Start with a brief, witty acknowledgement of their craving. Make it feel human (e.g., "Banku is legendary for a reason, I get it!").
    2. THE INSIGHT: Instead of a lecture, offer a quick "why" behind the choice. Address the {over_limit_amount} calorie overage and its impact on {request.health_condition} with clarity and warmth.
    3. THE SHIFT: Seamlessly pivot to the 'AVAILABLE OPTIONS'. Sell the benefits (energy, hydration, flavor) rather than just listing them.
    4. ZERO HALLUCINATION: You are strictly forbidden from inventing recipes. Only discuss the names in the AVAILABLE OPTIONS list.
    
    STYLE: Concise (max 3-4 sentences), balanced, and supportive. Use a touch of wit, but avoid clinical or 'medical emergency' language. No pre-amble like "Here is a response."
    """

        try:
            # 🌟 REFACTOR: Uses the centralized variable!
            client = AsyncClient(host=OLLAMA_HOST)
            
            # A. STREAM THE INTRO SENTENCE
            async for chunk in await client.chat(
                model='deepseek-r1:7b',
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

        except asyncio.CancelledError:
            print("🛑 User disconnected. Stopping Ollama generation.")
            return 
            
        except Exception as e:
            print(f"❌ Stream Error: {e}")
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    # 6. RETURN THE OPEN PIPELINE TO FLUTTER
    return StreamingResponse(recipe_stream_generator(), media_type="text/event-stream")