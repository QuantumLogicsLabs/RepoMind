# Contributing to RepoMind

Thank you for taking the time to contribute. RepoMind is the AI engine that powers HackingTheRepo — it clones real repositories, generates code with an LLM, and opens pull requests autonomously. That makes quality and correctness especially important.

This document covers everything you need to go from zero to a merged pull request.

---

## Table of Contents

1. [Before You Start](#1-before-you-start)
2. [Development Setup](#2-development-setup)
3. [Project Structure at a Glance](#3-project-structure-at-a-glance)
4. [Making Changes](#4-making-changes)
5. [Code Style](#5-code-style)
6. [Testing](#6-testing)
7. [Commit Messages](#7-commit-messages)
8. [Opening a Pull Request](#8-opening-a-pull-request)
9. [Adding a New Tool](#9-adding-a-new-tool)
10. [Working with Prompts](#10-working-with-prompts)
11. [Security Guidelines](#11-security-guidelines)

---

## 1. Before You Start

- **Search existing issues and PRs** before opening a new one — your idea may already be in progress.
- **Open an issue first** for any non-trivial change. This saves everyone time if the approach isn't right.
- **Security issues** must be reported privately — see [SECURITY.md](SECURITY.md), not as a public issue.

---

## 2. Development Setup

### Prerequisites

| Tool | Minimum Version |
|------|----------------|
| Python | 3.11+ |
| Git | Any recent |
| A GitHub PAT | `repo` scope |
| A Groq or OpenAI API key | — |

### Clone and install

```bash
git clone https://github.com/your-org/repomind.git
cd repomind

python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

pip install -e ".[dev]"
```

The `-e` flag installs the project in editable mode. Changes to source files take effect immediately without reinstalling.

### Configure environment variables

```bash
cp config/.env.example .env
```

Open `.env` and fill in every value. Refer to `config/settings.py` for the full list of supported variables. The `.env` file is listed in `.gitignore` — **never commit it**.

### Verify the setup

```bash
python -c "import fastapi, langchain, pydantic; print('OK')"
uvicorn api.main:app --reload --port 8000
# Visit http://localhost:8000/docs
pytest tests/ -v
```

---

## 3. Project Structure at a Glance

```
RepoMind/
├── agent/           ← LangChain orchestration (chain, planner, executor, memory)
├── tools/           ← Agent-callable tool implementations
├── prompts/         ← LLM prompt templates (version-controlled)
├── api/             ← FastAPI service (routes, schemas, error handlers)
├── config/          ← Pydantic settings, .env.example
├── utils/           ← Shared utilities (JobManager)
└── tests/           ← Full test suite (agent, tools, API)
```

The **agent layer** (`agent/`) is the brain. It reads memory, builds a plan, and calls tools. The **tools layer** (`tools/`) is the hands — each tool does exactly one thing (clone, parse, diff, PR). The **API layer** (`api/`) is the surface — it receives HTTP requests, hands off to the agent, and returns job status.

---

## 4. Making Changes

```bash
# Create a feature branch from main
git checkout main
git pull origin main
git checkout -b feat/your-feature-name
```

Branch naming conventions:

| Type | Prefix | Example |
|------|--------|---------|
| Feature | `feat/` | `feat/gitlab-support` |
| Bug fix | `fix/` | `fix/memory-context-overflow` |
| Prompt update | `prompt/` | `prompt/better-plan-decomposition` |
| Refactor | `refactor/` | `refactor/executor-error-handling` |
| Docs | `docs/` | `docs/architecture-diagram` |

---

## 5. Code Style

We use **Black** for formatting, **Ruff** for linting, and **mypy** for type checking. All three run in CI — a PR that fails any of them will not be merged.

```bash
# Format
black .

# Lint
ruff check .

# Type check
mypy .
```

Key style rules (enforced by `pyproject.toml`):

- Line length: 100 characters
- All public functions and classes must have type annotations
- All public functions must have docstrings
- No `# type: ignore` comments without an explanation
- No `eval()` or `exec()` anywhere — especially not on LLM-generated content

---

## 6. Testing

### Running the test suite

```bash
pytest tests/ -v                  # Full suite
pytest tests/test_agent.py        # Agent layer only
pytest tests/test_tools.py        # Tools layer only
pytest tests/test_api.py          # API / HTTP routes only
pytest tests/ --cov=. --cov-report=term-missing   # With coverage
```

### Writing tests

- Every new function needs at least one unit test.
- Mock the LLM (`MagicMock`, `patch.object`) — tests must not make real API calls.
- Mock GitHub interactions — tests must not clone real repos or open real PRs.
- Use `pytest`'s `tmp_path` fixture for any file system operations.
- New API endpoints need an integration test in `test_api.py` using `TestClient`.

### Test structure conventions

Follow the pattern already established in the existing tests:

```python
def test_descriptive_name():
    """One-line docstring describing what is being tested."""
    # 1. Setup
    # 2. Execute
    # 3. Assert
```

---

## 7. Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]
[optional footer]
```

| Type | Use for |
|------|---------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `prompt` | Changes to any file in `prompts/` |
| `refactor` | Code restructuring with no behaviour change |
| `test` | Adding or updating tests |
| `docs` | Documentation only |
| `chore` | Tooling, CI, dependency updates |

Examples:

```
feat(tools): add gitlab_tool for GitLab repo cloning
fix(executor): handle missing tool name without crashing
prompt(code_gen): improve few-shot examples for async refactors
test(api): add coverage for POST /refine error cases
```

---

## 8. Opening a Pull Request

1. Push your branch: `git push origin feat/your-feature-name`
2. Open a PR against `main` on GitHub
3. Fill in the PR template completely — empty sections will be asked about in review
4. Ensure all CI checks pass (lint → type check → tests → Docker build)
5. Request a review — one approval is required to merge

PRs are squash-merged to keep the `main` history clean.

---

## 9. Adding a New Tool

Tools are the agent's interface to the outside world. Each tool should do **one thing** and return a consistent payload.

### Step 1 — Create the tool file

```
tools/your_tool.py
```

Follow the pattern of existing tools. Every tool function must:

- Accept a `dict` of inputs
- Return a `dict` with at least a `"notes"` key
- Return a `"file_changes"` key (list of dicts with `filename`, `updated_content`, `reason`) if it modifies files
- Raise a descriptive exception on failure — never silently swallow errors

```python
def your_tool_function(inputs: dict) -> dict:
    """One-line docstring."""
    # ... implementation ...
    return {
        "notes": "What was done.",
        "file_changes": []   # omit if no file changes
    }
```

### Step 2 — Register the tool as a `ToolSpec`

In the code that wires up `AgentChain`, add:

```python
from tools.your_tool import your_tool_function

ToolSpec(
    name="your_tool_name",
    description="Clear description the LLM will use to decide when to call this tool.",
    fn=your_tool_function,
)
```

The description is what the executor's LLM reads to pick the right tool — make it precise.

### Step 3 — Add tests

Add unit tests to `tests/test_tools.py`. Mock any external services (GitHub API, filesystem writes to production paths). Use `tmp_path` for local file operations.

### Step 4 — Update this document

Add your tool to the project structure section and describe its purpose.

---

## 10. Working with Prompts

All LLM prompt templates live in `prompts/` and are version-controlled like code. Treat prompt changes with the same rigour as code changes — a bad prompt can break the entire agent.

### Rules for prompt changes

- Every prompt change needs a before/after comparison in the PR description (use the collapsible template in the PR template).
- Test against at least 3 representative instructions that cover edge cases.
- Do not hardcode expected output counts or file paths in prompts — keep them general.
- Prompts must instruct the LLM to return **structured output only** when used with `with_structured_output()`.
- Never include real API keys, repository URLs, or personal information in prompts or test fixtures.

---

## 11. Security Guidelines

Because RepoMind acts on real repositories with real credentials, security discipline is non-negotiable:

- **Never commit `.env`** — it is gitignored. Use `config/.env.example` as the only committed template.
- **Use fine-grained GitHub PATs** — scoped to the minimum repositories needed, with an expiration date.
- **Do not `eval()` or `exec()` LLM output** — ever. Parse structured responses through Pydantic models only.
- **Do not log API keys or tokens** — set `LOG_LEVEL=WARNING` in production and audit any new log statements before committing.
- **Mock GitHub in tests** — CI must never clone real repos, create real branches, or open real PRs.
- If you discover a security vulnerability, follow the process in [SECURITY.md](SECURITY.md).

---

Thank you for contributing to RepoMind. Every improvement makes the agent smarter and safer.
