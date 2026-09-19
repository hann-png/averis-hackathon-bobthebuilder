"""
main.py — FastAPI service for the Shipping Document Verification pipeline.

Endpoints:
  GET  /health            - Health check
  POST /process           - Runs the full pipeline on data/ and returns the submission
  GET  /submission        - Returns the current/cached submission.json
  GET  /email/{email_id}  - Process or retrieve result for a specific email
  GET  /stats             - Summary statistics of classification and verification
"""

import os
import json
import logging
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
from data.loader import Inbox

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


def _get_submission() -> dict:
    if os.path.exists(SUBMISSION_FILE):
        with open(SUBMISSION_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


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
    return {"status": "ok", "service": "sdoc-verification-api", "version": "1.0.0"}



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
    return sub


@app.get("/email/{email_id}")
def get_email_result(email_id: str, data_dir: str = DATA_DIR):
    """Get the classification and comparison result for a single email."""
    # First check cached submission
    sub = _get_submission()
    if email_id in sub:
        return {"email_id": email_id, **sub[email_id], "source": "cached"}

    # Otherwise process on-demand
    try:
        inbox = Inbox(data_dir)
        email = inbox.get(email_id)
        result = process_email(inbox, email)
        clean = {k: v for k, v in result.items() if k != "decided_by"}
        return {"email_id": email_id, **clean, "source": "on-demand"}
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Email {email_id} could not be processed: {e}"
        )
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
    inbox = Inbox(data_dir)
    try:
        email = inbox.get(email_id)
    except Exception:
        email = None

    if not email:
        raise HTTPException(status_code=404, detail=f"Email {email_id} not found in inbox")

    sub = _get_submission()
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


@app.get("/email/{email_id}/notification")
def get_email_notification_draft(email_id: str, data_dir: str = DATA_DIR):
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

    return {
        "email_id": email_id,
        "status": "MISMATCH",
        "notification_eligible": True,
        "recipient": draft["to"],
        "subject": draft["subject"],
        "body": draft["body"],
        "generated_at": draft["generated_at"],
        "defect_fields": result.get("defect_fields", []),
    }


class NotificationSendPayload(BaseModel):
    actually_send: bool = False
    save_locally: bool = True


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

    response = process_mismatch_notification(
        auto_email_enabled=True,
        email_id=email_id,
        email_data=email,
        result=result,
        si_fields=si_fields,
        bl_fields=bl_fields,
        local_check=payload.save_locally,
        actually_send=payload.actually_send,
    )
    return response


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

