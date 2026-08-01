from enum import StrEnum

from pydantic import BaseModel

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
    create_pr: bool = True  # When False, push branch + return diff without opening a PR
    github_token: str | None = None  # Optional per-user override; falls back to server env
    openai_api_key: str | None = None  # Optional per-user override; falls back to server env


class OpenPrRequest(BaseModel):
    """
    POST /open-pr
    Open a pull request for a completed preview-only job.
    """

    job_id: str
    github_token: str | None = None


class RefineRequest(BaseModel):
    """
    POST /refine
    Sent to iterate on an already-running or completed job without losing context.
    """

    job_id: str  # The job to refine
    instruction: str  # Follow-up instruction e.g. "also add type hints"
    github_token: str | None = None
    openai_api_key: str | None = None


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
    error_message: str | None = None  # Set when status = failed
    # Keep 'message' as an alias so existing callers don't break
    message: str | None = None


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


class OpenPrResponse(BaseModel):
    """Returned from POST /open-pr after creating the pull request."""

    job_id: str
    pr_url: str
    status: JobStatus


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
