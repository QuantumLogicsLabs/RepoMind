# RepoMind — Command Cheat Sheet

> Every command needed to open, run, test and ship RepoMind, in order. Windows (PowerShell) is shown first; macOS/Linux equivalents follow where they differ. For explanations see [SETUP.md](SETUP.md).

---

## 1. Open RepoMind from the parent repo

RepoMind is a git submodule of `HackingTheRepo`. If the `repomind/` folder is empty, pull it first.

```powershell
cd C:\QuantumLogicsLabs\HackingTheRepo

# First time only: fetch the submodule contents
git submodule update --init --recursive repomind

# Open the project
cd repomind

# Open it in VS Code
code .

# Open the docs folder only
code docs
# or in Explorer
explorer docs
```

Clone RepoMind on its own instead:

```powershell
git clone https://github.com/QuantumLogicsLabs/RepoMind.git
cd RepoMind
```

---

## 2. Python environment (run inside `repomind/`)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # PowerShell
# .venv\Scripts\activate            # cmd / MSYS2 bash
# source .venv/bin/activate         # macOS / Linux

# If PowerShell blocks activation (once):
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

pip install -e ".[dev]"
pip install tree-sitter-python      # grammar needed by tools/code_parser.py
```

Verify:

```powershell
python --version                    # needs 3.11+
python -c "import fastapi, langchain, pydantic; print('All core imports OK')"
```

---

## 3. Environment variables

```powershell
Copy-Item .env.example .env         # macOS/Linux: cp .env.example .env
notepad .env
```

Fill in `GROQ_API_KEY`, `GITHUB_TOKEN`, `GITHUB_USERNAME` (see `.env.example`). `.env` must sit in the project root, next to `pyproject.toml`. Never commit it.

---

## 4. Run the API

```powershell
uvicorn api.main:app --reload --port 8000
```

| URL                            | What                   |
| ------------------------------ | ---------------------- |
| `http://localhost:8000`        | Service status         |
| `http://localhost:8000/health` | Health check           |
| `http://localhost:8000/docs`   | Swagger UI             |
| `http://localhost:8000/redoc`  | ReDoc                  |

```powershell
Start-Process http://localhost:8000/docs     # open Swagger in the browser
```

Try the endpoints (PowerShell — use `curl.exe`, since bare `curl` is an alias for `Invoke-WebRequest`):

```powershell
curl.exe http://localhost:8000/health

curl.exe -X POST http://localhost:8000/run -H "Content-Type: application/json" `
  -d '{\"repo_url\":\"https://github.com/owner/repo\",\"instruction\":\"Add docstrings to all public functions\"}'

curl.exe http://localhost:8000/status/<job_id>

curl.exe -X POST http://localhost:8000/refine -H "Content-Type: application/json" `
  -d '{\"job_id\":\"<job_id>\",\"instruction\":\"Also add type hints\"}'
```

Stop the server with `Ctrl+C`. If port 8000 is taken:

```powershell
netstat -ano | findstr :8000
taskkill /PID <pid> /F
# or just use another port
uvicorn api.main:app --reload --port 8001
```

---

## 5. Tests

```powershell
pytest tests/ -v
pytest tests/test_agent.py -v
pytest tests/test_tools.py -v
pytest tests/test_api.py -v
pytest tests/test_api.py::test_api_endpoints_integration -v   # single test
pytest tests/ -v --tb=short                                   # CI style
pytest tests/ -v --cov=. --cov-report=term-missing            # coverage
```

> `test_api_error_handling` is a documented known failure — see [SETUP.md](SETUP.md#test_api_error_handling-always-fails).

---

## 6. Lint, format, type-check

```powershell
black --check .
ruff check .
mypy agent/ api/ tools/ utils/ config/

# Auto-fix
black .
ruff check . --fix
```

---

## 7. Docker

```powershell
docker build -t repomind .
docker run -p 8000:8000 --env-file .env repomind
docker run -d --name repomind -p 8000:8000 --env-file .env repomind   # detached
docker logs -f repomind
docker stop repomind; docker rm repomind
```

---

## 8. Website (`website/`)

```powershell
cd website
npm install
npm run dev                         # Vite dev server, usually http://localhost:5173
npm run build                       # type-check + production build into dist/
npm run preview                     # serve the production build locally
cd ..
```

---

## 9. Dependencies

```powershell
pip list --outdated
pip install --upgrade -e ".[dev]"
pip install --upgrade langchain langchain-groq
pip freeze > requirements-lock.txt
pip install -r requirements-lock.txt
```

Re-run `pytest tests/ -v --tb=short` after any upgrade.

---

## 10. Git (submodule workflow)

RepoMind has its own git history. Commit inside `repomind/` first, then record the new commit in the parent repo.

```powershell
# Inside repomind/
git checkout -b feat/your-feature
git add .
git commit -m "feat: your change"
git push origin feat/your-feature

# Pull latest RepoMind main
git checkout main
git pull origin main

# Back in the parent repo: record the updated submodule pointer
cd ..
git add repomind
git commit -m "chore: update repomind submodule"
git push
```

Update every submodule to the latest remote commit:

```powershell
git submodule update --remote --merge
```

---

## 11. Troubleshooting quick fixes

| Symptom                                | Fix                                                        |
| -------------------------------------- | ---------------------------------------------------------- |
| `repomind/` folder is empty            | `git submodule update --init --recursive repomind`         |
| `ModuleNotFoundError`                  | Activate `.venv`, then `pip install -e ".[dev]"`           |
| `externally-managed-environment`       | Use a venv; never `--break-system-packages`                |
| Settings validation error              | `.env` must be in the project root, not inside `config/`   |
| `tree-sitter` language errors          | `pip install tree-sitter-python`                           |
| `Activate.ps1` blocked                 | `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| Port 8000 already in use               | Use `--port 8001` or kill the process (section 4)          |
