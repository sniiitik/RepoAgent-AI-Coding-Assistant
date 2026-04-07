import os
import subprocess
from pathlib import Path
from typing import Any

# ── safety: agent can only touch files inside the workspace root ──
_WORKSPACE: Path | None = None

MAX_FILE_SIZE = 100_000
MAX_BATCH_FILES = 12


def set_workspace(path: str):
    global _WORKSPACE
    _WORKSPACE = Path(path).resolve()


def _safe(path: str) -> Path:
    if _WORKSPACE is None:
        raise RuntimeError("Workspace not set")

    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (_WORKSPACE / path).resolve()

    if not str(resolved).startswith(str(_WORKSPACE)):
        raise PermissionError(f"Path '{path}' escapes workspace")
    return resolved


def _read_path(path: str) -> dict[str, Any]:
    p = _safe(path)
    if not p.exists():
        return {"path": path, "error": f"File '{path}' not found"}
    if p.stat().st_size > MAX_FILE_SIZE:
        return {"path": path, "error": "File too large (>100KB). Use search_code instead."}
    content = p.read_text(encoding="utf-8", errors="replace")
    return {"path": path, "content": content, "lines": len(content.splitlines())}


def _run_subprocess(command: str, timeout: int = 20) -> dict[str, Any]:
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(_WORKSPACE),
    )
    return {
        "stdout": result.stdout[:5000],
        "stderr": result.stderr[:2000],
        "returncode": result.returncode,
    }


def list_files(directory: str = ".", pattern: str = "*") -> dict[str, Any]:
    """List files in a directory matching a pattern."""
    try:
        base = _safe(directory)
        if not base.exists():
            return {"error": f"Directory '{directory}' does not exist"}
        files = []
        for f in sorted(base.rglob(pattern)):
            if f.is_file() and ".git" not in f.parts and "__pycache__" not in f.parts:
                files.append(str(f.relative_to(_WORKSPACE)))
        return {"files": files[:120], "total": len(files)}
    except Exception as e:
        return {"error": str(e)}


def read_file(path: str) -> dict[str, Any]:
    """Read a file's contents."""
    try:
        return _read_path(path)
    except Exception as e:
        return {"error": str(e)}


def read_many_files(paths: list[str]) -> dict[str, Any]:
    """Read multiple files at once."""
    try:
        if not paths:
            return {"files": [], "total": 0}
        selected = paths[:MAX_BATCH_FILES]
        files = [_read_path(path) for path in selected]
        return {"files": files, "total": len(files), "truncated": len(paths) > len(selected)}
    except Exception as e:
        return {"error": str(e)}


def write_file(path: str, content: str) -> dict[str, Any]:
    """Write content to a file (creates or overwrites)."""
    try:
        p = _safe(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        original = p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
        p.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "path": path,
            "original": original,
            "new_content": content,
            "lines_written": len(content.splitlines()),
        }
    except Exception as e:
        return {"error": str(e)}


def create_file_patch(
    path: str,
    edits: list[dict[str, Any]] | None = None,
    old_text: str | None = None,
    new_text: str = "",
    replace_all: bool = False,
) -> dict[str, Any]:
    """Apply targeted search/replace edits to a file."""
    try:
        p = _safe(path)
        if not p.exists():
            return {"error": f"File '{path}' not found"}

        original = p.read_text(encoding="utf-8", errors="replace")
        updated = original
        applied = []

        normalized_edits = edits
        if normalized_edits is None:
            if old_text is None:
                return {"error": "Patch request is missing edits or old_text/new_text fields"}
            normalized_edits = [
                {
                    "old_text": old_text,
                    "new_text": new_text,
                    "replace_all": replace_all,
                }
            ]

        for index, edit in enumerate(normalized_edits, start=1):
            old_text = edit.get("old_text")
            new_text = edit.get("new_text", "")
            replace_all = bool(edit.get("replace_all", False))

            if not isinstance(old_text, str) or not old_text:
                return {"error": f"Edit {index} is missing non-empty old_text"}
            if not isinstance(new_text, str):
                return {"error": f"Edit {index} has invalid new_text"}

            occurrences = updated.count(old_text)
            if occurrences == 0:
                return {"error": f"Edit {index} could not find target text"}
            if occurrences > 1 and not replace_all:
                return {"error": f"Edit {index} matched multiple locations; set replace_all=true or use more specific text"}

            updated = updated.replace(old_text, new_text, -1 if replace_all else 1)
            applied.append({"index": index, "occurrences": occurrences if replace_all else 1})

        p.write_text(updated, encoding="utf-8")
        return {
            "success": True,
            "path": path,
            "original": original,
            "new_content": updated,
            "applied_edits": applied,
        }
    except Exception as e:
        return {"error": str(e)}


