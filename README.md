# RepoAgent

RepoAgent is a full-stack AI coding assistant for local repositories. It lets you connect a project folder, chat continuously with an agent about that codebase, stream intermediate reasoning and tool activity, and apply file changes directly inside the selected workspace.

The project combines a FastAPI backend, a Groq-powered agent loop, and a Next.js frontend that presents the interaction as an ongoing coding chat rather than a one-shot task runner.

## Features

- Continuous chat sessions tied to a single workspace
- Streaming agent responses over Server-Sent Events
- Safe, workspace-scoped file tools for listing, reading, writing, searching, and running limited commands
- Visual file change tracking with inline diffs
- Light and dark themes with a Claude-inspired light mode
- Session-based frontend UX for iterative requests like "Write me a README", "Now make it shorter", or "Add tests for that module too"

## Demo Workflow

1. Enter the absolute path to a local project.
2. Optionally send an initial prompt.
3. Open a session and continue chatting with the same repository context.
4. Watch the agent stream thoughts, tool calls, results, and file diffs.
5. Iterate on the result with follow-up prompts in the same conversation.

## Tech Stack

### Frontend

- Next.js 16
- React 19
- TypeScript
- CSS variables plus global styling in `frontend/app/globals.css`

### Backend

- FastAPI
- Python
- Groq API with `llama-3.3-70b-versatile`
- SSE streaming responses

## Architecture

RepoAgent is split into two main applications:

- `frontend/`
  - Handles the chat UI, theme switching, session flow, streamed event rendering, and diff display.
- `backend/`
  - Manages sessions, validates workspaces, runs the agent loop, executes safe repository tools, and streams events back to the UI.

### High-Level Flow

```text
User -> Next.js UI -> FastAPI session endpoint -> Agent loop -> Tool execution -> SSE stream -> UI updates
```

### Backend Architecture

#### `backend/main.py`

Responsible for:

- Creating chat sessions
- Returning existing session metadata
- Running agent turns for a session
- Streaming events back to the frontend

Current sessions are stored in memory in a process-local dictionary:

- Each session tracks:
  - `session_id`
  - `workspace`
  - `mode`
  - `busy`
  - `messages`
  - timestamps

This keeps the implementation simple, but sessions are not persistent across server restarts.

#### `backend/agent.py`

Implements the core agent loop:

- Builds conversation context for the current workspace
- Sends the accumulated chat history to Groq
- Allows tool calling through declared tool schemas
- Streams:
  - thoughts
  - tool calls
  - tool results
  - file changes
  - completion/error events

The agent also includes a recovery path for malformed tool-call generations returned by the model, which helps reduce failures when the model emits tool syntax outside the structured tool response format.

#### `backend/tools.py`

Defines the local tools the model can use:

- `list_files`
- `read_file`
- `write_file`
- `search_code`
- `run_command`

These tools are restricted to the currently selected workspace through a path safety layer, preventing the agent from escaping the repository root.

#### `backend/models.py`

Contains the Pydantic models used for:

- session creation
- session runs
- session responses
- streamed event payloads

### Frontend Architecture

#### `frontend/app/page.tsx`

Landing page for:

- entering a workspace path
- optionally sending the first message
- starting a new RepoAgent session

#### `frontend/app/session/page.tsx`

Main chat workspace for:

- loading or creating a session
- sending follow-up prompts
- rendering streamed events per turn
- showing diffs and changed files
- keeping the composer fixed while chat content scrolls


## Repository Structure

```text
RepoAgent/
├── backend/
│   ├── agent.py
│   ├── main.py
│   ├── models.py
│   ├── requirements.txt
│   └── tools.py
├── frontend/
│   ├── app/
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   └── session/page.tsx
│   ├── components/
│   │   ├── DiffViewer.tsx
│   │   ├── ThemeProvider.tsx
│   │   └── ThemeToggle.tsx
│   ├── package.json
│   └── ...
└── README.md
```

## API Overview

### `POST /api/sessions`

Creates a new session for a workspace.

Request body:

```json
{
  "workspace": "/absolute/path/to/project",
  "mode": "refactor"
}
```

Response:

```json
{
  "session_id": "uuid",
  "workspace": "/absolute/path/to/project",
  "mode": "refactor",
  "busy": false
}
```

### `GET /api/sessions/{session_id}`

Fetches metadata for an existing session.

### `POST /api/sessions/{session_id}/run`

Runs one prompt turn inside an existing session and streams events via SSE.

Request body:

```json
{
  "goal": "Write a professional README for this project",
  "mode": "document"
}
```


## Prerequisites

- Python 3.10+
- Node.js 18+
- npm
- A Groq API key

## Backend Setup

From the repository root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn python-dotenv groq pydantic
```

Create a `.env` file inside `backend/`:

```env
GROQ_API_KEY=your_groq_api_key_here
```

Run the backend:

```bash
uvicorn main:app --reload --port 8000
```

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

By default, the frontend expects the backend at:

```env
http://localhost:8000
```

If needed, define:

```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

## Safety Model

RepoAgent is designed to reduce the risk of unsafe file access:

- Every file path is resolved relative to the chosen workspace
- Paths that escape the workspace root are rejected
- File reads are size-limited
- Shell command execution is whitelisted

This is a practical local-development safeguard, not a hardened security boundary.


## Why RepoAgent Exists

Most repository agents are optimized for single prompts or hidden execution. RepoAgent is built around a more transparent workflow:

- connect a real local project
- watch the agent work
- keep the conversation going
- inspect the actual file changes

That makes it useful both as a coding assistant and as a learning/debugging interface for agentic development workflows.

## Contributing

If you want to improve RepoAgent:

- keep backend tools workspace-safe
- preserve the streaming event contract between backend and frontend
- verify UI changes in both light and dark themes
- keep the chat flow iterative and easy to follow

