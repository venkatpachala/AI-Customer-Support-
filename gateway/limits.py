"""Chat rate limits. A 429 returns before a workflow starts."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict

_WINDOW = 60.0
_SESSION_LIMIT = 20
_IP_LIMIT = 60
_hits: Dict[str, Deque[float]] = defaultdict(deque)


def _allow(key: str, limit: int, now: float) -> bool:
    bucket = _hits[key]
    while bucket and now - bucket[0] >= _WINDOW:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


def allow_chat(session_id: str, ip: str, *, now: float | None = None) -> bool:
    current = time.monotonic() if now is None else now
    session_ok = _allow(f"session:{session_id}", _SESSION_LIMIT, current)
    ip_ok = _allow(f"ip:{ip}", _IP_LIMIT, current)
    if session_ok and ip_ok:
        return True
    return False


def reset_limits() -> None:
    _hits.clear()
