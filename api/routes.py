from fastapi import APIRouter
from api.schemas import RunRequest, RunResponse, RefineRequest, RefineResponse, JobStatusResponse, JobStatus

# ── Router ────────────────────────────────────────────────────────────────────
# Implementation: Anam Daud
# This file is scaffolded by Ali. Anam will wire in the agent + GitHub logic.

router = APIRouter(tags=["Agent"])


@router.post("/run", response_model=RunResponse)
async def run(request: RunRequest):
    """
    Kick off a new agent job.
    - Accepts a repo URL and a plain-English instruction
    - Returns a job_id immediately so the client can start polling /status
    """
    # TODO (Anam): create job via JobManager, kick off background task
    return RunResponse(job_id="placeholder", status=JobStatus.queued)


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def status(job_id: str):
    """
    Poll the status of a running job.
    - Returns current status, PR URL once done, or error message if failed
    """
    # TODO (Anam): fetch real status from JobManager
    return JobStatusResponse(job_id=job_id, status=JobStatus.queued)


@router.post("/refine", response_model=RefineResponse)
async def refine(request: RefineRequest):
    """
    Send a follow-up instruction on an existing job.
    - Lets the user iterate on the same PR without losing session memory
    """
    # TODO (Anam): pass follow-up instruction back into the agent with memory context
    return RefineResponse(job_id=request.job_id, status=JobStatus.queued, message="Not implemented yet")
