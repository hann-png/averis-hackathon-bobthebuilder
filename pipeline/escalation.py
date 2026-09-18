"""
escalation.py — Rules-based escalation for edge cases.

NO AI calls. Pure deterministic Python.

When a document comparison cannot be completed confidently, the email
should be escalated with status=NEEDS_REVIEW and an appropriate review_reason:

  - missing_attachment:  BL_COMPARISON email asking to compare docs but missing attachments
  - wrong_doc_type:      Attachment is a commercial invoice / packing list / COO
  - unreadable:          Attachment is corrupted or image-only scanned PDF without text
  - missing_value:       A canonical field is blank/placeholder after extraction
"""

import re
import logging

from pipeline.extractor_text import ExtractionResult, CANONICAL_FIELDS

logger = logging.getLogger(__name__)

REVIEW_REASONS = [
    "wrong_doc_type",
    "missing_attachment",
    "unreadable",
    "missing_value",
]


class EscalationResult:
    """Result of the escalation check."""

    def __init__(self, needs_review: bool, review_reason: str | None = None):
        self.needs_review = needs_review
        self.review_reason = review_reason

    def __repr__(self):
        if self.needs_review:
            return f"NEEDS_REVIEW({self.review_reason})"
        return "OK"


def check_missing_attachment(email: dict) -> EscalationResult | None:
    """
    Check if a BL_COMPARISON email is missing attachments.
    Only emails that explicitly request document comparison or state documents
    are attached, but have fewer than 2 attachments, are escalated.
    """
    attachments = email.get("attachments", [])
    body = email.get("body", "")

    is_compare_req = bool(
        re.search(r"please\s+compare\s+the\s+si\s+and\s+draft\s+bl", body, re.I)
        or re.search(r"attached\s+are\s+the\s+si\s+and\s+draft\s+bl", body, re.I)
    )

    if len(attachments) < 2 and is_compare_req:
        logger.info(f"  {email.get('email_id')}: missing_attachment (requires 2, found {len(attachments)})")
        return EscalationResult(True, "missing_attachment")

    return None


def check_wrong_doc_type(email: dict,
                         si_result: ExtractionResult | None,
                         bl_result: ExtractionResult | None) -> EscalationResult | None:
    """
    Check if an attachment or email states a non-BL/SI document type
    (commercial invoice, packing list, certificate of origin).
    """
    body = email.get("body", "").lower()
    wrong_kw = ["commercial invoice", "packing list", "certificate of origin"]

    if any(k in body for k in wrong_kw):
        return EscalationResult(True, "wrong_doc_type")

    if si_result is not None and si_result.has_wrong_type:
        return EscalationResult(True, "wrong_doc_type")

    if bl_result is not None and bl_result.has_wrong_type:
        return EscalationResult(True, "wrong_doc_type")

    return None


def check_unreadable(si_result: ExtractionResult | None,
                     bl_result: ExtractionResult | None) -> EscalationResult | None:
    """
    Check if either document is unreadable (corrupt file, image-only scanned PDF).
    """
    if si_result is not None and not si_result.is_readable:
        return EscalationResult(True, "unreadable")

    if bl_result is not None and not bl_result.is_readable:
        return EscalationResult(True, "unreadable")

    return None


def check_missing_value(si_result: ExtractionResult | None,
                         bl_result: ExtractionResult | None) -> EscalationResult | None:
    """
    Check if required fields are blank/placeholder after extraction.
    """
    if si_result is not None and si_result.is_readable:
        missing = si_result.missing_fields()
        if missing:
            return EscalationResult(True, "missing_value")

    if bl_result is not None and bl_result.is_readable:
        missing = bl_result.missing_fields()
        if missing:
            return EscalationResult(True, "missing_value")

    return None


def check_escalation(
    email: dict,
    si_result: ExtractionResult | None = None,
    bl_result: ExtractionResult | None = None,
) -> EscalationResult:
    """
    Run all escalation checks in priority order:
    1. missing_attachment
    2. wrong_doc_type
    3. unreadable
    4. missing_value
    """
    res = check_missing_attachment(email)
    if res:
        return res

    res = check_wrong_doc_type(email, si_result, bl_result)
    if res:
        return res

    res = check_unreadable(si_result, bl_result)
    if res:
        return res

    res = check_missing_value(si_result, bl_result)
    if res:
        return res

    return EscalationResult(False)
