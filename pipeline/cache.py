"""
pipeline/cache.py — Per-email persistent result cache to disk.

Saves processed email results to .cache/results/{email_id}.json immediately.
Allows pipeline runs to resume seamlessly if interrupted (crash, network drop, rate-limits),
preserving completed results and avoiding redundant API quota consumption.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import threading
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(os.environ.get("SDOC_CACHE_DIR", ".cache/results"))


def get_cached_result(
    email_id: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    force_refresh: bool = False,
) -> Optional[dict]:
    """
    Retrieve cached processing result for an email if it exists and force_refresh is False.
    Returns None if cache miss or force_refresh is True.
    """
    if force_refresh:
        return None

    cache_file = cache_dir / f"{email_id}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "category" in data and "status" in data:
                    return data
        except Exception as e:
            logger.warning(f"Error reading cache for {email_id} from {cache_file}: {e}")
            return None
    return None


def set_cached_result(
    email_id: str,
    result: dict,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> None:
    """
    Immediately write an email's result to disk (.cache/results/{email_id}.json).
    Uses atomic replace to avoid partial writes.
    """
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{email_id}.json"
        temp_file = cache_dir / f"{email_id}.tmp.{os.getpid()}.{threading.get_ident()}"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        temp_file.replace(cache_file)
    except Exception as e:
        logger.warning(f"Failed to write cache for {email_id}: {e}")


def clear_cache(cache_dir: Path = DEFAULT_CACHE_DIR) -> int:
    """Remove all cached result files. Returns number of removed files."""
    if not cache_dir.exists():
        return 0
    count = 0
    for f in cache_dir.glob("*.json"):
        try:
            f.unlink()
            count += 1
        except Exception:
            pass
    return count


def count_cached_results(cache_dir: Path = DEFAULT_CACHE_DIR) -> int:
    """Return count of valid cached result files."""
    if not cache_dir.exists():
        return 0
    return len(list(cache_dir.glob("*.json")))
