# keep_alive.py - UptimeRobot üçün FastAPI ping serveri
from fastapi import FastAPI
import uvicorn
import asyncio

app = FastAPI(title="Raven Music", version="1.0.0")

@app.get("/")
async def root():
    return {
        "status": "alive",
        "bot": "Raven Music Userbot",
        "message": "🎵 Raven Music is running!"
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/ping")
async def ping():
    return {"ping": "pong"}
