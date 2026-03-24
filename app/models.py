from sqlalchemy import Column, Float, Integer, String, Boolean, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from .database import Base
from datetime import datetime
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    firstName = Column(String, index=True)
    lastName = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    health_condition = Column(String, default="None")
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)

    date_of_birth = Column(String, nullable=True) # e.g. "March 15, 1995"
    height_cm = Column(Integer, nullable=True)
    current_weight_kg = Column(Float, nullable=True)
    goal_weight_kg = Column(Float, nullable=True)
    goal_calories = Column(Integer, default=2000)
    goal_steps = Column(Integer, default=10000)
    activity_level = Column(String, default="Moderately Active")

    messages = relationship("Message", back_populates="owner")
    reset_code = Column(String(10), nullable=True) 
    reset_code_expires = Column(DateTime(timezone=True), nullable=True)
    


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(String)
    sender = Column(String)  # "user" or "ai"
    timestamp = Column(DateTime, default=datetime.utcnow)

    # A column to store the recipe list as JSON
    recipes = Column(JSON, default=[])
    
    # The "Magic Link": This connects the message to a specific user
    owner_id = Column(Integer, ForeignKey("users.id"))

    # Relationship to easily access user data from a message
    owner = relationship("User", back_populates="messages")