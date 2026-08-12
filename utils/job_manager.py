from importlib import reload
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
 task-10-persistent-jobs

from pytest import warns

from utils.job_db import get_connection, init_db

main

from utils.logging import get_logger
from utils.metrics import metrics_collector

logger = get_logger("utils.job_manager")


@dataclass
class JobRecord:
    job_id: str
    repo_url: str
    instruction: str
    status: str = "queued"
    pr_url: str | None = None
    diff_summary: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
 task-10-persistent-jobs

    branch_name: str = "repomind/auto-fix"
    pr_title: str | None = None
    # Request-scoped credentials — held only in memory for this job's
    # lifetime, never written to disk, and deliberately excluded from
    # to_dict() so they can never leak via all_jobs()/status endpoints.
    github_pat: str | None = None
    llm_provider: str | None = None
    llm_api_key: str | None = None
 main

    def elapsed_time(self) -> float | None:
        if self.started_at is None:
            return None
 task-10-persistent-jobs


 main
        end = self.finished_at if self.finished_at is not None else datetime.now(UTC)
        return (end - self.started_at).total_seconds()

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "repo_url": self.repo_url,
            "instruction": self.instruction,
            "status": self.status,
            "pr_url": self.pr_url,
            "diff_summary": self.diff_summary,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "elapsed_time": self.elapsed_time(),
        }


class JobManager:
    def __init__(self):
        init_db()

    def create_job(self, repo_url: str, instruction: str) -> str:
        job_id = str(uuid.uuid4())
 task-10-persistent-jobs


 main
        record = JobRecord(
            job_id=job_id,
            repo_url=repo_url,
            instruction=instruction,
        )
 task-10-persistent-jobs

        conn = get_connection()
        conn.execute(
            """
            INSERT INTO jobs (
                job_id,
                repo_url,
                instruction,
                status,
                pr_url,
                diff_summary,
                error_message,
                created_at,
                started_at,
                finished_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.job_id,
                record.repo_url,
                record.instruction,
                record.status,
                record.pr_url,
                record.diff_summary,
                record.error_message,
                record.created_at.isoformat(),
                None,
                None,
            ),
        )
        conn.commit()
        conn.close()


        self._store[job_id] = record
 task-10-persistent-jobs
main

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
 main
        return job_id

    def get(self, job_id: str) -> JobRecord:
        from api.errors import JobNotFoundError

 task-10-persistent-jobs
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        conn.close()

        if row is None:
            raise JobNotFoundError(job_id)

        return JobRecord(
            job_id=row["job_id"],
            repo_url=row["repo_url"],
            instruction=row["instruction"],
            status=row["status"],
            pr_url=row["pr_url"],
            diff_summary=row["diff_summary"],
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        )

    def update(
        self,
        record: JobRecord | str,
        **kwargs,
    ) -> None:
        """
        Update a job.

        Supports both:
            update(job_record)
        and
            update(job_id, status="running", pr_url="...")
        """

        if isinstance(record, str):
            record = self.get(record)

        for key, value in kwargs.items():
            setattr(record, key, value)

        conn = get_connection()

        conn.execute(
            """
            UPDATE jobs
            SET
                status=?,
                pr_url=?,
                diff_summary=?,
                error_message=?,
                started_at=?,
                finished_at=?
            WHERE job_id=?
            """,
            (
                record.status,
                record.pr_url,
                record.diff_summary,
                record.error_message,
                record.started_at.isoformat() if record.started_at else None,
                record.finished_at.isoformat() if record.finished_at else None,
                record.job_id,
            ),
        )

        conn.commit()
        conn.close()

        record = self._store.get(job_id)
        if record is None:
            logger.warning(
                "Job lookup failed - not found",
                extra={"event": "job_not_found", "job_id": job_id},
            )
            raise JobNotFoundError(job_id)
        return record

    def update(
        self,
        job_id: str,
        status: str | None = None,
        pr_url: str | None = None,
        diff_summary: str | None = None,
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
 main

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

    def all_jobs(self) -> dict:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM jobs").fetchall()
        conn.close()

        return {row["job_id"]: dict(row) for row in rows}

    def stats(self) -> dict:
 task-10-persistent-jobs
        conn = get_connection()

        rows = conn.execute("SELECT status, COUNT(*) as count FROM jobs GROUP BY status").fetchall()

        conn.close()

        stats = {
            "total": 0,
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,

        all_records = list(self._store.values())

        return {
            "total": len(all_records),
            "queued": sum(1 for r in all_records if r.status == "queued"),
            "running": sum(1 for r in all_records if r.status == "running"),
            "completed": sum(1 for r in all_records if r.status == "completed"),
            "failed": sum(1 for r in all_records if r.status == "failed"),
 main
        }

        for row in rows:
            stats[row["status"]] = row["count"]
            stats["total"] += row["count"]

        return stats


job_manager = JobManager()
