import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "repoagent.db"


def set_db_path(path: str | Path) -> None:
    global DB_PATH
    DB_PATH = Path(path)


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                workspace TEXT NOT NULL,
                mode TEXT NOT NULL,
                busy INTEGER NOT NULL DEFAULT 0,
                starred INTEGER NOT NULL DEFAULT 0,
                title_override TEXT,
                messages TEXT NOT NULL DEFAULT '[]',
                turn_summaries TEXT NOT NULL DEFAULT '[]',
                workspace_facts TEXT NOT NULL DEFAULT '[]',
                turn_history TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                tool TEXT NOT NULL,
                args TEXT NOT NULL DEFAULT '{}',
                decision TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_approvals_session_id ON approvals(session_id);
            """
        )
        _ensure_column(conn, "sessions", "turn_history", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "sessions", "starred", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "sessions", "title_override", "TEXT")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _encode(value: Any) -> str:
    return json.dumps(value)


def _decode_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _row_to_session(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "session_id": row["session_id"],
        "workspace": row["workspace"],
        "mode": row["mode"],
        "busy": bool(row["busy"]),
        "starred": bool(row["starred"]),
        "title_override": row["title_override"],
        "messages": _decode_json(row["messages"], []),
        "turn_summaries": _decode_json(row["turn_summaries"], []),
        "workspace_facts": _decode_json(row["workspace_facts"], []),
        "turn_history": _decode_json(row["turn_history"], []),
        "approvals": load_approvals(row["session_id"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_session(session: dict[str, Any]) -> dict[str, Any]:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id, workspace, mode, busy, starred, title_override, messages, turn_summaries,
                workspace_facts, turn_history, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session["session_id"],
                session["workspace"],
                session["mode"],
                int(bool(session["busy"])),
                int(bool(session.get("starred", False))),
                session.get("title_override"),
                _encode(session["messages"]),
                _encode(session["turn_summaries"]),
                _encode(session["workspace_facts"]),
                _encode(session.get("turn_history", [])),
                session["created_at"],
                session["updated_at"],
            ),
        )
    return session


def get_session(session_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if not row:
        return None
    return _row_to_session(row)


def save_session(session: dict[str, Any]) -> dict[str, Any]:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET workspace = ?, mode = ?, busy = ?, starred = ?, title_override = ?, messages = ?, turn_summaries = ?,
                workspace_facts = ?, turn_history = ?, updated_at = ?
            WHERE session_id = ?
            """,
            (
                session["workspace"],
                session["mode"],
                int(bool(session["busy"])),
                int(bool(session.get("starred", False))),
                session.get("title_override"),
                _encode(session["messages"]),
                _encode(session["turn_summaries"]),
                _encode(session["workspace_facts"]),
                _encode(session.get("turn_history", [])),
                session["updated_at"],
                session["session_id"],
            ),
        )
    return session


def list_sessions(limit: int = 30) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT session_id, workspace, mode, busy, starred, title_override, turn_history, created_at, updated_at
            FROM sessions
            ORDER BY starred DESC, updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    sessions = []
    for row in rows:
        turn_history = _decode_json(row["turn_history"], [])
        last_turn = turn_history[-1] if turn_history else {}
        title = row["title_override"] or last_turn.get("goal") or Path(row["workspace"]).name or row["workspace"]
        sessions.append(
            {
                "session_id": row["session_id"],
                "workspace": row["workspace"],
                "mode": row["mode"],
                "busy": bool(row["busy"]),
                "starred": bool(row["starred"]),
                "title_override": row["title_override"],
                "title": title[:80],
                "last_updated": row["updated_at"],
                "turn_count": len(turn_history),
            }
        )
    return sessions


def find_latest_session_by_workspace(workspace: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM sessions
            WHERE workspace = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (workspace,),
        ).fetchone()
    if not row:
        return None
    return _row_to_session(row)


def update_session_metadata(session_id: str, *, starred: bool | None = None, title: str | None = None) -> dict[str, Any] | None:
    session = get_session(session_id)
    if not session:
        return None
    if starred is not None:
        session["starred"] = bool(starred)
    if title is not None:
        session["title_override"] = title.strip() or None
    save_session(session)
    return session


def delete_session(session_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM approvals WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def clear_approvals(session_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM approvals WHERE session_id = ?", (session_id,))


def load_approvals(session_id: str) -> dict[str, dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT approval_id, tool, args, decision, created_at, updated_at FROM approvals WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    return {
        row["approval_id"]: {
            "tool": row["tool"],
            "args": _decode_json(row["args"], {}),
            "decision": row["decision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    }


def save_approval(
    session_id: str,
    approval_id: str,
    tool: str,
    args: dict[str, Any],
    decision: str | None,
    created_at: str,
    updated_at: str,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO approvals (approval_id, session_id, tool, args, decision, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(approval_id) DO UPDATE SET
                tool = excluded.tool,
                args = excluded.args,
                decision = excluded.decision,
                updated_at = excluded.updated_at
            """,
            (approval_id, session_id, tool, _encode(args), decision, created_at, updated_at),
        )


def get_approval(session_id: str, approval_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT approval_id, tool, args, decision, created_at, updated_at
            FROM approvals
            WHERE session_id = ? AND approval_id = ?
            """,
            (session_id, approval_id),
        ).fetchone()
    if not row:
        return None
    return {
        "approval_id": row["approval_id"],
        "tool": row["tool"],
        "args": _decode_json(row["args"], {}),
        "decision": row["decision"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def set_approval_decision(session_id: str, approval_id: str, decision: str, updated_at: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE approvals
            SET decision = ?, updated_at = ?
            WHERE session_id = ? AND approval_id = ?
            """,
            (decision, updated_at, session_id, approval_id),
        )
