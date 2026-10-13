"""Signup and login limits. Repeated failures lock the email."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

_WINDOW = 3600.0
_SIGNUP_LIMIT = 30
_LOGIN_LIMIT = 20
_LOCK_AFTER = 8
_LOCK_SECONDS = 15 * 60
_failures: Dict[str, Deque[float]] = defaultdict(deque)
_locked_until: Dict[str, float] = {}
_signup_hits: Dict[str, Deque[float]] = defaultdict(deque)


def reset_auth_limits() -> None:
    _failures.clear()
    _locked_until.clear()
    _signup_hits.clear()


def _prune(bucket: Deque[float], now: float, window: float) -> None:
    while bucket and now - bucket[0] >= window:
        bucket.popleft()


def signup_allowed(ip: str, *, now: float | None = None) -> Tuple[bool, str]:
    current = time.time() if now is None else now
    bucket = _signup_hits[ip or "unknown"]
    _prune(bucket, current, _WINDOW)
    if len(bucket) >= _SIGNUP_LIMIT:
        return False, "Too many signups from this network. Try again later."
    bucket.append(current)
    return True, ""


def login_allowed(email: str, *, now: float | None = None) -> Tuple[bool, str]:
    current = time.time() if now is None else now
    key = (email or "").strip().lower()
    until = _locked_until.get(key, 0.0)
    if until > current:
        return False, "This account is locked after repeated failures. Try again later."
    bucket = _failures[key]
    _prune(bucket, current, _LOCK_SECONDS)
    if len(bucket) >= _LOGIN_LIMIT:
        return False, "Too many login attempts. Try again later."
    return True, ""


def note_login_failure(email: str, *, now: float | None = None) -> None:
    current = time.time() if now is None else now
    key = (email or "").strip().lower()
    bucket = _failures[key]
    _prune(bucket, current, _LOCK_SECONDS)
    bucket.append(current)
    if len(bucket) >= _LOCK_AFTER:
        _locked_until[key] = current + _LOCK_SECONDS


def note_login_success(email: str) -> None:
    key = (email or "").strip().lower()
    _failures.pop(key, None)
    _locked_until.pop(key, None)
