import json
import os
import subprocess
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent import run_agent
from db import (
    clear_approvals,
    create_session as create_session_record,
    delete_session as delete_session_record,
    find_latest_session_by_workspace,
    get_approval,
    get_session as get_session_record,
    init_db,
    list_sessions as list_session_records,
    save_approval,
    save_session,
    set_approval_decision,
    update_session_metadata,
)
from models import ApprovalDecisionRequest, CreateSessionRequest, RollbackRequest, SessionResponse, SessionRunRequest, UpdateSessionRequest

load_dotenv()
init_db()

app = FastAPI(title="RepoAgent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VALID_MODES = {"refactor", "test", "document"}
ACTIVE_SESSIONS: dict[str, dict] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_session(session_id: str) -> dict:
    session = ACTIVE_SESSIONS.get(session_id)
    if session:
        return session

    session = get_session_record(session_id)
    if not session:
        raise HTTPException(404, f"Session '{session_id}' not found")
    return session


def _get_repo_overview(workspace: str) -> dict:
    if not os.path.isdir(workspace):
        return {
            "branch": None,
            "head_sha": None,
            "dirty": False,
            "status_lines": [],
            "staged_lines": [],
            "unstaged_lines": [],
            "recent_commits": [],
            "rollback_options": [],
        }

    try:
        branch = subprocess.run(
            "git rev-parse --abbrev-ref HEAD",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
            cwd=workspace,
        )
        head_sha = subprocess.run(
            "git rev-parse --short HEAD",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
            cwd=workspace,
        )
        status = subprocess.run(
            "git status --short",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
            cwd=workspace,
        )
        commits = subprocess.run(
            "git log --oneline -n 8",
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
            cwd=workspace,
        )
        status_lines = [line for line in status.stdout.splitlines() if line.strip()]
        staged_lines = [line for line in status_lines if line[:1].strip()]
        unstaged_lines = [line for line in status_lines if len(line) > 1 and line[1:2].strip()]
        return {
            "branch": branch.stdout.strip() or None,
            "head_sha": head_sha.stdout.strip() or None,
            "dirty": bool(status_lines),
            "status_lines": status_lines[:25],
            "staged_lines": staged_lines[:25],
            "unstaged_lines": unstaged_lines[:25],
            "recent_commits": commits.stdout.splitlines()[:8],
            "rollback_options": [
                {"id": "discard_worktree", "label": "Discard local uncommitted changes"},
                {"id": "revert_commit", "label": "Undo a previous commit safely"},
            ],
        }
    except Exception:
        return {
            "branch": None,
            "head_sha": None,
            "dirty": False,
            "status_lines": [],
            "staged_lines": [],
            "unstaged_lines": [],
            "recent_commits": [],
            "rollback_options": [],
        }


def _build_rollback_preview(workspace: str, action: str, value: str | None) -> dict:
    try:
        if action == "discard_worktree":
            status = subprocess.run(
                "git status --short",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
                cwd=workspace,
            )
            preview_lines = [line for line in status.stdout.splitlines() if line.strip()]
            return {
                "action": action,
                "command": "git restore --worktree --staged . && git clean -fd",
                "preview": preview_lines[:25],
            }
        if action == "revert_commit":
            if not value:
                raise HTTPException(400, "A commit SHA is required to revert a commit")
            show = subprocess.run(
                f"git show --stat --oneline --no-patch {value}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
                cwd=workspace,
            )
            return {
                "action": action,
                "command": f"git revert --no-edit {value}",
                "preview": [line for line in show.stdout.splitlines() if line.strip()],
            }
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Rollback preview timed out")
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, str(error))
    raise HTTPException(400, f"Unsupported rollback action '{action}'")


def _execute_rollback(workspace: str, action: str, value: str | None) -> dict:
    try:
        if action == "discard_worktree":
            restore = subprocess.run(
                "git restore --worktree --staged .",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=workspace,
            )
            clean = subprocess.run(
                "git clean -fd",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=workspace,
            )
            return {
                "action": action,
                "stdout": "\n".join(part for part in [restore.stdout.strip(), clean.stdout.strip()] if part),
                "stderr": "\n".join(part for part in [restore.stderr.strip(), clean.stderr.strip()] if part),
                "returncode": restore.returncode or clean.returncode,
            }
        if action == "revert_commit":
            if not value:
                raise HTTPException(400, "A commit SHA is required to revert a commit")
            result = subprocess.run(
                f"git revert --no-edit {value}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=20,
                cwd=workspace,
            )
            return {
                "action": action,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Rollback action timed out")
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, str(error))
    raise HTTPException(400, f"Unsupported rollback action '{action}'")


