"""Tenant credentials for tool calls. A chat body cannot supply a token."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from sqlalchemy import select

from controlplane.vault import open_seal
from db.models import ConnectionRow
from db.session import SessionLocal

_DROP = {
    "token",
    "api_key",
    "access_token",
    "secret",
    "stripe_secret",
    "stripe_key",
    "authorization",
    "password",
    "shopify_token",
    "gmail_token",
}


def scrub_tool_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Drop anything that looks like a credential. Keep the idempotency key."""
    clean: Dict[str, Any] = {}
    for key, value in dict(params or {}).items():
        lowered = str(key).lower()
        if lowered == "idempotency_key":
            clean[key] = value
            continue
        if lowered in _DROP or lowered.endswith("_token") or lowered.endswith("_secret"):
            continue
        clean[key] = value
    return clean


def credential_for(tenant_id: str, provider: str, session_factory=SessionLocal) -> Optional[str]:
    tenant = (tenant_id or "").strip()
    if not tenant:
        return None
    with session_factory() as db:
        row = db.execute(
            select(ConnectionRow)
            .where(ConnectionRow.tenant_id == tenant)
            .where(ConnectionRow.provider == provider)
        ).scalars().first()
        stored = None if row is None else row.secret_value
    if not stored:
        return None
    try:
        opened = open_seal(stored).strip()
    except ValueError:
        return None
    return opened or None


def shopify_for_tenant(tenant_id: str, session_factory=SessionLocal) -> Optional[Dict[str, str]]:
    token = credential_for(tenant_id, "shopify", session_factory=session_factory)
    if not token:
        return None
    with session_factory() as db:
        row = db.execute(
            select(ConnectionRow)
            .where(ConnectionRow.tenant_id == tenant_id)
            .where(ConnectionRow.provider == "shopify")
        ).scalars().first()
        domain = "" if row is None else (row.shop_domain or "")
    domain = domain.strip()
    if not domain:
        return None
    return {"token": token, "domain": domain}


def resolve_stripe_secret(tenant_id: str, session_factory=SessionLocal) -> str:
    stored = credential_for(tenant_id, "stripe", session_factory=session_factory)
    if stored:
        return stored
    from controlplane.settings import production
    if production():
        return ""
    return os.getenv("STRIPE_SECRET_KEY", "").strip()


def resolve_gmail_token(tenant_id: str, session_factory=SessionLocal) -> str:
    stored = credential_for(tenant_id, "gmail", session_factory=session_factory)
    if stored:
        return stored
    from controlplane.settings import production
    if production():
        return ""
    return os.getenv("GMAIL_REFRESH_TOKEN", "").strip()
