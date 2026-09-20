"""Safe assistant intent parsing and deterministic verification-data queries."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from pipeline.security import PIIRedactor, PromptInjectionGuard

logger = logging.getLogger(__name__)

ALLOWED_INTENTS = {
    "find_email",
    "list_status",
    "list_review_reason",
    "list_category",
    "latest_reviewed",
    "latest_opened",
    "open_draft",
    "summarize_email",
    "explain_discrepancies",
    "related_emails",
    "search",
    "overview",
    "help",
}
ALLOWED_STATUSES = {"MISMATCH", "NEEDS_REVIEW", "OK", "FLAGGED"}
ALLOWED_CATEGORIES = {"BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"}
ALLOWED_REVIEW_REASONS = {"wrong_doc_type", "missing_attachment", "unreadable", "missing_value"}

_gemini_client = None


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def _normalize_email_id(number: str) -> str:
    return f"email_{int(number):03d}"


def _rule_intent(query: str, selected_email_id: Optional[str]) -> Optional[dict]:
    """Resolve high-confidence commands without spending model quota."""
    text = query.lower().strip()
    explicit_id = re.search(r"email[\s_-]?(\d{1,4})", text)
    date_scope = (
        "24h" if re.search(r"last\s+24\s+hours?|past\s+24\s+hours?", text)
        else "7d" if re.search(r"last\s+7\s+days?|past\s+7\s+days?|this\s+week", text)
        else "today" if re.search(r"\btoday\b", text)
        else "all"
    )

    if explicit_id:
        email_id = _normalize_email_id(explicit_id.group(1))
        explicit_intent = (
            "open_draft" if re.search(r"draft|reply|response", text)
            else "explain_discrepancies" if re.search(r"explain|why|discrepanc|difference", text)
            else "summarize_email" if re.search(r"summar|overview", text)
            else "related_emails" if re.search(r"related|similar", text)
            else "find_email"
        )
        return {
            "intent": explicit_intent,
            "email_id": email_id,
            "date_scope": date_scope,
            "limit": 1,
        }
    if re.search(r"wrong\s+(document|doc)|document\s+type", text):
        return {"intent": "list_review_reason", "review_reason": "wrong_doc_type", "date_scope": date_scope, "limit": 6}
    if re.search(r"latest\s+reviewed|last\s+reviewed|recently\s+reviewed", text):
        return {"intent": "latest_reviewed", "limit": 1}
    if re.search(r"latest\s+opened|last\s+opened|recently\s+opened", text):
        return {"intent": "latest_opened", "limit": 1}
    if re.search(r"draft|reply|response", text) and selected_email_id:
        return {"intent": "open_draft", "email_id": selected_email_id, "limit": 1}
    if selected_email_id and re.search(r"^(?:please\s+)?explain\b|\b(?:this|current|selected)\s+(?:email|case)\b|\bwhy\s+is\s+(?:this|it)\b", text):
        return {"intent": "explain_discrepancies", "email_id": selected_email_id, "limit": 1}
    if re.search(r"summar", text) and selected_email_id:
        return {"intent": "summarize_email", "email_id": selected_email_id, "limit": 1}
    if re.search(r"related|similar", text) and selected_email_id:
        return {"intent": "related_emails", "email_id": selected_email_id, "sort": "relevance", "limit": 6}
    if re.search(r"review", text):
        return {"intent": "list_status", "status": "NEEDS_REVIEW", "date_scope": date_scope, "sort": "newest", "limit": 1 if re.search(r"latest|newest|most recent", text) else 6}
    if re.search(r"mismatch|discrepanc", text):
        return {"intent": "list_status", "status": "MISMATCH", "date_scope": date_scope, "sort": "newest", "limit": 6}
    if re.search(r"flagged", text):
        return {"intent": "list_status", "status": "FLAGGED", "date_scope": date_scope, "sort": "newest", "limit": 6}
    if re.search(r"clean|verified|passed", text):
        return {"intent": "list_status", "status": "OK", "date_scope": date_scope, "sort": "newest", "limit": 6}
    category_rules = [
        (r"bill of lading|bl comparison|\bbl\b", "BL_COMPARISON"),
        (r"shipping instruction|si request|\bsi\b", "SI_REQUEST"),
        (r"invoice", "INVOICE_QUERY"),
        (r"spam", "SPAM"),
        (r"general", "GENERAL"),
    ]
    for pattern, category in category_rules:
        if re.search(pattern, text):
            return {"intent": "list_category", "category": category, "date_scope": date_scope, "sort": "newest", "limit": 6}
    if re.search(r"what can you do|help|commands|examples", text):
        return {"intent": "help", "limit": 0}
    if re.search(r"overview|summary|how many emails|total emails", text):
        return {"intent": "overview", "limit": 0}
    return None


def _gemini_intent(query: str, selected_email_id: Optional[str]) -> dict:
    client = _get_gemini_client()
    redacted_query, _ = PIIRedactor.redact(query)
    prompt = f"""You interpret read-only questions for a shipping-document verification dashboard.
