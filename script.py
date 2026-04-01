import os
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# Use the CSV version that contains the URLs
CSV_PATH = "./data/ghana_recipes_v3.csv"
engine = create_engine(os.getenv("DATABASE_URL"))

def sync():
    df = pd.read_csv(CSV_PATH)
    print(f"🔄 Syncing images for {len(df)} recipes...")

    with engine.connect() as conn:
        for _, row in df.iterrows():
            if pd.notna(row['image_url']):
                # Find by name and update the image_url
                query = text("UPDATE recipes SET image_url = :url WHERE name = :name")
                conn.execute(query, {"url": row['image_url'], "name": row['name']})
                print(f"✅ Updated: {row['name']}")
        
        conn.commit()
    print("🎉 All images are now synced to Supabase!")

if __name__ == "__main__":
    sync()