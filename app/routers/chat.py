from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .. import crud, schemas
from ..database import get_db

router = APIRouter(
    prefix="/chat",
    tags=["Chat History"]
)

@router.get("/history/{user_id}", response_model=List[schemas.Message])
def get_history(user_id: int, db: Session = Depends(get_db)):
    """
    Fetch all previous messages for a specific user.
    """
    print(f"📬 Fetching chat history for User ID: {user_id}")
    messages = crud.get_user_messages(db, user_id=user_id)
    return messages

@router.post("/save/{user_id}", response_model=schemas.Message)
def save_message(user_id: int, message: schemas.MessageCreate, db: Session = Depends(get_db)):
    """
    Save a new message (either from User or AI) to the database.
    """
    print(f"💾 Saving new {message.sender} message for User ID: {user_id}")
    return crud.create_user_message(db=db, message=message, user_id=user_id)