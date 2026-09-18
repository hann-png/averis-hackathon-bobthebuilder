"""
classifier.py — Email classifier for the Shipping Document Verification pipeline.

Sorts emails into 5 categories:
  BL_COMPARISON, SI_REQUEST, INVOICE_QUERY, GENERAL, SPAM

Strategy:
  1. Fast, high-accuracy keyword and regex rules based on logistics patterns.
  2. Fallback: Gemini API when rules are ambiguous or no rule matches.
"""

import os
import re
import json
import logging

logger = logging.getLogger(__name__)

# ── Category constants ──────────────────────────────────────────────────────
CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]

SPAM_DOMAINS = {
    "prize-claims.info",
    "webmail-verify.co",
    "track-parcel.info",
    "secure-update.net",
    "verify-account.com",
    "payment-confirm.org",
    "parcel-track.co",
    "secure-mailbox.org",
    "logistics-deals.biz",
}

SPAM_PATTERNS = [
    r"congratulations\s*!",
    r"you\s+have\s+won",
    r"gift\s+card",
    r"claim\s+now",
    r"click\s+here\s+to\s+claim",
    r"\b90%\s+off\b",
    r"undelivered\s+messages",
    r"unpaid\s+customs\s+fee",
    r"your\s+(email\s+)?address\s+has\s+been\s+selected",
    r"account\s+to\s+avoid\s+suspension",
    r"limited\s+time\s+offer",
    r"act\s+now\s+before",
    r"your\s+package\s+could\s+not\s+be\s+delivered",
    r"bitcoin\s+investment",
    r"one\s+weird\s+trick",
    r"email\s+storage\s+is\s+full",
    r"verify\s+account\s+immediately",
    r"confirm\s+your\s+bank\s+details",
]


def classify_by_rules(email: dict) -> str | None:
    """
    Classify an email using logistics keyword/regex rules.
    Returns the category string, or None if ambiguous.
    """
    subj = email.get("subject", "")
    body = email.get("body", "")
    sender = email.get("from", "")
    combined = f"{subj} {body}"
    domain = sender.split("@")[-1].strip().lower() if "@" in sender else ""
    atts = email.get("attachments", [])

    # 1. SPAM check first
    if domain in SPAM_DOMAINS:
        return "SPAM"
    for pat in SPAM_PATTERNS:
        if re.search(pat, combined, re.I):
            return "SPAM"

    # 2. GENERAL (Internal HR notices, reports, RPA alerts, holidays, delivery planning)
    if (
        re.search(r"berthing\s+report", combined, re.I)
        or re.search(r"update\s+summary", subj, re.I)
        or re.search(r"_rpa_.*billing\s+process\s+completed", subj, re.I)
        or re.search(r"time\s+off\s+request", subj, re.I)
        or re.search(r"delivery\s+planning", subj, re.I)
        or re.search(r"submit\s+si\s*&\s*aed", subj, re.I)
        or re.search(r"wishing\s+everyone\s+a\s+happy", combined, re.I)
        or re.search(r"happy\s+.*new\s+year", combined, re.I)
        or re.search(r"sla\b.*reminder", combined, re.I)
        or re.search(r"pending\s+bl\s+release", combined, re.I)
    ):
        return "GENERAL"

    # 3. INVOICE_QUERY (Finance, charges, missing GR, billing)
    if (
        re.search(r"cancel\s+invoice", combined, re.I)
        or re.search(r"local\s+charges?", combined, re.I)
        or re.search(r"d\s*&\s*d\s+charges?", combined, re.I)
        or re.search(r"detention\s+charges?", combined, re.I)
        or re.search(r"total\s+freight", combined, re.I)
        or re.search(r"query\s+on\s+invoice", combined, re.I)
        or re.search(r"thc\s*/?\s*local\s+charge", combined, re.I)
        or re.search(r"missing\s+gr", combined, re.I)
        or re.search(r"reverse\s+the\s+pgi", combined, re.I)
    ):
        return "INVOICE_QUERY"

    # 4. SI_REQUEST (Explicit Shipping Instruction transmissions or requests)
    if (
        re.search(r"please\s+find\s+shipping\s+instruction\s+for", body, re.I)
        or re.search(r"\brequest\s+si\b", subj, re.I)
        or re.search(r"\bsi\s+needed\b", subj, re.I)
        or re.search(r"\bcust\s+si\b", subj, re.I)
        or re.search(r"^si\s*-\s*", subj, re.I)
        or re.search(r"^re_\s*si\s*-\s*", subj, re.I)
    ):
        return "SI_REQUEST"

    # 5. BL_COMPARISON (Draft BL checks, confirmations, or shipments with attachments)
    if (
        re.search(r"to\s+confirm\s+docs", subj, re.I)
        or re.search(r"request\s+bl\s+draft", subj, re.I)
        or re.search(r"draft\s+bl", subj, re.I)
        or re.search(r"\b(AFEMY|AIE|AFPTME|AFRT)\s*-\s*", subj, re.I)
        or re.search(r"please\s+compare\s+the\s+si\s+and\s+draft\s+bl", body, re.I)
        or re.search(r"attached\s+are\s+the\s+si\s+and\s+draft\s+bl", body, re.I)
        or len(atts) > 0
    ):
        return "BL_COMPARISON"

    return None


# ── Gemini fallback ─────────────────────────────────────────────────────────

_gemini_client = None


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is not set")
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def classify_by_gemini(email: dict) -> str:
    """Classify an email using Gemini API as a fallback with structured output."""
    client = _get_gemini_client()

    prompt = f"""You are classifying shipping/logistics company emails.
Classify this email into exactly ONE of these categories:
- BL_COMPARISON: Emails asking to compare/confirm SI and BL documents, or requesting/sending draft BL.
- SI_REQUEST: Emails providing or requesting a Shipping Instruction (SI).
- INVOICE_QUERY: Emails regarding invoices, billing disputes, local/D&D charges, or cancellations.
- GENERAL: Internal notifications, daily reports, HR, SLA reminders, holiday notices.
- SPAM: Unsolicited promotional, phishing, or scam emails.

Email:
From: {email.get('from', '')}
Subject: {email.get('subject', '')}
Body: {email.get('body', '')[:500]}

Respond with ONLY the category name."""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": CATEGORIES,
                    }
                },
                "required": ["category"],
            },
            "temperature": 0.0,
        },
    )

    result = json.loads(response.text)
    cat = result.get("category", "GENERAL")
    return cat if cat in CATEGORIES else "GENERAL"


# ── Public API ──────────────────────────────────────────────────────────────

def classify(email: dict) -> tuple[str, str]:
    """
    Classify an email into one of the 5 categories.
    Returns (category, decided_by) where decided_by is 'rule' or 'gemini'.
    """
    cat = classify_by_rules(email)
    if cat is not None:
        return cat, "rule"

    try:
        cat = classify_by_gemini(email)
        return cat, "gemini"
    except Exception as e:
        logger.debug(f"Gemini classification fallback not available or failed: {e}")
        return "GENERAL", "rule"
