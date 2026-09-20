"""PostgreSQL persistence for source emails, results, and operator workflow state."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional


ROOT_DIR = Path(__file__).resolve().parent.parent
SCHEMA_FILE = ROOT_DIR / "database" / "schema.sql"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return str(value)


class PostgresStore:
    """Database repository that also implements the operator-state interface."""

    def __init__(self, database_url: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb
        except ImportError as exc:
            raise RuntimeError("PostgreSQL requires psycopg[binary]. Install requirements.txt.") from exc
        self.database_url = database_url
        self._psycopg = psycopg
        self._dict_row = dict_row
        self._jsonb = Jsonb
        self.initialize_schema()

    def _connect(self):
        return self._psycopg.connect(self.database_url, row_factory=self._dict_row, connect_timeout=10)

    def initialize_schema(self) -> None:
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        with self._connect() as connection:
            for statement in schema.split(";"):
                if statement.strip():
                    connection.execute(statement)

    def health(self) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM emails) AS emails,
                    (SELECT COUNT(*) FROM verification_results) AS results,
                    (SELECT COUNT(*) FROM attachments) AS attachments
                """
            ).fetchone()
        return {"connected": True, **dict(row)}

    # Source dataset -------------------------------------------------
    def upsert_dataset_record(
        self,
        email: Mapping,
        result: Mapping,
        si_fields: Mapping,
        bl_fields: Mapping,
        attachments: list[Mapping],
        processed_at: Optional[str],
    ) -> None:
        email_id = str(email["email_id"])
        defect_fields = list(result.get("defect_fields") or [])
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO emails (email_id, sender, subject, body, raw_payload, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (email_id) DO UPDATE SET
                    sender = EXCLUDED.sender,
                    subject = EXCLUDED.subject,
                    body = EXCLUDED.body,
                    raw_payload = EXCLUDED.raw_payload,
                    updated_at = NOW()
                """,
                (
                    email_id,
                    str(email.get("from") or ""),
                    str(email.get("subject") or ""),
                    str(email.get("body") or ""),
                    self._jsonb(dict(email)),
                ),
            )
            connection.execute(
                """
                INSERT INTO verification_results
                    (email_id, category, status, review_reason, has_defect, defect_fields, processed_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (email_id) DO UPDATE SET
                    category = EXCLUDED.category,
                    status = EXCLUDED.status,
                    review_reason = EXCLUDED.review_reason,
                    has_defect = EXCLUDED.has_defect,
                    defect_fields = EXCLUDED.defect_fields,
                    processed_at = EXCLUDED.processed_at,
                    updated_at = NOW()
                """,
                (
                    email_id,
                    str(result.get("category") or "GENERAL"),
                    str(result.get("status") or "OK"),
                    result.get("review_reason"),
                    bool(result.get("has_defect")),
                    self._jsonb(defect_fields),
                    processed_at,
                ),
            )
            connection.execute("DELETE FROM attachments WHERE email_id = %s", (email_id,))
            for attachment in attachments:
                connection.execute(
                    """
                    INSERT INTO attachments
                        (email_id, attachment_path, filename, content_type, content_sha256, extracted_text)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        email_id,
                        attachment["attachment_path"],
                        attachment["filename"],
                        attachment.get("content_type"),
                        attachment.get("content_sha256"),
                        attachment.get("extracted_text"),
                    ),
                )
            connection.execute("DELETE FROM comparison_fields WHERE email_id = %s", (email_id,))
            for field_name in sorted(set(si_fields) | set(bl_fields) | set(defect_fields)):
                connection.execute(
                    """
                    INSERT INTO comparison_fields (email_id, field_name, si_value, bl_value, is_mismatch)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        email_id,
                        field_name,
                        None if si_fields.get(field_name) is None else str(si_fields.get(field_name)),
                        None if bl_fields.get(field_name) is None else str(bl_fields.get(field_name)),
                        field_name in defect_fields,
                    ),
                )
            self._ensure_email(connection, email_id, processed_at)

    def get_submission(self) -> dict[str, dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT email_id, category, status, review_reason, has_defect, defect_fields
                FROM verification_results ORDER BY email_id
                """
            ).fetchall()
        return {
            row["email_id"]: {
                "category": row["category"],
                "status": row["status"],
                "review_reason": row["review_reason"],
                "has_defect": bool(row["has_defect"]),
                "defect_fields": list(row["defect_fields"] or []),
            }
            for row in rows
        }

    def get_email(self, email_id: str) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT email_id, sender, subject, body FROM emails WHERE email_id = %s",
                (email_id,),
            ).fetchone()
            if not row:
                return None
            attachments = connection.execute(
                "SELECT attachment_path FROM attachments WHERE email_id = %s ORDER BY id",
                (email_id,),
            ).fetchall()
        return {
            "email_id": row["email_id"],
            "from": row["sender"],
            "subject": row["subject"],
            "body": row["body"],
            "attachments": [item["attachment_path"] for item in attachments],
        }

    def list_emails(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT email_id, sender, subject, body FROM emails ORDER BY email_id"
            ).fetchall()
        return [
            {"email_id": row["email_id"], "from": row["sender"], "subject": row["subject"], "body": row["body"]}
            for row in rows
        ]

    def get_comparison(self, email_id: str) -> dict:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT field_name, si_value, bl_value
                FROM comparison_fields WHERE email_id = %s ORDER BY field_name
                """,
                (email_id,),
            ).fetchall()
        return {
            "si": {row["field_name"]: row["si_value"] for row in rows},
            "bl": {row["field_name"]: row["bl_value"] for row in rows},
        }

    def latest_processed_at(self) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute("SELECT MAX(processed_at) AS value FROM verification_results").fetchone()
        return _iso(row["value"]) if row else None

    # Operator workflow ---------------------------------------------
    @staticmethod
    def _serialize_activity(row) -> Optional[dict]:
        if not row:
            return None
        return {
            "email_id": row["email_id"],
            "first_seen_at": _iso(row["first_seen_at"]),
            "processed_at": _iso(row["processed_at"]),
            "reviewed": bool(row["reviewed"]),
            "reviewed_at": _iso(row["reviewed_at"]),
            "last_opened_at": _iso(row["last_opened_at"]),
            "reviewed_by": row["reviewed_by"],
            "updated_at": _iso(row["updated_at"]),
        }

    @staticmethod
    def _ensure_email(connection, email_id: str, processed_at: Optional[str] = None) -> None:
        now = utc_now()
        connection.execute(
            """
            INSERT INTO email_activity (email_id, first_seen_at, processed_at, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (email_id) DO UPDATE SET
                processed_at = COALESCE(EXCLUDED.processed_at, email_activity.processed_at),
                updated_at = CASE
                    WHEN EXCLUDED.processed_at IS NOT NULL THEN EXCLUDED.updated_at
                    ELSE email_activity.updated_at
                END
            """,
            (email_id, now, processed_at, now),
        )

    def ensure_emails(self, email_ids: Iterable[str], processed_at: Optional[str] = None) -> None:
        with self._connect() as connection:
            for email_id in email_ids:
                self._ensure_email(connection, email_id, processed_at)

    def get(self, email_id: str) -> dict:
        self.ensure_emails([email_id])
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM email_activity WHERE email_id = %s", (email_id,)).fetchone()
        return self._serialize_activity(row) or {}

    def get_with_events(self, email_id: str) -> dict:
        activity = self.get(email_id)
        activity["events"] = self.list_events(email_id)
        return activity

    def list_all(self) -> dict[str, dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM email_activity ORDER BY email_id").fetchall()
        return {row["email_id"]: self._serialize_activity(row) for row in rows}

    def mark_reviewed(self, email_id: str, reviewed: bool, reviewer: str = "operator") -> dict:
        self.ensure_emails([email_id])
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE email_activity
                SET reviewed = %s, reviewed_at = %s, reviewed_by = %s, updated_at = %s
                WHERE email_id = %s
                """,
                (reviewed, now if reviewed else None, reviewer if reviewed else None, now, email_id),
            )
        self.log_event(
            email_id,
            "reviewed" if reviewed else "review_removed",
            "Operator reviewed" if reviewed else "Review mark removed",
            "Case marked as reviewed." if reviewed else "The operator review mark was removed.",
            reviewer,
        )
        return self.get_with_events(email_id)

    def mark_opened(self, email_id: str) -> dict:
        self.ensure_emails([email_id])
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE email_activity SET last_opened_at = %s, updated_at = %s WHERE email_id = %s",
                (now, now, email_id),
            )
        self.log_event(email_id, "opened", "Email opened", "Opened in the verification workspace.", "operator", 30)
        return self.get_with_events(email_id)

    def latest_reviewed(self) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM email_activity
                WHERE reviewed = TRUE AND reviewed_at IS NOT NULL
                ORDER BY reviewed_at DESC LIMIT 1
                """
            ).fetchone()
        return self._serialize_activity(row)

    def save_draft(self, email_id: str, recipient: str, subject: str, body: str) -> dict:
        saved_at = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO notification_drafts (email_id, recipient, subject, body, saved_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (email_id) DO UPDATE SET
                    recipient = EXCLUDED.recipient,
                    subject = EXCLUDED.subject,
                    body = EXCLUDED.body,
                    saved_at = EXCLUDED.saved_at
                """,
                (email_id, recipient, subject, body, saved_at),
            )
        self.log_event(email_id, "draft_saved", "Response draft saved", "Operator-approved edits were saved locally. No email was sent.", "operator")
        return {"email_id": email_id, "recipient": recipient, "subject": subject, "body": body, "saved_at": saved_at}

    def get_draft(self, email_id: str) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM notification_drafts WHERE email_id = %s", (email_id,)).fetchone()
        if not row:
            return None
        return {**dict(row), "saved_at": _iso(row["saved_at"])}

    def log_event(
        self,
        email_id: str,
        event_type: str,
        title: str,
        detail: str = "",
        actor: str = "system",
        dedupe_seconds: int = 0,
    ) -> dict:
        occurred_at = utc_now()
        with self._connect() as connection:
            if dedupe_seconds:
                latest = connection.execute(
                    """
                    SELECT occurred_at FROM activity_events
                    WHERE email_id = %s AND event_type = %s
                    ORDER BY occurred_at DESC LIMIT 1
                    """,
                    (email_id, event_type),
                ).fetchone()
                if latest:
                    latest_at = latest["occurred_at"]
                    if (datetime.now(timezone.utc) - latest_at).total_seconds() < dedupe_seconds:
                        occurred_at = _iso(latest_at)
                        return {"email_id": email_id, "event_type": event_type, "title": title, "detail": detail, "actor": actor, "occurred_at": occurred_at}
            connection.execute(
                """
                INSERT INTO activity_events (email_id, event_type, title, detail, actor, occurred_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (email_id, event_type, title, occurred_at) DO NOTHING
                """,
                (email_id, event_type, title, detail, actor, occurred_at),
            )
        return {"email_id": email_id, "event_type": event_type, "title": title, "detail": detail, "actor": actor, "occurred_at": occurred_at}

    def list_events(self, email_id: str, limit: int = 50) -> list[dict]:
        safe_limit = max(1, min(limit, 100))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT email_id, event_type, title, detail, actor, occurred_at
                FROM activity_events WHERE email_id = %s
                ORDER BY occurred_at DESC, id DESC LIMIT %s
                """,
                (email_id, safe_limit),
            ).fetchall()
        return [{**dict(row), "occurred_at": _iso(row["occurred_at"])} for row in rows]

    def import_operator_snapshot(
        self,
        activities: Iterable[Mapping],
        drafts: Iterable[Mapping],
        events: Iterable[Mapping],
    ) -> None:
        with self._connect() as connection:
            for row in activities:
                connection.execute(
                    """
                    INSERT INTO email_activity
                        (email_id, first_seen_at, processed_at, reviewed, reviewed_at, last_opened_at, reviewed_by, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (email_id) DO UPDATE SET
                        first_seen_at = LEAST(email_activity.first_seen_at, EXCLUDED.first_seen_at),
                        processed_at = COALESCE(EXCLUDED.processed_at, email_activity.processed_at),
                        reviewed = EXCLUDED.reviewed,
                        reviewed_at = EXCLUDED.reviewed_at,
                        last_opened_at = EXCLUDED.last_opened_at,
                        reviewed_by = EXCLUDED.reviewed_by,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        row["email_id"], row["first_seen_at"], row.get("processed_at"), bool(row.get("reviewed")),
                        row.get("reviewed_at"), row.get("last_opened_at"), row.get("reviewed_by"), row["updated_at"],
                    ),
                )
            for row in drafts:
                connection.execute(
                    """
                    INSERT INTO notification_drafts (email_id, recipient, subject, body, saved_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (email_id) DO UPDATE SET
                        recipient = EXCLUDED.recipient, subject = EXCLUDED.subject,
                        body = EXCLUDED.body, saved_at = EXCLUDED.saved_at
                    """,
                    (row["email_id"], row["recipient"], row["subject"], row["body"], row["saved_at"]),
                )
            for row in events:
                connection.execute(
                    """
                    INSERT INTO activity_events (email_id, event_type, title, detail, actor, occurred_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (email_id, event_type, title, occurred_at) DO NOTHING
                    """,
                    (row["email_id"], row["event_type"], row["title"], row.get("detail"), row.get("actor"), row["occurred_at"]),
                )
