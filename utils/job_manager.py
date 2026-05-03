import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JobRecord:
    job_id:        str
    repo_url:      str
    instruction:   str
    status:        str = "queued"
    pr_url:        Optional[str] = None
    diff_summary:  Optional[str] = None
    error_message: Optional[str] = None
    created_at:    datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at:    Optional[datetime] = None
    finished_at:   Optional[datetime] = None

    def elapsed_time(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.finished_at if self.finished_at is not None else datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()

    def to_dict(self) -> dict:
        return {
            "job_id":        self.job_id,
            "repo_url":      self.repo_url,
            "instruction":   self.instruction,
            "status":        self.status,
            "pr_url":        self.pr_url,
            "diff_summary":  self.diff_summary,
            "error_message": self.error_message,
            "created_at":    self.created_at.isoformat(),
            "started_at":    self.started_at.isoformat() if self.started_at else None,
            "finished_at":   self.finished_at.isoformat() if self.finished_at else None,
            "elapsed_time":  self.elapsed_time(),
        }


class JobManager:
    def __init__(self):
        self._store: dict[str, JobRecord] = {}

    def create_job(self, repo_url: str, instruction: str) -> str:
        job_id = str(uuid.uuid4())
        record = JobRecord(job_id=job_id, repo_url=repo_url, instruction=instruction)
        self._store[job_id] = record
        return job_id

    def get(self, job_id: str) -> JobRecord:
        from api.errors import JobNotFoundError
        record = self._store.get(job_id)
        if record is None:
            raise JobNotFoundError(job_id)
        return record

    def update(self, job_id: str, status: Optional[str] = None,
               pr_url: Optional[str] = None, diff_summary: Optional[str] = None,
               error_message: Optional[str] = None) -> None:
        record = self.get(job_id)
        if status is not None:
            record.status = status
        if pr_url is not None:
            record.pr_url = pr_url
        if diff_summary is not None:
            record.diff_summary = diff_summary
        if error_message is not None:
            record.error_message = error_message
        if status == "running" and record.started_at is None:
            record.started_at = datetime.now(timezone.utc)
        if status in ("completed", "failed"):
            record.finished_at = datetime.now(timezone.utc)

    def all_jobs(self) -> dict:
        return {job_id: record.to_dict() for job_id, record in self._store.items()}

    def stats(self) -> dict:
        all_records = list(self._store.values())
        return {
            "total":     len(all_records),
            "queued":    sum(1 for r in all_records if r.status == "queued"),
            "running":   sum(1 for r in all_records if r.status == "running"),
            "completed": sum(1 for r in all_records if r.status == "completed"),
            "failed":    sum(1 for r in all_records if r.status == "failed"),
        }


job_manager = JobManager()
