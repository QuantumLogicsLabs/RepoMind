## Summary

<!-- One or two sentences describing what this PR does and why. -->

Closes #<!-- issue number -->

---

## Type of Change

- [ ] Bug fix
- [ ] Agent improvement (planner, executor, memory)
- [ ] New or updated tool (`tools/`)
- [ ] Prompt update (`prompts/`)
- [ ] API change (`api/`)
- [ ] Configuration / settings
- [ ] Refactor / code quality
- [ ] Documentation
- [ ] CI/CD
- [ ] Other: <!-- describe -->

---

## Changes

<!-- Key files changed and what was done. -->

- `agent/` —
- `tools/` —
- `prompts/` —
- `api/` —
- `tests/` —
- `config/` —

---

## Testing

```bash
pytest tests/ -v
```

- [ ] All existing tests pass
- [ ] New tests added for new behaviour
- [ ] Linting passes: `ruff check . && black --check .`
- [ ] Type checks pass: `mypy .`

### For Agent / Planner Changes

- [ ] Tested with at least one real `POST /run` job end-to-end
- [ ] Plan output is sensible for the test instruction
- [ ] `MAX_PLAN_STEPS` limit is respected

### For Tool Changes

- [ ] `tests/test_tools.py` updated
- [ ] Tool tested against a real or mock GitHub repo (specify which)
- [ ] GitHub API calls are mocked in unit tests (no real commits in CI)

### For Prompt Changes

- [ ] Before/after prompt outputs documented below
- [ ] Tested against at least 2–3 representative instructions

<details>
<summary>Prompt output comparison (click to expand)</summary>

**Before:**
```
# paste old output
```

**After:**
```
# paste new output
```

</details>

### For API Changes

- [ ] `tests/test_api.py` updated
- [ ] Swagger docs (`/docs`) still render correctly
- [ ] Request/response schemas updated in `api/schemas.py`

---

## Security Checklist

- [ ] No API keys, tokens, or secrets introduced into tracked files
- [ ] `.env` values only reference variables defined in `config/.env.example`
- [ ] LLM-generated content is never passed to `eval()` or `exec()`
- [ ] New API endpoints require appropriate auth (or explicitly document why not)
- [ ] Docker image does not run as root (if `Dockerfile` modified)
- [ ] No new dependency added without a pinned version in `pyproject.toml`

---

## Breaking Changes

- [ ] This PR introduces breaking changes to the API or agent behaviour

If yes, describe what breaks and the migration path:

<!-- e.g. "`/run` response now returns `plan_steps` instead of `status`; clients must update their polling logic." -->

---

## Screenshots / Output (if applicable)

```
# Paste job output, diff summary, or PR URL from a test run
```

---

## Reviewer Notes

<!-- Anything specific you want the reviewer to focus on, or areas you're uncertain about. -->
