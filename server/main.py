from fastapi import FastAPI

from server.callbacks.router import router as callback_router
from typing import Dict

app = FastAPI(
    title="ABDM Sandbox API",
    version="1.0.0"
)

app.include_router(callback_router)

@app.get("/")
def home():
    return {"message": "Hello from my ABDM Backend!"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/echo")
def echo(data: Dict):
    return {
        "received": data
    }