#!/usr/bin/env python3
"""
run_pipeline.py — Main entry point for the Shipping Document Verification pipeline.

Usage:
    python run_pipeline.py                      # Process data/ folder → submission.json
    python run_pipeline.py --data path/to/data  # Custom data directory
    python run_pipeline.py --submit URL         # Also POST to scoring server

Output:
    submission.json in the current directory
"""

import argparse
import json
import logging
import os
import sys
import urllib.request

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.runner import run_pipeline


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
        datefmt="%H:%M:%S",
    )


def validate_submission(submission: dict, data_dir: str) -> bool:
    """
    Validate that the submission matches the expected shape.
    Returns True if valid.
    """
    # Load sample to get expected keys
    sample_path = os.path.join(data_dir, "sample_submission.json")
    if os.path.exists(sample_path):
        with open(sample_path) as f:
            sample = json.load(f)

        # Check all email_ids are present
        missing = set(sample.keys()) - set(submission.keys())
        extra = set(submission.keys()) - set(sample.keys())

        if missing:
            logging.error(f"Missing {len(missing)} email_ids: {sorted(missing)[:5]}...")
            return False
        if extra:
            logging.warning(f"Extra {len(extra)} email_ids (will be ignored by scorer)")

    # Check each entry has required fields
    required_fields = {"category", "status", "review_reason", "has_defect", "defect_fields"}
    valid_categories = {"BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"}
    valid_statuses = {"OK", "MISMATCH", "NEEDS_REVIEW"}
    valid_reasons = {None, "wrong_doc_type", "missing_attachment", "unreadable", "missing_value"}

    errors = 0
    for eid, entry in submission.items():
        entry_fields = set(entry.keys()) - {"decided_by"}  # decided_by is extra metadata
        missing_f = required_fields - entry_fields
        if missing_f:
            logging.error(f"{eid}: missing fields {missing_f}")
            errors += 1
            continue

        if entry["category"] not in valid_categories:
            logging.error(f"{eid}: invalid category '{entry['category']}'")
            errors += 1
        if entry["status"] not in valid_statuses:
            logging.error(f"{eid}: invalid status '{entry['status']}'")
            errors += 1
        if entry["review_reason"] not in valid_reasons:
            logging.error(f"{eid}: invalid review_reason '{entry['review_reason']}'")
            errors += 1
        if not isinstance(entry["defect_fields"], list):
            logging.error(f"{eid}: defect_fields must be a list")
            errors += 1
        if not isinstance(entry["has_defect"], bool):
            logging.error(f"{eid}: has_defect must be a bool")
            errors += 1

    if errors:
        logging.error(f"Validation found {errors} errors")
        return False

    logging.info("✓ Submission validated successfully")
    return True


def submit_to_server(submission: dict, server_url: str) -> dict | None:
    """POST the submission to the scoring server and return the scoreboard."""
    url = server_url.rstrip("/") + "/submit"
    data = json.dumps(submission).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
        return result
    except Exception as e:
        logging.error(f"Failed to submit to {url}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Shipping Document Verification Pipeline"
    )
    parser.add_argument(
        "--data", default="data",
        help="Path to the data directory (default: data)"
    )
    parser.add_argument(
        "--output", default="submission.json",
        help="Output file path (default: submission.json)"
    )
    parser.add_argument(
        "--submit", default=None,
        help="URL of the scoring server to POST results to (e.g., http://localhost:8080)"
    )
    parser.add_argument(
        "--force-refresh", action="store_true",
        help="Ignore cached results in .cache/results and reprocess all emails",
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=None,
        help="Number of concurrent workers (default: auto-calibrated based on API key pool size)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose/debug logging"
    )
    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # ── Run the pipeline ──
    logger.info(f"Running pipeline on {args.data} (force_refresh={args.force_refresh}, workers={args.workers})")
    submission = run_pipeline(args.data, force_refresh=args.force_refresh, workers=args.workers)

    # ── Strip internal metadata before saving ──
    # The 'decided_by' field is internal; remove it from the output
    clean_submission = {}
    for eid, result in submission.items():
        clean = {k: v for k, v in result.items() if k != "decided_by"}
        clean_submission[eid] = clean

    # ── Validate ──
    valid = validate_submission(clean_submission, args.data)

    # ── Save output ──
    with open(args.output, "w") as f:
        json.dump(clean_submission, f, indent=2)
    logger.info(f"Submission saved to {args.output}")

    # ── Optional: submit to scoring server ──
    if args.submit:
        logger.info(f"Submitting to {args.submit}...")
        scoreboard = submit_to_server(clean_submission, args.submit)
        if scoreboard:
            logger.info(f"\n{'='*60}")
            logger.info("SCOREBOARD")
            logger.info(f"{'='*60}")
            logger.info(f"Evaluation Server Score: {scoreboard.get('final_score', 'N/A')}")
            s1 = scoreboard.get("stage1", {})
            logger.info(f"Stage 1 (Classification): accuracy={s1.get('accuracy', 0):.3f}, macro_f1={s1.get('macro_f1', 0):.3f}")
            s3 = scoreboard.get("stage3", {})
            logger.info(f"Stage 3 (Defect Detection): defect_f1={s3.get('defect_f1', 0):.3f}, field_f1={s3.get('field_f1', 0):.3f}")
            e2e = scoreboard.get("end_to_end", {})
            logger.info(f"End-to-End: {e2e.get('success', 0)}/{e2e.get('total', 0)} = {e2e.get('rate', 0):.3f}")
            rel = scoreboard.get("reliability", {})
            logger.info(f"Reliability: esc_recall={rel.get('escalation_recall', 0):.3f}, esc_precision={rel.get('escalation_precision', 0):.3f}")

            # Save scoreboard
            score_path = args.output.replace(".json", "_scores.json")
            with open(score_path, "w") as f:
                json.dump(scoreboard, f, indent=2)
            logger.info(f"Scoreboard saved to {score_path}")

    if not valid:
        sys.exit(1)


if __name__ == "__main__":
    main()
