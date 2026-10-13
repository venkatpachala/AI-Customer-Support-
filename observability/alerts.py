"""One in-process alert: error rate or latency over the last requests."""
from __future__ import annotations

import os
from collections import deque
from typing import Deque

from observability.logging import log_event

_WINDOW = 50
_events: Deque[tuple[int, float]] = deque(maxlen=_WINDOW)
_last_alert = 0.0


def observe_request(status_code: int, latency_seconds: float, *, path: str, request_id: str) -> None:
    """Log a single alert when recent traffic is mostly errors or slow."""
    global _last_alert
    failed = 1 if status_code >= 500 else 0
    _events.append((failed, latency_seconds))
    if len(_events) < 10:
        return
    errors = sum(item[0] for item in _events)
    latencies = sorted(item[1] for item in _events)
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
    slow = sum(1 for item in _events if item[1] >= 8.0)
    error_rate = errors / len(_events)
    if error_rate < 0.2 and p95 < 8.0 and slow < 5:
        return
    import time
    now = time.time()
    if now - _last_alert < 300:
        return
    _last_alert = now
    log_event(
        "alert_error_or_latency",
        request_id,
        node="gateway",
        data={
            "path": path,
            "error_rate": round(error_rate, 3),
            "slow_requests": slow,
            "window": len(_events),
            "alert_webhook": bool(os.getenv("ALERT_WEBHOOK_URL", "").strip()),
        },
        level="error",
    )
    _notify(error_rate, slow, path)


def _notify(error_rate: float, slow: int, path: str) -> None:
    url = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return
    try:
        import json
        import urllib.request
        body = json.dumps({"text": f"d2c alert error_rate={error_rate:.2f} slow={slow} path={path}"}).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(request, timeout=3).read()
    except Exception:
        return
