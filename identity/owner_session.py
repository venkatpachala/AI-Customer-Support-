"""Brand-owner cookie. This is not the customer d2c_session cookie."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional

COOKIE_NAME = "d2c_owner"
TTL_SECONDS = 12 * 60 * 60
OWNER_EMAIL = "ops@zepto.local"


def _secret() -> str:
    return os.getenv("OPS_SESSION_SECRET") or os.getenv("OPS_PASSWORD") or ""


def credentials_match(email: str, password: str) -> bool:
    expected_password = os.getenv("OPS_PASSWORD", "")
    if not expected_password:
        return False
    email_ok = hmac.compare_digest(
        hashlib.sha256((email or "").strip().lower().encode("utf-8")).hexdigest(),
        hashlib.sha256(OWNER_EMAIL.encode("utf-8")).hexdigest(),
    )
    pass_ok = hmac.compare_digest(
        hashlib.sha256((password or "").encode("utf-8")).hexdigest(),
        hashlib.sha256(expected_password.encode("utf-8")).hexdigest(),
    )
    return email_ok and pass_ok


def issue_owner_token(tenant_id: str = "zepto", *, now: Optional[int] = None) -> str:
    secret = _secret()
    if not secret:
        raise RuntimeError("OPS_PASSWORD is not set")
    expires = int(now or time.time()) + TTL_SECONDS
    payload = f"owner|{tenant_id}|{expires}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}|{signature}"


def read_owner(token: Optional[str], *, now: Optional[int] = None) -> Optional[str]:
    """Return the tenant id when the cookie is valid."""
    secret = _secret()
    if not secret or not token or token.count("|") != 3:
        return None
    role, tenant_id, expires, signature = token.split("|", 3)
    payload = f"{role}|{tenant_id}|{expires}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        if int(expires) <= int(now or time.time()):
            return None
    except ValueError:
        return None
    if role != "owner" or not tenant_id:
        return None
    return tenant_id