Return one allowed structured intent. Never calculate counts and never invent email IDs.

Allowed intents: {sorted(ALLOWED_INTENTS)}
Allowed statuses: {sorted(ALLOWED_STATUSES)}
Allowed categories: {sorted(ALLOWED_CATEGORIES)}
Allowed review reasons: {sorted(ALLOWED_REVIEW_REASONS)}
Current selected email: {selected_email_id or 'none'}

Use search for subject, sender, or free-text lookup. Use overview for general totals.
User request: {redacted_query[:1000]}"""
    response = client.models.generate_content(
        model=os.environ.get("BOB_ASSISTANT_MODEL", "gemini-2.0-flash"),
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "enum": sorted(ALLOWED_INTENTS)},
                    "status": {"type": "string"},
                    "category": {"type": "string"},
                    "review_reason": {"type": "string"},
                    "email_id": {"type": "string"},
                    "date_scope": {"type": "string", "enum": ["all", "today", "24h", "7d"]},
                    "sort": {"type": "string", "enum": ["newest", "oldest", "relevance"]},
                    "search_terms": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                },
                "required": ["intent"],
            },
            "temperature": 0.0,
        },
    )
    parsed = json.loads(response.text)
    if parsed.get("intent") not in ALLOWED_INTENTS:
        raise ValueError("Gemini returned an unsupported assistant intent")
    return parsed


def interpret_query(query: str, selected_email_id: Optional[str]) -> tuple[dict, str]:
    ruled = _rule_intent(query, selected_email_id)
    if ruled:
        return ruled, "rules"
    if os.environ.get("BOB_ASSISTANT_AI_ENABLED", "true").lower() not in {"false", "0", "no"}:
        try:
            return _gemini_intent(query, selected_email_id), "gemini"
        except Exception as exc:
            logger.warning("Gemini assistant interpretation unavailable (%s); using search fallback", exc)
    terms = re.findall(r"[a-zA-Z0-9@._-]{3,}", query.lower())
    stop_words = {"find", "show", "open", "mail", "email", "please", "about", "with", "that", "from", "have", "there", "could", "would"}
    return {"intent": "search", "search_terms": [term for term in terms if term not in stop_words], "limit": 6}, "fallback"


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _id_number(email_id: str) -> int:
    match = re.search(r"\d+", email_id)
    return int(match.group()) if match else 0


def _today_matches(value: Optional[str], timezone_offset_minutes: int) -> bool:
    timestamp = _parse_timestamp(value)
    if not timestamp:
        return False
    offset = timedelta(minutes=-timezone_offset_minutes)
    local_date = (timestamp.astimezone(timezone.utc) + offset).date()
    today = datetime.now(timezone.utc) + offset
    return local_date == today.date()


def _date_scope_matches(value: Optional[str], scope: str, timezone_offset_minutes: int) -> bool:
    if scope == "all":
        return True
    if scope == "today":
        return _today_matches(value, timezone_offset_minutes)
    timestamp = _parse_timestamp(value)
    if not timestamp:
        return False
    age = datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)
    return timedelta(0) <= age <= (timedelta(hours=24) if scope == "24h" else timedelta(days=7))


def _result_card(email_id: str, submission: dict, metadata: dict, emails_by_id: dict, tab: str = "comparison") -> dict:
    item = submission[email_id]
    email = emails_by_id.get(email_id, {})
    activity = metadata.get(email_id, {})
    return {
        "email_id": email_id,
        "status": item.get("status"),
        "category": item.get("category"),
        "subject": email.get("subject") or email_id.upper(),
        "sender": email.get("from"),
        "issue_count": len(item.get("defect_fields") or []),
        "defect_fields": item.get("defect_fields") or [],
        "review_reason": item.get("review_reason"),
        "processed_at": activity.get("processed_at"),
        "reviewed_at": activity.get("reviewed_at"),
        "last_opened_at": activity.get("last_opened_at"),
        "action": "open_draft" if tab == "draft" else "open_email",
        "tab": tab,
    }


def run_assistant_query(
    query: str,
    submission: dict,
    metadata: dict,
    emails: list[dict],
    selected_email_id: Optional[str] = None,
    timezone_offset_minutes: int = 0,
) -> dict:
    """Interpret a question, execute it deterministically, and return UI-safe cards."""
    security = PromptInjectionGuard.scan_text(query)
    if not security["is_safe"]:
        return {
            "message": "I can’t process that request because it contains instructions that conflict with the verification safety policy.",
            "metric": None,
            "results": [],
            "intent": "blocked",
            "interpreted_by": "security",
            "blocked": True,
        }

    intent, interpreted_by = interpret_query(query, selected_email_id)
    intent_name = intent.get("intent", "help")
    email_map = {email.get("email_id"): email for email in emails if email.get("email_id")}
    all_ids = list(submission)
    limit = max(0, min(int(intent.get("limit") or 6), 10))
    results: list[str] = []
    tab = "comparison"
    metric = None

    if intent_name in {"find_email", "open_draft"}:
        email_id = intent.get("email_id") or selected_email_id
        if email_id in submission:
            results = [email_id]
            tab = "draft" if intent_name == "open_draft" and submission[email_id].get("status") == "MISMATCH" else "comparison"
            message = f"{email_id.upper()} is ready. Open it to inspect the {'response draft' if tab == 'draft' else 'verification result'}."
        else:
            message = f"I couldn’t find {(email_id or 'that email').upper()} in the current dataset."
    elif intent_name in {"summarize_email", "explain_discrepancies"}:
        email_id = intent.get("email_id") or selected_email_id
        if email_id not in submission:
            message = "Select an email first so I can inspect it."
        else:
            item = submission[email_id]
            email = email_map.get(email_id, {})
            results = [email_id]
            if intent_name == "summarize_email":
                attachment_count = len(email.get("attachments") or [])
                subject = str(email.get("subject") or email_id.upper()).strip()
                sender = str(email.get("from") or "an unavailable sender").strip()
                status_label = str(item.get("status") or "unknown").replace("_", " ").lower()
                message = (
                    f"{email_id.upper()} is “{subject}” from {sender}. It is classified as "
                    f"{str(item.get('category') or 'unknown').replace('_', ' ').title()} with status "
                    f"{status_label}, and includes {attachment_count} attachment{'s' if attachment_count != 1 else ''}."
                )
            elif item.get("status") == "MISMATCH":
                fields = [str(field).replace("_", " ").title() for field in item.get("defect_fields") or []]
                field_text = ", ".join(fields) if fields else "the compared document values"
                message = f"{email_id.upper()} is mismatched because {field_text} differ between the shipping instruction and Bill of Lading. Select a field below to inspect the evidence."
            elif item.get("status") == "NEEDS_REVIEW":
                reason = str(item.get("review_reason") or "uncertain result").replace("_", " ").title()
                message = f"{email_id.upper()} requires human review because of: {reason}."
            else:
                message = f"{email_id.upper()} is verified clean; no mismatch fields were recorded."
    elif intent_name == "related_emails":
        email_id = intent.get("email_id") or selected_email_id
        if email_id not in submission:
            message = "Select an email first so I can find related cases."
        else:
            source_item = submission[email_id]
            source_email = email_map.get(email_id, {})
            source_sender = str(source_email.get("from") or "").lower()
            scored = []
            for candidate_id in all_ids:
                if candidate_id == email_id:
                    continue
                candidate = submission[candidate_id]
                candidate_email = email_map.get(candidate_id, {})
                score = int(candidate.get("category") == source_item.get("category"))
                score += 2 * int(bool(source_sender) and str(candidate_email.get("from") or "").lower() == source_sender)
                if score:
                    scored.append((candidate_id, score))
            scored.sort(key=lambda pair: (pair[1], _id_number(pair[0])), reverse=True)
            results = [candidate_id for candidate_id, _ in scored]
            message = f"I found {len(results)} emails related by sender or category to {email_id.upper()}."
            metric = {"value": len(results), "label": "Related emails"}
    elif intent_name == "latest_reviewed":
        candidates = [(email_id, activity) for email_id, activity in metadata.items() if activity.get("reviewed") and activity.get("reviewed_at") and email_id in submission]
        candidates.sort(key=lambda pair: pair[1].get("reviewed_at") or "", reverse=True)
        results = [candidates[0][0]] if candidates else []
        message = f"{results[0].upper()} is the most recently reviewed email." if results else "No reviewed email has been recorded yet."
    elif intent_name == "latest_opened":
        candidates = [(email_id, activity) for email_id, activity in metadata.items() if activity.get("last_opened_at") and email_id in submission]
        candidates.sort(key=lambda pair: pair[1].get("last_opened_at") or "", reverse=True)
        results = [candidates[0][0]] if candidates else []
        message = f"{results[0].upper()} is the most recently opened email." if results else "No opened-email activity has been recorded yet."
    elif intent_name == "list_status":
        status = intent.get("status") if intent.get("status") in ALLOWED_STATUSES else "FLAGGED"
        if status == "FLAGGED":
            results = [email_id for email_id in all_ids if submission[email_id].get("status") in {"MISMATCH", "NEEDS_REVIEW"}]
            label = "Flagged cases"
        else:
            results = [email_id for email_id in all_ids if submission[email_id].get("status") == status]
            label = {"MISMATCH": "Mismatches", "NEEDS_REVIEW": "Need review", "OK": "Verified clean"}.get(status, status.title())
        date_scope = intent.get("date_scope", "all")
        if date_scope != "all":
            results = [email_id for email_id in results if _date_scope_matches(metadata.get(email_id, {}).get("processed_at"), date_scope, timezone_offset_minutes)]
            label = f"{label} {'today' if date_scope == 'today' else 'in the last 24 hours' if date_scope == '24h' else 'in the last 7 days'}"
        metric = {"value": len(results), "label": label}
        message = f"I found {len(results)} {label.lower()}."
    elif intent_name == "list_review_reason":
        reason = intent.get("review_reason") if intent.get("review_reason") in ALLOWED_REVIEW_REASONS else "wrong_doc_type"
        results = [email_id for email_id in all_ids if submission[email_id].get("review_reason") == reason]
        date_scope = intent.get("date_scope", "all")
        if date_scope != "all":
            results = [email_id for email_id in results if _date_scope_matches(metadata.get(email_id, {}).get("processed_at"), date_scope, timezone_offset_minutes)]
        label = reason.replace("_", " ").title()
        metric = {"value": len(results), "label": label}
        message = f"I found {len(results)} emails escalated for {label.lower()}."
    elif intent_name == "list_category":
        category = intent.get("category") if intent.get("category") in ALLOWED_CATEGORIES else "GENERAL"
        results = [email_id for email_id in all_ids if submission[email_id].get("category") == category]
        date_scope = intent.get("date_scope", "all")
        if date_scope != "all":
            results = [email_id for email_id in results if _date_scope_matches(metadata.get(email_id, {}).get("processed_at"), date_scope, timezone_offset_minutes)]
        metric = {"value": len(results), "label": category.replace("_", " ").title()}
        message = f"I found {len(results)} emails classified as {metric['label']}."
    elif intent_name == "overview":
        mismatch_count = sum(1 for item in submission.values() if item.get("status") == "MISMATCH")
        review_count = sum(1 for item in submission.values() if item.get("status") == "NEEDS_REVIEW")
        message = f"The workspace contains {len(submission)} emails: {mismatch_count} mismatches and {review_count} requiring review."
        metric = {"value": len(submission), "label": "Total emails"}
    elif intent_name == "search":
        terms = [str(term).lower() for term in intent.get("search_terms") or [] if len(str(term)) >= 2]
        scored = []
        for email_id in all_ids:
            email = email_map.get(email_id, {})
            haystack = " ".join([email_id, str(email.get("subject", "")), str(email.get("from", "")), str(email.get("body", ""))]).lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((email_id, score))
        scored.sort(key=lambda pair: (pair[1], _id_number(pair[0])), reverse=True)
        results = [email_id for email_id, _ in scored]
        metric = {"value": len(results), "label": "Search results"}
        message = f"I found {len(results)} emails matching that search." if results else "I couldn’t find an email matching that search. Try a sender, subject phrase, or email ID."
    else:
        message = "I can count mismatches, show review cases, search senders and subjects, find wrong document types, open a specific email, or take you to a saved response draft."

    def sort_key(email_id: str):
        timestamp = _parse_timestamp(metadata.get(email_id, {}).get("processed_at"))
        return (timestamp or datetime.min.replace(tzinfo=timezone.utc), _id_number(email_id))

    if intent.get("sort") in {"newest", "oldest"} or intent_name in {"list_status", "list_review_reason", "list_category"}:
        results.sort(key=sort_key, reverse=intent.get("sort") != "oldest")
    cards = [_result_card(email_id, submission, metadata, email_map, tab) for email_id in results[:limit]]
    return {
        "message": message,
        "metric": metric,
        "results": cards,
        "intent": intent_name,
        "interpreted_by": interpreted_by,
        "blocked": False,
    }
