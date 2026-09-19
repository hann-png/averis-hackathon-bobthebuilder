"""
runner.py — Pipeline orchestrator.

Ties together: classifier → extractor → escalation → comparator
to produce a complete submission dict for all emails.
"""

import json
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.classifier import classify
from pipeline.extractor_text import extract_text, ExtractionResult
from pipeline.extractor_docs import extract_document
from pipeline.comparator import compare
from pipeline.escalation import check_escalation, check_missing_attachment, EscalationResult

logger = logging.getLogger(__name__)


def _identify_attachment(path: str) -> str | None:
    """Identify whether an attachment is SI or BL from its filename."""
    basename = os.path.basename(path).upper()
    if "_SI." in basename or "_SI_" in basename:
        return "SI"
    if "_BL." in basename or "_BL_" in basename:
        return "BL"
    return None


def _extract_attachment(inbox, att_path: str, expected_type: str = None) -> ExtractionResult:
    """
    Extract fields from an attachment using inbox.read_bytes() or inbox.read_text().
    Works with both local directory and HTTP server Inbox instances.
    """
    ext = os.path.splitext(att_path)[-1].lower()
    if ext == ".txt":
        text = inbox.read_text(att_path)
        return extract_text(text, expected_type)
    else:
        file_bytes = inbox.read_bytes(att_path)
        return extract_document(file_bytes, filename=att_path)


def _make_default_result(category: str, decided_by: str) -> dict:
    """Default result for non-BL_COMPARISON categories."""
    return {
        "category": category,
        "status": "OK",
        "review_reason": None,
        "has_defect": False,
        "defect_fields": [],
        "decided_by": decided_by,
    }


def process_email(inbox, email: dict) -> dict:
    """
    Process a single email through the complete pipeline.
    Returns a result dict conforming to the submission schema.
    """
    email_id = email.get("email_id", "")

    # 1. Classify
    category, decided_by = classify(email)

    if category != "BL_COMPARISON":
        return _make_default_result(category, decided_by)

    # 2. Check missing attachments
    attachments = email.get("attachments", [])
    esc_att = check_missing_attachment(email)
    if esc_att and esc_att.needs_review:
        return {
            "category": "BL_COMPARISON",
            "status": "NEEDS_REVIEW",
            "review_reason": esc_att.review_reason,
            "has_defect": False,
            "defect_fields": [],
            "decided_by": decided_by,
        }

    if len(attachments) < 2:
        # Standard draft BL request without comparison requirement
        return {
            "category": "BL_COMPARISON",
            "status": "OK",
            "review_reason": None,
            "has_defect": False,
            "defect_fields": [],
            "decided_by": decided_by,
        }

    # 3. Identify SI and BL attachments
    si_path = None
    bl_path = None
    for att in attachments:
        role = _identify_attachment(att)
        if role == "SI" and not si_path:
            si_path = att
        elif role == "BL" and not bl_path:
            bl_path = att

    # Fallback if names don't have _SI / _BL
    if not si_path and len(attachments) >= 1:
        si_path = attachments[0]
    if not bl_path and len(attachments) >= 2:
        bl_path = attachments[1]

    # Extract documents
    si_result = None
    bl_result = None

    if si_path:
        try:
            si_result = _extract_attachment(inbox, si_path, "SI")
        except Exception as e:
            logger.info(f"Failed to read SI {si_path}: {e}")
            si_result = ExtractionResult(fields={}, doc_type=None, is_readable=False)

    if bl_path:
        try:
            bl_result = _extract_attachment(inbox, bl_path, "BL")
        except Exception as e:
            logger.info(f"Failed to read BL {bl_path}: {e}")
            bl_result = ExtractionResult(fields={}, doc_type=None, is_readable=False)

    # 4. Check Escalation (wrong_doc_type, unreadable, missing_value)
    esc = check_escalation(email, si_result, bl_result)
    if esc.needs_review:
        return {
            "category": "BL_COMPARISON",
            "status": "NEEDS_REVIEW",
            "review_reason": esc.review_reason,
            "has_defect": False,
            "defect_fields": [],
            "decided_by": decided_by,
        }

    # 5. Compare documents
    si_fields = si_result.fields if si_result else {}
    bl_fields = bl_result.fields if bl_result else {}
    defect_fields = compare(si_fields, bl_fields)

    has_defect = len(defect_fields) > 0
    status = "MISMATCH" if has_defect else "OK"

    return {
        "category": "BL_COMPARISON",
        "status": status,
        "review_reason": None,
        "has_defect": has_defect,
        "defect_fields": defect_fields,
        "decided_by": decided_by,
    }


def run_pipeline(data_dir: str = "data") -> dict:
    """
    Run the pipeline on all emails in the inbox.
    Returns the complete submission dict keyed by email_id.
    """
    # Import Inbox
    try:
        from data.loader import Inbox
    except ImportError:
        sys.path.insert(0, data_dir)
        from loader import Inbox

    inbox = Inbox(data_dir)
    emails = inbox.emails()
    logger.info(f"Loaded {len(emails)} emails from {data_dir}")

    submission = {}
    stats = {"total": 0, "by_category": {}, "by_status": {}, "by_review_reason": {}}

    for email in emails:
        email_id = email["email_id"]
        result = process_email(inbox, email)
        submission[email_id] = {k: v for k, v in result.items() if k != 'decided_by'}

        stats["total"] += 1
        cat = result["category"]
        stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1
        st = result["status"]
        stats["by_status"][st] = stats["by_status"].get(st, 0) + 1
        rn = result.get("review_reason")
        if rn:
            stats["by_review_reason"][rn] = stats["by_review_reason"].get(rn, 0) + 1

    logger.info(f"\n{'='*60}")
    logger.info(f"Pipeline complete: {stats['total']} emails processed")
    logger.info(f"Categories: {stats['by_category']}")
    logger.info(f"Statuses: {stats['by_status']}")
    logger.info(f"Review reasons: {stats['by_review_reason']}")

    return submission
