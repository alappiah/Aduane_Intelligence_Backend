from fastapi import FastAPI
from . import models
from .database import engine
from .routers import auth, recipes, chat # Assuming you make a chat router too
from fastapi.middleware.cors import CORSMiddleware

# Create database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Ghana Recipe AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace "*" with your app's domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the routers
app.include_router(auth.router)
app.include_router(recipes.router)
app.include_router(chat.router)

@app.get("/")
def root():
    return {"message": "Welcome to the Ghana Recipe AI API"}