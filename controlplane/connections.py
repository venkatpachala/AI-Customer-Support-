"""Connection cards. Secrets stay in the row. Screens show last4."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select

from controlplane.mode import current_tools_mode
from db.models import ConnectionRow
from db.session import SessionLocal

PROVIDERS = ("shopify", "stripe", "gmail", "whatsapp")


def list_cards(tenant_id: str, *, sandbox_passed: bool, session_factory=SessionLocal) -> list[dict]:
    stored = {row.provider: row for row in _rows(tenant_id, session_factory)}
    cards = []
    for provider in PROVIDERS:
        row = stored.get(provider)
        if provider == "whatsapp":
            badge = "Disabled"
            detail = "This channel is not available."
        elif row is None or not row.token_last4:
            badge = "not connected"
            detail = "No credential stored."
        else:
            badge = "sandbox" if current_tools_mode() != "live" else "saved"
            detail = "Credential stored. The full token is not shown."
        cards.append(
            {
                "provider": provider,
                "badge": badge,
                "detail": detail,
                "shop_domain": None if row is None else row.shop_domain,
                "token_last4": None if row is None else row.token_last4,
                "live_toggle": "Available after sandbox pass" if not sandbox_passed else "Live charges are not enabled",
            }
        )
    return cards


def save_connection(
    tenant_id: str,
    provider: str,
    *,
    shop_domain: str,
    token: str,
    session_factory=SessionLocal,
) -> Dict[str, Any]:
    if provider not in {"shopify", "stripe", "gmail"}:
        raise ValueError("that connection cannot be saved")
    secret = (token or "").strip()
    domain = (shop_domain or "").strip()
    if provider == "shopify" and not domain:
        raise ValueError("shop domain is required")
    if not secret:
        raise ValueError("token is required")
    last4 = secret[-4:]
    with session_factory() as db:
        row = db.execute(
            select(ConnectionRow)
            .where(ConnectionRow.tenant_id == tenant_id)
            .where(ConnectionRow.provider == provider)
        ).scalars().first()
        if row is None:
            row = ConnectionRow(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                provider=provider,
            )
            db.add(row)
        row.shop_domain = domain or None
        row.token_last4 = last4
        row.secret_value = secret
        row.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(row)
        return {
            "provider": row.provider,
            "shop_domain": row.shop_domain,
            "token_last4": row.token_last4,
        }


def mock_health(provider: str) -> Dict[str, Any]:
    if provider == "whatsapp":
        return {"ok": False, "badge": "Disabled", "detail": "WhatsApp is disabled"}
    if current_tools_mode() == "live":
        return {"ok": False, "badge": "not connected", "detail": "Live checks are not enabled"}
    return {"ok": True, "badge": "sandbox", "detail": "Mock health check passed"}


def _rows(tenant_id: str, session_factory) -> list[ConnectionRow]:
    with session_factory() as db:
        rows = db.execute(
            select(ConnectionRow).where(ConnectionRow.tenant_id == tenant_id)
        ).scalars().all()
        for row in rows:
            db.expunge(row)
        return rows
