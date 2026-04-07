import json
import os
import re
import asyncio
import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator
from uuid import uuid4

from dotenv import load_dotenv
from groq import Groq

from db import save_approval
from tools import TOOL_MAP, TOOL_SCHEMAS, set_workspace

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"
MAX_ITERATIONS = 20
MAX_API_RETRIES = 3
RECENT_MESSAGE_WINDOW = 10
MAX_SUMMARIES = 8
MAX_FACTS = 10
MAX_TOOL_REPETITIONS = 3
APPROVAL_POLL_INTERVAL = 0.25

BASE_SYSTEM_PROMPT = """You are CodeWeave, an expert software engineer working inside a local repository.
You are in an ongoing conversation with the user about the same workspace.

Core behavior:
- First produce a concise execution plan before making edits
- Use tools to inspect the repository before changing files
- Prefer targeted edits over unnecessary rewrites
- Verify your work with tests or diff inspection when possible
- Before finalizing, review the git diff and self-correct if needed
- If earlier turns are summarized, treat the summaries as trusted memory"""

MODE_GUIDANCE = {
    "analyze": "Focus on understanding the codebase, answering questions, and explaining architecture without making unnecessary edits.",
    "edit": "Focus on implementing or modifying code and docs with minimal, precise changes.",
    "test": "Focus on writing or improving tests and validating behavior.",
    "document": "Focus on README files, docstrings, comments, and developer-facing documentation.",
}

SMALL_TALK_PATTERNS = {
    "hi",
    "hello",
    "hey",
    "yo",
    "sup",
    "good morning",
    "good afternoon",
    "good evening",
    "how are you",
    "how are you?",
    "what's up",
    "whats up",
}

AMBIGUOUS_PATTERNS = {
    "help",
    "help me",
    "can you help",
    "can you check",
    "check this",
    "fix this",
    "look into this",
    "do this",
    "what about this",
    "can you do this",
}

APPROVAL_REQUIRED_TOOLS = {
    "write_file",
    "create_file_patch",
    "run_command",
    "run_tests",
}

RISKY_COMMAND_PREFIXES = ("git", "python", "python3", "node", "npm")
DESTRUCTIVE_COMMAND_TOKENS = ("rm ", "git reset", "git clean", "mv ", "cp ", "chmod ", "chown ")


@dataclass
class PendingToolCall:
    id: str
    name: str
    arguments: str


