import os, subprocess, fnmatch
from pathlib import Path

# ── safety: agent can only touch files inside the workspace root ──
_WORKSPACE: Path | None = None

def set_workspace(path: str):
    global _WORKSPACE
    _WORKSPACE = Path(path).resolve()

def _safe(path: str) -> Path:
    if _WORKSPACE is None:
        raise RuntimeError("Workspace not set")

    candidate = Path(path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (_WORKSPACE / path).resolve()

    if not str(resolved).startswith(str(_WORKSPACE)):
        raise PermissionError(f"Path '{path}' escapes workspace")
    return resolved

# ── tool implementations ──────────────────────────────────────────

def list_files(directory: str = ".", pattern: str = "*") -> dict:
    """List files in a directory matching a pattern."""
    try:
        base = _safe(directory)
        if not base.exists():
            return {"error": f"Directory '{directory}' does not exist"}
        files = []
        for f in sorted(base.rglob(pattern)):
            if f.is_file() and ".git" not in f.parts and "__pycache__" not in f.parts:
                rel = str(f.relative_to(_WORKSPACE))
                files.append(rel)
        return {"files": files[:80], "total": len(files)}
    except Exception as e:
        return {"error": str(e)}

def read_file(path: str) -> dict:
    """Read a file's contents."""
    try:
        p = _safe(path)
        if not p.exists():
            return {"error": f"File '{path}' not found"}
        if p.stat().st_size > 100_000:
            return {"error": "File too large (>100KB). Use search_code instead."}
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        return {"content": content, "lines": len(lines), "path": path}
    except Exception as e:
        return {"error": str(e)}

def write_file(path: str, content: str) -> dict:
    """Write content to a file (creates or overwrites)."""
    try:
        p = _safe(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Keep original for diff
        original = p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
        p.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "path": path,
            "original": original,
            "new_content": content,
            "lines_written": len(content.splitlines())
        }
    except Exception as e:
        return {"error": str(e)}

def search_code(query: str, file_pattern: str = "*.py") -> dict:
    """Search for a string across files in the workspace."""
    try:
        results = []
        for f in sorted(_WORKSPACE.rglob(file_pattern)):
            if ".git" in f.parts or "__pycache__" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if query.lower() in line.lower():
                        results.append({
                            "file": str(f.relative_to(_WORKSPACE)),
                            "line": i,
                            "content": line.strip()
                        })
                        if len(results) >= 40:
                            return {"results": results, "truncated": True}
            except Exception:
                continue
        return {"results": results, "truncated": False}
    except Exception as e:
        return {"error": str(e)}

def run_command(command: str) -> dict:
    """Run a shell command in the workspace (read-only commands only)."""
    # Whitelist safe commands only
    allowed = ["python", "pytest", "python3", "node", "npm", "cat",
               "ls", "find", "grep", "wc", "head", "tail", "echo"]
    cmd_name = command.strip().split()[0] if command.strip() else ""
    if cmd_name not in allowed:
        return {"error": f"Command '{cmd_name}' not allowed. Allowed: {allowed}"}
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True,
            text=True, timeout=15, cwd=str(_WORKSPACE)
        )
        return {
            "stdout": result.stdout[:3000],
            "stderr": result.stderr[:1000],
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out after 15 seconds"}
    except Exception as e:
        return {"error": str(e)}

# ── Groq tool schemas (passed to the API) ─────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in the workspace directory. Use this first to understand the project structure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory to list (relative to workspace root). Default: '.'"},
                    "pattern": {"type": "string", "description": "Glob pattern e.g. '*.py', '*.ts'. Default: '*'"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full contents of a file. Use after list_files to inspect specific files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. This will create or overwrite the file. Always read the file first before writing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root"},
                    "content": {"type": "string", "description": "Full file content to write"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a string or pattern across all files in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "String to search for"},
                    "file_pattern": {"type": "string", "description": "File glob pattern e.g. '*.py'. Default: '*.py'"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a safe read-only shell command (pytest, python, ls, grep etc.) in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"}
                },
                "required": ["command"]
            }
        }
    }
]

TOOL_MAP = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "search_code": search_code,
    "run_command": run_command,
}
