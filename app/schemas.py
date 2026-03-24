from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional, Any

# Schema for RECEIVING data (User Signup form from Flutter)
class UserCreate(BaseModel):
    firstName: str
    lastName: str
    email: str
    password: str
    health_condition: str = "None" # Defaults to "None" if they skip it

# Schema for SENDING data back (Returning the User Profile)
class User(BaseModel):
    id: int
    email: str
    firstName: str
    lastName: str
    health_condition: str
    is_active: bool

    class Config:
        from_attributes = True # This tells Pydantic to read from your PostgreSQL database model

# Schema for RECEIVING login data
class UserLogin(BaseModel):
    email: str
    password: str

class UserUpdate(BaseModel):
    firstName: str
    lastName: Optional[str] = ""
    date_of_birth: Optional[str] = None
    height_cm: Optional[int] = None
    current_weight_kg: Optional[float] = None
    goal_weight_kg: Optional[float] = None
    goal_calories: Optional[int] = 2000
    goal_steps: Optional[int] = 10000
    activity_level: Optional[str] = "Moderately Active"
    health_condition: Optional[str] = "None"

class MessageBase(BaseModel):
    content: str
    sender: str

    # Allow the API to accept the recipes list, defaulting to empty
    recipes: Optional[List[Any]] = []

class MessageCreate(MessageBase):
    pass

class Message(MessageBase):
    id: int
    owner_id: int
    timestamp: datetime

    recipes: List[Any] = []
    class Config:
        from_attributes = True

class RecipeRequest(BaseModel):
    query: str
    health_condition: str

class ChatRequest(BaseModel):
    query: str
    health_condition: str

class EditMessageRequest(BaseModel):
    user_message_id: int
    ai_message_id: int
    new_user_text: str

class UpdateMessageRequest(BaseModel):
    content: str
    recipes: List[Any] = []

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    reset_code: str
    new_password: str