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
from tools.test_executor import run_test_executor

router = APIRouter(tags=["Agent"])


def process_job(job_id: str):
    try:
        job = job_manager.get(job_id)
        job_manager.update(job_id, status=JobStatus.running)
        result = run_test_executor(repo_url=job.repo_url, instruction=job.instruction)

        pr_url = result.get("pr_url")  # may be None if no changes were made

        if pr_url:
            job_manager.update(
                job_id,
                status=JobStatus.completed,
                pr_url=pr_url,
                diff_summary=result.get("summary"),
            )
        else:
            # Agent ran successfully but made no changes → mark failed with a clear message
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
async def run(request: RunRequest, background_tasks: BackgroundTasks):
    if urlparse(request.repo_url).netloc != "github.com":
        raise InvalidRepoURLError(request.repo_url)  # fix: pass the actual URL not a string literal
    if not request.instruction.strip():
        raise InvalidInstructionError()
    job_id = job_manager.create_job(repo_url=request.repo_url, instruction=request.instruction)
    background_tasks.add_task(process_job, job_id)
    return RunResponse(job_id=job_id, status=JobStatus.queued)


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def status(job_id: str):
    try:
        job = job_manager.get(job_id)
    except Exception:
        raise JobNotFoundError("Job not found")
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        pr_url=job.pr_url,
        diff_summary=job.diff_summary,
        error_message=job.error_message,
    )


@router.post("/refine", response_model=RefineResponse)
async def refine(request: RefineRequest, background_tasks: BackgroundTasks):
    try:
        job = job_manager.get(request.job_id)
    except Exception:
        raise JobNotFoundError("Job not found")
    if job.status == JobStatus.running:
        raise JobAlreadyRunningError("Job still running")
    if not request.instruction.strip():
        raise InvalidInstructionError()
    job.instruction += f"\nRefinement: {request.instruction}"
    job_manager.update(request.job_id, status=JobStatus.queued)
    background_tasks.add_task(process_job, request.job_id)
    return RefineResponse(
        job_id=request.job_id, status=JobStatus.queued, message="Refinement started"
    )
