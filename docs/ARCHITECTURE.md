# RepoMind — Architecture

This document describes how RepoMind is structured, how data flows through the system, and the design decisions behind each layer. Read this before making changes to the agent, tools, or API.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Layer Breakdown](#2-layer-breakdown)
3. [Request Lifecycle](#3-request-lifecycle)
4. [Agent Internals](#4-agent-internals)
5. [Tool System](#5-tool-system)
6. [API Layer](#6-api-layer)
7. [Job Management](#7-job-management)
8. [Memory System](#8-memory-system)
9. [Configuration](#9-configuration)
10. [Data Models](#10-data-models)
11. [Known Limitations & Future Work](#11-known-limitations--future-work)

---

## 1. System Overview

RepoMind is a stateless FastAPI service that wraps a LangChain-based AI agent. A caller sends a repository URL and a plain-English instruction. The agent plans a sequence of code edits, executes them using tools, and opens a pull request with the result.

```
External Caller (HackingTheRepo platform)
        │
        │  POST /run  { repo_url, instruction, branch_name, pr_title }
        ▼
┌─────────────────────────────────────────────┐
│               FastAPI  (api/)               │
│  routes.py → job_manager → background task  │
└─────────────────┬───────────────────────────┘
                  │  async background task
                  ▼
┌─────────────────────────────────────────────┐
│              Agent Chain  (agent/)          │
│                                             │
│  MemoryManager ──► TaskPlanner ──► StepExecutor
│       │                                 │   │
│       │ conversation history            │   │
│       └─────────────────────────────────┘   │
│                                             │
│  (LangChain + Groq / OpenAI LLM)            │
└──────────────────┬──────────────────────────┘
                   │  tool calls
        ┌──────────┼──────────────┐
        ▼          ▼              ▼
  github_tool  code_parser   pr_tool
  diff_gen     test_executor
        │
        │  clone / commit / push / PR
        ▼
  GitHub API (PyGitHub + GitPython)
```

---

## 2. Layer Breakdown

| Layer | Package | Responsibility |
|-------|---------|----------------|
| **HTTP API** | `api/` | Receive requests, manage job lifecycle, return status |
| **Agent Orchestration** | `agent/` | Wire LLM + memory + tools into a single `run()` call |
| **Planner** | `agent/planner.py` | Turn an instruction into an ordered list of `PlanStep` objects |
| **Executor** | `agent/executor.py` | Iterate over steps, pick a tool per step, collect `FileChange` objects |
| **Memory** | `agent/memory.py` | Persist conversation history and plan state per session |
| **Tools** | `tools/` | Atomic operations: clone, parse, diff, commit, open PR |
| **Prompts** | `prompts/` | Version-controlled LLM prompt templates |
| **Config** | `config/` | Environment variables and application settings |
| **Utils** | `utils/` | Shared helpers (in-memory job store) |

---

## 3. Request Lifecycle

### POST /run — start a new job

```
1. api/routes.py receives RunRequest { repo_url, instruction, branch_name, pr_title }
2. Validates repo_url starts with https://github.com/ → raises InvalidRepoURLError otherwise
3. Validates instruction is non-empty → raises InvalidInstructionError otherwise
4. job_manager.create_job() assigns a UUID job_id, stores status=queued
5. FastAPI BackgroundTasks schedules process_job(job_id)
6. Response { job_id, status: "queued" } returned immediately
```

### Background: process_job

```
7.  job_manager.update(status=running)
8.  AgentChain.run(session_id=job_id, instruction=instruction) called
9.  MemoryManager retrieves conversation history for session
10. TaskPlanner.plan() calls LLM → returns Plan { steps: [PlanStep, ...] }
11. StepExecutor.execute(plan) iterates steps:
        a. _decide_tool() calls LLM → returns ToolDecision { tool_name, tool_input }
        b. Looks up tool by name in tools_by_name dict
        c. Calls tool.fn(tool_input) → receives dict with optional file_changes
        d. Accumulates FileChange objects
12. AgentChain builds summary string, saves to MemoryManager
13. ChainResult returned to process_job
14. job_manager.update(status=completed, pr_url=..., diff_summary=...)
```

### GET /status/{job_id}

```
15. job_manager.get(job_id) → raises JobNotFoundError if not found
16. Returns JobStatusResponse { status, pr_url, diff_summary, error_message }
```

### POST /refine — follow-up instruction

```
17. Fetches existing job → raises JobNotFoundError / JobAlreadyRunningError as appropriate
18. Appends "Refinement: {instruction}" to job.instruction
19. Sets status=queued, schedules process_job again
20. Returns RefineResponse { job_id, status: "queued" }
```

Memory from the original run is preserved in `MemoryManager` under the same `session_id = job_id`, so the agent has full context of what was already done.

---

## 4. Agent Internals

### AgentChain (`agent/chain.py`)

The top-level orchestrator. It does not call the LLM directly — it delegates to the Planner and Executor, then writes a summary back to memory.

```python
chain.run(session_id, instruction)
  → memory.append_user_message()
  → memory.get_context_messages()       # last 12 messages
  → planner.plan(instruction, context)
  → memory.set_plan(steps)
  → executor.execute(plan)
  → memory.mark_step_completed() × N
  → memory.append_ai_message(summary)
  → ChainResult
```

### TaskPlanner (`agent/planner.py`)

Uses `with_structured_output(Plan)` to force the LLM to return a valid `Plan` Pydantic model — no free-text parsing. The prompt instructs the LLM to produce a minimal, ordered, concrete set of steps. Each `PlanStep` carries:

- `id` — 1-based sequence number
- `task` — human-readable description of the edit
- `target_files` — files likely to be touched (hint for the executor)
- `acceptance_criteria` — how to verify the step is done

### StepExecutor (`agent/executor.py`)

Iterates the plan one step at a time. For each step it calls `_decide_tool()`, which uses a second LLM call (also structured output via `ToolDecision`) to pick the right tool from the registered list. The tool descriptions passed to this prompt are the primary signal the LLM uses to decide — write them carefully.

File changes from each step accumulate in `ExecutorOutput.all_file_changes`. If a tool name is not found in `tools_by_name`, the step is skipped with a note rather than crashing.

---

## 5. Tool System

Each tool is a plain Python function wrapped in a `ToolSpec` dataclass:

```python
@dataclass
class ToolSpec:
    name: str           # Identifier used by the executor LLM
    description: str    # What the LLM reads to decide when to call this tool
    fn: ToolFn          # Callable: dict → dict
```

### Built-in tools

| Tool | File | What it does |
|------|------|-------------|
| `github_tool` | `tools/github_tool.py` | Clone repo, create branch, stage, commit, push via GitPython |
| `code_parser` | `tools/code_parser.py` | Walk a repo directory, read source files into `{path: content}` dict; filters hidden dirs and non-code files |
| `diff_generator` | `tools/diff_generator.py` | Produce unified diffs from `old_content`/`new_content` strings using `difflib` |
| `pr_tool` | `tools/pr_tool.py` | Build PR title + body, open PR via PyGitHub |
| `test_executor` | `tools/test_executor.py` | Stub executor used by the API routes (bypasses the real LLM agent in the current integration) |

### Tool return contract

Every tool function must return a `dict`. Optional keys:

```python
{
    "notes": str,              # Required — summary of what was done
    "file_changes": [          # Optional — list of file edits
        {
            "filename": str,
            "updated_content": str,
            "reason": str
        }
    ]
}
```

Any exception raised inside a tool propagates up to `StepExecutor`, which records it in `step_result.notes` and continues to the next step.

---

## 6. API Layer

### Routes (`api/routes.py`)

| Endpoint | Method | Handler | Background? |
|----------|--------|---------|------------|
| `/` | GET | Health check | No |
| `/health` | GET | Health check | No |
| `/run` | POST | Start new agent job | Yes — `process_job` |
| `/status/{job_id}` | GET | Poll job status | No |
| `/refine` | POST | Follow-up instruction on existing job | Yes — `process_job` |

### Error handling (`api/errors.py` + `api/main.py`)

Custom exception classes are registered as FastAPI exception handlers. Each returns a structured JSON error:

```json
{
  "status": "error",
  "code": 400,
  "type": "InvalidRepoURLError",
  "message": "..."
}
```

| Exception | HTTP Status |
|-----------|-------------|
| `InvalidRepoURLError` | 400 |
| `InvalidInstructionError` | 400 |
| `JobAlreadyRunningError` | 409 |
| `JobNotFoundError` | 404 |

### Schemas (`api/schemas.py`)

All request and response bodies are Pydantic v2 models. Internal models (`FileChange`, `AgentOutput`) are defined here too, to keep the data contract in one place.

---

## 7. Job Management

`utils/job_manager.py` provides a simple in-memory store backed by a Python dict. It supports `create_job`, `get`, and `update` operations.

**Important:** This is intentionally simple. It means:

- All job records are lost on server restart
- Multiple instances of the API do not share job state

For production use with persistence or horizontal scaling, replace `job_manager` with a Redis-backed implementation. The interface (`create_job`, `get`, `update`) is designed to be swapped without changing `routes.py`.

---

## 8. Memory System

`agent/memory.py` manages per-session state using LangChain's `InMemoryChatMessageHistory`.

Each session (identified by `job_id`) stores:

- **Conversation history** — alternating `HumanMessage` / `AIMessage` objects, capped at the last 12 messages by default to stay within LLM context windows
- **Completed steps** — list of step task strings that have been executed
- **Last plan** — the most recent plan's step task strings

Memory is keyed by `session_id = job_id`, so a `POST /refine` call on the same job automatically has full context of the original run.

**Current limitation:** Memory lives in the same Python process as `job_manager`. It is lost on restart. Future work: externalise to Redis alongside the job store.

---

## 9. Configuration

All configuration is managed by `config/settings.py` using Pydantic `BaseSettings`. Values are read from environment variables (or a `.env` file in the project root).

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | Yes | — | Groq LLM API key (primary LLM backend) |
| `OPENAI_API_KEY` | No | `None` | Optional OpenAI fallback |
| `LLM_MODEL` | No | `llama-3.3-70b-versatile` | Model identifier |
| `MAX_PLAN_STEPS` | No | `15` | Max steps the planner will produce |
| `GITHUB_TOKEN` | Yes | — | Fine-grained PAT with `repo` scope |
| `GITHUB_USERNAME` | Yes | — | GitHub username for attribution |
| `APP_ENV` | No | `development` | `development` or `production` |
| `LOG_LEVEL` | No | `INFO` | Python logging level |

`get_settings()` is decorated with `@lru_cache` so the `.env` file is parsed once per process.

---

## 10. Data Models

Key Pydantic models and where they flow:

```
RunRequest          (api/schemas.py)   → routes.py → process_job
  │
  ▼
Plan                (agent/planner.py) → executor.execute()
  └─ PlanStep[]
        │
        ▼
ToolDecision        (agent/executor.py) → tool.fn()
        │
        ▼
FileChange[]        (agent/executor.py) → ExecutorOutput → github_tool / pr_tool
        │
        ▼
AgentOutput         (api/schemas.py)   → job_manager.update()
        │
        ▼
JobStatusResponse   (api/schemas.py)   → GET /status response
```

---

## 11. Known Limitations & Future Work

### Current limitations

**In-memory state only.** Both `JobManager` and `MemoryManager` store state in RAM. A server restart clears everything. Horizontal scaling (multiple containers) is not currently supported.

**GitHub only.** `github_tool.py` and `pr_tool.py` are hardcoded to GitHub URLs and the PyGitHub API. GitLab and Bitbucket support is on the roadmap.

**No streaming.** Job status must be polled via `GET /status/{job_id}`. WebSocket streaming for real-time step-by-step updates is planned.

**Stub executor in production routes.** `api/routes.py` currently calls `run_test_executor` (from `tools/test_executor.py`) rather than the full `AgentChain`. The real agent wiring (`agent/chain.py`) is tested in isolation but not yet connected to the HTTP layer end-to-end.

**Single-file context limit.** The executor passes one step at a time to the LLM. For large monorepos, the code context passed per step may exceed the model's context window. LlamaIndex-based indexing is planned to address this.

### Roadmap items

- Redis-backed `JobManager` and `MemoryManager` for persistence and horizontal scale
- GitLab and Bitbucket support via an abstract `VCSProvider` interface
- WebSocket endpoint for streaming step-by-step agent progress
- LlamaIndex codebase indexing for large monorepos
- Plugin system for custom tools (linters, formatters, test runners)
- Fine-tuned code generation model as a drop-in LLM backend
