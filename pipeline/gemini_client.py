"""
pipeline/gemini_client.py — Resilient multi-key Gemini client pool with automatic rotation and cooldown.

Provides a unified interface for all Gemini API calls across the pipeline:
- Auto-loads GEMINI_API_KEYS (comma-separated) with fallback to GEMINI_API_KEY.
- Thread-safe key rotation on 429 (Resource Exhausted / Rate Limit) errors.
- Lock is ONLY held during index lookup/rotation (<1ms) — NEVER during network calls.
- Strictly bounded cooldown: up to 2 cooldown cycles (~40s total), then raises RuntimeError.
- Configurable default model: defaults to gemini-3.5-flash-lite (with GEMINI_MODEL override).
- Clean fallback to caller's rules/dictionary when quota is genuinely exhausted.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Constants for retry, backoff, and model
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
DEFAULT_KEY_BACKOFF_SECONDS = 1.0
DEFAULT_COOLDOWN_SECONDS = 20.0
MAX_COOLDOWN_CYCLES = 2  # Exactly 2 cooldown cycles (~40s total) before raising RuntimeError
DEFAULT_RPM_PER_KEY = float(os.environ.get("GEMINI_RPM_PER_KEY", "15"))


class TokenBucketRateLimiter:
    """
    Thread-safe token bucket rate limiter to throttle API requests.
    Enforces target RPM bounded by (number of keys * RPM per key).
    """

    def __init__(self, target_rpm: float = DEFAULT_RPM_PER_KEY):
        self.target_rpm = max(1.0, float(target_rpm))
        self.capacity = max(1.0, float(target_rpm))
        self.tokens = self.capacity
        self.fill_rate = self.target_rpm / 60.0  # tokens added per second
        self.last_update = time.monotonic()
        self._lock = threading.Lock()

    def update_rate(self, new_rpm: float) -> None:
        """Update rate dynamically when pool size changes."""
        with self._lock:
            self.target_rpm = max(1.0, float(new_rpm))
            self.capacity = max(1.0, float(new_rpm))
            self.fill_rate = self.target_rpm / 60.0

    def acquire(self) -> None:
        """Acquire 1 token, waiting if bucket is temporarily depleted."""
        while True:
            wait_time = 0.0
            with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.last_update = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return

                needed = 1.0 - self.tokens
                wait_time = needed / self.fill_rate

            time.sleep(min(wait_time, 0.25))


class GeminiClientPool:
    """Thread-safe pool of Gemini clients with automatic key rotation on 429."""

    def __init__(
        self,
        key_backoff: float = DEFAULT_KEY_BACKOFF_SECONDS,
        cooldown: float = DEFAULT_COOLDOWN_SECONDS,
        max_cooldown_cycles: int = MAX_COOLDOWN_CYCLES,
        rpm_per_key: float = DEFAULT_RPM_PER_KEY,
    ):
        self.key_backoff = key_backoff
        self.cooldown = cooldown
        self.max_cooldown_cycles = max_cooldown_cycles
        self.rpm_per_key = rpm_per_key
        self.rate_limiter = TokenBucketRateLimiter(target_rpm=self.rpm_per_key)
        self._lock = threading.Lock()
        self._keys: list[str] = []
        self._clients: list[Any] = []
        self._current_index: int = 0
        self._initialized: bool = False

        # Metrics for progress visibility
        self.stats = {
            "rotations": 0,
            "cooldowns": 0,
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
        }

    def _load_keys(self) -> list[str]:
        """Extract unique keys from GEMINI_API_KEYS (plural) or GEMINI_API_KEY (singular)."""
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        raw_keys = os.environ.get("GEMINI_API_KEYS", "")
        keys: list[str] = []

        if raw_keys:
            for k in raw_keys.split(","):
                cleaned = k.strip().strip('"').strip("'")
                if cleaned and cleaned not in keys:
                    keys.append(cleaned)

        # Backward compatibility: fall back to single GEMINI_API_KEY
        if not keys:
            single = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
            if single:
                keys.append(single)

        return keys

    def _ensure_initialized(self) -> None:
        """Lazily initialize client instances for each configured key."""
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            self._keys = self._load_keys()
            if not self._keys:
                logger.warning("No Gemini API keys found in GEMINI_API_KEYS or GEMINI_API_KEY.")
                self._initialized = True
                return

            from google import genai

            self._clients = []
            for key in self._keys:
                try:
                    client = genai.Client(api_key=key)
                    self._clients.append(client)
                except Exception as e:
                    masked = self._mask_key(key)
                    logger.error(f"Failed to initialize client for key {masked}: {e}")

            target_pool_rpm = max(1.0, len(self._clients) * self.rpm_per_key)
            self.rate_limiter.update_rate(target_pool_rpm)
            logger.info(
                f"GeminiClientPool initialized with {len(self._clients)} active key(s) "
                f"(rate limiter calibrated to {target_pool_rpm:.1f} RPM)."
            )
            self._initialized = True

    @staticmethod
    def _mask_key(key: str) -> str:
        """Safely mask key for logs: e.g. AIza...4ZrQ"""
        if len(key) <= 8:
            return "***"
        return f"{key[:4]}...{key[-4:]}"

    @property
    def pool_size(self) -> int:
        self._ensure_initialized()
        return len(self._clients)

    def is_available(self) -> bool:
        """Return True if at least one client is configured."""
        self._ensure_initialized()
        return len(self._clients) > 0

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        """Check if exception represents a 429 or quota exhaustion error."""
        code = getattr(exc, "code", None)
        if code == 429:
            return True

        msg = str(exc).lower()
        return (
            "429" in msg
            or "resource_exhausted" in msg
            or "quota exceeded" in msg
            or "rate limit" in msg
        )

    def _rotate_key_if_current(self, failed_index: int, reason: str = "") -> int:
        """
        Switch to the next key in the pool (thread-safe compare-and-swap).
        Only rotates if the current active index matches failed_index, preventing
        multiple concurrent failures on the same key from skipping ahead too fast.
        """
        with self._lock:
            if self._current_index == failed_index:
                old_idx = self._current_index
                self._current_index = (self._current_index + 1) % len(self._clients)
                self.stats["rotations"] += 1
                new_idx = self._current_index

                old_masked = self._mask_key(self._keys[old_idx])
                new_masked = self._mask_key(self._keys[new_idx])
                logger.warning(
                    f"Rotated Gemini key ({old_idx + 1}/{len(self._clients)} [{old_masked}] -> "
                    f"{new_idx + 1}/{len(self._clients)} [{new_masked}]) {reason}"
                )
                return new_idx
            return self._current_index

    def generate_content(
        self,
        model: str = DEFAULT_MODEL,
        contents: Any = None,
        config: Optional[dict] = None,
    ) -> Any:
        """
        Execute generate_content with automatic key rotation on 429 errors.
        
        Concurrency guarantee:
        - The lock is ONLY acquired to read the current client / update rotation index.
        - The lock is RELEASED before the actual network call begins.
        
        Strictly bounded cooldown:
        - Cycles through all keys on 429.
        - If all keys return 429 in a cycle, enters cooldown (default 20s).
        - Maximum cooldown cycles: 2 (~40s total).
        - Raises RuntimeError immediately after max cycles so caller can fall back.
        """
        self._ensure_initialized()
        if not self._clients:
            raise RuntimeError("GEMINI_API_KEYS (or GEMINI_API_KEY) is not configured")

        with self._lock:
            self.stats["total_calls"] += 1

        pool_size = len(self._clients)
        cooldown_cycles_done = 0
        attempts_in_current_cycle = 0
        last_rate_limit_error: Optional[Exception] = None

        while True:
            # 1. Thread-safely pick the current client (LOCK RELEASED BEFORE CALL)
            with self._lock:
                idx = self._current_index
                client = self._clients[idx]
                key_masked = self._mask_key(self._keys[idx])

            # 2. Acquire token from rate limiter (outside self._lock)
            self.rate_limiter.acquire()

            # 3. Network call runs OUTSIDE the lock (enabling concurrent requests)
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                with self._lock:
                    self.stats["successful_calls"] += 1
                return response

            except Exception as e:
                if self._is_rate_limit_error(e):
                    last_rate_limit_error = e
                    attempts_in_current_cycle += 1

                    # Check if all keys in pool were tried in this cycle
                    if attempts_in_current_cycle >= pool_size:
                        cooldown_cycles_done += 1
                        if cooldown_cycles_done > self.max_cooldown_cycles:
                            # Concrete bound reached: STOP and raise
                            with self._lock:
                                self.stats["failed_calls"] += 1
                            total_wait = self.max_cooldown_cycles * self.cooldown
                            raise RuntimeError(
                                f"All {pool_size} Gemini API keys exhausted rate limits after "
                                f"{self.max_cooldown_cycles} cooldown cycles (~{total_wait:.0f}s total). "
                                f"Last error: {last_rate_limit_error}"
                            )

                        with self._lock:
                            self.stats["cooldowns"] += 1
                        logger.warning(
                            f"All {pool_size} Gemini key(s) rate-limited. "
                            f"Entering cooldown cycle {cooldown_cycles_done}/{self.max_cooldown_cycles} "
                            f"({self.cooldown:.1f}s wait)..."
                        )
                        time.sleep(self.cooldown)
                        attempts_in_current_cycle = 0
                        self._rotate_key_if_current(idx, reason=f"after cooldown {cooldown_cycles_done}")
                    else:
                        time.sleep(self.key_backoff)
                        self._rotate_key_if_current(idx, reason="due to 429 rate limit")
                    continue

                # Non-429 errors fail immediately
                with self._lock:
                    self.stats["failed_calls"] += 1
                logger.error(f"Gemini call failed on key {idx + 1}/{pool_size} [{key_masked}]: {e}")
                raise


# Global singleton instance
_global_pool = GeminiClientPool()


def get_gemini_pool() -> GeminiClientPool:
    """Return the shared GeminiClientPool singleton."""
    return _global_pool


def generate_content(
    model: str = DEFAULT_MODEL,
    contents: Any = None,
    config: Optional[dict] = None,
) -> Any:
    """
    Convenience function: Drop-in replacement for client.models.generate_content.
    Calls the shared pool with automatic key rotation and bounded cooldown.
    """
    return _global_pool.generate_content(model=model, contents=contents, config=config)
