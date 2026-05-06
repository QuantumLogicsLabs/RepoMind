# Security Policy

RepoMind is an AI agent that clones repositories, writes code, and opens pull requests on behalf of users. It handles GitHub tokens, LLM API keys, and third-party code — making responsible security practices especially important.

---

## Supported Versions

| Version | Supported |
|---------|-----------|
| `main` (latest) | ✅ Active |
| Older releases | ❌ Not supported |

---

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report privately by emailing: **security@hackingt​herepo.dev**

Include as much of the following as possible:

- A description of the vulnerability and its potential impact
- The affected component (e.g. `tools/github_tool.py`, `api/routes.py`, Docker image)
- Steps to reproduce or a minimal proof-of-concept
- Any suggested fix or mitigation

We will acknowledge your report within **48 hours** and aim to ship a fix within **14 days** for critical issues.

---

## Scope

The following are **in scope**:

| Component | Examples |
|-----------|---------|
| **GitHub Tool** (`tools/github_tool.py`) | Token leakage, unauthorised repo access, branch/commit injection |
| **Agent / Executor** (`agent/`) | Prompt injection via malicious repo content, runaway plan execution |
| **REST API** (`api/`) | Auth bypass on `/run` or `/refine`, job ID enumeration on `/status/{job_id}` |
| **Configuration** (`config/settings.py`, `.env.example`) | Secrets leaked in logs, insecure defaults |
| **Docker image** (`Dockerfile`) | Running as root, exposed credentials in image layers |
| **Dependencies** (`pyproject.toml`) | Known CVEs in pinned packages |

The following are **out of scope**:

- Vulnerabilities in repositories *submitted to* RepoMind for editing (user-supplied content)
- Theoretical prompt injection with no reproducible exploit path
- Rate limiting or abuse on a self-hosted deployment

---

## Known Security Considerations

These are acknowledged design decisions, not bugs:

**GitHub Token scope**
`GITHUB_TOKEN` requires `repo` scope to clone private repos and open PRs. Use a fine-grained PAT scoped to only the repositories RepoMind needs to access. Never use a token with `admin:org` or `delete_repo` scope.

**Agent executes LLM-generated plans against real repos**
The executor (`agent/executor.py`) carries out steps planned by the LLM. Maliciously crafted repository content (e.g. files with adversarial comments) could influence plan generation. Do not point RepoMind at untrusted repositories without review.

**Job IDs and status polling**
`GET /status/{job_id}` is unauthenticated in the reference implementation. In any multi-user deployment, add authentication middleware so users can only poll their own jobs.

**LLM responses are parsed and executed**
Structured outputs from the LLM (`ToolDecision`, `Plan`) drive tool calls. Ensure your LLM provider enforces strict output schemas; do not eval or exec any LLM-generated string directly.

**`.env` files**
`OPENAI_API_KEY` and `GITHUB_TOKEN` must never be committed. Both `.env` and `.env.local` are in `.gitignore`. Always use `config/.env.example` as the only committed template.

---

## Dependency Vulnerabilities

We monitor dependencies via GitHub Dependabot. To audit locally:

```bash
pip install pip-audit
pip-audit
```

---

## Disclosure Policy

We follow **coordinated disclosure**:

1. Reporter notifies us privately.
2. We confirm, reproduce, and develop a fix.
3. We release the fix and credit the reporter (unless anonymity is requested).
4. Details are published in the release notes after users have had time to update.

---

## Hall of Fame

Researchers who have responsibly disclosed issues will be credited here.

*No disclosures yet — be the first!*

---

_RepoMind — AI-powered code editing, responsibly._
