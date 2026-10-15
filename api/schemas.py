from enum import StrEnum

from pydantic import BaseModel, SecretStr

# ── Enums ────────────────────────────────────────────────────────────────────


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


# ── Request Models ────────────────────────────────────────────────────────────


class RunRequest(BaseModel):
    """
    POST /run
    Sent by the HackingTheRepo platform to kick off a new agent job.
    """

    repo_url: str  # GitHub repo URL to clone and modify
    instruction: str  # Plain-English change description
    branch_name: str = "repomind/auto-fix"  # Branch that will be created for the PR
    pr_title: str = "refactor: RepoMind automated change"  # Title of the Pull Request

    # ── Request-scoped credentials (optional) ────────────────────────────────
    # If not supplied, the server falls back to its own configured defaults
    # (config.settings.get_settings()). SecretStr prevents these values from
    # appearing in OpenAPI docs, logs, or accidental repr()/print() calls.
    github_pat: SecretStr | None = None  # Per-request GitHub PAT, overrides server default
    llm_provider: str | None = None  # e.g. "groq", "openai", "gemini" — overrides server default
    llm_api_key: SecretStr | None = None  # Per-request LLM key, overrides server default


class RepoJobSpec(BaseModel):
    """One repository's job spec within a batch request."""

    repo_url: str
    instruction: str
    branch_name: str = "repomind/auto-fix"
    pr_title: str = "refactor: RepoMind automated change"
    github_pat: SecretStr | None = None
    llm_provider: str | None = None
    llm_api_key: SecretStr | None = None


class BatchRunRequest(BaseModel):
    """
    POST /run-batch
    Run the agent across multiple repositories concurrently, each with its
    own instruction.
    """

    repos: list[RepoJobSpec]
    base_branch: str = "main"


class BatchRunResponse(BaseModel):
    """Returned immediately from POST /run-batch so the platform can start polling."""

    batch_id: str
    job_ids: list[str]
    status: JobStatus  # Always "queued" on first response


class RefineRequest(BaseModel):
    """
    POST /refine
    Sent to iterate on an already-running or completed job without losing context.
    """

    job_id: str  # The job to refine
    instruction: str  # Follow-up instruction e.g. "also add type hints"


# ── Response Models ───────────────────────────────────────────────────────────


class JobStatusResponse(BaseModel):
    """
    GET /status/{job_id}
    Full status snapshot of a job — polled by the platform until status = completed | failed.
    """

    job_id: str
    status: JobStatus
    pr_url: str | None = (
        None  # GitHub PR URL — only set when status = completed AND a real PR was created
    )
    diff_summary: str | None = None  # e.g. "Modified 3 files"
    diff: str | None = None  # Raw unified diff (git diff format), when available
    error_message: str | None = None  # Set when status = failed
    # Keep 'message' as an alias so existing callers don't break
    message: str | None = None


class BatchStatusResponse(BaseModel):
    """
    GET /batch-status/{batch_id}
    Aggregated status snapshot across every job in the batch.
    """

    batch_id: str
    total: int
    succeeded: int
    failed: int
    pending: int
    jobs: list[JobStatusResponse]


class RunResponse(BaseModel):
    """
    Returned immediately from POST /run so the platform can start polling.
    """

    job_id: str
    status: JobStatus  # Always "queued" on first response


class RefineResponse(BaseModel):
    """
    Returned from POST /refine confirming the follow-up instruction was accepted.
    """

    job_id: str
    status: JobStatus
    message: str | None = None


# ── Internal Models ───────────────────────────────────────────────────────────
# Used between modules — not exposed directly in API responses


class FileChange(BaseModel):
    """
    A single file edit produced by the agent executor.
    Passed from agent/executor.py -> tools/github_tool.py
    """

    file_path: str  # Relative path inside the repo e.g. "src/db/queries.py"
    new_content: str  # Full updated file content


class AgentOutput(BaseModel):
    """
    Complete output from the agent after finishing all planned steps.
    Passed from agent/executor.py -> tools/pr_tool.py
    """

    changes: list[FileChange]
    diff_summary: str  # Human-readable summary of all changes made
