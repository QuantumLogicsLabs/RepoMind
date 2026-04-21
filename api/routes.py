from fastapi import APIRouter
from api.schemas import RunRequest, RunResponse, RefineRequest, RefineResponse, JobStatusResponse, JobStatus
from core.job_manager import job_manager
from core.exceptions import InvalidRepoURLError, InvalidInstructionError, JobAlreadyRunningError

router = APIRouter(tags=["Agent"])


@router.post("/run", response_model=RunResponse)
async def run(request: RunRequest):
    if not request.repo_url.startswith("https://github.com/"):
        raise InvalidRepoURLError(request.repo_url)
    if not request.instruction.strip():
        raise InvalidInstructionError(request.instruction)

    job_id = job_manager.create_job(
        repo_url=request.repo_url,
        instruction=request.instruction,
    )
    return RunResponse(job_id=job_id, status=JobStatus.queued)


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def status(job_id: str):
    record = job_manager.get(job_id)
    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        pr_url=record.pr_url,
        diff_summary=record.diff_summary,
        message=record.error_message,
    )


@router.post("/refine", response_model=RefineResponse)
async def refine(request: RefineRequest):
    record = job_manager.get(request.job_id)
    if record.status == JobStatus.running:
        raise JobAlreadyRunningError(request.job_id)
    return RefineResponse(
        job_id=request.job_id,
        status=record.status,
        message="Refine endpoint ready — agent wiring coming soon.",
    )
