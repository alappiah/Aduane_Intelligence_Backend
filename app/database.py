from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Connection String
SQLALCHEMY_DATABASE_URL = "postgresql://recipe_user:recipe_pass@localhost/recipe_app"

# Create the engine
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# Create a session factory (to talk to db for each request)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

#Base Class (All models will inherit from this)
Base = declarative_base()

# db connection
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()