@app.post("/api/sessions", response_model=SessionResponse)
def create_session(payload: CreateSessionRequest):
    if payload.mode not in VALID_MODES:
        raise HTTPException(400, "mode must be refactor, test, or document")
    if not os.path.isdir(payload.workspace):
        raise HTTPException(400, f"Workspace '{payload.workspace}' is not a valid directory")

    existing_session = find_latest_session_by_workspace(payload.workspace)
    if existing_session:
        return SessionResponse(
            session_id=existing_session["session_id"],
            workspace=existing_session["workspace"],
            mode=existing_session["mode"],
            busy=existing_session["busy"],
        )

    session = {
        "session_id": str(uuid4()),
        "workspace": payload.workspace,
        "mode": payload.mode,
        "busy": False,
        "starred": False,
        "title_override": None,
        "messages": [],
        "turn_summaries": [],
        "workspace_facts": [],
        "turn_history": [],
        "approvals": {},
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    create_session_record(session)
    return SessionResponse(
        session_id=session["session_id"],
        workspace=session["workspace"],
        mode=session["mode"],
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


@app.get("/api/sessions")
def list_sessions():
    return {"sessions": list_session_records()}


@app.patch("/api/sessions/{session_id}")
def update_session(session_id: str, payload: UpdateSessionRequest):
    session = update_session_metadata(session_id, starred=payload.starred, title=payload.title)
    if not session:
        raise HTTPException(404, f"Session '{session_id}' not found")
    ACTIVE_SESSIONS[session_id] = session
    return {
        "session_id": session["session_id"],
        "starred": session.get("starred", False),
        "title": session.get("title_override"),
    }


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    existing = get_session_record(session_id)
    if not existing:
        raise HTTPException(404, f"Session '{session_id}' not found")
    delete_session_record(session_id)
    ACTIVE_SESSIONS.pop(session_id, None)
    return {"deleted": True, "session_id": session_id}


@app.get("/api/sessions/{session_id}/history")
def get_session_history(session_id: str):
    session = _get_session(session_id)
    return {
        "session_id": session["session_id"],
        "workspace": session["workspace"],
        "turn_history": session.get("turn_history", []),
    }


@app.get("/api/sessions/{session_id}/repo")
def get_session_repo(session_id: str):
    session = _get_session(session_id)
    return _get_repo_overview(session["workspace"])


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
    session["approvals"] = {}
    clear_approvals(session_id)
    save_session(session)
    ACTIVE_SESSIONS[session_id] = session

    async def event_stream():
        try:
            async for event in run_agent(
                goal=payload.goal,
                mode=mode,
                workspace=session["workspace"],
                conversation_messages=session["messages"],
                turn_summaries=session["turn_summaries"],
                session_state=session,
            ):
                session["updated_at"] = _utc_now()
                save_session(session)
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        finally:
            session["busy"] = False
            session["updated_at"] = _utc_now()
            save_session(session)
            ACTIVE_SESSIONS.pop(session_id, None)

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


@app.post("/api/sessions/{session_id}/approvals/{approval_id}")
def decide_approval(session_id: str, approval_id: str, payload: ApprovalDecisionRequest):
    session = _get_session(session_id)
    approval = session.get("approvals", {}).get(approval_id)
    if not approval:
        db_approval = get_approval(session_id, approval_id)
        if not db_approval:
            raise HTTPException(404, f"Approval '{approval_id}' not found")
        approval = db_approval
        session.setdefault("approvals", {})[approval_id] = approval
    if approval.get("decision") is not None:
        raise HTTPException(409, "This approval has already been decided")

    approval["decision"] = payload.decision
    approval["updated_at"] = _utc_now()
    session["updated_at"] = _utc_now()
    set_approval_decision(session_id, approval_id, payload.decision, approval["updated_at"])
    save_session(session)
    return {"approval_id": approval_id, "decision": payload.decision}


@app.post("/api/sessions/{session_id}/rollback/preview")
def preview_rollback(session_id: str, payload: RollbackRequest):
    session = _get_session(session_id)
    return _build_rollback_preview(session["workspace"], payload.action, payload.value)


@app.post("/api/sessions/{session_id}/rollback/execute")
def execute_rollback(session_id: str, payload: RollbackRequest):
    session = _get_session(session_id)
    result = _execute_rollback(session["workspace"], payload.action, payload.value)
    session["updated_at"] = _utc_now()
    save_session(session)
    return result


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model": "llama-3.3-70b-versatile",
        "database": "sqlite",
    }
