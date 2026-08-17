"""In-memory fixed-window rate limiter (design-log.md Section 8, brownfield
scenario 2/2). Scoped to POST /api/links only — link creation is the
resource-consuming, abuse-prone operation; redirects need to stay fast and
always-available, so they are deliberately NOT rate-limited here.

In-memory + per-process: state does not survive a restart and is NOT shared
across multiple app instances behind a load balancer (design-log.md Section
9) — acceptable for a single-process prototype, called out explicitly as a
limitation rather than silently assumed away.
"""
from __future__ import annotations

import os
import threading
import time

DEFAULT_MAX_REQUESTS = 10
DEFAULT_WINDOW_SECONDS = 60.0


def _max_requests() -> int:
    return int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", DEFAULT_MAX_REQUESTS))


def _window_seconds() -> float:
    return float(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS))


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"rate limit exceeded, retry after {retry_after:.1f}s")


_lock = threading.Lock()
_windows: dict[str, tuple[float, int]] = {}  # client_key -> (window_start, count)


def reset() -> None:
    """Test-only hook to clear all rate-limit state between test cases —
    this module's state is process-global, so without an explicit reset
    one test's requests would count against the next test's limit."""
    with _lock:
        _windows.clear()


def check(client_key: str) -> None:
    """Raises RateLimitExceeded if client_key has exceeded the limit within
    the current fixed window; otherwise records this request and returns."""
    max_requests = _max_requests()
    window_seconds = _window_seconds()
    now = time.monotonic()

    with _lock:
        window_start, count = _windows.get(client_key, (now, 0))
        if now - window_start >= window_seconds:
            window_start, count = now, 0  # window elapsed — start a fresh one

        count += 1
        if count > max_requests:
            retry_after = max(window_seconds - (now - window_start), 0.0)
            _windows[client_key] = (window_start, count - 1)  # don't count the rejected request
            raise RateLimitExceeded(retry_after)

        _windows[client_key] = (window_start, count)
