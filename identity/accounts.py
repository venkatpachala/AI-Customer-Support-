"""Brand signup. One email owns one tenant. The password is stored as a hash."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid

from sqlalchemy import select

from controlplane.keys import ensure_tenant, issue_key
from db.models import OwnerAccountRow
from db.session import SessionLocal

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str, salt: str | None = None) -> str:
    material = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        (password or "").encode("utf-8"),
        material.encode("utf-8"),
        120_000,
    ).hex()
    return f"pbkdf2${material}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = (stored or "").split("$", 2)
    except ValueError:
        return False
    if scheme != "pbkdf2" or not salt or not digest:
        return False
    return hmac.compare_digest(hash_password(password, salt), f"pbkdf2${salt}${digest}")


def signup(email: str, password: str, session_factory=SessionLocal) -> dict:
    cleaned = (email or "").strip().lower()
    if not _EMAIL.match(cleaned):
        raise ValueError("Enter a valid email")
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters")
    with session_factory() as db:
        existing = db.execute(
            select(OwnerAccountRow).where(OwnerAccountRow.email == cleaned)
        ).scalar_one_or_none()
        if existing is not None:
            raise ValueError("An account with that email already exists")
    local = re.sub(r"[^a-z0-9]", "", cleaned.split("@", 1)[0])[:16] or "brand"
    tenant_id = f"{local}{secrets.token_hex(3)}"
    ensure_tenant(tenant_id, cleaned.split("@", 1)[0], session_factory=session_factory)
    _widget, widget_key = issue_key(tenant_id, role="widget", mode="test", session_factory=session_factory)
    _supervisor, supervisor_key = issue_key(
        tenant_id, role="supervisor", mode="test", session_factory=session_factory
    )
    with session_factory() as db:
        db.add(
            OwnerAccountRow(
                id=str(uuid.uuid4()),
                email=cleaned,
                password_hash=hash_password(password),
                tenant_id=tenant_id,
            )
        )
        db.commit()
    return {
        "email": cleaned,
        "tenant_id": tenant_id,
        "widget_key": widget_key,
        "supervisor_key": supervisor_key,
    }


def tenant_for_credentials(email: str, password: str, session_factory=SessionLocal) -> str | None:
    cleaned = (email or "").strip().lower()
    with session_factory() as db:
        row = db.execute(
            select(OwnerAccountRow).where(OwnerAccountRow.email == cleaned)
        ).scalar_one_or_none()
        if row is not None:
            if verify_password(password, row.password_hash):
                return row.tenant_id
            return None
    from identity.owner_session import credentials_match

    if credentials_match(cleaned, password):
        return "zepto"
    return None
