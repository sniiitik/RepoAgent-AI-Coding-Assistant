import json
import os
import re
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from groq import Groq

from tools import TOOL_MAP, TOOL_SCHEMAS, set_workspace

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"
MAX_ITERATIONS = 20

BASE_SYSTEM_PROMPT = """You are RepoAgent, an expert software engineer working inside a local repository.
You are in an ongoing conversation with the user about the same workspace, so keep context from earlier messages.

General rules:
- Use tools to inspect the repository before making changes
- Read relevant files before writing them
- Make focused edits instead of rewriting unrelated code
- When you finish a request, explain what you changed or found
- If the user asks for a follow-up, build on the existing conversation and prior edits"""

MODE_GUIDANCE = {
    "refactor": """Focus on improving code quality, maintainability, naming, duplication, and obvious bugs.""",
    "test": """Focus on adding or improving tests, covering edge cases, and validating behavior.""",
    "document": """Focus on README files, docstrings, comments, and other developer documentation.""",
}


@dataclass
class PendingToolCall:
    id: str
    name: str
    arguments: str


def _run_tool(name: str, args: dict[str, Any]) -> str:
    fn = TOOL_MAP.get(name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {name}"})
    result = fn(**args)
    return json.dumps(result, indent=2)


def _format_user_message(goal: str, mode: str, workspace: str) -> str:
    guidance = MODE_GUIDANCE.get(mode, MODE_GUIDANCE["refactor"])
    return (
        f"Workspace: {workspace}\n"
        f"Current mode: {mode}\n"
        f"Mode guidance: {guidance}\n\n"
        f"User request:\n{goal}"
    )


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


async def run_agent(
    goal: str,
    mode: str,
    workspace: str,
    conversation_messages: list[dict[str, Any]],
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Core agentic loop. Mutates conversation_messages so later requests can
    continue the same chat session.
    """
    set_workspace(workspace)

    user_message = {"role": "user", "content": _format_user_message(goal, mode, workspace)}
    conversation_messages.append(user_message)

    changed_files: list[dict[str, Any]] = []
    iteration = 0

    yield {"type": "thought", "content": f"Working on: {goal}"}

    while iteration < MAX_ITERATIONS:
        iteration += 1
        model_messages = [{"role": "system", "content": BASE_SYSTEM_PROMPT}, *conversation_messages]
        recovered_tool_calls: list[PendingToolCall] = []
        assistant_content = ""

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=model_messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                max_tokens=4096,
                temperature=0.2,
            )
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
            yield {
                "type": "thought",
                "content": "Recovered a malformed tool call from the model and continued automatically.",
            }

        if assistant_content:
            yield {"type": "thought", "content": assistant_content}

        if finish_reason == "stop" or not structured_tool_calls:
            if assistant_content:
                conversation_messages.append({"role": "assistant", "content": assistant_content})
            yield {
                "type": "done",
                "content": assistant_content or "Task complete.",
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
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments,
                    },
                }
                for tc in structured_tool_calls
            ],
        }
        conversation_messages.append(assistant_message)

        for tc in structured_tool_calls:
            tool_name = tc.name
            try:
                args = json.loads(tc.arguments)
            except json.JSONDecodeError:
                args = {}

            yield {"type": "tool_call", "tool": tool_name, "args": args}

            result_str = _run_tool(tool_name, args)
            result_data = json.loads(result_str)

            if tool_name == "write_file" and result_data.get("success"):
                change = {
                    "path": result_data["path"],
                    "original": result_data.get("original", ""),
                    "new_content": result_data["new_content"],
                }
                changed_files.append(change)
                yield {"type": "file_changed", **change}

            yield {"type": "tool_result", "tool": tool_name, "result": result_data}

            conversation_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                }
            )

    final_message = f"Reached max iterations ({MAX_ITERATIONS}). Stopping."
    conversation_messages.append({"role": "assistant", "content": final_message})
    yield {
        "type": "done",
        "content": final_message,
        "changed_files": changed_files,
        "iterations": iteration,
    }
