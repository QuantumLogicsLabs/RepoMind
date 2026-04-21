import uuid
import logging
from datetime import datetime, timezone
from threading import Lock
from dataclasses import dataclass, field
from typing import Optional

from api.schemas import JobStatus
from core.exceptions import JobNotFoundError, JobAlreadyRunningError

logger = logging.getLogger(__name__)


@dataclass
class JobRecord:
    job_id:        str
    repo_url:      str
    instruction:   str
    status:        JobStatus = JobStatus.queued
    created_at:    datetime  = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at:    Optional[datetime] = None
    finished_at:   Optional[datetime] = None
    pr_url:        Optional[str] = None
    diff_summary:  Optional[str] = None
    error_message: Optional[str] = None

    def elapsed_seconds(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.finished_at or datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()

    def to_dict(self) -> dict:
        return {
            "job_id":          self.job_id,
            "status":          self.status.value,
            "repo_url":        self.repo_url,
            "instruction":     self.instruction,
            "created_at":      self.created_at.isoformat(),
            "started_at":      self.started_at.isoformat()  if self.started_at  else None,
            "finished_at":     self.finished_at.isoformat() if self.finished_at else None,
            "elapsed_seconds": self.elapsed_seconds(),
            "pr_url":          self.pr_url,
            "diff_summary":    self.diff_summary,
            "error_message":   self.error_message,
        }


class JobManager:

    def __init__(self):
        self._store: dict[str, JobRecord] = {}
        self._lock  = Lock()

    def create_job(self, repo_url: str, instruction: str) -> str:
        job_id = str(uuid.uuid4())
        record = JobRecord(job_id=job_id, repo_url=repo_url, instruction=instruction)
        with self._lock:
            self._store[job_id] = record
        logger.info(f"[JobManager] Created job={job_id}")
        return job_id

    def set_running(self, job_id: str) -> None:
        with self._lock:
            record = self._require(job_id)
            if record.status == JobStatus.running:
                raise JobAlreadyRunningError(job_id)
            record.status     = JobStatus.running
            record.started_at = datetime.now(timezone.utc)
        logger.info(f"[JobManager] Running job={job_id}")

    def complete(self, job_id: str, pr_url: str, diff_summary: str) -> None:
        with self._lock:
            record = self._require(job_id)
            record.status       = JobStatus.completed
            record.finished_at  = datetime.now(timezone.utc)
            record.pr_url       = pr_url
            record.diff_summary = diff_summary
        logger.info(f"[JobManager] Completed job={job_id}")

    def fail(self, job_id: str, reason: str) -> None:
        with self._lock:
            record = self._require(job_id)
            record.status        = JobStatus.failed
            record.finished_at   = datetime.now(timezone.utc)
            record.error_message = reason
        logger.error(f"[JobManager] Failed job={job_id}")

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            return self._require(job_id)

    def list_all(self) -> list[dict]:
        with self._lock:
            return [r.to_dict() for r in self._store.values()]

    def stats(self) -> dict:
        with self._lock:
            records = list(self._store.values())
        return {
            "total":     len(records),
            "queued":    sum(1 for r in records if r.status == JobStatus.queued),
            "running":   sum(1 for r in records if r.status == JobStatus.running),
            "completed": sum(1 for r in records if r.status == JobStatus.completed),
            "failed":    sum(1 for r in records if r.status == JobStatus.failed),
        }

    def _require(self, job_id: str) -> JobRecord:
        record = self._store.get(job_id)
        if record is None:
            raise JobNotFoundError(job_id)
        return record


job_manager = JobManager()
