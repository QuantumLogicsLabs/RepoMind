"""
FastAPI Routes for RepoMind Agent System
"""

import traceback
from urllib.parse import urlparse
from fastapi import APIRouter, BackgroundTasks
from api.schemas import (
    RunRequest,
    RunResponse,
    JobStatusResponse,
    RefineRequest,
    RefineResponse,
    JobStatus,
)
from utils.job_manager import job_manager
from api.errors import (
    InvalidRepoURLError,
    InvalidInstructionError,
    JobAlreadyRunningError,
    JobNotFoundError,
)

# ── Real agent runner (replaces the old stub test_executor) ───────────────────
from tools.agent_runner import run_agent

router = APIRouter(tags=["Agent"])


def process_job(job_id: str) -> None:
    """
    Background task: run the real AgentChain against the target repository,
    then update the job record with the result or error.
    """
    try:
        job = job_manager.get(job_id)
        job_manager.update(job_id, status=JobStatus.running)

        result = run_agent(
            repo_url=job.repo_url,
            instruction=job.instruction,
            session_id=job_id,  # session_id == job_id → memory persists across /refine
            branch_name=getattr(job, "branch_name", "repomind/auto-fix"),
            pr_title_override=getattr(job, "pr_title", None),
        )

        pr_url = result.get("pr_url")

        if pr_url:
            job_manager.update(
                job_id,
                status=JobStatus.completed,
                pr_url=pr_url,
                diff_summary=result.get("summary"),
            )
        else:
            # Agent ran successfully but produced no changes.
            job_manager.update(
                job_id,
                status=JobStatus.failed,
                error_message=result.get("summary")
                or "Agent completed but no file changes were made.",
            )

    except Exception as e:
        traceback.print_exc()
        job_manager.update(job_id, status=JobStatus.failed, error_message=str(e))


@router.post("/run", response_model=RunResponse)
async def run(request: RunRequest, background_tasks: BackgroundTasks) -> RunResponse:
    """Start a new agent job against the given repository."""
    if urlparse(request.repo_url).netloc != "github.com":
        raise InvalidRepoURLError(request.repo_url)
    if not request.instruction.strip():
        raise InvalidInstructionError()

    job_id = job_manager.create_job(
        repo_url=request.repo_url,
        instruction=request.instruction,
    )
    # Stash branch_name and pr_title on the job record so process_job can read them.
    record = job_manager.get(job_id)
    record.branch_name = request.branch_name  # type: ignore[attr-defined]
    record.pr_title = request.pr_title  # type: ignore[attr-defined]

    background_tasks.add_task(process_job, job_id)
    return RunResponse(job_id=job_id, status=JobStatus.queued)


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def status(job_id: str) -> JobStatusResponse:
    """Poll the status of a running or completed job."""
    try:
        job = job_manager.get(job_id)
    except Exception:
        raise JobNotFoundError(job_id)
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        pr_url=job.pr_url,
        diff_summary=job.diff_summary,
        error_message=job.error_message,
    )


@router.post("/refine", response_model=RefineResponse)
async def refine(request: RefineRequest, background_tasks: BackgroundTasks) -> RefineResponse:
    """
    Send a follow-up instruction on an existing job.

    The same session_id (= job_id) is reused, so the agent's MemoryManager
    has full context of what was already done in the original run.
    """
    try:
        job = job_manager.get(request.job_id)
    except Exception:
        raise JobNotFoundError(request.job_id)
    if job.status == JobStatus.running:
        raise JobAlreadyRunningError(request.job_id)
    if not request.instruction.strip():
        raise InvalidInstructionError()

    # Append the refinement so the instruction history grows naturally.
    job.instruction += f"\nRefinement: {request.instruction}"
    job_manager.update(request.job_id, status=JobStatus.queued)
    background_tasks.add_task(process_job, request.job_id)

    return RefineResponse(
        job_id=request.job_id,
        status=JobStatus.queued,
        message="Refinement queued — agent will run with full prior context.",
    )
