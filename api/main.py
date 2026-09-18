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
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from pipeline.runner import run_pipeline, process_email
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


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
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

