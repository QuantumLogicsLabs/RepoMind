import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from utils.logging import get_logger
from utils.metrics import metrics_collector

logger = get_logger("utils.job_manager")


@dataclass
class JobRecord:
    job_id: str
    repo_url: str
    instruction: str
    status: str = "queued"
    current_stage: str = "queued"
    progress: float = 0.0
    pr_url: str | None = None
    diff_summary: str | None = None
    diff: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    events: list[dict] = field(default_factory=list)
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    branch_name: str = "repomind/auto-fix"
    pr_title: str | None = None
    # Request-scoped credentials — held only in memory for this job's
    # lifetime, never written to disk, and deliberately excluded from
    # to_dict() so they can never leak via all_jobs()/status endpoints.
    github_pat: str | None = None
    llm_provider: str | None = None
    llm_api_key: str | None = None

    def elapsed_time(self) -> float | None:
        if self.started_at is None:
            return None

        end = self.finished_at if self.finished_at is not None else datetime.now(UTC)
        return (end - self.started_at).total_seconds()

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "repo_url": self.repo_url,
            "instruction": self.instruction,
            "status": self.status,
            "current_stage": self.current_stage,
            "progress": self.progress,
            "pr_url": self.pr_url,
            "diff_summary": self.diff_summary,
            "diff": self.diff,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "elapsed_time": self.elapsed_time(),
            "events_count": len(self.events),
        }


class JobManager:
    def __init__(self):
        self._store: dict[str, JobRecord] = {}

    def create_job(self, repo_url: str, instruction: str) -> str:
        job_id = str(uuid.uuid4())
        record = JobRecord(
            job_id=job_id,
            repo_url=repo_url,
            instruction=instruction,
        )
        self._store[job_id] = record
        metrics_collector.record_job_created()
        logger.info(
            "Job created",
            extra={
                "event": "job_created",
                "job_id": job_id,
                "repo_url": repo_url,
                "instruction": instruction,
            },
        )
        # Emit initial queued event
        self.add_event(
            job_id=job_id,
            stage="queued",
            message="Job queued and waiting for worker.",
            progress=0.0,
        )
        return job_id

    def get(self, job_id: str) -> JobRecord:
        from api.errors import JobNotFoundError

        record = self._store.get(job_id)
        if record is None:
            logger.warning(
                "Job lookup failed - not found",
                extra={"event": "job_not_found", "job_id": job_id},
            )
            raise JobNotFoundError(job_id)
        return record

    def add_event(
        self,
        job_id: str | None = None,
        stage: str = "running",
        message: str = "",
        progress: float = 0.0,
        data: dict | None = None,
        session_id: str | None = None,
    ) -> dict:
        """Add an execution progress event to a job and notify active streaming subscribers."""
        target_id = job_id or session_id
        if target_id is None:
            raise ValueError("Either job_id or session_id must be provided")
        record = self.get(target_id)
        event_id = len(record.events) + 1
        event_payload = {
            "id": event_id,
            "job_id": target_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "stage": stage,
            "message": message,
            "progress": round(progress, 2),
            "data": data or {},
        }
        record.events.append(event_payload)
        record.current_stage = stage
        record.progress = round(progress, 2)

        # Notify all active queue subscribers safely
        dead_subscribers = []
        for queue in list(record.subscribers):
            try:
                queue.put_nowait(event_payload)
            except Exception:
                dead_subscribers.append(queue)

        for dead in dead_subscribers:
            if dead in record.subscribers:
                record.subscribers.remove(dead)

        logger.debug(
            "Progress event emitted",
            extra={
                "event": "progress_event",
                "job_id": job_id,
                "stage": stage,
                "progress": progress,
            },
        )
        return event_payload

    def update(
        self,
        job_id: str,
        status: str | None = None,
        pr_url: str | None = None,
        diff_summary: str | None = None,
        diff: str | None = None,
        error_message: str | None = None,
    ) -> None:
        record = self.get(job_id)
        old_status = record.status

        if status is not None:
            record.status = status

        if pr_url is not None:
            record.pr_url = pr_url

        if diff_summary is not None:
            record.diff_summary = diff_summary

        if error_message is not None:
            record.error_message = error_message

        if status == "running" and record.started_at is None:
            record.started_at = datetime.now(UTC)

        if status in ("completed", "failed"):
            record.finished_at = datetime.now(UTC)

        metrics_collector.record_job_status_change(old_status, record.status)
        logger.info(
            f"Job updated: {old_status} -> {record.status}",
            extra={
                "event": "job_status_change",
                "job_id": job_id,
                "old_status": old_status,
                "new_status": record.status,
                "pr_url": record.pr_url,
                "elapsed_time": record.elapsed_time(),
                "error_message": record.error_message,
            },
        )

    def subscribe(
        self, job_id: str, last_event_id: int | None = None
    ) -> tuple[asyncio.Queue, list[dict]]:
        """
        Subscribe to live job progress events.

        Returns:
            (queue, missed_events): queue to listen for new events, and
            missed_events list for reconnected clients (where event['id'] > last_event_id).
        """
        record = self.get(job_id)
        queue: asyncio.Queue = asyncio.Queue()
        record.subscribers.append(queue)

        missed_events = []
        if last_event_id is not None:
            missed_events = [e for e in record.events if e["id"] > last_event_id]
        else:
            missed_events = list(record.events)

        return queue, missed_events

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        try:
            record = self.get(job_id)
            if queue in record.subscribers:
                record.subscribers.remove(queue)
        except Exception:
            pass

    def all_jobs(self) -> dict:
        return {job_id: record.to_dict() for job_id, record in self._store.items()}

    def stats(self) -> dict:
        all_records = list(self._store.values())

        return {
            "total": len(all_records),
            "queued": sum(1 for r in all_records if r.status == "queued"),
            "running": sum(1 for r in all_records if r.status == "running"),
            "completed": sum(1 for r in all_records if r.status == "completed"),
            "failed": sum(1 for r in all_records if r.status == "failed"),
        }


job_manager = JobManager()
