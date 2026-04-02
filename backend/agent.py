import json, os
from groq import Groq
from tools import TOOL_SCHEMAS, TOOL_MAP, set_workspace
from typing import AsyncGenerator
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"
MAX_ITERATIONS = 20

MODE_PROMPTS = {
    "refactor": """You are an expert software engineer performing code refactoring.
Your job: analyse the codebase, identify improvements, and make targeted edits.

Refactoring goals:
- Improve readability and maintainability
- Remove duplication (DRY principle)
- Improve naming (variables, functions, classes)
- Add type hints where missing (Python)
- Simplify complex logic
- Fix obvious bugs or anti-patterns

Process:
1. ALWAYS start with list_files to understand the project structure
2. Read relevant files before modifying them
3. Make focused, minimal changes — don't rewrite everything
4. Write improved versions using write_file
5. After writing, verify by reading the file back""",

    "test": """You are an expert software engineer writing comprehensive tests.
Your job: analyse existing code and write thorough test suites.

Testing goals:
- Cover happy paths, edge cases, and error conditions
- Use pytest for Python, Jest for JavaScript/TypeScript
- Write descriptive test names that explain what is being tested
- Mock external dependencies appropriately
- Aim for meaningful coverage, not just line coverage

Process:
1. ALWAYS start with list_files to understand the project structure
2. Read the source files you'll be testing
3. Identify all functions/classes/methods to test
4. Write test files (e.g. test_<module>.py or <module>.test.ts)
5. Run pytest or similar to verify tests pass (use run_command)""",

    "document": """You are an expert technical writer creating code documentation.
Your job: analyse the codebase and add clear, useful documentation.

Documentation goals:
- Add docstrings to all functions and classes
- Update or create README.md
- Document parameters, return values, and exceptions
- Add inline comments for complex logic
- Keep docs concise — avoid obvious comments

Process:
1. ALWAYS start with list_files to understand the project structure
2. Read each file to understand what it does
3. Add docstrings and comments using write_file
4. Update README.md with project overview, setup, and usage"""
}

def _run_tool(name: str, args: dict) -> str:
    fn = TOOL_MAP.get(name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {name}"})
    result = fn(**args)
    return json.dumps(result, indent=2)

async def run_agent(
    goal: str,
    mode: str,
    workspace: str,
) -> AsyncGenerator[dict, None]:
    """
    Core agentic loop. Yields event dicts for SSE streaming.
    Event types: thought | tool_call | tool_result | file_changed | done | error
    """
    set_workspace(workspace)

    system_prompt = MODE_PROMPTS.get(mode, MODE_PROMPTS["refactor"])
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Goal: {goal}\n\nWorkspace: {workspace}\n\nPlease begin."}
    ]

    changed_files: list[dict] = []
    iteration = 0

    yield {"type": "thought", "content": f"Starting {mode} agent for goal: {goal}"}

    while iteration < MAX_ITERATIONS:
        iteration += 1

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                max_tokens=4096,
                temperature=0.2,
            )
        except Exception as e:
            yield {"type": "error", "content": str(e)}
            return

        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        # Emit any text the model produced
        if msg.content:
            yield {"type": "thought", "content": msg.content}

        # No tool calls → agent is done
        if finish_reason == "stop" or not msg.tool_calls:
            yield {
                "type": "done",
                "content": msg.content or "Task complete.",
                "changed_files": changed_files,
                "iterations": iteration
            }
            return

        # Append assistant message with tool calls
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in msg.tool_calls
            ]
        })

        # Execute each tool call
        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            yield {"type": "tool_call", "tool": tool_name, "args": args}

            result_str = _run_tool(tool_name, args)
            result_data = json.loads(result_str)

            # Track file changes for diff view
            if tool_name == "write_file" and result_data.get("success"):
                change = {
                    "path": result_data["path"],
                    "original": result_data.get("original", ""),
                    "new_content": result_data["new_content"],
                }
                changed_files.append(change)
                yield {"type": "file_changed", **change}

            yield {"type": "tool_result", "tool": tool_name, "result": result_data}

            # Add tool result to messages
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str
            })

    yield {
        "type": "done",
        "content": f"Reached max iterations ({MAX_ITERATIONS}). Stopping.",
        "changed_files": changed_files,
        "iterations": iteration
    }
