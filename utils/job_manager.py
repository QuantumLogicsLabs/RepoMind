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
        return job_id

    def get(self, job_id: str) -> JobRecord:
        from api.errors import JobNotFoundError
        record = self._store.get(job_id)
        if record is None:
            raise JobNotFoundError(job_id)
        return record

    def update(
        self,
        job_id:        str,
        status:        Optional[str] = None,
        pr_url:        Optional[str] = None,
        diff_summary:  Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        record = self.get(job_id)
        if status        is not None: record.status        = status
        if pr_url        is not None: record.pr_url        = pr_url
        if diff_summary  is not None: record.diff_summary  = diff_summary
        if error_message is not None: record.error_message = error_message

    def all_jobs(self) -> dict:
        return {job_id: record.to_dict() for job_id, record in self._store.items()}


job_manager = JobManager()