def _run_tool(name: str, args: dict[str, Any] | None) -> str:
    fn = TOOL_MAP.get(name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {name}"})
    safe_args = args if isinstance(args, dict) else {}
    result = fn(**safe_args)
    return json.dumps(result, indent=2)


def _infer_mode(goal: str, requested_mode: str | None) -> str:
    lowered = goal.lower()
    if any(word in lowered for word in ["readme", "docs", "document", "docstring", "comment"]):
        return "document"
    if any(word in lowered for word in ["test", "pytest", "jest", "spec", "coverage"]):
        return "test"
    if any(word in lowered for word in ["explain", "analyze", "architecture", "understand", "what does"]):
        return "analyze"
    if requested_mode and requested_mode != "refactor":
        return "edit" if requested_mode == "refactor" else requested_mode
    return "edit"


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _is_small_talk(goal: str) -> bool:
    normalized = _normalize_text(goal)
    if normalized in SMALL_TALK_PATTERNS:
        return True

    short_greeting_pattern = re.compile(r"^(hi|hello|hey|yo)( there| codeweave| repoagent| agent)?[!.?]*$")
    return bool(short_greeting_pattern.match(normalized))


def _classify_intent(goal: str, requested_mode: str | None) -> str:
    normalized = _normalize_text(goal)
    tokens = set(re.findall(r"\b[a-z0-9']+\b", normalized))
    if _is_small_talk(goal):
        return "small_talk"
    if normalized in {"thanks", "thank you", "thx", "ty"}:
        return "gratitude"
    if normalized in {"ok", "okay", "cool", "nice"}:
        return "small_talk"
    if normalized in AMBIGUOUS_PATTERNS:
        return "clarify"
    if len(normalized.split()) <= 4 and tokens.intersection({"this", "that", "it", "help", "check", "fix"}):
        return "clarify"
    return _infer_mode(goal, requested_mode)


def _workspace_label(workspace: str) -> str:
    label = Path(workspace).name.strip()
    return label or workspace


def _small_talk_response(workspace: str) -> str:
    label = _workspace_label(workspace)
    return (
        f"Hi! I'm ready to help with `{label}`.\n\n"
        "You can ask me to inspect the codebase, explain the architecture, write a README, "
        "modify files, or add tests. Tell me what you want to work on and I'll jump in."
    )


def _gratitude_response() -> str:
    return "You're welcome. If you want, I can help with another change or explain anything in the repo."


def _clarifying_question(goal: str, workspace: str) -> str:
    label = _workspace_label(workspace)
    return (
        f"I can help with `{label}`, but I need a bit more direction first.\n\n"
        f"You said: `{goal}`\n\n"
        "Tell me what you want me to do, for example:\n"
        "- explain the architecture\n"
        "- write a README\n"
        "- add tests for a module\n"
        "- modify a specific file or feature"
    )


def _format_user_message(goal: str, mode: str, workspace: str) -> str:
    guidance = MODE_GUIDANCE.get(mode, MODE_GUIDANCE["edit"])
    return (
        f"Workspace: {workspace}\n"
        f"Execution mode: {mode}\n"
        f"Mode guidance: {guidance}\n\n"
        f"User request:\n{goal}"
    )


def _build_system_prompt(tool_summaries: list[str], workspace_facts: list[str]) -> str:
    sections = [BASE_SYSTEM_PROMPT]
    if workspace_facts:
        fact_block = "\n".join(f"- {fact}" for fact in workspace_facts[-MAX_FACTS:])
        sections.append(f"Important known repository facts:\n{fact_block}")
    if tool_summaries:
        summary_block = "\n".join(f"- {summary}" for summary in tool_summaries[-MAX_SUMMARIES:])
        sections.append(f"Summaries of older tool-heavy turns:\n{summary_block}")
    return "\n\n".join(sections)


def _build_model_messages(
    conversation_messages: list[dict[str, Any]],
    tool_summaries: list[str],
    workspace_facts: list[str],
) -> list[dict[str, Any]]:
    recent_messages = conversation_messages[-RECENT_MESSAGE_WINDOW:]
    return [{"role": "system", "content": _build_system_prompt(tool_summaries, workspace_facts)}, *recent_messages]


def _is_retryable_error(error: Exception) -> bool:
    text = str(error).lower()
    retry_tokens = [
        "timeout",
        "timed out",
        "rate limit",
        "temporarily unavailable",
        "internal server error",
        "bad gateway",
        "service unavailable",
        "connection",
        "overloaded",
    ]
    return any(token in text for token in retry_tokens)


def _extract_failed_generation(error: Exception) -> str | None:
    if hasattr(error, "body") and isinstance(error.body, dict):
        failed_generation = error.body.get("error", {}).get("failed_generation")
        if isinstance(failed_generation, str) and failed_generation.strip():
            return failed_generation

    text = str(error)
    match = re.search(r"'failed_generation':\s*'(.+?)'\s*}", text, re.DOTALL)
    if not match:
        return None
    return match.group(1).encode("utf-8").decode("unicode_escape")


def _parse_failed_tool_calls(error: Exception, iteration: int) -> list[PendingToolCall]:
    failed_generation = _extract_failed_generation(error)
    if not failed_generation:
        return []

    tool_calls: list[PendingToolCall] = []
    pattern = re.compile(r"<function=(?P<name>[a-zA-Z_][\w-]*)\s+(?P<args>\{.*?\})</function>", re.DOTALL)

    for index, match in enumerate(pattern.finditer(failed_generation), start=1):
        args_text = match.group("args").strip()
        try:
            json.loads(args_text)
        except json.JSONDecodeError:
            continue

        tool_calls.append(
            PendingToolCall(
                id=f"recovered-tool-{iteration}-{index}",
                name=match.group("name"),
                arguments=args_text,
            )
        )

    return tool_calls


def _chat_completion(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
) -> Any:
    last_error: Exception | None = None
    retry_messages = list(messages)
    for attempt in range(MAX_API_RETRIES):
        try:
            kwargs: dict[str, Any] = {
                "model": MODEL,
                "messages": retry_messages,
                "max_tokens": 4096,
                "temperature": 0.2,
            }
            if tools is not None:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            response = client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            if not (message.content or message.tool_calls):
                if attempt < MAX_API_RETRIES - 1:
                    retry_messages = [
                        *messages,
                        {
                            "role": "user",
                            "content": (
                                "You returned an empty response. "
                                "Please continue by either calling the right tool first or answering directly with a concise useful response."
                            ),
                        },
                    ]
                    continue
                raise RuntimeError("Model returned an empty response")
            return response
        except Exception as error:
            last_error = error
            if _parse_failed_tool_calls(error, 0):
                raise
            if "empty response" in str(error).lower() and attempt < MAX_API_RETRIES - 1:
                retry_messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "Your last reply was empty. "
                            "Do not return nothing. Either inspect the repo with tools or answer the user's request directly."
                        ),
                    },
                ]
                continue
            if not _is_retryable_error(error):
                raise
    if last_error:
        raise last_error
    raise RuntimeError("Model call failed unexpectedly")


