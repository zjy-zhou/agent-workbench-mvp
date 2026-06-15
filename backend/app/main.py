from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.agent import run_agent
from backend.app.models import ChatRequest, ChatResponse
from backend.app.tools import registry


BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="Agent Workbench MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": "agent-workbench-mvp"}


@app.get("/api/tools")
def list_tools() -> list[dict]:
    return [tool.model_dump() for tool in registry.definitions()]


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return run_agent(message=request.message, user_id=request.user_id)


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

