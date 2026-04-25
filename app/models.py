from sqlalchemy import Column, Float, Integer, String, Boolean, ForeignKey, DateTime, JSON, Date, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
from datetime import datetime, timezone
from pgvector.sqlalchemy import Vector




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
    fcm_token = Column(String, nullable=True)

    messages = relationship("Message", back_populates="owner", cascade="all, delete-orphan")
    meals = relationship("MealLog", back_populates="owner", cascade="all, delete-orphan")
    step_logs = relationship("DailyStepLog", back_populates="owner", cascade="all, delete-orphan")
    workouts = relationship("WorkoutLog", back_populates="owner", cascade="all, delete-orphan")
    achievements = relationship("Achievement", back_populates="user", cascade="all, delete-orphan")
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

    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    
    # The "Magic Link": This connects the message to a specific user
    owner_id = Column(Integer, ForeignKey("users.id"))

    # Relationship to easily access user data from a message
    owner = relationship("User", back_populates="messages")


class MealLog(Base):
    __tablename__ = "meal_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    name = Column(String, index=True, nullable=False)
    meal_type = Column(String) 
    time_of_day = Column(String) # Stores "12:30 PM"
    
    # Macros & Medical
    calories = Column(Integer, nullable=False)
    carbs = Column(Integer, default=0)
    protein = Column(Integer, default=0)
    fats = Column(Integer, default=0)
    sodium = Column(Integer, default=0)
    sugar = Column(Integer, default=0)
    
    # Auto-generates the exact timestamp when they hit "Save"
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Links back to the User table
    owner = relationship("User", back_populates="meals")

class DailyStepLog(Base):
    __tablename__ = "daily_step_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # We use Date because we only care about the specific day (e.g., 2026-03-25)
    date = Column(Date, nullable=False) 
    steps = Column(Integer, default=0)
    calories_burned = Column(Integer, default=0)
    # Links back to the User table
    owner = relationship("User", back_populates="step_logs")

class WorkoutLog(Base):
    __tablename__ = "workout_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    name = Column(String, nullable=False)
    workout_type = Column(String) 
    duration_minutes = Column(Integer, default=0)
    calories_burned = Column(Integer, default=0)
    time_of_day = Column(String)
    
    # Auto-generates the exact timestamp when they hit "Save"
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Links back to the User table
    owner = relationship("User", back_populates="workouts")



class MedicalGuideline(Base):
    __tablename__ = "medical_guidelines"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, nullable=False)
    metadata_json = Column(JSON) 
    embedding = Column(Vector(384))

class Recipe(Base):
    __tablename__ = "recipes"
    id = Column(Integer, primary_key=True)
    name = Column(String, index=True)
    description = Column(String)
    ingredients = Column(String)
    instructions = Column(String)
    calories = Column(Integer)
    carbs_g = Column(Float)
    protein_g = Column(Float)
    fat_total_g = Column(Float)
    fat_saturated_g = Column(Float)
    sodium_mg = Column(Float)
    sugar_g = Column(Float)
    fiber_g = Column(Float)
    potassium_mg = Column(Float)
    iron_mg = Column(Float)
    meal_type = Column(String)
    tags = Column(String)
    image_url = Column(String)
    embedding = Column(Vector(384)) # For vector search in Supabase

class Achievement(Base):
    __tablename__ = "achievements"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # The 'key' is the unique identifier (e.g., 'first_steps', 'market_navigator')
    achievement_key = Column(String, nullable=False)
    
    # Automatically set the time when the badge is earned
    achieved_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships (Optional, but helpful for querying)
    user = relationship("User", back_populates="achievements")

    # 🌟 CRITICAL: This prevents a user from earning the same badge twice.
    __table_args__ = (
        UniqueConstraint('user_id', 'achievement_key', name='_user_achievement_uc'),
    )