def _make_turn_summary(goal: str, mode: str, changed_files: list[dict[str, Any]], final_content: str) -> str:
    changed_paths = ", ".join(change["path"] for change in changed_files[:5]) or "no files changed"
    shortened = " ".join(final_content.split())[:240]
    return f"Goal: {goal} | Mode: {mode} | Changed: {changed_paths} | Result: {shortened}"


def _append_summary(
    goal: str,
    mode: str,
    changed_files: list[dict[str, Any]],
    final_content: str,
    tool_summaries: list[str],
) -> None:
    tool_summaries.append(_make_turn_summary(goal, mode, changed_files, final_content))
    if len(tool_summaries) > MAX_SUMMARIES:
        del tool_summaries[:-MAX_SUMMARIES]


def _extract_workspace_facts(mode: str, final_content: str) -> list[str]:
    if mode not in {"analyze", "document"}:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", final_content.strip())
    fact_keywords = ("backend", "frontend", "api", "session", "tool", "architecture", "stream", "workspace", "agent", "fastapi", "next.js")
    facts = []
    for sentence in sentences:
        cleaned = " ".join(sentence.split()).strip("- ")
        if len(cleaned) < 25:
            continue
        lowered = cleaned.lower()
        if any(keyword in lowered for keyword in fact_keywords):
            facts.append(cleaned[:220])
        if len(facts) >= 3:
            break
    return facts


def _append_workspace_facts(mode: str, final_content: str, workspace_facts: list[str]) -> None:
    for fact in _extract_workspace_facts(mode, final_content):
        if fact not in workspace_facts:
            workspace_facts.append(fact)
    if len(workspace_facts) > MAX_FACTS:
        del workspace_facts[:-MAX_FACTS]


def _format_final_answer(
    assistant_content: str,
    changed_files: list[dict[str, Any]],
    verifications: list[str],
    user_attention: list[str],
) -> str:
    what_changed = ", ".join(change["path"] for change in changed_files[:6]) if changed_files else "No files were changed."
    verified_text = "; ".join(verifications) if verifications else "No automated verification was run."
    attention_text = "; ".join(user_attention) if user_attention else "Nothing specific needs user attention."
    summary = assistant_content.strip() or "Task complete."
    if all(marker in summary for marker in ("What changed:", "What was verified:", "What still needs attention:")):
        return summary
    return (
        f"{summary}\n\n"
        f"What changed: {what_changed}\n"
        f"What was verified: {verified_text}\n"
        f"What still needs attention: {attention_text}"
    )


