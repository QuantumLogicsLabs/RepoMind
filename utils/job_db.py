import sqlite3
from pathlib import Path

DB_PATH = Path("jobs.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            repo_url TEXT NOT NULL,
            instruction TEXT NOT NULL,
            status TEXT NOT NULL,
            pr_url TEXT,
            diff_summary TEXT,
            error_message TEXT,
            created_at TEXT,
            started_at TEXT,
            finished_at TEXT
        )
        """)

    conn.commit()
    conn.close()
