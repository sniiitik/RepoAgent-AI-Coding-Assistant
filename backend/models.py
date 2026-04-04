from pydantic import BaseModel, Field
from typing import Literal, Any


# ── Request schemas ────────────────────────────────────────────────

class RunRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=2000, description="What the agent should do")
    mode: Literal["refactor", "test", "document"] = Field(..., description="Agent operating mode")
    workspace: str = Field(..., min_length=1, description="Absolute path to the project directory")


class CreateSessionRequest(BaseModel):
    workspace: str = Field(..., min_length=1, description="Absolute path to the project directory")
    mode: Literal["refactor", "test", "document"] = Field("refactor", description="Default agent operating mode")


class SessionRunRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=2000, description="What the agent should do next")
    mode: Literal["refactor", "test", "document"] | None = Field(None, description="Optional mode override for this message")

class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]


class RollbackRequest(BaseModel):
    action: Literal["discard_worktree", "revert_commit"]
    value: str | None = None


class UpdateSessionRequest(BaseModel):
    starred: bool | None = None
    title: str | None = Field(None, max_length=120)


class SessionResponse(BaseModel):
    session_id: str
    workspace: str
    mode: Literal["refactor", "test", "document"]
    busy: bool


# ── Agent event schemas (streamed via SSE) ─────────────────────────

class ThoughtEvent(BaseModel):
    type: Literal["thought"] = "thought"
    content: str

class PlanEvent(BaseModel):
    type: Literal["plan"] = "plan"
    content: str

class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool: str
    args: dict[str, Any]

class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool: str
    result: dict[str, Any]

class ApprovalRequiredEvent(BaseModel):
    type: Literal["approval_required"] = "approval_required"
    approval_id: str
    tool: str
    args: dict[str, Any]
    reason: str
    severity: Literal["safe", "risky", "destructive"]
    actions: list[dict[str, Any]] = Field(default_factory=list)

class FileChange(BaseModel):
    path: str
    original: str | None       # None if file is newly created
    new_content: str

class FileChangedEvent(BaseModel):
    type: Literal["file_changed"] = "file_changed"
    path: str
    original: str | None
    new_content: str

class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    content: str
    changed_files: list[FileChange]
    iterations: int

class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    content: str


# Union type for all possible streamed events
AgentEvent = (
    ThoughtEvent
    | PlanEvent
    | ToolCallEvent
    | ToolResultEvent
    | ApprovalRequiredEvent
    | FileChangedEvent
    | DoneEvent
    | ErrorEvent
)


# ── Response schemas ───────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    model: str