def _tool_signature(tool_name: str, args: dict[str, Any]) -> str:
    return f"{tool_name}:{json.dumps(args, sort_keys=True)[:240]}"


def _load_tool_args(tool_call: PendingToolCall) -> dict[str, Any]:
    try:
        parsed = json.loads(tool_call.arguments)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _append_turn_history(
    session_state: dict[str, Any],
    goal: str,
    content: str,
    changed_files: list[dict[str, Any]],
    iterations: int,
) -> None:
    turn_history = session_state.setdefault("turn_history", [])
    turn_history.append(
        {
            "goal": goal,
            "content": content,
            "changed_files": changed_files,
            "iterations": iterations,
        }
    )
    if len(turn_history) > 50:
        del turn_history[:-50]


def _approval_reason(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == "write_file":
        return f"The agent wants to overwrite or create `{args.get('path', 'a file')}`."
    if tool_name == "create_file_patch":
        return f"The agent wants to apply targeted edits to `{args.get('path', 'a file')}`."
    if tool_name == "run_tests":
        return f"The agent wants to run tests using `{args.get('command', 'pytest')}`."
    if tool_name == "run_command":
        return f"The agent wants to run the shell command `{args.get('command', '')}`."
    return "The agent wants to perform a sensitive action."


def _safe_resolve_preview_path(workspace: str, path: str) -> Path:
    base = Path(workspace).resolve()
    candidate = Path(path)
    resolved = candidate.resolve() if candidate.is_absolute() else (base / path).resolve()
    if not str(resolved).startswith(str(base)):
        raise PermissionError(f"Path '{path}' escapes workspace")
    return resolved


def _build_write_preview(workspace: str, path: str, new_content: str) -> dict[str, Any]:
    try:
        resolved = _safe_resolve_preview_path(workspace, path)
        original = resolved.read_text(encoding="utf-8", errors="replace") if resolved.exists() else ""
        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(),
                new_content.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
        )
        return {
            "type": "write",
            "path": path,
            "diff_preview": "\n".join(diff_lines[:120]),
            "line_count_before": len(original.splitlines()),
            "line_count_after": len(new_content.splitlines()),
        }
    except Exception as error:
        return {"type": "write", "path": path, "error": str(error)}


def _build_patch_preview(workspace: str, path: str, edits: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        resolved = _safe_resolve_preview_path(workspace, path)
        original = resolved.read_text(encoding="utf-8", errors="replace")
        updated = original
        for edit in edits:
            old_text = edit.get("old_text", "")
            new_text = edit.get("new_text", "")
            replace_all = bool(edit.get("replace_all", False))
            occurrences = updated.count(old_text) if old_text else 0
            if not old_text:
                return {"type": "patch", "path": path, "error": "Patch preview could not be generated because an edit is missing old_text."}
            if occurrences == 0:
                return {"type": "patch", "path": path, "error": "Patch preview could not find the target text in the current file contents."}
            if occurrences > 1 and not replace_all:
                return {
                    "type": "patch",
                    "path": path,
                    "error": "Patch preview matched multiple locations. The edit needs more specific target text or replace_all=true.",
                }
            updated = updated.replace(old_text, new_text, -1 if replace_all else 1)
        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(),
                updated.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
        )
        return {
            "type": "patch",
            "path": path,
            "diff_preview": "\n".join(diff_lines[:120]) or "No line-level diff preview was generated for this patch.",
            "edits": edits,
        }
    except Exception as error:
        return {"type": "patch", "path": path, "error": str(error)}


def _command_severity(command: str) -> str:
    lowered = command.strip().lower()
    if any(token in lowered for token in DESTRUCTIVE_COMMAND_TOKENS):
        return "destructive"
    if lowered.startswith(RISKY_COMMAND_PREFIXES):
        return "risky"
    return "safe"


