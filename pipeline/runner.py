from __future__ import annotations

import json
import logging
import sys
import os
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.classifier import classify
from pipeline.extractor_text import extract_text, ExtractionResult
from pipeline.extractor_docs import extract_document
from pipeline.comparator import compare
from pipeline.escalation import check_escalation, check_missing_attachment, EscalationResult
from pipeline.notification import process_mismatch_notification
from pipeline.cache import get_cached_result, set_cached_result
from data.loader import Inbox

logger = logging.getLogger(__name__)


def _identify_attachment(path: str) -> str | None:
    """Identify whether an attachment is SI or BL from its filename."""
    basename = os.path.basename(path).upper()
    if "_SI." in basename or "_SI_" in basename:
        return "SI"
    if "_BL." in basename or "_BL_" in basename:
        return "BL"
    return None


def _extract_attachment(inbox, att_path: str, expected_type: Optional[str] = None) -> ExtractionResult:
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


def process_email(inbox, email: dict, force_refresh: bool = False) -> dict:
    """
    Process a single email through the complete pipeline.
    Checks and writes per-email disk cache (.cache/results/{email_id}.json) immediately.
    Returns a result dict conforming to the submission schema.
    """
    email_id = email.get("email_id", "")

    # 0. Check per-email disk cache
    if email_id and not force_refresh:
        cached = get_cached_result(email_id)
        if cached is not None:
            return cached

    def _finish(res: dict) -> dict:
        if email_id:
            set_cached_result(email_id, res)
        return res

    # 1. Classify
    category, decided_by = classify(email)

    if category != "BL_COMPARISON":
        return _finish(_make_default_result(category, decided_by))

    # 2. Check missing attachments
    attachments = email.get("attachments", [])
    esc_att = check_missing_attachment(email)
    if esc_att and esc_att.needs_review:
        return _finish({
            "category": "BL_COMPARISON",
            "status": "NEEDS_REVIEW",
            "review_reason": esc_att.review_reason,
            "has_defect": False,
            "defect_fields": [],
            "decided_by": decided_by,
        })

    if len(attachments) < 2:
        # Standard draft BL request without comparison requirement
        return _finish({
            "category": "BL_COMPARISON",
            "status": "OK",
            "review_reason": None,
            "has_defect": False,
            "defect_fields": [],
            "decided_by": decided_by,
        })

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
        return _finish({
            "category": "BL_COMPARISON",
            "status": "NEEDS_REVIEW",
            "review_reason": esc.review_reason,
            "has_defect": False,
            "defect_fields": [],
            "decided_by": decided_by,
        })

    # 5. Compare documents
    si_fields = si_result.fields if si_result else {}
    bl_fields = bl_result.fields if bl_result else {}
    defect_fields = compare(si_fields, bl_fields)

    has_defect = len(defect_fields) > 0
    status = "MISMATCH" if has_defect else "OK"

    result = {
        "category": "BL_COMPARISON",
        "status": status,
        "review_reason": None,
        "has_defect": has_defect,
        "defect_fields": defect_fields,
        "decided_by": decided_by,
    }

    # Pure side effect: generate local notification draft if auto email is enabled
    if status == "MISMATCH":
        auto_email_enabled = os.getenv("BOB_AUTO_EMAIL_ENABLED", "").strip().lower() in ("true", "1", "yes")
        if auto_email_enabled:
            try:
                process_mismatch_notification(
                    auto_email_enabled=True,
                    email_id=email_id,
                    email_data=email,
                    result=result,
                    si_fields=si_fields,
                    bl_fields=bl_fields,
                    local_check=True,
                    actually_send=False,
                )
            except Exception as e:
                logger.warning(f"Could not generate mismatch notification for {email_id}: {e}")

    return _finish(result)


def run_pipeline(
    data_dir: str = "data",
    force_refresh: bool = False,
    workers: Optional[int] = None,
) -> dict:
    """
    Run the pipeline on all emails in the inbox concurrently.
    Rate-limited by GeminiClientPool's token bucket and resilient to 429 errors.
    Returns the complete submission dict keyed by email_id.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from pipeline.gemini_client import get_gemini_pool

    inbox = Inbox(data_dir)
    emails = inbox.emails()
    total_emails = len(emails)
    logger.info(f"Loaded {total_emails} emails from {data_dir}")

    pool = get_gemini_pool()
    pool_size = max(1, pool.pool_size)

    if workers is None:
        env_workers = os.environ.get("SDOC_CONCURRENT_WORKERS")
        if env_workers:
            workers = max(1, int(env_workers))
        else:
            # Calibrated worker count: 2 workers per active key, bounded between 2 and 16
            workers = max(2, min(pool_size * 2, 16))

    logger.info(
        f"Processing {total_emails} emails with {workers} concurrent worker(s) "
        f"(active key pool: {pool_size} key(s), rate limiter: {pool.rate_limiter.target_rpm:.1f} RPM)..."
    )

    def _worker(email_data: dict) -> tuple[str, dict, bool]:
        eid = email_data["email_id"]
        from_cache = (not force_refresh) and (get_cached_result(eid) is not None)
        res = process_email(inbox, email_data, force_refresh=force_refresh)
        return eid, res, from_cache

    submission = {}
    stats = {"total": 0, "by_category": {}, "by_status": {}, "by_review_reason": {}}
    cache_hits = 0
    ai_count = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_email = {
            executor.submit(_worker, email): email["email_id"]
            for email in emails
        }

        for future in as_completed(future_to_email):
            email_id, result, from_cache = future.result()
            submission[email_id] = {k: v for k, v in result.items() if k != "decided_by"}

            if from_cache:
                cache_hits += 1
            else:
                ai_count += 1

            stats["total"] += 1
            cat = result.get("category", "GENERAL")
            stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1
            st = result.get("status", "OK")
            stats["by_status"][st] = stats["by_status"].get(st, 0) + 1
            rn = result.get("review_reason")
            if rn:
                stats["by_review_reason"][rn] = stats["by_review_reason"].get(rn, 0) + 1

            # Progress visibility (Step 4)
            done = stats["total"]
            rot = pool.stats["rotations"]
            cd = pool.stats["cooldowns"]
            if done % 10 == 0 or done == total_emails:
                cd_label = f"{cd} cooldown wait" if cd == 1 else f"{cd} cooldown waits"
                rot_label = f"{rot} key rotation" if rot == 1 else f"{rot} key rotations"
                logger.info(
                    f"Processed {done}/{total_emails} emails — "
                    f"{cache_hits} from cache, {ai_count} via AI "
                    f"({rot_label}, {cd_label})"
                )

    # Sort final submission by email_id for consistency
    sorted_submission = {
        eid: submission[eid] for eid in sorted(submission.keys())
    }

    logger.info(f"\n{'='*60}")
    logger.info(f"Pipeline complete: {stats['total']} emails processed")
    logger.info(f"Categories: {stats['by_category']}")
    logger.info(f"Statuses: {stats['by_status']}")
    logger.info(f"Review reasons: {stats['by_review_reason']}")
    logger.info(
        f"Cache stats: {cache_hits} cache hits, {ai_count} processed via AI "
        f"({pool.stats['rotations']} rotations, {pool.stats['cooldowns']} cooldowns)"
    )

    return sorted_submission
