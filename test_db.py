from app.database import SessionLocal
from sqlalchemy import text

def test_connection():
    db = SessionLocal()
    try:
        # This sends a tiny query to Supabase
        result = db.execute(text("SELECT 1"))
        print("✅ Connection Successful! Aduane Intelligence is live.")
    except Exception as e:
        print(f"❌ Connection Failed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    test_connection()