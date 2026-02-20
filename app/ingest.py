import pandas as pd
import chromadb
from sentence_transformers import SentenceTransformer
import os
import shutil

# CONFIGURATION
# If your file is named 'ghana_recipes_v2.csv', change this line!
# otherwise keep it as 'final_recipes.csv'
DATA_PATH = "./data/ghana_recipes_v2.csv" 
DB_PATH = "./ghana_recipe_db"

print("🔄 Initializing Vector Database...")

# 1. Load Data
print(f"   Loading data from: {DATA_PATH}")
data = pd.read_csv(DATA_PATH)

# 2. Setup ChromaDB
# Delete old database to start fresh (prevents conflicts)
if os.path.exists(DB_PATH):
    shutil.rmtree(DB_PATH)
    print("   Deleted old database version.")

chroma_client = chromadb.PersistentClient(path=DB_PATH)
collection = chroma_client.create_collection(name="ghana_recipes")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

# 3. Process & Index
documents = []
metadatas = []
ids = []

print(f"🔄 Indexing {len(data)} recipes... (This depends on your CPU speed)")

for idx, row in data.iterrows():
    # Create the text for the AI to search
    # We combine Name + Description + Tags + Ingredients
    text = f"{row['name']}. {row.get('description', '')}. {row.get('tags', '')}. Ingredients: {row.get('ingredients', '')}"
    
    documents.append(text)
    
    # Store essential data for retrieval
    metadatas.append({
        "recipe_id": idx,
        "name": row['name'],
        "meal_type": str(row.get('meal_type', 'General'))
    })
    
    ids.append(str(idx))

# 4. Save to Disk (in batches)
batch_size = 100 
for i in range(0, len(documents), batch_size):
    end = min(i + batch_size, len(documents))
    collection.add(
        documents=documents[i:end],
        embeddings=embedding_model.encode(documents[i:end]).tolist(),
        metadatas=metadatas[i:end],
        ids=ids[i:end]
    )
    print(f"   Processed batch {i} to {end}...")

print(f"✅ Success! Database built at '{DB_PATH}'")