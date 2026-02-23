from pydantic import BaseModel
from datetime import datetime

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

class MessageBase(BaseModel):
    content: str
    sender: str

class MessageCreate(MessageBase):
    pass

class Message(MessageBase):
    id: int
    owner_id: int
    timestamp: datetime

    class Config:
        from_attributes = True

class RecipeRequest(BaseModel):
    query: str
    health_condition: str