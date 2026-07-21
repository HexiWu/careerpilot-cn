from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from careerpilot.models import AgentEvent, ApplicationStatus, JobPosting, SourceHealth

SCHEMA = """
CREATE TABLE IF NOT EXISTS resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    company_name TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_name);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    score REAL NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(resume_id, job_id)
);
CREATE TABLE IF NOT EXISTS applications (
    job_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON agent_events(run_id);
CREATE TABLE IF NOT EXISTS source_health (
    company_name TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL,
    jobs_found INTEGER NOT NULL,
    error TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY(company_name, url)
);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save_resume(self, filename: str, profile_json: str, created_at: datetime) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO resumes(filename, profile_json, created_at) VALUES (?, ?, ?)",
                (filename, profile_json, created_at.isoformat()),
            )
            return int(cur.lastrowid)

    def latest_resume(self) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM resumes ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return None
            return {"id": row["id"], "filename": row["filename"], **json.loads(row["profile_json"])}

    def upsert_job(self, job: JobPosting) -> tuple[int, str]:
        job.ensure_content_hash()
        payload = job.model_dump_json()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id, content_hash FROM jobs WHERE fingerprint=?", (job.fingerprint,)
            ).fetchone()
            if existing:
                state = "updated" if existing["content_hash"] != job.content_hash else "unchanged"
                conn.execute(
                    """UPDATE jobs SET company_name=?, title=?, location=?, source_url=?,
                       content_hash=?, payload_json=?, last_seen_at=?, status=? WHERE id=?""",
                    (
                        job.company_name,
                        job.title,
                        job.location,
                        str(job.source_url),
                        job.content_hash,
                        payload,
                        job.last_seen_at.isoformat(),
                        job.status,
                        existing["id"],
                    ),
                )
                return int(existing["id"]), state
            cur = conn.execute(
                """INSERT INTO jobs(fingerprint, company_name, title, location, source_url,
                   content_hash, payload_json, first_seen_at, last_seen_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.fingerprint,
                    job.company_name,
                    job.title,
                    job.location,
                    str(job.source_url),
                    job.content_hash,
                    payload,
                    job.first_seen_at.isoformat(),
                    job.last_seen_at.isoformat(),
                    job.status,
                ),
            )
            return int(cur.lastrowid), "created"

    def list_jobs(self, query: str = "", limit: int = 100) -> list[JobPosting]:
        sql = "SELECT id, payload_json FROM jobs WHERE status='active'"
        params: list[object] = []
        if query:
            sql += " AND (title LIKE ? OR company_name LIKE ? OR location LIKE ?)"
            term = f"%{query}%"
            params.extend([term, term, term])
        sql += " ORDER BY last_seen_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            job = JobPosting.model_validate_json(row["payload_json"])
            job.id = int(row["id"])
            result.append(job)
        return result

    def save_event(self, event: AgentEvent) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO agent_events(run_id, agent, event_type, status, message,
                   payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.run_id,
                    event.agent,
                    event.event_type,
                    event.status,
                    event.message,
                    json.dumps(event.payload, ensure_ascii=False),
                    event.created_at.isoformat(),
                ),
            )

    def list_events(self, run_id: str | None = None, limit: int = 200) -> list[dict]:
        with self.connect() as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM agent_events WHERE run_id=? ORDER BY id", (run_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_events ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload_json"])} for row in rows]

    def save_source_health(self, health: SourceHealth) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO source_health(
                       company_name, url, status, jobs_found, error, checked_at
                   )
                   VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(company_name, url) DO UPDATE SET
                   status=excluded.status, jobs_found=excluded.jobs_found, error=excluded.error,
                   checked_at=excluded.checked_at""",
                (
                    health.company_name,
                    health.url,
                    health.status,
                    health.jobs_found,
                    health.error,
                    health.checked_at.isoformat(),
                ),
            )

    def source_health(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM source_health ORDER BY checked_at DESC").fetchall()
        return [dict(row) for row in rows]

    def update_application(self, job_id: int, status: ApplicationStatus, note: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO applications(job_id, status, note, updated_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, note=excluded.note,
                   updated_at=excluded.updated_at""",
                (job_id, status, note, datetime.now(UTC).isoformat()),
            )

    def list_applications(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT a.*, j.payload_json FROM applications a
                   JOIN jobs j ON j.id=a.job_id ORDER BY a.updated_at DESC"""
            ).fetchall()
        return [dict(row) | {"job": json.loads(row["payload_json"])} for row in rows]
