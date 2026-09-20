"""
main.py — FastAPI service for the Shipping Document Verification pipeline.

Endpoints:
  GET  /health            - Health check
  POST /process           - Runs the full pipeline on data/ and returns the submission
  GET  /submission        - Returns the current/cached submission.json
  GET  /email/{email_id}  - Process or retrieve result for a specific email
  GET  /operator/metadata - Persistent operator review/open activity
  POST /email/{email_id}/review - Persist an operator review decision
  POST /email/{email_id}/opened - Record dashboard navigation activity
  POST /assistant/query     - Safe natural-language workspace queries
  GET  /stats             - Summary statistics of classification and verification
"""

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

from pipeline.runner import run_pipeline, process_email, _identify_attachment, _extract_attachment
from pipeline.notification import (
    generate_mismatch_email,
    process_mismatch_notification,
    save_email_locally,
)
from pipeline.security import (
    scan_email_security,
    PromptInjectionGuard,
    PIIRedactor,
)
from data.loader import Inbox
from api.operator_state import OperatorStateStore, utc_now
from api.postgres_store import PostgresStore
from api.assistant import run_assistant_query

logger = logging.getLogger(__name__)

DOCS_HTML_FILE = Path(__file__).resolve().parent / "docs.html"

app = FastAPI(
    title="Shipping Document Verification API",
    description="Automated email classification and SI/BL document verification pipeline",
    version="1.0.0",
    docs_url="/swagger",
    redoc_url="/redoc",
)

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

DATA_DIR = os.environ.get("SDOC_DATA_DIR", "data")
SUBMISSION_FILE = os.environ.get("SDOC_SUBMISSION_FILE", "submission.json")
_state_db_setting = Path(os.environ.get("SDOC_STATE_DB", "runtime/operator_state.db"))
STATE_DB_FILE = _state_db_setting if _state_db_setting.is_absolute() else ROOT_DIR / _state_db_setting
DATABASE_URL = os.environ.get("SDOC_DATABASE_URL") or os.environ.get("DATABASE_URL")
postgres_store = PostgresStore(DATABASE_URL) if DATABASE_URL else None
operator_state = postgres_store or OperatorStateStore(STATE_DB_FILE)


