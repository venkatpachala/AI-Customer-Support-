"""Connection cards. Secrets stay in the row. Screens show last4."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select

from controlplane.mode import current_tools_mode
from controlplane.vault import open_seal, seal
from db.models import ConnectionRow, TenantAccountRow
from db.session import SessionLocal

PROVIDERS = ("shopify", "stripe", "gmail", "whatsapp")


def list_cards(
    tenant_id: str,
    *,
    sandbox_passed: bool,
    live_enabled: bool = False,
    session_factory=SessionLocal,
) -> list[dict]:
    stored = {row.provider: row for row in _rows(tenant_id, session_factory)}
    if live_enabled:
        toggle = "Live tools are on for this tenant. Refunds still wait for approval."
    elif not sandbox_passed:
        toggle = "Available after sandbox pass"
    else:
        toggle = "Live tools stay off until an admin enables this tenant"
    cards = []
    for provider in PROVIDERS:
        row = stored.get(provider)
        if provider == "whatsapp":
            badge = "Disabled"
            detail = "WhatsApp is not built. There is no save button."
        elif row is None or not row.token_last4:
            badge = "not connected"
            detail = "No credential stored."
        else:
            badge = "live" if live_enabled else "saved"
            detail = "Credential stored. The page shows the last four characters."
        cards.append(
            {
                "provider": provider,
                "badge": badge,
                "detail": detail,
                "shop_domain": None if row is None else row.shop_domain,
                "token_last4": None if row is None else row.token_last4,
                "live_toggle": toggle,
                "can_save": provider != "whatsapp",
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
    if provider == "shopify":
        import re
        domain = domain.removeprefix("https://").rstrip("/").lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", domain):
            raise ValueError("use the store's canonical .myshopify.com domain")
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
        row.secret_value = seal(secret)
        row.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(row)
        return {
            "provider": row.provider,
            "shop_domain": row.shop_domain,
            "token_last4": row.token_last4,
        }


def mock_health(provider: str) -> Dict[str, Any]:
    """Backward-compatible name. The check reads the stored credential and does not print it."""
    return probe_connection("", provider)


def probe_connection(tenant_id: str, provider: str, session_factory=SessionLocal) -> Dict[str, Any]:
    if provider == "whatsapp":
        return {"ok": False, "badge": "Disabled", "detail": "WhatsApp is disabled"}
    if provider not in {"shopify", "stripe", "gmail"}:
        return {"ok": False, "badge": "Disabled", "detail": "That connection cannot be tested"}
    with session_factory() as db:
        row = db.execute(
            select(ConnectionRow)
            .where(ConnectionRow.tenant_id == tenant_id)
            .where(ConnectionRow.provider == provider)
        ).scalars().first()
        sealed = None if row is None else row.secret_value
        last4 = None if row is None else row.token_last4
        domain = None if row is None else row.shop_domain
    if not sealed:
        return {"ok": False, "badge": "not connected", "detail": "No credential stored"}
    try:
        secret = open_seal(sealed)
    except ValueError:
        return {"ok": False, "badge": "error", "detail": "Stored credential could not be opened"}
    if not secret or (last4 and not secret.endswith(last4)):
        return {"ok": False, "badge": "error", "detail": "Stored credential does not match the last four"}
    if provider == "shopify" and not domain:
        return {"ok": False, "badge": "error", "detail": "Shop domain is missing"}
    mode = "live" if _tenant_live(tenant_id, session_factory) else "test"
    return {
        "ok": True,
        "badge": mode,
        "detail": f"Credential stored for {mode} mode. The full token is not shown.",
    }


def _tenant_live(tenant_id: str, session_factory) -> bool:
    if current_tools_mode() != "live":
        with session_factory() as db:
            row = db.get(TenantAccountRow, tenant_id) if tenant_id else None
            return bool(row and row.live_enabled_at and row.sandbox_passed_at)
    return True


def _rows(tenant_id: str, session_factory) -> list[ConnectionRow]:
    with session_factory() as db:
        rows = db.execute(
            select(ConnectionRow).where(ConnectionRow.tenant_id == tenant_id)
        ).scalars().all()
        for row in rows:
            db.expunge(row)
        return rows
