import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
from app.models import Base, MedicalGuideline

load_dotenv()

# Path configuration relative to the project root
PDF_DIR = "./data/disease_guidelines"
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
model = SentenceTransformer("all-MiniLM-L6-v2")

def ingest():
    # 1. Initialize Supabase
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # 2. Process Medical PDFs
    print(f"📚 Loading PDFs from: {PDF_DIR}")
    if not os.path.exists(PDF_DIR):
        print(f"❌ Error: {PDF_DIR} not found!")
        return

    loader = PyPDFDirectoryLoader(PDF_DIR)
    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    chunks = splitter.split_documents(docs)
    
    print(f"🚀 Uploading {len(chunks)} chunks to Supabase...")
    for i, chunk in enumerate(chunks):
        vector = model.encode(chunk.page_content).tolist()
        db.add(MedicalGuideline(
            content=chunk.page_content,
            metadata_json=chunk.metadata,
            embedding=vector
        ))
        if (i + 1) % 10 == 0:
            db.commit()
            print(f"   ... Progress: {i+1}/{len(chunks)}")
            
    db.commit()
    db.close()
    print("🎉 Medical data is now LIVE in Supabase!")

if __name__ == "__main__":
    ingest()