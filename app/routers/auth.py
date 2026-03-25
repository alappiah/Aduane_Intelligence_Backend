from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from .. import crud, schemas, auth, models
from ..database import get_db
import random, os, smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from ..schemas import ForgotPasswordRequest, ResetPasswordRequest, StepSync
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/signup", response_model=schemas.User)
def signup(user: schemas.UserCreate, db: Session = Depends(get_db)):
    print(f"📝 New signup attempt for email: {user.email}")
    
    # 1. Check if the user already exists
    db_user = crud.get_user_by_email(db, email=user.email)
    if db_user:
      raise HTTPException(status_code=400, detail="Email already registered")
    
    # 2. Create the user in the database
    new_user = crud.create_user(db=db, user=user)
    return new_user

@router.post("/login", response_model=schemas.User)
def login(user_credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    print(f"🔐 Login attempt for email: {user_credentials.email}")
    
    # 1. Search for the user by email
    db_user = crud.get_user_by_email(db, email=user_credentials.email)
    
    # If the email isn't in the database, reject them
    if not db_user:
        raise HTTPException(status_code=403, detail="Invalid Credentials")
        
    # 2. Check if the password matches the scrambled hash in the database
    if not auth.verify_password(user_credentials.password, str(db_user.hashed_password)):
        raise HTTPException(status_code=403, detail="Invalid Credentials")
        
    # 3. If everything matches, return the user's profile data!
    print("✅ Login successful!")
    return db_user


# --- HELPER: SEND EMAIL ---
def send_reset_email(to_email: str, first_name: str, code: str):
    # ⚠️ For your capstone, use a dedicated project Gmail account
    sender_email = os.getenv("EMAIL_SENDER")
    sender_password = os.getenv("EMAIL_PASSWORD") 

    subject = "Aduane Intelligence - Password Reset Code"
    body = f"""
    Hello {first_name},

    You requested a password reset for your Aduane Intelligence account.
    
    Your 6-digit reset code is: {code}
    
    This code will expire in 15 minutes. If you did not request this, please ignore this email.
    """

    msg = MIMEMultipart()
    msg['From'] = "Aduane Intelligence Support"
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    # Add these right above 'try:'
    print(f"🕵️ DEBUG Email: '{sender_email}'")
    print(f"🕵️ DEBUG Password Length: {len(str(sender_password))} characters")

    try:
        # 🌟 THE FIX: Use SMTP_SSL and Port 465
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        
        # NOTE: We deleted server.starttls() because Port 465 is already secure!
        
        server.login(str(sender_email), str(sender_password))
        server.send_message(msg)
        server.quit()
        print(f"📧 Reset email sent successfully to {to_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


# --- ENDPOINT: FORGOT PASSWORD ---
@router.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    print(f"🔐 Password reset requested for: {request.email}")
    
    # 1. Find the user in the database
    user = db.query(models.User).filter(models.User.email == request.email).first()
    
    # Security Best Practice: Always return a success message even if the email doesn't exist.
    if not user:
        return {"message": "If that email exists in our system, a reset code has been sent."}
    
    # 2. Generate a random 6-digit code
    reset_code = str(random.randint(100000, 999999))
    
    # 3. Set expiration time to 15 minutes from now (using UTC for safety)
    expiration_time = datetime.now(timezone.utc) + timedelta(minutes=15)
    
    # 4. Save to the database 
    # (Adding type: ignore tells VS Code's Pylance to stop worrying about SQLAlchemy Columns)
    user.reset_code = reset_code  # type: ignore
    user.reset_code_expires = expiration_time  # type: ignore
    db.commit()
    
    # 5. Send the email! 
    # (Wrapping in str() forces Pylance to recognize these are strings, not Column objects)
    send_reset_email(str(user.email), str(user.firstName), reset_code)
    
    return {"message": "If that email exists in our system, a reset code has been sent."}

@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    print(f"🔄 Password reset attempt for: {request.email}")
    
    # 1. Find the user
    user = db.query(models.User).filter(models.User.email == request.email).first()
    
    if not user:
        raise HTTPException(status_code=400, detail="Invalid email or reset code.")
        
    # 2. Check if the code matches
    if str(user.reset_code) != request.reset_code:
        raise HTTPException(status_code=400, detail="Invalid reset code.")
        
    # 3. Check if the code has expired (using UTC to match how we saved it)
    if user.reset_code_expires is None or datetime.now(timezone.utc) > user.reset_code_expires:
        raise HTTPException(status_code=400, detail="Reset code has expired. Please request a new one.")
        
    # 4. Hash the new password (assuming you have a get_password_hash function in your auth file)
    # If your signup uses a different function name to hash passwords, use that here!
    hashed_pw = auth.get_password_hash(request.new_password) 
    
    # 5. Update the database
    user.password = hashed_pw  # type: ignore
    
    # 6. VERY IMPORTANT: Wipe the code so it can't be used again!
    user.reset_code = None  # type: ignore
    user.reset_code_expires = None  # type: ignore
    
    db.commit()
    
    print("✅ Password successfully reset!")
    return {"message": "Password has been reset successfully. You can now log in."}

@router.put("/users/update/{user_id}")
def update_user_profile(user_id: int, profile_data: schemas.UserUpdate, db: Session = Depends(get_db)):
    # 1. Find the exact user in the database
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    
    # 2. If they don't exist, throw a 404
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # 3. Update all the fields (Adding type: ignore to bypass Pylance false positives)
    db_user.firstName = profile_data.firstName  # type: ignore
    db_user.lastName = profile_data.lastName  # type: ignore
    db_user.date_of_birth = profile_data.date_of_birth  # type: ignore
    db_user.height_cm = profile_data.height_cm  # type: ignore
    db_user.current_weight_kg = profile_data.current_weight_kg  # type: ignore
    db_user.goal_weight_kg = profile_data.goal_weight_kg  # type: ignore
    db_user.goal_calories = profile_data.goal_calories  # type: ignore
    db_user.goal_steps = profile_data.goal_steps  # type: ignore
    db_user.activity_level = profile_data.activity_level  # type: ignore
    db_user.health_condition = profile_data.health_condition  # type: ignore

    # 4. Commit the changes to the PostgreSQL database
    try:
        db.commit()
        db.refresh(db_user)
        return {"message": "Profile updated successfully", "user_id": db_user.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update profile: {str(e)}")
    
@router.post("/users/meals/log")
def log_meal(meal_data: schemas.MealCreate, db: Session = Depends(get_db)):
    try:
        # 1. Map the incoming Pydantic schema to our SQLAlchemy Database Model
        new_meal = models.MealLog(
            user_id=meal_data.user_id,
            name=meal_data.name,
            meal_type=meal_data.mealType,
            time_of_day=meal_data.time,
            calories=meal_data.calories,
            carbs=meal_data.carbs,
            protein=meal_data.protein,
            fats=meal_data.fats,
            sodium=meal_data.sodium,
            sugar=meal_data.sugar
        )
        
        # 2. Save it to Postgres!
        db.add(new_meal)
        db.commit()
        db.refresh(new_meal)
        
        print(f"✅ Successfully logged {new_meal.calories} kcal for User {new_meal.user_id}")
        return {"message": "Meal logged successfully!", "meal_id": new_meal.id}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to log meal: {str(e)}")
    
@router.post("/users/steps/sync")
def sync_steps(step_data: schemas.StepSync, db: Session = Depends(get_db)):
    try:
        # Check if we already have a row for this exact user and date
        existing_log = db.query(models.DailyStepLog).filter(
            models.DailyStepLog.user_id == step_data.user_id,
            models.DailyStepLog.date == step_data.date
        ).first()

        if existing_log:
            # Overwrite the old number with the new, higher number
            existing_log.steps = step_data.steps 
        else:
            # First sync of the day! Create a new row.
            new_log = models.DailyStepLog(
                user_id=step_data.user_id,
                date=step_data.date,
                steps=step_data.steps
            )
            db.add(new_log)
            
        db.commit()
        return {"message": "Steps synced successfully!"}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to sync steps: {str(e)}")
    
@router.get("/users/{user_id}/dashboard/today")
def get_today_dashboard(user_id: int, db: Session = Depends(get_db)):
    try:
        today = datetime.now(timezone.utc).date()

        # 1. Fetch Steps
        step_log = db.query(models.DailyStepLog).filter(
            models.DailyStepLog.user_id == user_id,
            models.DailyStepLog.date == today
        ).first()
        today_steps = step_log.steps if step_log else 0

        # 2. Fetch Meals
        today_meals = db.query(models.MealLog).filter(
            models.MealLog.user_id == user_id,
            func.date(models.MealLog.created_at) == today
        ).order_by(models.MealLog.created_at.desc()).all()

        # 🌟 3. NEW: Fetch Workouts!
        today_workouts = db.query(models.WorkoutLog).filter(
            models.WorkoutLog.user_id == user_id,
            func.date(models.WorkoutLog.created_at) == today
        ).order_by(models.WorkoutLog.created_at.desc()).all()

        # 4. Send it all back to Flutter
        return {
            "steps": today_steps,
            "meals": [
                {
                    "name": meal.name,
                    "mealType": meal.meal_type,
                    "calories": meal.calories,
                    "carbs": meal.carbs,
                    "protein": meal.protein,
                    "fats": meal.fats,
                    "sodium": meal.sodium,
                    "sugar": meal.sugar,
                    "time": meal.time_of_day
                } for meal in today_meals
            ],
            # 🌟 NEW: Add workouts to the JSON package
            "workouts": [
                {
                    "name": workout.name,
                    "type": workout.workout_type,
                    "durationMinutes": workout.duration_minutes,
                    "caloriesBurned": workout.calories_burned,
                    "time": workout.time_of_day
                } for workout in today_workouts
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch dashboard: {str(e)}")
    
@router.post("/users/workouts/log")
def log_workout(workout_data: schemas.WorkoutCreate, db: Session = Depends(get_db)):
    try:
        # 1. Map the incoming JSON to our Database Model
        new_workout = models.WorkoutLog(
            user_id=workout_data.user_id,
            name=workout_data.name,
            workout_type=workout_data.type,
            duration_minutes=workout_data.durationMinutes,
            calories_burned=workout_data.caloriesBurned,
            time_of_day=workout_data.time
        )
        
        # 2. Save it to Postgres!
        db.add(new_workout)
        db.commit()
        db.refresh(new_workout)
        
        print(f"✅ Successfully logged {new_workout.duration_minutes} min workout for User {new_workout.user_id}")
        return {"message": "Workout logged successfully!", "workout_id": new_workout.id}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to log workout: {str(e)}")