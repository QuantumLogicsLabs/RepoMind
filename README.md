# 🧠 RepoMind

> **The Brain of HackingTheRepo** — A pure ML/AI engine that understands, plans, and rewrites code repositories on demand.

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)](https://www.python.org/)
[![LangChain](https://img.shields.io/badge/LangChain-0.2%2B-green)](https://langchain.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-teal?logo=fastapi)](https://fastapi.tiangolo.com/)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/your-org/repomind/ci.yml?label=CI)](/.github/workflows/)

---

## What is RepoMind?

**RepoMind** is the standalone ML core that powers [HackingTheRepo](https://github.com/your-org/hackingtherep) — a web-based platform where users describe code changes in plain English and an AI agent clones the target repository, implements the changes, and opens a Pull Request automatically.

RepoMind lives as a **separate, independently deployable ML service**. It is intentionally decoupled from the web frontend so it can be iterated on, tested, and scaled without touching the UI layer. Once mature, RepoMind is consumed by the HackingTheRepo backend over a simple REST API.

**RepoMind is responsible for:**

- Receiving a natural-language change instruction and a repository URL
- Cloning the repository and deeply understanding its structure
- Planning a step-by-step set of code edits using an LLM-powered agent
- Executing those edits via code generation tools
- Producing a diff and pushing a Pull Request back to GitHub

---

## Where RepoMind fits in the bigger picture

```
┌─────────────────────────────────────────────────┐
│              HackingTheRepo (Web Platform)       │
│  User → describes change → selects repo → done  │
│                                                 │
│   Frontend (React/Next.js)                      │
│         │                                       │
│   Backend (Node / Django / etc.)                │
│         │                                       │
│         │  POST /run   (REST API call)           │
│         ▼                                       │
│  ┌─────────────────────────────────┐            │
│  │        RepoMind  (this repo)    │            │
│  │   FastAPI · LangChain · GitHub  │            │
│  └─────────────────────────────────┘            │
│         │                                       │
│         ▼                                       │
│     GitHub PR created automatically             │
└─────────────────────────────────────────────────┘
```

---

## Core Features

- **Agentic Planning** — A LangChain-powered planner breaks any free-text instruction into an ordered list of atomic code edits before touching a single file.
- **Context-Aware Code Generation** — The agent reads and reasons over the entire repo before generating new code, respecting existing patterns and style.
- **GitHub Integration** — Clones repos, creates branches, commits changes, and opens PRs fully programmatically via the GitHub API.
- **Diff Generation** — Every proposed change is surfaced as a human-readable diff before being committed.
- **Memory Layer** — Conversation/session memory lets users refine and iterate on the same repo without losing context.
- **FastAPI Service** — Ships as a lightweight HTTP service so HackingTheRepo (or any other consumer) can call it with a simple POST request.
- **Prompt Library** — All LLM prompts are first-class citizens living in version-controlled Python files, not buried in application logic.
- **Fully Tested & Dockerised** — Comes with agent, tool, and API-level test suites plus a production-ready Dockerfile.

---

## Tech Stack

| Layer              | Technology                   |
| ------------------ | ---------------------------- |
| Agent Framework    | LangChain / LlamaIndex       |
| LLM Backend        | Groq (Llama 3.3 70B)         |
| API Server         | FastAPI + Uvicorn            |
| GitHub Integration | PyGitHub + GitPython         |
| Code Parsing       | Tree-sitter / AST            |
| Config Management  | Pydantic Settings            |
| Testing            | Pytest                       |
| Containerisation   | Docker                       |
| CI                 | GitHub Actions               |

---

## Folder Structure

```
RepoMind/                          ← Project root
│
├── agent/                         ← 🧠 Core ML logic (LangChain agent)
│   ├── chain.py                   ← Main LangChain chain definition; wires LLM + memory + tools
│   ├── planner.py                 ← Decomposes the user's instruction into ordered edit steps
│   ├── executor.py                ← Runs each planned step, calling the right tools in sequence
│   └── memory.py                  ← Manages conversation / session memory across turns
│
├── tools/                         ← 🔧 Agent-callable tool implementations
│   ├── github_tool.py             ← Clone repo, create branch, push commits, open PR via GitHub API
│   ├── code_parser.py             ← Parse repository files into AST/tree-sitter structures the LLM can reason about
│   ├── diff_generator.py          ← Produce human-readable diffs from before/after file states
│   └── pr_tool.py                 ← Compose PR title, body, and labels; submit the pull request
│
├── prompts/                       ← 💬 All LLM prompt templates (version-controlled)
│   ├── system_prompt.py           ← Global system persona: "You are RepoMind, an expert software engineer…"
│   ├── code_gen_prompt.py         ← Few-shot template for generating code edits given a file + instruction
│   └── pr_description.py          ← Template that turns a list of diffs into a clear PR description
│
├── api/                           ← 🌐 FastAPI HTTP service (consumed by HackingTheRepo backend)
│   ├── main.py                    ← FastAPI app entry-point; mounts router, configures middleware
│   ├── routes.py                  ← POST /run, GET /status/{job_id}, POST /refine endpoints
│   └── schemas.py                 ← Pydantic request/response models (RunRequest, JobStatus, etc.)
│
├── tests/                         ← ✅ Test suite
│   ├── test_agent.py              ← Unit tests for chain, planner, and executor logic
│   ├── test_tools.py              ← Tests for github_tool, code_parser, diff_generator, pr_tool
│   └── test_api.py                ← Integration tests against the FastAPI routes
│
├── config/                        ← ⚙️ Configuration & environment
│   ├── settings.py                ← Pydantic BaseSettings: reads env vars, sets defaults
│   └── .env.example               ← Template listing all required environment variables
│
├── README.md                      ← You are here
├── Dockerfile                     ← Production Docker image for the RepoMind service
├── .github/workflows/             ← GitHub Actions CI pipeline (lint → test → build → push)
└── pyproject.toml                 ← Project metadata, dependencies, and tool config (black, ruff, pytest)
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- A GitHub Personal Access Token (PAT) with `repo` scope
- A Groq API key ([console.groq.com/keys](https://console.groq.com/keys))
- Docker (optional, for containerised deployment)

### 1. Clone the repo

```bash
git clone https://github.com/your-org/repomind.git
cd repomind
```

### 2. Install dependencies

```bash
pip install -e ".[dev]"
# or
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp config/.env.example .env
```

Open `.env` and fill in the required values:

```env
GROQ_API_KEY=gsk_...
GITHUB_TOKEN=ghp_...
GITHUB_USERNAME=your-github-username
LLM_MODEL=openai/gpt-oss-120b
MAX_PLAN_STEPS=15
LOG_LEVEL=INFO
```

### 4. Run the API server

```bash
uvicorn api.main:app --reload --port 8000
```

The API is now live at `http://localhost:8000`. Visit `http://localhost:8000/docs` for the interactive Swagger UI.

### 5. Run with Docker

```bash
docker build -t repomind .
docker run -p 8000:8000 --env-file .env repomind
```

---

## API Reference

### `POST /run`

Kick off a new agent job.

**Request body:**

```json
{
  "repo_url": "https://github.com/owner/repo",
  "instruction": "Refactor all database calls in src/db/ to use async/await",
  "branch_name": "repomind/async-db-refactor",
  "pr_title": "refactor: async database calls"
}
```

**Response:**

```json
{
  "job_id": "a1b2c3d4",
  "status": "running"
}
```

### `GET /status/{job_id}`

Poll the status of a running job.

**Response:**

```json
{
  "job_id": "a1b2c3d4",
  "status": "completed",
  "pr_url": "https://github.com/owner/repo/pull/42",
  "diff_summary": "Modified 6 files, added 120 lines, removed 95 lines"
}
```

### `POST /refine`

Send a follow-up instruction on an existing job to iterate on the same PR.

**Request body:**

```json
{
  "job_id": "a1b2c3d4",
  "instruction": "Also add type hints to all the new async functions"
}
```

---

## How the Agent Works

```
User Instruction
      │
      ▼
  [ Planner ]          ← Breaks instruction into 1..N ordered steps
      │
      ▼
  [ Executor ]         ← Iterates over steps; decides which tool to call
      │
  ┌───┴────────────────────────────────┐
  │                                    │
  ▼                                    ▼
[ code_parser ]               [ github_tool ]
Parse existing files           Clone, branch, commit
      │                                │
      ▼                                ▼
[ code_gen_prompt ]           [ diff_generator ]
Generate new code              Produce human-readable diff
      │                                │
      └───────────────┬────────────────┘
                      ▼
                 [ pr_tool ]
            Compose & open PR
```

Memory is maintained throughout the session via `agent/memory.py`, so follow-up refinement instructions have full context of what was already done.

---

## Running Tests

```bash
pytest tests/ -v
```

To run only a specific layer:

```bash
pytest tests/test_agent.py   # agent logic
pytest tests/test_tools.py   # tool integrations
pytest tests/test_api.py     # HTTP API
```

---

## CI / CD

The `.github/workflows/` directory contains a GitHub Actions pipeline that runs on every push and pull request:

1. **Lint** — `ruff` and `black --check`
2. **Type check** — `mypy`
3. **Test** — `pytest` with coverage reporting
4. **Build** — Docker image build
5. **Push** — Push image to container registry (on `main` only)

---

## Contributing

RepoMind is the internal ML engine for HackingTheRepo. Contributions, bug reports, and feature suggestions are welcome.

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit your changes: `git commit -m "feat: add your feature"`
4. Push the branch: `git push origin feat/your-feature`
5. Open a Pull Request

Please follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages.

---

## Roadmap

- [ ] Support for GitLab and Bitbucket alongside GitHub
- [ ] Streaming job status via WebSockets
- [ ] LlamaIndex-based codebase indexing for large monorepos
- [ ] Multi-file, multi-PR orchestration
- [ ] Fine-tuned code generation model as a drop-in LLM backend
- [ ] Plugin system for custom tools (linters, formatters, test runners)

---

## License

This software is licensed under the [HackingTheRepo Proprietary Software License Agreement (PPSLA v1.0)](LICENSE).

Copyright © 2025 QuantumLogics Incorporated. All Rights Reserved. Unauthorized use, reproduction, modification, or distribution is strictly prohibited.
