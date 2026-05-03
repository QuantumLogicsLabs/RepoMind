# RepoMind — Setup, Testing & Upgrade Guide

> Complete local development guide for Windows (MSYS2/MinGW), macOS, and Linux.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Clone the Repository](#2-clone-the-repository)
3. [Create a Virtual Environment](#3-create-a-virtual-environment)
4. [Install Dependencies](#4-install-dependencies)
5. [Configure Environment Variables](#5-configure-environment-variables)
6. [Run the API Server](#6-run-the-api-server)
7. [Running Tests](#7-running-tests)
8. [Upgrading Dependencies](#8-upgrading-dependencies)
9. [Known Issues & Fixes](#9-known-issues--fixes)
10. [Project Structure Reference](#10-project-structure-reference)

---

## 1. Prerequisites

| Tool           | Minimum Version | Check                                                            |
| -------------- | --------------- | ---------------------------------------------------------------- |
| Python         | 3.11+           | `python --version`                                               |
| pip            | 23+             | `pip --version`                                                  |
| Git            | Any recent      | `git --version`                                                  |
| OpenAI API Key | —               | [platform.openai.com](https://platform.openai.com)               |
| GitHub PAT     | —               | [github.com/settings/tokens](https://github.com/settings/tokens) |

> **Windows / MSYS2 users:** You are running Python inside an MSYS2-managed environment, which blocks system-wide `pip install`. You **must** use a virtual environment — see Section 3 for the exact commands.

---

## 2. Clone the Repository

```bash
git clone https://github.com/your-org/repomind.git
cd repomind
```

---

## 3. Create a Virtual Environment

A virtual environment isolates RepoMind's dependencies from your system Python. This is **required** on MSYS2/MinGW and recommended everywhere.

### Windows (PowerShell or MSYS2 terminal)

```powershell
# Create the virtual environment
python -m venv .venv

# Activate it (PowerShell)
.venv\Scripts\Activate.ps1

# Activate it (Command Prompt / MSYS2 bash)
.venv\Scripts\activate
```

If PowerShell blocks the activation script due to execution policy, run this once:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

> **Verify activation:** your terminal prompt should show `(.venv)` at the start. All `pip` and `python` commands from this point forward operate inside the virtual environment — your system Python is untouched.

---

## 4. Install Dependencies

With the virtual environment active:

```bash
# Install the project + all dev dependencies (pytest, black, ruff, mypy)
pip install -e ".[dev]"
```

This reads from `pyproject.toml` and installs everything in one shot. The `-e` flag installs the project in editable mode, so changes to your source files are reflected immediately without reinstalling.

### What gets installed

| Group | Packages                                                                                                                                                                                  |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Core  | `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `langchain`, `langchain-openai`, `langchain-community`, `openai`, `PyGithub`, `gitpython`, `python-dotenv`, `httpx`, `tree-sitter` |
| Dev   | `pytest`, `pytest-asyncio`, `black`, `ruff`, `mypy`                                                                                                                                       |

### Verify the install

```bash
python -c "import fastapi, langchain, pydantic; print('All core imports OK')"
pytest --version
```

---

## 5. Configure Environment Variables

```bash
# Copy the example file
cp config/.env.example .env
```

Open `.env` in your editor and fill in every value:

```env
# ── LLM ──────────────────────────────────────────────────────────────────────
OPENAI_API_KEY=sk-...          # Your OpenAI secret key
LLM_MODEL=gpt-4o               # Or gpt-3.5-turbo for cheaper testing
MAX_PLAN_STEPS=15              # Max steps the planner will produce

# ── GitHub ────────────────────────────────────────────────────────────────────
GITHUB_TOKEN=ghp_...           # Personal Access Token with 'repo' scope
GITHUB_USERNAME=your-username  # Your GitHub username

# ── App ───────────────────────────────────────────────────────────────────────
APP_ENV=development
LOG_LEVEL=INFO
```

### How to create a GitHub PAT

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens) → **Tokens (classic)**
2. Click **Generate new token (classic)**
3. Set expiration and check the `repo` scope
4. Copy the token — you won't see it again

> **Security:** `.env` is already listed in `.gitignore`. Never commit it or share it. Never push it to any public repository.

---

## 6. Run the API Server

```bash
uvicorn api.main:app --reload --port 8000
```

The `--reload` flag auto-restarts the server whenever you save a file — ideal for development.

| URL                            | Description                                                           |
| ------------------------------ | --------------------------------------------------------------------- |
| `http://localhost:8000`        | Health check — returns `{"service": "RepoMind", "status": "running"}` |
| `http://localhost:8000/health` | Simple health endpoint                                                |
| `http://localhost:8000/docs`   | Interactive Swagger UI                                                |
| `http://localhost:8000/redoc`  | ReDoc API reference                                                   |

### Test it manually with curl

```bash
# Start a new job
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/your-org/your-repo",
    "instruction": "Add docstrings to all public functions in src/"
  }'

# Response: {"job_id": "a1b2c3d4", "status": "queued"}

# Poll for status
curl http://localhost:8000/status/a1b2c3d4

# Send a refinement
curl -X POST http://localhost:8000/refine \
  -H "Content-Type: application/json" \
  -d '{"job_id": "a1b2c3d4", "instruction": "Also add type hints"}'
```

---

## 7. Running Tests

Make sure your virtual environment is active before running tests.

### Run the full suite

```bash
pytest tests/ -v
```

### Run individual test layers

```bash
pytest tests/test_agent.py -v    # Agent logic: planner, executor, chain, memory
pytest tests/test_tools.py -v    # Tool layer: code parser, diff, GitHub, PR
pytest tests/test_api.py   -v    # API layer: all HTTP endpoints
```

### Run a single test by name

```bash
pytest tests/test_agent.py::test_planner_creates_plan -v
pytest tests/test_api.py::test_api_endpoints_integration -v
```

### Run with short traceback (CI style)

```bash
pytest tests/ -v --tb=short
```

### Understanding test output

| Result   | Meaning                                                    |
| -------- | ---------------------------------------------------------- |
| `PASSED` | Test succeeded                                             |
| `FAILED` | Test failed — read the traceback                           |
| `ERROR`  | Test crashed before it could run (usually an import error) |
| `XFAIL`  | Test was expected to fail and did — this is normal         |

> **Known expected failure:** `test_api_error_handling` in `test_api.py` is documented as intentionally failing due to a bug in `main.py` where non-GitHub URLs are not properly rejected. This is a bug to fix, not something to ignore.

### Run with coverage (optional)

```bash
pip install pytest-cov
pytest tests/ -v --cov=. --cov-report=term-missing
```

### Lint and type-check (not yet in CI but documented in README)

```bash
# Format check
black --check .

# Lint
ruff check .

# Type check
mypy agent/ api/ tools/ utils/ config/
```

To auto-fix formatting and lint issues:

```bash
black .
ruff check . --fix
```

---

## 8. Upgrading Dependencies

### Check what's outdated

```bash
pip list --outdated
```

### Upgrade all dev dependencies

```bash
pip install --upgrade -e ".[dev]"
```

### Upgrade a single package

```bash
pip install --upgrade langchain langchain-openai
```

### After upgrading

Always re-run the full test suite to catch regressions:

```bash
pytest tests/ -v --tb=short
```

If `mypy` or `ruff` start flagging new issues after an upgrade, check the changelog of the upgraded package. LangChain in particular has frequent breaking changes between minor versions.

### Pinning versions for reproducibility

If you need a locked, reproducible environment (e.g. for a production deployment):

```bash
pip freeze > requirements-lock.txt
```

To recreate this exact environment later:

```bash
pip install -r requirements-lock.txt
```

---

## 9. Known Issues & Fixes

### `externally-managed-environment` error on Windows / MSYS2

**Problem:** Running `pip install` globally fails with the MSYS2 policy error.

**Fix:** Always activate a virtual environment first (see Section 3). Never use `--break-system-packages` — it can corrupt your MSYS2 Python installation.

---

### `ModuleNotFoundError` on import

**Problem:** `pytest` or `uvicorn` can't find project modules.

**Fix:** Make sure the project is installed in editable mode:

```bash
pip install -e ".[dev]"
```

If the error persists, check that your virtual environment is active:

```bash
which python      # macOS/Linux — should point inside .venv/
where python      # Windows — should point inside .venv\
```

---

### `tree-sitter` language bindings not working

**Problem:** `code_parser.py` may fail at runtime because `tree-sitter>=0.23` requires language grammar packages to be installed separately.

**Fix:** Install the Python language grammar:

```bash
pip install tree-sitter-python
```

For other languages, install the corresponding `tree-sitter-<lang>` package from PyPI.

---

### `test_api_error_handling` always fails

**Problem:** This test sends a GitLab URL to `POST /run` and expects a 422 response, but the server returns 200.

**Root cause:** The URL validation in `api/routes.py` raises `InvalidRepoURLError` with a string message instead of the URL object, and the error handler in `api/main.py` does not properly map this to a 422 status.

**Fix (apply to `api/routes.py`):**

```python
# Change this line:
raise InvalidRepoURLError("Invalid GitHub URL")

# To:
raise InvalidRepoURLError(request.repo_url)
```

---

### `.env` file not loading

**Problem:** Settings raise a validation error even after filling in `.env`.

**Fix:** Ensure `.env` is in the project root (same level as `pyproject.toml`), not inside `config/`. The `Settings` class in `config/settings.py` loads from `env_file = ".env"` relative to the working directory you launch from.

---

## 10. Project Structure Reference

```
RepoMind/
│
├── agent/                  ← Core ML logic
│   ├── chain.py            ← Wires LLM + memory + tools into one run() call
│   ├── planner.py          ← Breaks instruction into ordered PlanSteps
│   ├── executor.py         ← Runs each step, decides which tool to call
│   └── memory.py           ← Per-session conversation + task memory
│
├── tools/                  ← Agent-callable tool implementations
│   ├── github_tool.py      ← Clone, branch, commit, push via PyGitHub
│   ├── code_parser.py      ← Parse files into tree-sitter / AST structures
│   ├── diff_generator.py   ← Produce human-readable diffs
│   ├── pr_tool.py          ← Compose and open Pull Requests
│   └── test_executor.py    ← Stub executor used by routes (replaces real agent)
│
├── prompts/                ← LLM prompt templates (currently empty — see Known Issues)
│   └── __init__.py
│
├── api/                    ← FastAPI HTTP service
│   ├── main.py             ← App entry-point, middleware, error handlers
│   ├── routes.py           ← POST /run, GET /status/{id}, POST /refine
│   ├── schemas.py          ← Pydantic request/response models
│   └── errors.py           ← Custom exception classes
│
├── tests/                  ← Full test suite
│   ├── test_agent.py       ← Unit tests: planner, executor, chain
│   ├── test_tools.py       ← Unit tests: all tool functions
│   └── test_api.py         ← Integration tests: all HTTP routes
│
├── config/
│   ├── settings.py         ← Pydantic BaseSettings (reads .env)
│   └── .env.example        ← Template — copy to project root as .env
│
├── utils/
│   └── job_manager.py      ← In-memory job store (create, get, update)
│
├── Dockerfile              ← Production container image
├── pyproject.toml          ← Project metadata, deps, tool config
└── .github/workflows/ci.yml  ← GitHub Actions CI pipeline
```
