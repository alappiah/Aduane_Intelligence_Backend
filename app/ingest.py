import os
import pandas as pd
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction


# --- CONFIGURATION ---
PDF_DIR = "./data/disease_guidelines"
CSV_PATH = "./data/ghana_recipes_v2.csv"
DB_PATH = "./ghana_recipe_db"
EMBED_MODEL = "mxbai-embed-large"

def get_chroma_client():
    """Initializes the Chroma database and Ollama embeddings."""
    print("🔄 Initializing unified Vector Database...")

    
    
    # Define the embedding function to use Ollama locally
    ollama_ef = OllamaEmbeddingFunction(
        model_name=EMBED_MODEL,
        url="http://localhost:11434/api/embeddings",
    )
    
    client = chromadb.PersistentClient(path=DB_PATH)
    return client, ollama_ef

def ingest_medical_pdfs(client, ollama_ef):
    """Processes disease guidelines into the medical collection."""
    print("\n📚 --- Processing Medical PDFs ---")
    
    # Get or create the medical collection
    med_collection = client.get_or_create_collection(
        name="medical_guidelines",
        embedding_function=ollama_ef
    )
    
    # 1. Load PDFs
    loader = PyPDFDirectoryLoader(PDF_DIR)
    docs = loader.load()
    if not docs:
        print("⚠️ No PDFs found. Skipping medical ingestion.")
        return
        
    print(f"   Loaded {len(docs)} pages. Chunking text...")
    
    # 2. Chunk Text (Smaller chunks help Ollama process faster)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,  # Lowered so Ollama doesn't choke
        chunk_overlap=100
    )
    chunks = splitter.split_documents(docs)
    
    # 3. Prepare for Chroma
    documents = [chunk.page_content for chunk in chunks]
    metadatas = [chunk.metadata for chunk in chunks]
    ids = [f"med_doc_{i}" for i in range(len(chunks))]
    
    print(f"   Found {len(chunks)} chunks. Sending to Ollama in batches...")
    
    # 4. Insert into database IN BATCHES to prevent timeouts!
    batch_size = 20 # Only send 20 chunks at a time
    for i in range(0, len(chunks), batch_size):
        end = min(i + batch_size, len(chunks))
        med_collection.add(
            documents=documents[i:end],
            metadatas=metadatas[i:end],
            ids=ids[i:end]
        )
        print(f"   ... embedded batch {i} to {end}")
        
    print(f"✅ Successfully added {len(chunks)} medical chunks to 'medical_guidelines'.")

def ingest_ghanaian_recipes(client, ollama_ef):
    """Processes the recipe CSV into the culinary collection."""
    print("\n🍲 --- Processing Ghanaian Recipes ---")
    
    # Get or create the recipe collection
    recipe_collection = client.get_or_create_collection(
        name="ghana_recipes",
        embedding_function=ollama_ef
    )
    
    if not os.path.exists(CSV_PATH):
        print(f"⚠️ CSV not found at {CSV_PATH}. Skipping recipe ingestion.")
        return
        
    # 1. Load CSV
    data = pd.read_csv(CSV_PATH)
    print(f"   Loaded {len(data)} recipes. Formatting for vector search...")
    
    documents = []
    metadatas = []
    ids = []
    
    # 2. Format Rows
    for idx, row in data.iterrows():
        text = f"Recipe Name: {row['name']}. Description: {row.get('description', '')}. Dietary Tags: {row.get('tags', '')}. Ingredients: {row.get('ingredients', '')}"
        
        documents.append(text)
        metadatas.append({
            "recipe_id": idx,
            "name": row['name'],
            "meal_type": str(row.get('meal_type', 'General'))
        })
        ids.append(f"recipe_{idx}")
        
    # 3. Insert into database in batches
    batch_size = 50 
    for i in range(0, len(documents), batch_size):
        end = min(i + batch_size, len(documents))
        recipe_collection.add(
            documents=documents[i:end],
            metadatas=metadatas[i:end],
            ids=ids[i:end]
        )
    print(f"✅ Successfully added {len(documents)} recipes to 'ghana_recipes'.")

if __name__ == "__main__":
    print("🚀 Starting full ingestion pipeline...")
    
    db_client, embedding_func = get_chroma_client()
    
    # Run both ingestion pipelines
    ingest_medical_pdfs(db_client, embedding_func)
    ingest_ghanaian_recipes(db_client, embedding_func)
    
    print("\n🎉 Master Knowledge Base is complete and ready for retrieval!")