import json
import os
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

from agent import run_agent

load_dotenv()

app = FastAPI(title="RepoAgent API")

# ✅ CORS (required for frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # you can restrict later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ SSE endpoint (GET + POST, for UI and direct URL calls)
@app.api_route("/api/run", methods=["GET", "POST"])
async def run(
    request: Request,
    goal: str | None = Query(None, min_length=1),
    mode: str | None = Query(None),
    workspace: str | None = Query(None)
):
    # Support POST body from frontend + GET query params
    if request.method == "POST":
        body = await request.json()
        if isinstance(body, dict):
            goal = body.get("goal", goal)
            mode = body.get("mode", mode)
            workspace = body.get("workspace", workspace)

    if not goal or not mode or not workspace:
        raise HTTPException(400, "goal, mode, and workspace are required")

    if mode not in ("refactor", "test", "document"):
        raise HTTPException(400, "mode must be refactor, test, or document")

    # Validate workspace
    if not os.path.isdir(workspace):
        raise HTTPException(400, f"Workspace '{workspace}' is not a valid directory")

    async def event_stream():
        try:
            async for event in run_agent(goal, mode, workspace):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

        # Signal completion
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


# ✅ Health check
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model": "llama-3.3-70b-versatile"
    }