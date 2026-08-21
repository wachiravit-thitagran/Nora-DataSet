"""SQLite storage for access requests and download events.

Two tables only. `access_request` holds the personal data the form collects
and is subject to the retention sweep; `download_event` holds non-identifying
counters that survive the sweep so usage statistics remain meaningful after
personal data is erased.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .config import settings

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS access_request (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT    NOT NULL,
    organization   TEXT,
    purpose        TEXT    NOT NULL,
    purpose_detail TEXT,
    consent        INTEGER NOT NULL,
    consent_text   TEXT    NOT NULL,
    ip             TEXT,
    user_agent     TEXT,
    lang           TEXT,
    created_at     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_access_request_created
    ON access_request (created_at);

CREATE INDEX IF NOT EXISTS idx_access_request_email
    ON access_request (email);

CREATE TABLE IF NOT EXISTS download_event (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER,
    bundle_id  TEXT NOT NULL,
    version    TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_download_event_bundle
    ON download_event (bundle_id);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    path = Path(settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # sqlite reports an unwritable directory as "unable to open database file",
    # which says nothing about the cause. The usual cause is a named volume
    # created before the image had the mount point, so it belongs to root while
    # the service runs unprivileged. Name it plainly instead.
    if not os.access(path.parent, os.W_OK):
        raise RuntimeError(
            f"Cannot write to {path.parent} (running as uid {os.getuid()}). "
            "The database directory is not writable by this user — if it is a "
            "Docker volume, it was probably created root-owned before the "
            "image declared the directory. Recreate it: "
            "docker volume rm nora-dataset-db"
        )

    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL keeps readers from blocking the writer; without it, concurrent
    # downloads and form submissions contend for the same database lock.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_connection() -> sqlite3.Connection:
    """One connection per thread; sqlite3 objects are not thread-safe."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    with transaction() as conn:
        conn.executescript(SCHEMA)


def insert_access_request(
    *,
    email: str,
    organization: str | None,
    purpose: str,
    purpose_detail: str | None,
    consent_text: str,
    ip: str | None,
    user_agent: str | None,
    lang: str | None,
) -> int:
    with transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO access_request
                (email, organization, purpose, purpose_detail, consent,
                 consent_text, ip, user_agent, lang, created_at)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                email,
                organization,
                purpose,
                purpose_detail,
                consent_text,
                ip,
                user_agent,
                lang,
                _utcnow(),
            ),
        )
    return int(cursor.lastrowid)


def record_download(
    request_id: int | None, bundle_id: str, version: str | None
) -> None:
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO download_event (request_id, bundle_id, version, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (request_id, bundle_id, version, _utcnow()),
        )


def count_recent_requests_from_ip(ip: str, within_seconds: int = 3600) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=within_seconds)).isoformat(
        timespec="seconds"
    )
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM access_request WHERE ip = ? AND created_at >= ?",
        (ip, cutoff),
    ).fetchone()
    return int(row["n"]) if row else 0


def purge_expired_requests() -> int:
    """Delete access requests past the retention window.

    Download events are kept but detached from the deleted request, so
    aggregate statistics survive while the personal data does not.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
    ).isoformat(timespec="seconds")
    with transaction() as conn:
        conn.execute(
            """
            UPDATE download_event SET request_id = NULL
            WHERE request_id IN (SELECT id FROM access_request WHERE created_at < ?)
            """,
            (cutoff,),
        )
        cursor = conn.execute(
            "DELETE FROM access_request WHERE created_at < ?", (cutoff,)
        )
    return cursor.rowcount


def delete_requests_by_email(email: str) -> int:
    """Support PDPA erasure requests. Called by scripts/erase_subject.py."""
    with transaction() as conn:
        conn.execute(
            """
            UPDATE download_event SET request_id = NULL
            WHERE request_id IN (SELECT id FROM access_request WHERE email = ?)
            """,
            (email,),
        )
        cursor = conn.execute("DELETE FROM access_request WHERE email = ?", (email,))
    return cursor.rowcount