def _get_file_submission() -> dict:
    if os.path.exists(SUBMISSION_FILE):
        with open(SUBMISSION_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _get_submission() -> dict:
    """Use a complete PostgreSQL import first, with the file dataset as fallback."""
    file_submission = _get_file_submission()
    if postgres_store:
        database_submission = postgres_store.get_submission()
        if database_submission and (
            not file_submission or database_submission == file_submission
        ):
            return database_submission
        if database_submission:
            logger.warning(
                "PostgreSQL contains %s results but the file dataset contains %s; using file fallback",
                len(database_submission),
                len(file_submission),
            )
    return file_submission


def _submission_processed_at() -> str | None:
    """Use the submission file timestamp when no per-email source timestamp exists."""
    if postgres_store:
        processed_at = postgres_store.latest_processed_at()
        if processed_at:
            return processed_at
    try:
        timestamp = Path(SUBMISSION_FILE).stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _require_known_email(email_id: str) -> None:
    if email_id not in _get_submission():
        raise HTTPException(status_code=404, detail=f"Email {email_id} not found in submission")


@app.get("/", include_in_schema=False)
def root_redirect():
    """Redirect root access directly to the Verity Web App."""
    return RedirectResponse(url="/app/")


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
def docs_ui():
    """Interactive visual API documentation portal."""
    if DOCS_HTML_FILE.exists():
        return HTMLResponse(content=DOCS_HTML_FILE.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>API Docs</h1><p>docs.html not found.</p>")



@app.get("/health")
def health_check():
    """Liveness check endpoint."""
    database = postgres_store.health() if postgres_store else {"connected": False}
    return {
        "status": "ok",
        "service": "sdoc-verification-api",
        "version": "1.0.0",
        "storage": "postgresql" if postgres_store else "files+sqlite",
        "database": database,
    }



@app.post("/process")
def trigger_process(data_dir: str = DATA_DIR):
    """Trigger the pipeline to process all emails in the inbox."""
    try:
        submission = run_pipeline(data_dir)
        # Strip internal metadata
        clean_submission = {
            eid: {k: v for k, v in result.items() if k != "decided_by"}
            for eid, result in submission.items()
        }
        with open(SUBMISSION_FILE, "w", encoding="utf-8") as f:
            json.dump(clean_submission, f, indent=2)
        if postgres_store:
            from scripts.migrate_to_postgres import migrate_dataset

            migrate_dataset(postgres_store, data_dir, SUBMISSION_FILE)
            if postgres_store.get_submission() != clean_submission:
                raise RuntimeError("PostgreSQL verification failed after pipeline processing")
        operator_state.ensure_emails(clean_submission.keys(), processed_at=utc_now())
        return {
            "status": "success",
            "emails_processed": len(clean_submission),
            "submission_saved": SUBMISSION_FILE,
        }
    except Exception as e:
        logger.error(f"Error running pipeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/submission")
def get_submission():
    """Return the cached or previously generated submission.json."""
    sub = _get_submission()
    if not sub:
        raise HTTPException(
            status_code=404,
            detail="No submission found. Run POST /process first."
        )
    operator_state.ensure_emails(sub.keys(), processed_at=_submission_processed_at())
    return sub


@app.get("/email/{email_id}")
def get_email_result(email_id: str, data_dir: str = DATA_DIR):
    """Get the classification and comparison result for a single email."""
    # First check cached submission
    sub = _get_submission()
    if email_id in sub:
        operator_state.ensure_emails([email_id], processed_at=_submission_processed_at())
        return {"email_id": email_id, **sub[email_id], "source": "cached"}

    # Otherwise process on-demand
    try:
        inbox = Inbox(data_dir)
        email = inbox.get(email_id)
        result = process_email(inbox, email)
        clean = {k: v for k, v in result.items() if k != "decided_by"}
        operator_state.ensure_emails([email_id], processed_at=utc_now())
        return {"email_id": email_id, **clean, "source": "on-demand"}
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Email {email_id} could not be processed: {e}"
        )


@app.get("/email/{email_id}/source")
def get_email_source(email_id: str, data_dir: str = DATA_DIR):
    """Return the source email needed by the operator UI without exposing data/ publicly."""
    _require_known_email(email_id)
    if postgres_store:
        email = postgres_store.get_email(email_id)
        if email:
            return email
    try:
        email = Inbox(data_dir).get(email_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Source email {email_id} is unavailable: {exc}")
    return {
        "email_id": email_id,
        "from": email.get("from", ""),
        "subject": email.get("subject", ""),
        "body": email.get("body", ""),
        "attachments": email.get("attachments", []),
    }


class ReviewPayload(BaseModel):
    reviewed: bool = True
    reviewer: str = "operator"


@app.get("/operator/metadata")
def get_operator_metadata():
    """Return review/open activity without altering the competition submission schema."""
    submission = _get_submission()
    operator_state.ensure_emails(submission.keys(), processed_at=_submission_processed_at())
    return {
        "emails": operator_state.list_all(),
        "latest_reviewed": operator_state.latest_reviewed(),
    }


@app.get("/email/{email_id}/metadata")
def get_email_metadata(email_id: str):
    _require_known_email(email_id)
    return operator_state.get_with_events(email_id)


@app.get("/email/{email_id}/activity")
def get_email_activity(email_id: str):
    """Return the operator audit events stored outside the hackathon submission."""
    _require_known_email(email_id)
    return {"email_id": email_id, "events": operator_state.list_events(email_id)}


@app.post("/email/{email_id}/review")
def update_email_review(email_id: str, payload: ReviewPayload):
    _require_known_email(email_id)
    reviewer = payload.reviewer.strip()[:80] or "operator"
    return operator_state.mark_reviewed(email_id, payload.reviewed, reviewer)


@app.post("/email/{email_id}/opened")
def record_email_opened(email_id: str):
    _require_known_email(email_id)
    return operator_state.mark_opened(email_id)


@app.get("/email/{email_id}/confidence")
def get_email_confidence(email_id: str, data_dir: str = DATA_DIR):
    """
    Return SI/BL extraction confidence as percentages.

    This endpoint is separate from /submission so the competition
    submission format is not changed.
    """
    try:
        inbox = Inbox(data_dir)
        email = inbox.get(email_id)

        attachments = email.get("attachments", [])

        si_path = None
        bl_path = None

        for attachment in attachments:
            role = _identify_attachment(attachment)

            if role == "SI" and not si_path:
                si_path = attachment

            elif role == "BL" and not bl_path:
                bl_path = attachment

        if not si_path and len(attachments) >= 1:
            si_path = attachments[0]

        if not bl_path and len(attachments) >= 2:
            bl_path = attachments[1]

        si_confidence = {}
        bl_confidence = {}

        si_low_confidence = []
        bl_low_confidence = []

        if si_path:
            si_result = _extract_attachment(
                inbox,
                si_path,
                "SI",
            )

            si_confidence = (
                si_result.confidence_percentages()
                if hasattr(si_result, "confidence_percentages")
                else {}
            )

            si_low_confidence = (
                si_result.low_confidence_fields()
                if hasattr(si_result, "low_confidence_fields")
                else []
            )

        if bl_path:
            bl_result = _extract_attachment(
                inbox,
                bl_path,
                "BL",
            )

            bl_confidence = (
                bl_result.confidence_percentages()
                if hasattr(bl_result, "confidence_percentages")
                else {}
            )

            bl_low_confidence = (
                bl_result.low_confidence_fields()
                if hasattr(bl_result, "low_confidence_fields")
                else []
            )

        def average_confidence(values: dict[str, float]) -> float:
            if not values:
                return 0.0

            return round(
                sum(values.values()) / len(values),
                1,
            )

        return {
            "email_id": email_id,
            "si": {
                "attachment": si_path,
                "confidence": si_confidence,
                "overall_confidence": average_confidence(
                    si_confidence
                ),
                "low_confidence_fields": si_low_confidence,
            },
            "bl": {
                "attachment": bl_path,
                "confidence": bl_confidence,
                "overall_confidence": average_confidence(
                    bl_confidence
                ),
                "low_confidence_fields": bl_low_confidence,
            },
        }

    except Exception as e:
        logger.error(
            f"Could not calculate confidence for {email_id}: {e}"
        )

        raise HTTPException(
            status_code=404,
            detail=(
                f"Confidence information for {email_id} "
                f"could not be generated: {e}"
            ),
        )

def _get_email_and_fields(email_id: str, data_dir: str = DATA_DIR):
    """Internal helper to retrieve email, classification/result, and extracted fields."""
    sub = _get_submission()
    if postgres_store:
        database_email = postgres_store.get_email(email_id)
        if database_email and email_id in sub:
            comparison = postgres_store.get_comparison(email_id)
            if comparison["si"] or comparison["bl"] or sub[email_id].get("category") != "BL_COMPARISON":
                return None, database_email, sub[email_id], comparison["si"], comparison["bl"]

    inbox = Inbox(data_dir)
    try:
        email = inbox.get(email_id)
    except Exception:
        email = None

    if not email:
        raise HTTPException(status_code=404, detail=f"Email {email_id} not found in inbox")

    if email_id in sub:
        result = sub[email_id]
    else:
        result = process_email(inbox, email)
        result = {k: v for k, v in result.items() if k != "decided_by"}

    si_fields = {}
    bl_fields = {}
    atts = email.get("attachments", [])
    if len(atts) >= 2:
        si_path = None
        bl_path = None
        for att in atts:
            role = _identify_attachment(att)
            if role == "SI" and not si_path:
                si_path = att
            elif role == "BL" and not bl_path:
                bl_path = att
        if not si_path and len(atts) >= 1:
            si_path = atts[0]
        if not bl_path and len(atts) >= 2:
            bl_path = atts[1]

        if si_path:
            try:
                si_res = _extract_attachment(inbox, si_path, "SI")
                si_fields = getattr(si_res, "fields", {})
            except Exception:
                pass
        if bl_path:
            try:
                bl_res = _extract_attachment(inbox, bl_path, "BL")
                bl_fields = getattr(bl_res, "fields", {})
            except Exception:
                pass

    return inbox, email, result, si_fields, bl_fields


@app.get("/email/{email_id}/comparison")
def get_email_comparison(email_id: str, data_dir: str = DATA_DIR):
    """Return extracted SI/BL fields through the API for the comparison UI."""
    _require_known_email(email_id)
    _, email, _, si_fields, bl_fields = _get_email_and_fields(email_id, data_dir)
    return {
        "email_id": email_id,
        "attachments": email.get("attachments", []),
        "si": si_fields,
        "bl": bl_fields,
    }


@app.get("/email/{email_id}/notification")
def get_email_notification_draft(
    email_id: str,
    regenerate: bool = False,
    data_dir: str = DATA_DIR,
):
    """
    Generate or retrieve the drafted mismatch email notification for an email.
    If the email has status MISMATCH, generates an email addressed to the original sender
    detailing the specific SI vs BL discrepancies and action items.
    """
    inbox, email, result, si_fields, bl_fields = _get_email_and_fields(email_id, data_dir)

    if result.get("status") != "MISMATCH":
        return {
            "email_id": email_id,
            "status": result.get("status"),
            "notification_eligible": False,
            "reason": "Email does not have a confirmed mismatch (status is not MISMATCH)",
        }

    draft = generate_mismatch_email(
        email_id=email_id,
        email_data=email,
        result=result,
        si_fields=si_fields,
        bl_fields=bl_fields,
    )
    if not draft:
        return {
            "email_id": email_id,
            "status": "MISMATCH",
            "notification_eligible": False,
            "reason": "Original sender email address could not be identified from email headers",
        }

    saved_draft = None if regenerate else operator_state.get_draft(email_id)
    if saved_draft:
        draft["subject"] = saved_draft["subject"]
        draft["body"] = saved_draft["body"]
    else:
        operator_state.log_event(
            email_id,
            "draft_regenerated" if regenerate else "draft_generated",
            "Response draft regenerated" if regenerate else "Response draft generated",
            "A clarification draft was prepared for operator review. No email was sent.",
            "system",
            dedupe_seconds=30,
        )

    return {
        "email_id": email_id,
        "status": "MISMATCH",
        "notification_eligible": True,
        "recipient": draft["to"],
        "subject": draft["subject"],
        "body": draft["body"],
        "generated_at": draft["generated_at"],
        "saved_at": saved_draft["saved_at"] if saved_draft else None,
        "is_saved": bool(saved_draft),
        "defect_fields": result.get("defect_fields", []),
    }


class NotificationSendPayload(BaseModel):
    actually_send: bool = False
    save_locally: bool = True
    subject: str | None = None
    body: str | None = None


@app.post("/email/{email_id}/notification/send")
def trigger_notification_action(
    email_id: str,
    payload: NotificationSendPayload = None,
    data_dir: str = DATA_DIR,
):
    """
    Process notification action for a mismatch email.
    
    SAFETY RAILS:
    1. By default, actually_send=False (saves draft locally to testing_generated_emails/).
    2. Actual email sending is structurally blocked by notification.send_mismatch_email()
       unless the environment variable BOB_ALLOW_REAL_SEND=true is explicitly configured.
    """
    if payload is None:
        payload = NotificationSendPayload()

    inbox, email, result, si_fields, bl_fields = _get_email_and_fields(email_id, data_dir)

    if result.get("status") != "MISMATCH":
        raise HTTPException(
            status_code=400,
            detail=f"Email {email_id} has status {result.get('status')}. Notifications are only generated for MISMATCH.",
        )

    subject = payload.subject.strip() if payload.subject is not None else None
    body = payload.body.strip() if payload.body is not None else None
    if subject is not None and (not subject or len(subject) > 300 or "\n" in subject or "\r" in subject):
        raise HTTPException(status_code=422, detail="Draft subject must be 1-300 characters with no line breaks")
    if body is not None and (not body or len(body) > 20000):
        raise HTTPException(status_code=422, detail="Draft body must be 1-20000 characters")

    response = process_mismatch_notification(
        auto_email_enabled=True,
        email_id=email_id,
        email_data=email,
        result=result,
        si_fields=si_fields,
        bl_fields=bl_fields,
        local_check=payload.save_locally,
        actually_send=payload.actually_send,
        draft_overrides={"subject": subject, "body": body},
    )
    if payload.save_locally and response.get("local_check", {}).get("saved"):
        saved_draft = operator_state.save_draft(
            email_id=email_id,
            recipient=response["recipient"],
            subject=response["subject"],
            body=response["body"],
        )
        response["draft"] = saved_draft
        response["activity"] = operator_state.get_with_events(email_id)
    return response


@app.get("/email/{email_id}/security")
def get_email_security_audit(email_id: str, data_dir: str = DATA_DIR):
    """
    Enterprise Zero-Trust Security & Compliance Audit for a specific email.
    Evaluates:
    - Attachment magic bytes & anti-spoofing verification
    - Zip-bomb and malicious executable detection
    - Adversarial prompt injection scans
    - PII & financial data redaction audit
    - SHA-256 cryptographic provenance fingerprints
    """
    inbox = Inbox(data_dir)
    audit = scan_email_security(inbox, email_id)
    if "error" in audit:
        raise HTTPException(status_code=404, detail=audit["error"])
    return audit


class SecurityScanTextPayload(BaseModel):
    text: str


@app.post("/security/scan-text")
def scan_text_security(payload: SecurityScanTextPayload):
    """
    Scan arbitrary text or document extract for prompt injection threats and PII.
    Returns prompt injection threat level and sanitized PII-masked text.
    """
    injection_report = PromptInjectionGuard.scan_text(payload.text)
    redacted_text, pii_stats = PIIRedactor.redact(payload.text)
    return {
        "is_safe": injection_report["is_safe"],
        "threat_level": injection_report["threat_level"],
        "matched_threats": injection_report["matched_patterns"],
        "pii_redacted_count": pii_stats["total_redactions"],
        "pii_breakdown": pii_stats["by_type"],
        "sanitized_text": redacted_text,
    }


class AssistantQueryPayload(BaseModel):
    query: str
    selected_email_id: str | None = None
    timezone_offset_minutes: int = 0


@app.post("/assistant/query")
def query_workspace_assistant(payload: AssistantQueryPayload, data_dir: str = DATA_DIR):
    """Interpret a question and execute an allowlisted, read-only dataset query."""
    query = payload.query.strip()
    if not query or len(query) > 2000:
        raise HTTPException(status_code=422, detail="Assistant query must be 1-2000 characters")
    if not -840 <= payload.timezone_offset_minutes <= 840:
        raise HTTPException(status_code=422, detail="Invalid timezone offset")

    submission = _get_submission()
    if not submission:
        raise HTTPException(status_code=404, detail="No submission data available")
    operator_state.ensure_emails(submission.keys(), processed_at=_submission_processed_at())
    emails = postgres_store.list_emails() if postgres_store else []
    if set(item.get("email_id") for item in emails) != set(submission):
        try:
            emails = Inbox(data_dir).emails()
        except Exception as exc:
            logger.warning("Assistant could not load full email index: %s", exc)
            emails = [{"email_id": email_id} for email_id in submission]

    return run_assistant_query(
        query=query,
        submission=submission,
        metadata=operator_state.list_all(),
        emails=emails,
        selected_email_id=payload.selected_email_id,
        timezone_offset_minutes=payload.timezone_offset_minutes,
    )


@app.get("/stats")
def get_stats():
    """Return aggregated metrics across the submission."""
    sub = _get_submission()
    if not sub:
        raise HTTPException(status_code=404, detail="No submission data available")

    categories = {}
    statuses = {}
    review_reasons = {}
    defect_fields = {}
    total_defects = 0

    for eid, item in sub.items():
        cat = item.get("category", "UNKNOWN")
        categories[cat] = categories.get(cat, 0) + 1

        st = item.get("status", "UNKNOWN")
        statuses[st] = statuses.get(st, 0) + 1

        rr = item.get("review_reason")
        if rr:
            review_reasons[rr] = review_reasons.get(rr, 0) + 1

        if item.get("has_defect"):
            total_defects += 1
            for f in item.get("defect_fields", []):
                defect_fields[f] = defect_fields.get(f, 0) + 1

    return {
        "total_emails": len(sub),
        "categories": categories,
        "statuses": statuses,
        "review_reasons": review_reasons,
        "total_defects": total_defects,
        "defect_fields_breakdown": defect_fields,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="127.0.0.1", port=8080, reload=True)
