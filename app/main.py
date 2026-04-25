import os
import firebase_admin


from fastapi import FastAPI
from . import models
from .database import engine
from .routers import auth, recipes, chat, users 
from fastapi.middleware.cors import CORSMiddleware
from app.database import SessionLocal
from sqlalchemy.orm import Session
from firebase_admin import credentials, messaging
from app.services.notifications import send_fcm_notification
from apscheduler.schedulers.background import BackgroundScheduler






base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
service_account_path = os.path.join(base_dir, "firebase-service-account.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(service_account_path)
    firebase_admin.initialize_app(cred)

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Ghana Recipe AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the routers
app.include_router(auth.router)
app.include_router(recipes.router)
app.include_router(chat.router)
app.include_router(users.router)

@app.get("/")
def root():
    return {"message": "Welcome to the Ghana Recipe AI API"}




# 1. The universal sender function
def send_scheduled_reminders(time_of_day: str):
    db: Session = SessionLocal()
    try:
        # Find all users who have an FCM token
        users = db.query(models.User).filter(models.User.fcm_token != None).all()
        
        for user in users:
            title = ""
            body = ""
            
            # Match the time of day to the correct message
            if time_of_day == "morning":
                title = "☀️ Akwaaba, Good Morning!"
                body = f"Time to start your day, {user.firstName}! Let's make healthy choices today."
            elif time_of_day == "breakfast":
                title = "🍳 Breakfast Time!"
                body = "Did you have Hausa Koko or Waakye today? Don't forget to log it."
            elif time_of_day == "lunch":
                title = "🍛 Lunch Time!"
                body = "Fuel up for the afternoon. Log your lunch when you finish eating!"
            elif time_of_day == "dinner":
                title = "🍲 Dinner Time!"
                body = "Time to wind down. Log your dinner to keep your calories accurate."
            elif time_of_day == "evening":
                title = "🏃 Keep Your Streak Going!"
                body = "The day is almost over. Make sure everything is logged to keep your active record going!"
            
            # Send the push notification
            # NOTE: Ensure your FCM function takes (token, title, body)
            send_fcm_notification(user.fcm_token, title, body)
            
    except Exception as e:
        print(f"❌ Error sending scheduled reminders: {e}")
    finally:
        db.close()

# 2. Start the Scheduler
def start_scheduler():
    
    scheduler = BackgroundScheduler(timezone="UTC") 
    
    # Schedule all the jobs (Uses 24-hour time)
    scheduler.add_job(send_scheduled_reminders, 'cron', hour=8, minute=0, args=["morning"])
    scheduler.add_job(send_scheduled_reminders, 'cron', hour=10, minute=0, args=["breakfast"])
    scheduler.add_job(send_scheduled_reminders, 'cron', hour=14, minute=0, args=["lunch"])
    scheduler.add_job(send_scheduled_reminders, 'cron', hour=20, minute=0, args=["dinner"])
    scheduler.add_job(send_scheduled_reminders, 'cron', hour=21, minute=0, args=["evening"])

    scheduler.start()
    print("⏰ Aduane Background Scheduler Started!")


start_scheduler()

# # Paste this near the bottom of main.py
# @app.get("/test-morning-brief")
# def test_morning_brief():
#     print("🚀 Forcing the 8:00 AM Morning Brief to run NOW...")
#     send_scheduled_reminders("morning")
#     return {"message": "Morning brief trigger sent to Firebase!"}