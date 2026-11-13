"""Tiny in-memory fixed-window rate limiter.

JobPilot runs a single backend worker, so a dict is enough. Login attempts are
the only endpoint currently limited, to stop password brute force.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


def allow(key: str, limit: int, window_seconds: int) -> bool:
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        bucket = [stamp for stamp in _hits.get(key, []) if stamp > cutoff]
        if len(bucket) >= limit:
            _hits[key] = bucket
            return False
        bucket.append(now)
        _hits[key] = bucket
    return True


def reset(key: str) -> None:
    with _lock:
        _hits.pop(key, None)
