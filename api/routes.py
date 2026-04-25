"""
FastAPI Routes for RepoMind Agent System
Handles job creation, status tracking, and refinement requests.
"""

# -----------------------
# Standard library imports
# -----------------------
import traceback
from urllib.parse import urlparse

# -----------------------
# Third-party imports
# -----------------------
from fastapi import APIRouter, BackgroundTasks

# -----------------------
# Local application imports
# -----------------------
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

# ✅ Temporary executor (DO NOT use agent/ folder)
from tools.test_executor import run_test_executor


router = APIRouter(tags=["Agent"])


# =========================================================
# Background Worker
# =========================================================
def process_job(job_id: str):
    """
    Background worker that executes jobs using temporary executor.
    This avoids using agent/ folder as per instructor instructions.
    """
    try:
        print(f"\n🚀 JOB STARTED: {job_id}")

        job = job_manager.get(job_id)
        job_manager.update(job_id, status=JobStatus.running)

        print("📦 Job marked as running")

        # -------------------------------------------------
        # Execute using temporary executor
        # -------------------------------------------------
        result = run_test_executor(
            repo_url=job.repo_url,
            instruction=job.instruction,
        )

        summary = result.get("summary", "No summary generated")
        pr_url = result.get("pr_url", None)

        # -------------------------------------------------
        # Update job as completed
        # -------------------------------------------------
        job_manager.update(
            job_id,
            status=JobStatus.completed,
            pr_url=pr_url,
            diff_summary=summary,
        )

        print("🎉 JOB COMPLETED")

    except Exception as e:
        print("\n❌ ERROR IN JOB:")
        traceback.print_exc()

        try:
            job_manager.update(
                job_id,
                status=JobStatus.failed,
                error_message=str(e),
            )
        except Exception as inner_error:
            print("🔥 Failed to update job status:", inner_error)


# =========================================================
# POST /run
# =========================================================
@router.post("/run", response_model=RunResponse)
async def run(request: RunRequest, background_tasks: BackgroundTasks):
    """Create and start a new job."""

    parsed = urlparse(request.repo_url)
    if parsed.netloc != "github.com":
        raise InvalidRepoURLError("Invalid GitHub URL")

    if not request.instruction.strip():
        raise InvalidInstructionError("Instruction cannot be empty")

    job_id = job_manager.create_job(
        repo_url=request.repo_url,
        instruction=request.instruction,
    )

    background_tasks.add_task(process_job, job_id)

    return RunResponse(
        job_id=job_id,
        status=JobStatus.queued,
    )


# =========================================================
# GET /status/{job_id}
# =========================================================
@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def status(job_id: str):
    """Get job status."""

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


# =========================================================
# POST /refine
# =========================================================
@router.post("/refine", response_model=RefineResponse)
async def refine(request: RefineRequest, background_tasks: BackgroundTasks):
    """Refine an existing job."""

    try:
        job = job_manager.get(request.job_id)
    except Exception:
        raise JobNotFoundError("Job not found")

    if job.status == JobStatus.running:
        raise JobAlreadyRunningError("Job still running")

    if not request.instruction.strip():
        raise InvalidInstructionError("Instruction cannot be empty")

    job.instruction += f"\nRefinement: {request.instruction}"

    job_manager.update(request.job_id, status=JobStatus.queued)

    background_tasks.add_task(process_job, request.job_id)

    return RefineResponse(
        job_id=request.job_id,
        status=JobStatus.queued,
        message="Refinement started",
    )
 
