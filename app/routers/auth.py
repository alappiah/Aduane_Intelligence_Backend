from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .. import crud, schemas, auth
from ..database import get_db

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