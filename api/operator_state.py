"""Persistent operator activity metadata kept separate from hackathon source data."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


def utc_now() -> str:
    """Return a stable ISO-8601 UTC timestamp for API responses and storage."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class OperatorStateStore:
    """Small SQLite repository for review/open activity.

    The verification submission remains untouched. This database only contains
    operational UI metadata and can be placed on persistent storage by setting
    ``SDOC_STATE_DB``.
    """

    def __init__(self, database_path: Path | str):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS email_activity (
                    email_id TEXT PRIMARY KEY,
                    first_seen_at TEXT NOT NULL,
                    processed_at TEXT,
                    reviewed INTEGER NOT NULL DEFAULT 0,
                    reviewed_at TEXT,
                    last_opened_at TEXT,
                    reviewed_by TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_drafts (
                    email_id TEXT PRIMARY KEY,
                    recipient TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    saved_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _serialize(row: sqlite3.Row | None) -> Optional[dict]:
        if row is None:
            return None
        return {
            "email_id": row["email_id"],
            "first_seen_at": row["first_seen_at"],
            "processed_at": row["processed_at"],
            "reviewed": bool(row["reviewed"]),
            "reviewed_at": row["reviewed_at"],
            "last_opened_at": row["last_opened_at"],
            "reviewed_by": row["reviewed_by"],
            "updated_at": row["updated_at"],
        }

    def ensure_emails(self, email_ids: Iterable[str], processed_at: str | None = None) -> None:
        now = utc_now()
        rows = [(email_id, now, processed_at, now) for email_id in email_ids]
        if not rows:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO email_activity (email_id, first_seen_at, processed_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(email_id) DO UPDATE SET
                    processed_at = COALESCE(email_activity.processed_at, excluded.processed_at)
                """,
                rows,
            )

    def get(self, email_id: str) -> dict:
        self.ensure_emails([email_id])
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM email_activity WHERE email_id = ?",
                (email_id,),
            ).fetchone()
        return self._serialize(row) or {}

    def list_all(self) -> dict[str, dict]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM email_activity ORDER BY email_id"
            ).fetchall()
        return {row["email_id"]: self._serialize(row) for row in rows}

    def mark_reviewed(self, email_id: str, reviewed: bool, reviewer: str = "operator") -> dict:
        self.ensure_emails([email_id])
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE email_activity
                SET reviewed = ?, reviewed_at = ?, reviewed_by = ?, updated_at = ?
                WHERE email_id = ?
                """,
                (int(reviewed), now if reviewed else None, reviewer if reviewed else None, now, email_id),
            )
        return self.get(email_id)

    def mark_opened(self, email_id: str) -> dict:
        self.ensure_emails([email_id])
        now = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE email_activity
                SET last_opened_at = ?, updated_at = ?
                WHERE email_id = ?
                """,
                (now, now, email_id),
            )
        return self.get(email_id)

    def latest_reviewed(self) -> Optional[dict]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM email_activity
                WHERE reviewed = 1 AND reviewed_at IS NOT NULL
                ORDER BY reviewed_at DESC
                LIMIT 1
                """
            ).fetchone()
        return self._serialize(row)

    def save_draft(self, email_id: str, recipient: str, subject: str, body: str) -> dict:
        saved_at = utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO notification_drafts (email_id, recipient, subject, body, saved_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(email_id) DO UPDATE SET
                    recipient = excluded.recipient,
                    subject = excluded.subject,
                    body = excluded.body,
                    saved_at = excluded.saved_at
                """,
                (email_id, recipient, subject, body, saved_at),
            )
        return {
            "email_id": email_id,
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "saved_at": saved_at,
        }

    def get_draft(self, email_id: str) -> Optional[dict]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM notification_drafts WHERE email_id = ?",
                (email_id,),
            ).fetchone()
        return dict(row) if row is not None else None