def search_code(query: str, file_pattern: str = "*.py") -> dict[str, Any]:
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
                        results.append(
                            {
                                "file": str(f.relative_to(_WORKSPACE)),
                                "line": i,
                                "content": line.strip(),
                            }
                        )
                        if len(results) >= 60:
                            return {"results": results, "truncated": True}
            except Exception:
                continue
        return {"results": results, "truncated": False}
    except Exception as e:
        return {"error": str(e)}


def run_command(command: str) -> dict[str, Any]:
    """Run a shell command in the workspace (read-only commands only)."""
    allowed = ["python", "pytest", "python3", "node", "npm", "cat", "ls", "find", "grep", "wc", "head", "tail", "echo", "git"]
    cmd_name = command.strip().split()[0] if command.strip() else ""
    if cmd_name not in allowed:
        return {"error": f"Command '{cmd_name}' not allowed. Allowed: {allowed}"}
    try:
        return _run_subprocess(command, timeout=20)
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out after 20 seconds"}
    except Exception as e:
        return {"error": str(e)}


def run_tests(command: str = "pytest") -> dict[str, Any]:
    """Run a test command using a small safe allowlist."""
    allowed_commands = {
        "pytest",
        "python -m pytest",
        "python3 -m pytest",
        "npm test",
        "npm run test",
        "node --test",
    }
    normalized = command.strip()
    if normalized not in allowed_commands:
        return {"error": f"Test command '{command}' not allowed. Allowed: {sorted(allowed_commands)}"}
    try:
        result = _run_subprocess(normalized, timeout=90)
        result["command"] = normalized
        return result
    except subprocess.TimeoutExpired:
        return {"error": "Tests timed out after 90 seconds"}
    except Exception as e:
        return {"error": str(e)}


def list_git_diff() -> dict[str, Any]:
    """Return git branch, status, and diff for the current workspace."""
    try:
        branch = subprocess.run(
            "git rev-parse --abbrev-ref HEAD",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(_WORKSPACE),
        )
        status = subprocess.run(
            "git status --short",
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(_WORKSPACE),
        )
        diff = subprocess.run(
            "git diff -- .",
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(_WORKSPACE),
        )
        return {
            "branch": branch.stdout.strip() or None,
            "status": status.stdout[:4000],
            "diff": diff.stdout[:12000],
            "stderr": "\n".join(part for part in [branch.stderr.strip(), status.stderr.strip(), diff.stderr.strip()] if part),
        }
    except subprocess.TimeoutExpired:
        return {"error": "Git diff timed out"}
    except Exception as e:
        return {"error": str(e)}


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
                    "pattern": {"type": "string", "description": "Glob pattern e.g. '*.py', '*.ts'. Default: '*'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full contents of a file. Use after listing files to inspect a specific file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_many_files",
            "description": "Read multiple files in one call when you need to inspect several related files together.",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Relative file paths to read",
                    }
                },
                "required": ["paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write full content to a file. Always read the file first before writing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root"},
                    "content": {"type": "string", "description": "Full file content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file_patch",
            "description": "Apply targeted search/replace edits to an existing file instead of rewriting the entire file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root"},
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_text": {"type": "string", "description": "Exact text to replace"},
                                "new_text": {"type": "string", "description": "Replacement text"},
                                "replace_all": {"type": "boolean", "description": "Replace all matches instead of one"},
                            },
                            "required": ["old_text", "new_text"],
                        },
                    },
                },
                "required": ["path", "edits"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a string or pattern across files in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "String to search for"},
                    "file_pattern": {"type": "string", "description": "File glob pattern e.g. '*.py'. Default: '*.py'"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a safe shell command in the workspace when inspection is needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run a safe test command such as pytest or npm test to verify changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Optional test command. Examples: 'pytest', 'npm test'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_git_diff",
            "description": "Inspect the current git branch, status, and diff so you can review changes before finalizing.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

TOOL_MAP = {
    "list_files": list_files,
    "read_file": read_file,
    "read_many_files": read_many_files,
    "write_file": write_file,
    "create_file_patch": create_file_patch,
    "search_code": search_code,
    "run_command": run_command,
    "run_tests": run_tests,
    "list_git_diff": list_git_diff,
}
