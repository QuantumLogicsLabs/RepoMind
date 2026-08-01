"""
FastAPI Routes for RepoMind Agent System
"""

import traceback
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.errors import (
    InvalidInstructionError,
    InvalidRepoURLError,
    JobAlreadyRunningError,
    JobNotFoundError,
)
from api.schemas import (
    JobStatus,
    JobStatusResponse,
    OpenPrRequest,
    OpenPrResponse,
    RefineRequest,
    RefineResponse,
    RunRequest,
    RunResponse,
)

# ── Real agent runner (replaces the old stub test_executor) ───────────────────
from tools.agent_runner import open_pull_request_for_job, run_agent
from utils.job_manager import job_manager

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
            create_pr=getattr(job, "create_pr", True),
            github_token=getattr(job, "github_token", None),
            openai_api_key=getattr(job, "openai_api_key", None),
            base_branch=getattr(job, "base_branch", "main"),
        )

        pr_url = result.get("pr_url")
        summary = result.get("summary") or result.get("diff_summary")

        if pr_url:
            job_manager.update(
                job_id,
                status=JobStatus.completed,
                pr_url=pr_url,
                diff_summary=summary,
            )
        elif summary and "no file changes" not in summary.lower() and "no disk changes" not in summary.lower():
            # Preview-only success (or completed without PR)
            job_manager.update(
                job_id,
                status=JobStatus.completed,
                pr_url=None,
                diff_summary=summary,
            )
        else:
            job_manager.update(
                job_id,
                status=JobStatus.failed,
                error_message=summary
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
    record = job_manager.get(job_id)
    record.branch_name = request.branch_name
    record.pr_title = request.pr_title
    record.create_pr = request.create_pr
    record.github_token = request.github_token
    record.openai_api_key = request.openai_api_key

    background_tasks.add_task(process_job, job_id)
    return RunResponse(job_id=job_id, status=JobStatus.queued)


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def status(job_id: str) -> JobStatusResponse:
    """Poll the status of a running or completed job."""
    try:
        job = job_manager.get(job_id)
    except Exception:
        raise JobNotFoundError(job_id) from None
    return JobStatusResponse(
        job_id=job.job_id,
        status=JobStatus(job.status),
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
        raise JobNotFoundError(request.job_id) from None
    if job.status == JobStatus.running:
        raise JobAlreadyRunningError(request.job_id)
    if not request.instruction.strip():
        raise InvalidInstructionError()

    job.instruction += f"\nRefinement: {request.instruction}"
    if request.github_token:
        job.github_token = request.github_token
    if request.openai_api_key:
        job.openai_api_key = request.openai_api_key
    job.create_pr = True
    job_manager.update(request.job_id, status=JobStatus.queued)
    background_tasks.add_task(process_job, request.job_id)

    return RefineResponse(
        job_id=request.job_id,
        status=JobStatus.queued,
        message="Refinement queued — agent will run with full prior context.",
    )


@router.post("/open-pr", response_model=OpenPrResponse)
async def open_pr(request: OpenPrRequest) -> OpenPrResponse:
    """Open a pull request for a completed preview-only job."""
    try:
        job = job_manager.get(request.job_id)
    except Exception:
        raise JobNotFoundError(request.job_id) from None

    if job.pr_url:
        return OpenPrResponse(
            job_id=job.job_id,
            pr_url=job.pr_url,
            status=JobStatus(job.status),
        )

    if job.status != JobStatus.completed:
        raise HTTPException(
            status_code=400,
            detail="Job must be completed before opening a pull request",
        )

    token = request.github_token or job.github_token
    pr_url = open_pull_request_for_job(
        repo_url=job.repo_url,
        instruction=job.instruction,
        branch_name=job.branch_name,
        pr_title=job.pr_title,
        base_branch=job.base_branch,
        github_token=token,
        diff_summary=job.diff_summary,
    )
    job_manager.update(job.job_id, status=JobStatus.completed, pr_url=pr_url)
    return OpenPrResponse(job_id=job.job_id, pr_url=pr_url, status=JobStatus.completed)
