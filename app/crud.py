from sqlalchemy.orm import Session
from . import models, schemas, auth

def get_user_by_email(db: Session, email: str):
    # Searches the database for a user with this exact email
    return db.query(models.User).filter(models.User.email == email).first()

def create_user(db: Session, user: schemas.UserCreate):
    # 1. Scramble the password using the auth file we just made
    hashed_password = auth.get_password_hash(user.password)
    
    # 2. Build the database row based on your models.py
    db_user = models.User(
        email=user.email,
        firstName=user.firstName,
        lastName=user.lastName,
        health_condition=user.health_condition,
        hashed_password=hashed_password
    )
    
    # 3. Save it to PostgreSQL
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def create_user_message(db: Session, message: schemas.MessageCreate, user_id: int):
    db_message = models.Message(**message.model_dump(), owner_id=user_id)
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

def get_user_messages(db: Session, user_id: int):
    #This is the security filter: it ONLY returns messages for this user_id
    # Added .order_by to ensure the chat history is in the correct chronological order
    return db.query(models.Message).filter(models.Message.owner_id == user_id).order_by(models.Message.timestamp.asc()).all()