"""Bounded backoff for a retryable step. Four attempts, then the run fails."""
from __future__ import annotations

# Seconds to wait after attempt 1, 2, 3, and 4.
BACKOFF_SECONDS = (1, 2, 4, 8)
MAX_ATTEMPTS = 4


def backoff_seconds(failed_attempt: int) -> int:
    """Delay after ``failed_attempt`` (1-based) before the next try."""
    index = max(0, min(int(failed_attempt), len(BACKOFF_SECONDS)) - 1)
    return BACKOFF_SECONDS[index]


def attempts_exhausted(attempt: int) -> bool:
    return int(attempt) >= MAX_ATTEMPTS
