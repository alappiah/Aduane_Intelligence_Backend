from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from .. import crud, schemas, auth, models
from ..database import get_db
import random, os, smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from ..schemas import ForgotPasswordRequest, ResetPasswordRequest, StepSync, ChangePasswordRequest
from ..auth import verify_password, get_password_hash
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/signup", response_model=schemas.User)
def signup(user: schemas.UserCreate, db: Session = Depends(get_db)):
    print(f"📝 New signup attempt for email: {user.email}")
    
    # Check if the user already exists
    db_user = crud.get_user_by_email(db, email=user.email)
    if db_user:
      raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create the user in the database
    new_user = crud.create_user(db=db, user=user)
    return new_user

@router.post("/login", response_model=schemas.User)
def login(user_credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    print(f"🔐 Login attempt for email: {user_credentials.email}")
    
    # Search for the user by email
    db_user = crud.get_user_by_email(db, email=user_credentials.email)
    
    # Reject them if the email does not exist
    if not db_user:
        raise HTTPException(status_code=403, detail="Invalid Credentials")
        
    # Check if the password matches the scrambled hash in the database
    if not auth.verify_password(user_credentials.password, str(db_user.hashed_password)):
        raise HTTPException(status_code=403, detail="Invalid Credentials")
        
    # If everything matches, return the user's profile data
    print("✅ Login successful!")
    return db_user



def send_reset_email(to_email: str, first_name: str, code: str):
   
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

    
    print(f"🕵️ DEBUG Email: '{sender_email}'")
    print(f"🕵️ DEBUG Password Length: {len(str(sender_password))} characters")

    try:
        
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        
       
        
        server.login(str(sender_email), str(sender_password))
        server.send_message(msg)
        server.quit()
        print(f"📧 Reset email sent successfully to {to_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")



@router.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    print(f"🔐 Password reset requested for: {request.email}")
    
    # Find the user in the database
    user = db.query(models.User).filter(models.User.email == request.email).first()
    
    
    if not user:
        return {"message": "If that email exists in our system, a reset code has been sent."}
    
    # Generate a random 6-digit code
    reset_code = str(random.randint(100000, 999999))
    
    # Set expiration time to 15 minutes from now (using UTC for safety)
    expiration_time = datetime.now(timezone.utc) + timedelta(minutes=15)
    
    # Save to the database 

    user.reset_code = reset_code  # type: ignore
    user.reset_code_expires = expiration_time  # type: ignore
    db.commit()
    
    # Send the email 
   
    send_reset_email(str(user.email), str(user.firstName), reset_code)
    
    return {"message": "If that email exists in our system, a reset code has been sent."}

@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    print(f"🔄 Password reset attempt for: {request.email}")
    
    # Find the user
    user = db.query(models.User).filter(models.User.email == request.email).first()
    
    if not user:
        raise HTTPException(status_code=400, detail="Invalid email or reset code.")
        
    # Check if the code matches
    if str(user.reset_code) != request.reset_code:
        raise HTTPException(status_code=400, detail="Invalid reset code.")
        
    #  Check if the code has expired (using UTC to match how it was saved)
    if user.reset_code_expires is None or datetime.now(timezone.utc) > user.reset_code_expires:
        raise HTTPException(status_code=400, detail="Reset code has expired. Please request a new one.")
        
    # Hash the new password 
    hashed_pw = auth.get_password_hash(request.new_password) 
    
    # Update the database
    user.password = hashed_pw  # type: ignore
    
    # Wipe the code so it can't be used again
    user.reset_code = None  # type: ignore
    user.reset_code_expires = None  # type: ignore
    
    db.commit()
    
    print("✅ Password successfully reset!")
    return {"message": "Password has been reset successfully. You can now log in."}

@router.post("/change-password")
async def change_password(request: ChangePasswordRequest, db: Session = Depends(get_db)):
    # Find the user
    user = db.query(models.User).filter(models.User.id == request.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Verify the current password
    if not verify_password(request.current_password, str(user.hashed_password)):
        raise HTTPException(status_code=400, detail="Incorrect current password")

    # Hash the new password and save it
    user.hashed_password = get_password_hash(request.new_password)
    db.commit()

    return {"message": "Password updated successfully"}