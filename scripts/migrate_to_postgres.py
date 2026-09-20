#!/usr/bin/env python3
"""Idempotently import the file dataset and SQLite operator state into PostgreSQL."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from api.postgres_store import PostgresStore  # noqa: E402
from data.loader import Inbox  # noqa: E402
from pipeline.runner import _extract_attachment, _identify_attachment  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("SDOC_DATABASE_URL") or os.getenv("DATABASE_URL"))
    parser.add_argument("--data-dir", default=os.getenv("SDOC_DATA_DIR", str(ROOT_DIR / "data")))
    parser.add_argument("--submission", default=os.getenv("SDOC_SUBMISSION_FILE", str(ROOT_DIR / "submission.json")))
    parser.add_argument("--sqlite-state", default=os.getenv("SDOC_STATE_DB", str(ROOT_DIR / "runtime" / "operator_state.db")))
    parser.add_argument("--skip-operator-state", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def submission_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def extract_comparison(inbox: Inbox, email: dict, result: dict) -> tuple[dict, dict]:
    if result.get("category") != "BL_COMPARISON":
        return {}, {}
    attachments = email.get("attachments") or []
    if len(attachments) < 2:
        return {}, {}
    si_path = next((path for path in attachments if _identify_attachment(path) == "SI"), attachments[0])
    bl_path = next((path for path in attachments if _identify_attachment(path) == "BL"), attachments[1])
    try:
        si_fields = getattr(_extract_attachment(inbox, si_path, "SI"), "fields", {})
    except Exception as exc:
        print(f"Warning: SI extraction failed for {email['email_id']}: {exc}")
        si_fields = {}
    try:
        bl_fields = getattr(_extract_attachment(inbox, bl_path, "BL"), "fields", {})
    except Exception as exc:
        print(f"Warning: BL extraction failed for {email['email_id']}: {exc}")
        bl_fields = {}
    return si_fields, bl_fields


def attachment_records(inbox: Inbox, email: dict) -> list[dict]:
    records = []
    for attachment_path in email.get("attachments") or []:
        content = inbox.read_bytes(attachment_path)
        suffix = Path(attachment_path).suffix.lower()
        records.append(
            {
                "attachment_path": attachment_path,
                "filename": Path(attachment_path).name,
                "content_type": mimetypes.guess_type(attachment_path)[0] or "application/octet-stream",
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "extracted_text": content.decode("utf-8", errors="replace") if suffix == ".txt" else None,
            }
        )
    return records


def sqlite_rows(connection: sqlite3.Connection, table: str) -> list[dict]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table}").fetchall()] if exists else []


def migrate_operator_state(store: PostgresStore, sqlite_path: Path) -> None:
    if not sqlite_path.exists():
        print(f"Operator-state import skipped: {sqlite_path} does not exist")
        return
    connection = sqlite3.connect(sqlite_path)
    connection.row_factory = sqlite3.Row
    try:
        activities = sqlite_rows(connection, "email_activity")
        drafts = sqlite_rows(connection, "notification_drafts")
        events = sqlite_rows(connection, "activity_events")
    finally:
        connection.close()
    store.import_operator_snapshot(activities, drafts, events)
    print(f"Operator state imported: {len(activities)} activity rows, {len(drafts)} drafts, {len(events)} events")


def verify(store: PostgresStore, expected_submission: dict) -> None:
    health = store.health()
    stored_submission = store.get_submission()
    if stored_submission != expected_submission:
        missing = sorted(set(expected_submission) - set(stored_submission))[:10]
        extra = sorted(set(stored_submission) - set(expected_submission))[:10]
        changed = sorted(key for key in set(expected_submission) & set(stored_submission) if expected_submission[key] != stored_submission[key])[:10]
        raise RuntimeError(f"Verification failed. missing={missing}, extra={extra}, changed={changed}")
    print(
        "Verification passed: "
        f"{health['emails']} emails, {health['results']} results, {health['attachments']} attachments"
    )


def migrate_dataset(store: PostgresStore, data_dir: str | Path, submission_path: str | Path) -> dict:
    """Import all source emails/results and return the exact expected submission."""
    submission_path = Path(submission_path)
    expected_submission = json.loads(submission_path.read_text(encoding="utf-8"))
    inbox = Inbox(str(data_dir))
    emails = inbox.emails()
    email_map = {email["email_id"]: email for email in emails}
    processed_at = submission_timestamp(submission_path)

    for index, email_id in enumerate(sorted(expected_submission), start=1):
        email = email_map.get(email_id)
        if not email:
            raise RuntimeError(f"Source email missing: {email_id}")
        result = expected_submission[email_id]
        si_fields, bl_fields = extract_comparison(inbox, email, result)
        store.upsert_dataset_record(
            email=email,
            result=result,
            si_fields=si_fields,
            bl_fields=bl_fields,
            attachments=attachment_records(inbox, email),
            processed_at=processed_at,
        )
        if index % 50 == 0 or index == len(expected_submission):
            print(f"Imported {index}/{len(expected_submission)} emails")

    return expected_submission


def main() -> int:
    args = parse_args()
    if not args.database_url:
        print("Missing DATABASE_URL or SDOC_DATABASE_URL.", file=sys.stderr)
        return 2
    submission_path = Path(args.submission)
    expected_submission = json.loads(submission_path.read_text(encoding="utf-8"))
    store = PostgresStore(args.database_url)
    if args.verify_only:
        verify(store, expected_submission)
        return 0

    expected_submission = migrate_dataset(store, args.data_dir, submission_path)

    if not args.skip_operator_state:
        migrate_operator_state(store, Path(args.sqlite_state))
    verify(store, expected_submission)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