def _approval_severity(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name in {"write_file", "create_file_patch"}:
        return "risky"
    if tool_name == "run_tests":
        return "safe"
    if tool_name == "run_command":
        return _command_severity(str(args.get("command", "")))
    return "risky"


def _build_approval_actions(workspace: str, tool_name: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    if tool_name == "write_file":
        return [_build_write_preview(workspace, str(args.get("path", "")), str(args.get("content", "")))]
    if tool_name == "create_file_patch":
        return [_build_patch_preview(workspace, str(args.get("path", "")), args.get("edits", []))]
    if tool_name == "run_tests":
        return [{"type": "command", "command": args.get("command", "pytest"), "kind": "test"}]
    if tool_name == "run_command":
        return [{"type": "command", "command": args.get("command", ""), "kind": "shell"}]
    return []


def _infer_test_command(workspace: str, changed_files: list[dict[str, Any]], mode: str) -> str | None:
    if mode not in {"edit", "test"}:
        return None

    workspace_path = Path(workspace)
    changed_paths = [str(change.get("path", "")) for change in changed_files]
    changed_suffixes = {Path(path).suffix.lower() for path in changed_paths if path}

    if workspace_path.joinpath("pytest.ini").exists() or workspace_path.joinpath("pyproject.toml").exists():
        if any(suffix == ".py" for suffix in changed_suffixes):
            return "python3 -m pytest"

    if workspace_path.joinpath("package.json").exists():
        if any(suffix in {".js", ".jsx", ".ts", ".tsx"} for suffix in changed_suffixes):
            package_text = workspace_path.joinpath("package.json").read_text(encoding="utf-8", errors="replace")
            if '"test"' in package_text:
                return "npm test"

    return None


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def _wait_for_approval(session_state: dict[str, Any], approval_id: str) -> str:
    approvals = session_state.setdefault("approvals", {})
    while True:
        decision = approvals.get(approval_id, {}).get("decision")
        if decision in {"approved", "rejected"}:
            return decision
        await asyncio.sleep(APPROVAL_POLL_INTERVAL)


async def run_agent(
    goal: str,
    mode: str,
    workspace: str,
    conversation_messages: list[dict[str, Any]],
    turn_summaries: list[str],
    session_state: dict[str, Any],
) -> AsyncGenerator[dict[str, Any], None]:
    set_workspace(workspace)

    workspace_facts = session_state.setdefault("workspace_facts", [])
    intent = _classify_intent(goal, mode)

    if intent == "small_talk":
        final_content = _small_talk_response(workspace)
        conversation_messages.append({"role": "user", "content": goal})
        conversation_messages.append({"role": "assistant", "content": final_content})
        _append_summary(goal, "analyze", [], final_content, turn_summaries)
        _append_turn_history(session_state, goal, final_content, [], 0)
        yield {"type": "thought", "content": final_content}
        yield {
            "type": "done",
            "content": final_content,
            "changed_files": [],
            "iterations": 0,
        }
        return

    if intent == "gratitude":
        final_content = _gratitude_response()
        conversation_messages.append({"role": "user", "content": goal})
        conversation_messages.append({"role": "assistant", "content": final_content})
        _append_summary(goal, "analyze", [], final_content, turn_summaries)
        _append_turn_history(session_state, goal, final_content, [], 0)
        yield {"type": "thought", "content": final_content}
        yield {
            "type": "done",
            "content": final_content,
            "changed_files": [],
            "iterations": 0,
        }
        return

    if intent == "clarify":
        final_content = _clarifying_question(goal, workspace)
        conversation_messages.append({"role": "user", "content": goal})
        conversation_messages.append({"role": "assistant", "content": final_content})
        _append_summary(goal, "analyze", [], final_content, turn_summaries)
        _append_turn_history(session_state, goal, final_content, [], 0)
        yield {"type": "thought", "content": final_content}
        yield {
            "type": "done",
            "content": final_content,
            "changed_files": [],
            "iterations": 0,
        }
        return

    effective_mode = intent
    user_message = {"role": "user", "content": _format_user_message(goal, effective_mode, workspace)}
    conversation_messages.append(user_message)

    changed_files: list[dict[str, Any]] = []
    verifications: list[str] = []
    user_attention: list[str] = []
    iteration = 0
    reviewed_diff = False
    auto_test_requested = False
    auto_fix_attempted = False
    last_test_failure: str | None = None
    tool_history: list[str] = []

    yield {"type": "thought", "content": f"Working on: {goal}"}

    plan_prompt = (
        "Create a short execution plan before using tools.\n"
        "Include:\n"
        "1. What you think the user wants\n"
        "2. Which files or areas you will inspect first\n"
        "3. The changes or outputs you expect to produce\n"
        "4. How you will verify the result\n"
        "Keep it concise."
    )

    try:
        plan_response = _chat_completion(
            [*_build_model_messages(conversation_messages, turn_summaries, workspace_facts), {"role": "user", "content": plan_prompt}],
            tools=None,
        )
        plan_content = plan_response.choices[0].message.content or "Inspect the repository, implement the request, and verify the result."
    except Exception as e:
        plan_content = "Inspect the repository, make targeted changes, and review the resulting diff before finalizing."
        yield {"type": "thought", "content": f"Planning fallback used after model issue: {e}"}

    conversation_messages.append({"role": "assistant", "content": f"Execution plan:\n{plan_content}"})
    yield {"type": "plan", "content": plan_content}

    while iteration < MAX_ITERATIONS:
        iteration += 1
        recovered_tool_calls: list[PendingToolCall] = []
        assistant_content = ""

        try:
            response = _chat_completion(_build_model_messages(conversation_messages, turn_summaries, workspace_facts), tools=TOOL_SCHEMAS)
            msg = response.choices[0].message
            finish_reason = response.choices[0].finish_reason
            structured_tool_calls = [
                PendingToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                )
                for tc in (msg.tool_calls or [])
            ]
            assistant_content = msg.content or ""
        except Exception as e:
            recovered_tool_calls = _parse_failed_tool_calls(e, iteration)
            if not recovered_tool_calls:
                yield {"type": "error", "content": str(e)}
                return
            finish_reason = "tool_calls"
            structured_tool_calls = recovered_tool_calls
            assistant_content = ""
            yield {"type": "thought", "content": "Recovered a malformed tool call from the model and continued automatically."}

        if assistant_content:
            yield {"type": "thought", "content": assistant_content}

        if finish_reason == "stop" or not structured_tool_calls:
            if changed_files and not auto_test_requested:
                inferred_test_command = _infer_test_command(workspace, changed_files, effective_mode)
                if inferred_test_command:
                    auto_test_requested = True
                    conversation_messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"Before finalizing, verify the changes with `{inferred_test_command}`. "
                                "If it fails, fix the problem and try to leave the repo in a better state."
                            ),
                        }
                    )
                    continue

            if last_test_failure and not auto_fix_attempted:
                auto_fix_attempted = True
                conversation_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The last verification step failed. "
                            f"Please fix the issues revealed by the test output and verify again. Failure details:\n{last_test_failure[:3000]}"
                        ),
                    }
                )
                continue

            if changed_files and not reviewed_diff:
                diff_result = json.loads(_run_tool("list_git_diff", {}))
                yield {"type": "tool_call", "tool": "list_git_diff", "args": {}}
                yield {"type": "tool_result", "tool": "list_git_diff", "result": diff_result}
                review_tool_call_id = f"review-diff-{iteration}"
                conversation_messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content or "Preparing a final review.",
                        "tool_calls": [
                            {
                                "id": review_tool_call_id,
                                "type": "function",
                                "function": {"name": "list_git_diff", "arguments": "{}"},
                            }
                        ],
                    }
                )
                conversation_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": review_tool_call_id,
                        "content": json.dumps(diff_result, indent=2),
                    }
                )
                conversation_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Review the git diff above before finalizing. "
                            "If anything is incomplete or risky, use more tools to fix it. "
                            "If it looks good, summarize the result clearly."
                        ),
                    }
                )
                reviewed_diff = True
                verifications.append("Reviewed git diff")
                continue

            final_content = _format_final_answer(assistant_content or "Task complete.", changed_files, verifications, user_attention)
            if assistant_content:
                conversation_messages.append({"role": "assistant", "content": final_content})
            else:
                conversation_messages.append({"role": "assistant", "content": final_content})
            _append_summary(goal, effective_mode, changed_files, final_content, turn_summaries)
            _append_workspace_facts(effective_mode, final_content, workspace_facts)
            _append_turn_history(session_state, goal, final_content, changed_files, iteration)
            yield {
                "type": "done",
                "content": final_content,
                "changed_files": changed_files,
                "iterations": iteration,
            }
            return

        assistant_message = {
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in structured_tool_calls
            ],
        }
        conversation_messages.append(assistant_message)

        tool_call_args = [_load_tool_args(tc) for tc in structured_tool_calls]
        tool_index = 0
        while tool_index < len(structured_tool_calls):
            tc = structured_tool_calls[tool_index]
            tool_name = tc.name
            args = tool_call_args[tool_index]

            signature = _tool_signature(tool_name, args)
            tool_history.append(signature)
            if tool_history.count(signature) >= MAX_TOOL_REPETITIONS:
                loop_message = (
                    f"I stopped because I was repeating the same action: `{tool_name}`. "
                    "Please clarify the request or give me a more specific direction."
                )
                user_attention.append(f"Loop detected on {tool_name}")
                final_content = _format_final_answer(loop_message, changed_files, verifications, user_attention)
                conversation_messages.append({"role": "assistant", "content": final_content})
                _append_summary(goal, effective_mode, changed_files, final_content, turn_summaries)
                _append_turn_history(session_state, goal, final_content, changed_files, iteration)
                yield {
                    "type": "done",
                    "content": final_content,
                    "changed_files": changed_files,
                    "iterations": iteration,
                }
                return

            if tool_name in {"write_file", "create_file_patch"}:
                batch_calls: list[tuple[PendingToolCall, dict[str, Any]]] = []
                batch_actions: list[dict[str, Any]] = []
                batch_payload: list[dict[str, Any]] = []
                while tool_index < len(structured_tool_calls) and structured_tool_calls[tool_index].name in {"write_file", "create_file_patch"}:
                    current_tc = structured_tool_calls[tool_index]
                    current_args = tool_call_args[tool_index]
                    batch_calls.append((current_tc, current_args))
                    batch_payload.append({"tool": current_tc.name, "args": current_args, "tool_call_id": current_tc.id})
                    batch_actions.extend(_build_approval_actions(workspace, current_tc.name, current_args))
                    tool_index += 1

                approval_id = str(uuid4())
                now = _utc_now()
                approval_args = {"operations": batch_payload}
                session_state.setdefault("approvals", {})[approval_id] = {
                    "tool": "write_batch",
                    "args": approval_args,
                    "decision": None,
                    "created_at": now,
                    "updated_at": now,
                }
                save_approval(session_state["session_id"], approval_id, "write_batch", approval_args, None, now, now)
                yield {
                    "type": "approval_required",
                    "approval_id": approval_id,
                    "tool": "write_batch",
                    "args": approval_args,
                    "reason": f"The agent wants to apply {len(batch_calls)} file edit{'s' if len(batch_calls) != 1 else ''}.",
                    "severity": "risky",
                    "actions": batch_actions,
                }
                decision = await _wait_for_approval(session_state, approval_id)
                if decision == "rejected":
                    user_attention.append("You rejected the proposed file edits")
                    for rejected_tc, _ in batch_calls:
                        rejection_result = {"approved": False, "error": f"User rejected execution of {rejected_tc.name}"}
                        yield {"type": "tool_result", "tool": rejected_tc.name, "result": rejection_result}
                        conversation_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": rejected_tc.id,
                                "content": json.dumps(rejection_result, indent=2),
                            }
                        )
                    rejection_message = _format_final_answer(
                        "No file changes were applied because you rejected the proposed edit. If you want, ask for a different change or a smaller patch.",
                        changed_files,
                        verifications,
                        user_attention,
                    )
                    conversation_messages.append({"role": "assistant", "content": rejection_message})
                    _append_summary(goal, effective_mode, changed_files, rejection_message, turn_summaries)
                    _append_turn_history(session_state, goal, rejection_message, changed_files, iteration)
                    yield {
                        "type": "done",
                        "content": rejection_message,
                        "changed_files": changed_files,
                        "iterations": iteration,
                    }
                    return

                for approved_tc, approved_args in batch_calls:
                    yield {"type": "tool_call", "tool": approved_tc.name, "args": approved_args}
                    result_str = _run_tool(approved_tc.name, approved_args)
                    result_data = json.loads(result_str)
                    if approved_tc.name in {"write_file", "create_file_patch"} and result_data.get("success"):
                        change = {
                            "path": result_data["path"],
                            "original": result_data.get("original", ""),
                            "new_content": result_data["new_content"],
                        }
                        changed_files.append(change)
                        yield {"type": "file_changed", **change}
                    yield {"type": "tool_result", "tool": approved_tc.name, "result": result_data}
                    conversation_messages.append({"role": "tool", "tool_call_id": approved_tc.id, "content": result_str})
                continue

            if tool_name in APPROVAL_REQUIRED_TOOLS:
                approval_id = str(uuid4())
                now = _utc_now()
                session_state.setdefault("approvals", {})[approval_id] = {
                    "tool": tool_name,
                    "args": args,
                    "decision": None,
                    "created_at": now,
                    "updated_at": now,
                }
                save_approval(session_state["session_id"], approval_id, tool_name, args, None, now, now)
                yield {
                    "type": "approval_required",
                    "approval_id": approval_id,
                    "tool": tool_name,
                    "args": args,
                    "reason": _approval_reason(tool_name, args),
                    "severity": _approval_severity(tool_name, args),
                    "actions": _build_approval_actions(workspace, tool_name, args),
                }
                decision = await _wait_for_approval(session_state, approval_id)
                if decision == "rejected":
                    rejection_result = {"approved": False, "error": f"User rejected execution of {tool_name}"}
                    user_attention.append(f"You rejected {tool_name}")
                    yield {"type": "tool_result", "tool": tool_name, "result": rejection_result}
                    conversation_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(rejection_result, indent=2),
                        }
                    )
                    tool_index += 1
                    continue

            yield {"type": "tool_call", "tool": tool_name, "args": args}

            result_str = _run_tool(tool_name, args)
            result_data = json.loads(result_str)

            if tool_name in {"write_file", "create_file_patch"} and result_data.get("success"):
                change = {
                    "path": result_data["path"],
                    "original": result_data.get("original", ""),
                    "new_content": result_data["new_content"],
                }
                changed_files.append(change)
                yield {"type": "file_changed", **change}
            if tool_name == "run_tests":
                if result_data.get("returncode") == 0:
                    verifications.append(f"Tests passed with `{result_data.get('command', args.get('command', 'pytest'))}`")
                    last_test_failure = None
                else:
                    failure_output = result_data.get("stderr") or result_data.get("stdout") or "Tests failed without output."
                    last_test_failure = str(failure_output)
                    user_attention.append(f"Test command failed: `{result_data.get('command', args.get('command', 'pytest'))}`")
            if tool_name == "run_command" and result_data.get("returncode") == 0:
                verifications.append(f"Ran `{args.get('command', '')}`")
            if tool_name == "list_git_diff" and result_data.get("diff") is not None:
                verifications.append("Inspected git diff")

            yield {"type": "tool_result", "tool": tool_name, "result": result_data}
            conversation_messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})
            tool_index += 1

    final_message = f"Reached max iterations ({MAX_ITERATIONS}). Stopping."
    user_attention.append("Agent reached the iteration limit")
    final_content = _format_final_answer(final_message, changed_files, verifications, user_attention)
    conversation_messages.append({"role": "assistant", "content": final_content})
    _append_summary(goal, effective_mode, changed_files, final_content, turn_summaries)
    _append_turn_history(session_state, goal, final_content, changed_files, iteration)
    yield {
        "type": "done",
        "content": final_content,
        "changed_files": changed_files,
        "iterations": iteration,
    }
