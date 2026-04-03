import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent import run_agent
from models import CreateSessionRequest, SessionResponse, SessionRunRequest

load_dotenv()

app = FastAPI(title="RepoAgent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VALID_MODES = {"refactor", "test", "document"}
SESSIONS: dict[str, dict] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_session(session_id: str) -> dict:
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, f"Session '{session_id}' not found")
    return session


@app.post("/api/sessions", response_model=SessionResponse)
def create_session(payload: CreateSessionRequest):
    if payload.mode not in VALID_MODES:
        raise HTTPException(400, "mode must be refactor, test, or document")
    if not os.path.isdir(payload.workspace):
        raise HTTPException(400, f"Workspace '{payload.workspace}' is not a valid directory")

    session_id = str(uuid4())
    SESSIONS[session_id] = {
        "session_id": session_id,
        "workspace": payload.workspace,
        "mode": payload.mode,
        "busy": False,
        "messages": [],
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    return SessionResponse(
        session_id=session_id,
        workspace=payload.workspace,
        mode=payload.mode,
        busy=False,
    )


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str):
    session = _get_session(session_id)
    return SessionResponse(
        session_id=session["session_id"],
        workspace=session["workspace"],
        mode=session["mode"],
        busy=session["busy"],
    )


@app.post("/api/sessions/{session_id}/run")
async def run_session(session_id: str, payload: SessionRunRequest):
    session = _get_session(session_id)
    if session["busy"]:
        raise HTTPException(409, "This session is already running a request")

    mode = payload.mode or session["mode"]
    if mode not in VALID_MODES:
        raise HTTPException(400, "mode must be refactor, test, or document")

    session["mode"] = mode
    session["busy"] = True
    session["updated_at"] = _utc_now()

    async def event_stream():
        try:
            async for event in run_agent(
                goal=payload.goal,
                mode=mode,
                workspace=session["workspace"],
                conversation_messages=session["messages"],
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        finally:
            session["busy"] = False
            session["updated_at"] = _utc_now()

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model": "llama-3.3-70b-versatile",
    }
