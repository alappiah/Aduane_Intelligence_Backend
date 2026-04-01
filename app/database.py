import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Load environment variables from the .env file
load_dotenv()

# Fetch the connection string securely
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL")

if not SQLALCHEMY_DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set!")

# Create the engine
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# Create a session factory (to talk to db for each request)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base Class (All models will inherit from this)
Base = declarative_base()

# db connection
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()