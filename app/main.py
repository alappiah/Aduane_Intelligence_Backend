from fastapi import FastAPI
from . import models
from .database import engine
from .routers import auth, recipes, chat # Assuming you make a chat router too

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Ghana Recipe AI")

# Include the routers
app.include_router(auth.router)
app.include_router(recipes.router)
app.include_router(chat.router)

@app.get("/")
def root():
    return {"message": "Welcome to the Ghana Recipe AI API"}