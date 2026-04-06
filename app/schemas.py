from pydantic import BaseModel, field_validator
from datetime import datetime, date
from typing import List, Optional, Any
import json



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
    date_of_birth: Optional[str] = None
    height_cm: Optional[int] = None
    current_weight_kg: Optional[float] = None
    goal_weight_kg: Optional[float] = None
    goal_calories: Optional[int] = 2000
    goal_steps: Optional[int] = 10000
    activity_level: Optional[str] = "Moderately Active"

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

    # 🌟 THE FIX: This intercepts the string from the database and turns it back into a list!
    @field_validator('recipes', mode='before')
    @classmethod
    def parse_recipes_string(cls, value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return []
        return value or []

    class Config:
        from_attributes = True

class MessageCreate(MessageBase):
    pass

class Message(MessageBase):
    id: int
    owner_id: int
    timestamp: datetime

    # recipes: List[Any] = []
    class Config:
        from_attributes = True

class RecipeRequest(BaseModel):
    query: str
    health_condition: str
    current_calories: Optional[int] = 0 # How much they ate today
    calorie_goal: Optional[int] = 2000
    current_weight_kg: Optional[float] = None
    goal_weight_kg: Optional[float] = None

class ChatRequest(BaseModel):
    query: str
    health_condition: str
    current_calories: Optional[int] = 0 # How much they ate today
    calorie_goal: Optional[int] = 2000
    current_weight_kg: Optional[float] = None
    goal_weight_kg: Optional[float] = None

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

class ChangePasswordRequest(BaseModel):
    user_id: int
    current_password: str
    new_password: str

class MealCreate(BaseModel):
    user_id: int  # We need to know WHO ate the food!
    name: str
    mealType: str
    calories: int
    carbs: Optional[int] = 0
    protein: Optional[int] = 0
    fats: Optional[int] = 0
    sodium: Optional[int] = 0
    sugar: Optional[int] = 0
    time: str  # e.g., "12:30 PM"

class StepSync(BaseModel):
    user_id: int
    date: date
    steps: int
    calories_burned: int

class WorkoutCreate(BaseModel):
    user_id: int
    name: str
    type: str  
    durationMinutes: int
    caloriesBurned: int
    time: str

class AchievementBase(BaseModel):
    achievement_key: str

class AchievementCreate(AchievementBase):
    user_id: int

class Achievement(AchievementBase):
    id: int
    achieved_at: datetime

    class Config:
        from_attributes = True

# 🌟 Add these first
class MealLogSchema(BaseModel):
    id: int
    name: str
    meal_type: Optional[str]
    time_of_day: Optional[str]
    calories: int
    carbs: int
    protein: int
    fats: int
    sodium: int
    sugar: int
    created_at: datetime

    class Config:
        from_attributes = True # This allows Pydantic to read SQLAlchemy objects

class WorkoutLogSchema(BaseModel):
    id: int
    name: str
    workout_type: Optional[str]
    duration_minutes: int
    calories_burned: int
    time_of_day: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class DailyAggregate(BaseModel):
    date: date
    steps: int = 0
    calories_consumed: int = 0
    calories_burned: int = 0

class WeeklyStatsResponse(BaseModel):
    daily_summary: List[DailyAggregate]
    meals: List[MealLogSchema] # This should match your MealLog Pydantic schema
    workouts: List[WorkoutLogSchema] # This should match your WorkoutLog Pydantic schema

    class Config:
        from_attributes = True


class FCMTokenUpdate(BaseModel):
    fcm_token: str