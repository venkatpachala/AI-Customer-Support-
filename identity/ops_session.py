"""Supervisor cookie. A customer session cannot mint this."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional

COOKIE_NAME = "d2c_ops"
TTL_SECONDS = 8 * 60 * 60


def _secret() -> str:
    return os.getenv("OPS_SESSION_SECRET") or os.getenv("OPS_PASSWORD") or ""


def issue_ops_token(*, now: Optional[int] = None) -> str:
    secret = _secret()
    if not secret:
        raise RuntimeError("OPS_PASSWORD is not set")
    expires = int(now or time.time()) + TTL_SECONDS
    payload = f"supervisor|{expires}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}|{signature}"


def ops_role(token: Optional[str], *, now: Optional[int] = None) -> Optional[str]:
    secret = _secret()
    if not secret or not token or token.count("|") != 2:
        return None
    role, expires, signature = token.split("|", 2)
    payload = f"{role}|{expires}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        if int(expires) <= int(now or time.time()):
            return None
    except ValueError:
        return None
    if role != "supervisor":
        return None
    return role


def credentials_match(username: str, password: str) -> bool:
    expected_user = os.getenv("OPS_USER", "")
    expected_password = os.getenv("OPS_PASSWORD", "")
    if not expected_user or not expected_password:
        return False
    user_ok = hmac.compare_digest(
        hashlib.sha256(username.encode("utf-8")).hexdigest(),
        hashlib.sha256(expected_user.encode("utf-8")).hexdigest(),
    )
    pass_ok = hmac.compare_digest(
        hashlib.sha256(password.encode("utf-8")).hexdigest(),
        hashlib.sha256(expected_password.encode("utf-8")).hexdigest(),
    )
    return user_ok and pass_ok
