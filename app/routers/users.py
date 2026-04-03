from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone, timedelta
from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/users", tags=["User Dashboard & Tracking"])

@router.get("/{user_id}/profile")
def get_user_profile(user_id: int, db: Session = Depends(get_db)):
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        return {
            "id": user.id,
            "firstName": user.firstName,
            "lastName": user.lastName,
            "email": user.email,
            "dateOfBirth": user.date_of_birth,
            "height_cm": user.height_cm,
            "current_weight_kg": user.current_weight_kg,
            "goal_weight_kg": user.goal_weight_kg,
            "activity_level": user.activity_level,
            "goal_calories": user.goal_calories,
            "goal_steps": user.goal_steps,
            "health_condition": user.health_condition
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch profile: {str(e)}")

@router.put("/update/{user_id}")
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
    
@router.post("/meals/log")
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
    
@router.post("/steps/sync")
def sync_steps(step_data: schemas.StepSync, db: Session = Depends(get_db)):
    try:
        # Check if we already have a row for this exact user and date
        existing_log = db.query(models.DailyStepLog).filter(
            models.DailyStepLog.user_id == step_data.user_id,
            models.DailyStepLog.date == step_data.date
        ).first()

        if existing_log:
            if step_data.steps > existing_log.steps:
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
    
@router.get("/{user_id}/dashboard/today")
def get_today_dashboard(user_id: int, db: Session = Depends(get_db)):
    try:
        today = datetime.now(timezone.utc).date()

        # ---------------------------------------------------------
        # 🌟 1. CALCULATE "DAYS ACTIVE" STREAK
        # ---------------------------------------------------------
        # A. Get all dates where the user did something
        step_dates = db.query(models.DailyStepLog.date).filter(models.DailyStepLog.user_id == user_id, models.DailyStepLog.steps > 0).all()
        meal_dates = db.query(func.date(models.MealLog.created_at)).filter(models.MealLog.user_id == user_id).all()
        workout_dates = db.query(func.date(models.WorkoutLog.created_at)).filter(models.WorkoutLog.user_id == user_id).all()

        # B. Combine them into a single set of unique dates
        active_dates = set()
        for d in step_dates: active_dates.add(d[0])
        for d in meal_dates: active_dates.add(d[0])
        for d in workout_dates: active_dates.add(d[0])

        # C. Run the Streak Algorithm
        streak = 0
        check_date = today

        # The Grace Period Check
        if check_date in active_dates:
            streak += 1
            check_date -= timedelta(days=1)
        elif (check_date - timedelta(days=1)) in active_dates:
            # They haven't logged today yet, but yesterday was active!
            check_date -= timedelta(days=1)
        else:
            # No activity today or yesterday. Streak is dead.
            active_dates = set() # Quick way to skip the while loop

        # Count backwards
        while check_date in active_dates:
            streak += 1
            check_date -= timedelta(days=1)

        # ---------------------------------------------------------
        # 2. FETCH TODAY'S DATA
        # ---------------------------------------------------------
        step_log = db.query(models.DailyStepLog).filter(
            models.DailyStepLog.user_id == user_id,
            models.DailyStepLog.date == today
        ).first()
        today_steps = step_log.steps if step_log else 0

        today_meals = db.query(models.MealLog).filter(
            models.MealLog.user_id == user_id,
            func.date(models.MealLog.created_at) == today
        ).order_by(models.MealLog.created_at.desc()).all()

        today_workouts = db.query(models.WorkoutLog).filter(
            models.WorkoutLog.user_id == user_id,
            func.date(models.WorkoutLog.created_at) == today
        ).order_by(models.WorkoutLog.created_at.desc()).all()

        # 3. Send it all back to Flutter
        return {
            "daysActive": streak, # 🌟 The new streak stat!
            "steps": today_steps,
            "meals": [
                {
                    "name": meal.name, "mealType": meal.meal_type, "calories": meal.calories,
                    "carbs": meal.carbs, "protein": meal.protein, "fats": meal.fats,
                    "sodium": meal.sodium, "sugar": meal.sugar, "time": meal.time_of_day
                } for meal in today_meals
            ],
            "workouts": [
                {
                    "name": workout.name, "type": workout.workout_type,
                    "durationMinutes": workout.duration_minutes, "caloriesBurned": workout.calories_burned,
                    "time": workout.time_of_day
                } for workout in today_workouts
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch dashboard: {str(e)}")
    
@router.post("/workouts/log")
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