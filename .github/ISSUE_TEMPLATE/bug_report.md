---
name: Bug Report
about: Something in RepoMind isn't working correctly
title: "[BUG] "
labels: bug
assignees: ""
---

## Description

<!-- A clear, concise description of what the bug is. -->

## Component

- [ ] Agent — Chain / Planner / Executor (`agent/`)
- [ ] Agent — Memory (`agent/memory.py`)
- [ ] Tool — GitHub (`tools/github_tool.py`)
- [ ] Tool — Code Parser (`tools/code_parser.py`)
- [ ] Tool — Diff Generator (`tools/diff_generator.py`)
- [ ] Tool — PR Tool (`tools/pr_tool.py`)
- [ ] API — Routes / Schemas (`api/`)
- [ ] Configuration / Settings (`config/settings.py`)
- [ ] Docker / Deployment
- [ ] Other: <!-- describe -->

## Steps to Reproduce

```bash
# curl command, Python snippet, or exact API request that triggers the bug
```

1.
2.
3.

## Expected Behavior

<!-- What should happen. -->

## Actual Behavior

<!-- What actually happens. Paste the full error / traceback below. -->

```
Paste error output here
```

## Environment

| Field | Value |
|-------|-------|
| OS | <!-- e.g. Ubuntu 22.04, macOS 14, Windows 11 --> |
| Python | <!-- e.g. 3.11.4 --> |
| RepoMind version / commit | <!-- git SHA or tag --> |
| LLM model | <!-- e.g. gpt-4o, claude-3-5-sonnet --> |
| Deployment | <!-- local uvicorn / Docker / hosted --> |

## Additional Context

<!-- Logs, screenshots, or anything else that helps. Remove any API keys or tokens before pasting. -->
