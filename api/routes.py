"""
FastAPI Routes for RepoMind Agent System
"""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from urllib.parse import urlparse

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Header,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse

from api.errors import (
    InvalidInstructionError,
    InvalidRepoURLError,
    JobAlreadyRunningError,
    JobNotFoundError,
)
from api.schemas import (
    BatchRunRequest,
    BatchRunResponse,
    BatchStatusResponse,
    JobStatus,
    JobStatusResponse,
    RefineRequest,
    RefineResponse,
    RunRequest,
    RunResponse,
)

# ── Real agent runner (replaces the old stub test_executor) ───────────────────
from tools.agent_runner import run_agent, run_agent_batch
from utils.job_manager import job_manager
from utils.logging import get_logger
from utils.metrics import metrics_collector

logger = get_logger("api.routes")
router = APIRouter(tags=["Agent"])
# Simple in-memory mapping of batch_id -> list of job_ids belonging to it.
# Mirrors job_manager's in-memory-only design (see utils/job_manager.py).
_batch_registry: dict[str, list[str]] = {}


def process_job(job_id: str) -> None:
    """
    Background task: run the real AgentChain against the target repository,
    then update the job record with the result or error.
    """
    try:
        job = job_manager.get(job_id)
        job_manager.update(job_id, status=JobStatus.running)

        # Request-scoped credentials (if the caller supplied any) were stashed on the job record by run().
        result = run_agent(
            repo_url=job.repo_url,
            instruction=job.instruction,
            session_id=job_id,  # session_id == job_id → memory persists across /refine
            branch_name=getattr(job, "branch_name", "repomind/auto-fix"),
            pr_title_override=getattr(job, "pr_title", None),
            github_pat=getattr(job, "github_pat", None),
            llm_provider_override=getattr(job, "llm_provider", None),
            llm_api_key=getattr(job, "llm_api_key", None),
        )

        pr_url = result.get("pr_url")

        if pr_url:
            job_manager.update(
                job_id,
                status=JobStatus.completed,
                pr_url=pr_url,
                diff_summary=result.get("summary"),
                diff=result.get("diff"),
            )
        else:
            # Agent ran successfully but produced no changes.
            err_msg = result.get("summary") or "Agent completed but no file changes were made."
            logger.warning(
                "Job failed - no file changes generated",
                extra={
                    "event": "job_failed_no_changes",
                    "job_id": job_id,
                    "summary": result.get("summary"),
                },
            )
            metrics_collector.record_failure("JobNoChanges", err_msg)
            job_manager.update(
                job_id,
                status=JobStatus.failed,
                error_message=err_msg,
            )

    except Exception as e:

        logger.error(
            "Job execution failed with unhandled exception",
            exc_info=e,
            extra={
                "event": "job_execution_exception",
                "job_id": job_id,
                "exception_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        metrics_collector.record_failure(f"JobException:{type(e).__name__}", str(e))
        job_manager.update(job_id, status=JobStatus.failed, error_message=str(e))


def process_batch(batch_id: str, job_ids: list[str], repos: list[dict], base_branch: str) -> None:
    """
    Background task: run every repo in the batch concurrently via
    run_agent_batch(), then update each individual job record with its
    own outcome as results come in.
    """
    for job_id in job_ids:
        job_manager.update(job_id, status=JobStatus.running)

    try:
        batch_result = run_agent_batch(
            repos=repos,
            session_id_prefix=batch_id,
            base_branch=base_branch,
        )

        for job_id, repo_result in zip(job_ids, batch_result["results"], strict=True):
            if repo_result["status"] == "completed":
                job_manager.update(
                    job_id,
                    status=JobStatus.completed,
                    pr_url=repo_result["pr_url"],
                    diff_summary=repo_result["summary"],
                )
            else:
                job_manager.update(
                    job_id,
                    status=JobStatus.failed,
                    error_message=repo_result["error_message"] or "Batch item failed.",
                )

    except Exception as e:
        # A failure here means something broke the whole batch mechanism
        # itself (not an individual repo) — mark every job as failed.
        logger.error(
            "Batch execution failed with unhandled exception",
            exc_info=e,
            extra={"event": "batch_execution_exception", "batch_id": batch_id},
        )
        for job_id in job_ids:
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
    # Stash branch_name, pr_title, and any request-scoped credentials on the job record so process_job can read them.
    # Credentials are unwrapped from SecretStr to plain strings only here, right before being handed to the background task
    record = job_manager.get(job_id)
    record.branch_name = request.branch_name
    record.pr_title = request.pr_title
    record.github_pat = request.github_pat.get_secret_value() if request.github_pat else None
    record.llm_provider = request.llm_provider
    record.llm_api_key = request.llm_api_key.get_secret_value() if request.llm_api_key else None

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
        diff=job.diff,
        error_message=job.error_message,
    )


@router.get("/stream/{job_id}")
async def stream_job_progress(
    job_id: str,
    request: Request,
    last_event_id: int | None = Query(None),
    last_event_id_header: str | None = Header(None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """
    Stream live execution progress via Server-Sent Events (SSE).

    Supports client reconnects via Last-Event-ID header or query parameter.
    """
    try:
        job = job_manager.get(job_id)
    except Exception:
        raise JobNotFoundError(job_id) from None

    parsed_last_id: int | None = None
    if last_event_id is not None:
        parsed_last_id = last_event_id
    elif last_event_id_header:
        try:
            parsed_last_id = int(last_event_id_header)
        except ValueError:
            parsed_last_id = None

    queue, missed_events = job_manager.subscribe(job_id, last_event_id=parsed_last_id)

    async def sse_generator() -> AsyncGenerator[str, None]:
        try:
            # 1. Play back any missed historical events (reconnect catch-up)
            for event in missed_events:
                yield f"id: {event['id']}\nevent: progress\ndata: {json.dumps(event)}\n\n"

            # Check if job was already completed/failed before new events
            if job.status in ("completed", "failed") and queue.empty():
                yield f"event: close\ndata: {json.dumps({'job_id': job_id, 'status': job.status})}\n\n"
                return

            # 2. Stream new live events as they occur
            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"id: {event['id']}\nevent: progress\ndata: {json.dumps(event)}\n\n"

                    if event.get("stage") in ("completed", "failed"):
                        yield f"event: close\ndata: {json.dumps({'job_id': job_id, 'status': event['stage']})}\n\n"
                        break
                except TimeoutError:
                    # Keep-alive ping
                    yield ": keep-alive\n\n"
                    if job.status in ("completed", "failed") and queue.empty():
                        yield f"event: close\ndata: {json.dumps({'job_id': job_id, 'status': job.status})}\n\n"
                        break

        finally:
            job_manager.unsubscribe(job_id, queue)

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/ws/jobs/{job_id}")
async def websocket_job_progress(websocket: WebSocket, job_id: str):
    """
    Stream live execution progress via WebSockets.
    """
    try:
        job = job_manager.get(job_id)
    except Exception:
        await websocket.close(code=4004, reason="Job not found")
        return

    await websocket.accept()
    queue, missed_events = job_manager.subscribe(job_id, last_event_id=0)

    try:
        for event in missed_events:
            await websocket.send_json(event)

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                await websocket.send_json(event)

                if event.get("stage") in ("completed", "failed"):
                    break
            except TimeoutError:
                if job.status in ("completed", "failed") and queue.empty():
                    break
    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected from job {job_id}")
    finally:
        job_manager.unsubscribe(job_id, queue)


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

    # Append the refinement so the instruction history grows naturally.
    job.instruction += f"\nRefinement: {request.instruction}"
    job_manager.update(request.job_id, status=JobStatus.queued)
    background_tasks.add_task(process_job, request.job_id)

    return RefineResponse(
        job_id=request.job_id,
        status=JobStatus.queued,
        message="Refinement queued — agent will run with full prior context.",
    )


@router.post("/run-batch", response_model=BatchRunResponse)
async def run_batch(
    request: BatchRunRequest, background_tasks: BackgroundTasks
) -> BatchRunResponse:
    """Start a batch of agent jobs across multiple repositories, each running independently."""
    for repo_spec in request.repos:
        if urlparse(repo_spec.repo_url).netloc != "github.com":
            raise InvalidRepoURLError(repo_spec.repo_url)
        if not repo_spec.instruction.strip():
            raise InvalidInstructionError()

    batch_id = str(uuid.uuid4())
    job_ids: list[str] = []
    repos_for_runner: list[dict] = []

    for repo_spec in request.repos:
        job_id = job_manager.create_job(
            repo_url=repo_spec.repo_url,
            instruction=repo_spec.instruction,
        )
        record = job_manager.get(job_id)
        record.branch_name = repo_spec.branch_name
        record.pr_title = repo_spec.pr_title
        record.github_pat = (
            repo_spec.github_pat.get_secret_value() if repo_spec.github_pat else None
        )
        record.llm_provider = repo_spec.llm_provider
        record.llm_api_key = (
            repo_spec.llm_api_key.get_secret_value() if repo_spec.llm_api_key else None
        )

        job_ids.append(job_id)
        repos_for_runner.append(
            {
                "repo_url": repo_spec.repo_url,
                "instruction": repo_spec.instruction,
                "branch_name": repo_spec.branch_name,
                "pr_title_override": repo_spec.pr_title,
                "github_pat": record.github_pat,
                "llm_provider_override": record.llm_provider,
                "llm_api_key": record.llm_api_key,
            }
        )

    _batch_registry[batch_id] = job_ids
    background_tasks.add_task(
        process_batch, batch_id, job_ids, repos_for_runner, request.base_branch
    )

    return BatchRunResponse(batch_id=batch_id, job_ids=job_ids, status=JobStatus.queued)


@router.get("/batch-status/{batch_id}", response_model=BatchStatusResponse)
async def batch_status(batch_id: str) -> BatchStatusResponse:
    """Poll the aggregated status of every job in a batch."""
    job_ids = _batch_registry.get(batch_id)
    if job_ids is None:
        raise JobNotFoundError(batch_id)

    job_responses: list[JobStatusResponse] = []
    succeeded = 0
    failed = 0
    pending = 0

    for job_id in job_ids:
        job = job_manager.get(job_id)
        job_responses.append(
            JobStatusResponse(
                job_id=job.job_id,
                status=JobStatus(job.status),
                pr_url=job.pr_url,
                diff_summary=job.diff_summary,
                diff=job.diff,
                error_message=job.error_message,
            )
        )
        if job.status == JobStatus.completed:
            succeeded += 1
        elif job.status == JobStatus.failed:
            failed += 1
        else:
            pending += 1

    return BatchStatusResponse(
        batch_id=batch_id,
        total=len(job_ids),
        succeeded=succeeded,
        failed=failed,
        pending=pending,
        jobs=job_responses,
    )


@router.get("/metrics", tags=["Monitoring"])
async def metrics() -> dict:
    """Return system execution metrics snapshot."""
    from utils.metrics import metrics_collector

    return metrics_collector.get_metrics_summary()
