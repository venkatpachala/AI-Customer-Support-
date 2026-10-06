"""Tenant API keys. The bearer token is the tenant."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from db.models import ApiKeyRow, TenantAccountRow
from db.session import SessionLocal

PREFIX_TEST = "d2c_test_"
PREFIX_LIVE = "d2c_live_"


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class Principal:
    key_id: str
    tenant_id: str
    role: str
    mode: str
    prefix: str
    sandbox_passed_at: Optional[datetime]
    killed_at: Optional[datetime]

    @property
    def live_blocked(self) -> bool:
        return self.mode == "live" and self.sandbox_passed_at is None


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def ensure_tenant(tenant_id: str, name: str = "", session_factory=SessionLocal) -> TenantAccountRow:
    tenant = (tenant_id or "").strip()
    if not tenant:
        raise ValueError("tenant_id is required")
    with session_factory() as db:
        row = db.get(TenantAccountRow, tenant)
        if row is None:
            row = TenantAccountRow(id=tenant, name=name or tenant)
            db.add(row)
            db.commit()
        db.refresh(row)
        db.expunge(row)
        return row


def issue_key(
    tenant_id: str,
    *,
    role: str,
    mode: str,
    session_factory=SessionLocal,
) -> tuple[ApiKeyRow, str]:
    if role not in {"widget", "supervisor"}:
        raise ValueError("role must be widget or supervisor")
    if mode not in {"test", "live"}:
        raise ValueError("mode must be test or live")
    ensure_tenant(tenant_id, session_factory=session_factory)
    stem = PREFIX_TEST if mode == "test" else PREFIX_LIVE
    secret = stem + secrets.token_urlsafe(24)
    prefix = secret[: len(stem) + 6]
    row = ApiKeyRow(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        prefix=prefix,
        key_hash=_hash(secret),
        role=role,
        mode=mode,
        reveal_once=secret,
    )
    with session_factory() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        db.expunge(row)
    return row, secret


def authenticate(token: str, *, session_factory=SessionLocal) -> Principal:
    secret = (token or "").strip()
    if not secret.startswith(PREFIX_TEST) and not secret.startswith(PREFIX_LIVE):
        raise AuthError(401, "invalid api key")
    digest = _hash(secret)
    with session_factory() as db:
        row = db.execute(select(ApiKeyRow).where(ApiKeyRow.key_hash == digest)).scalars().first()
        if row is None or row.revoked_at is not None:
            raise AuthError(401, "invalid api key")
        if not hmac.compare_digest(row.key_hash, digest):
            raise AuthError(401, "invalid api key")
        tenant = db.get(TenantAccountRow, row.tenant_id)
        if tenant is None:
            raise AuthError(401, "invalid api key")
        mode = "test" if secret.startswith(PREFIX_TEST) else "live"
        if row.mode != mode:
            raise AuthError(401, "invalid api key")
        if mode == "live" and tenant.sandbox_passed_at is None:
            raise AuthError(403, "live key is blocked until the sandbox passes")
        return Principal(
            key_id=row.id,
            tenant_id=row.tenant_id,
            role=row.role,
            mode=mode,
            prefix=row.prefix,
            sandbox_passed_at=tenant.sandbox_passed_at,
            killed_at=tenant.killed_at,
        )


def list_keys(tenant_id: str, session_factory=SessionLocal) -> list[dict]:
    with session_factory() as db:
        rows = db.execute(
            select(ApiKeyRow)
            .where(ApiKeyRow.tenant_id == tenant_id)
            .order_by(ApiKeyRow.created_at.asc())
        ).scalars().all()
        return [_public_key(row) for row in rows]


def reveal_key(key_id: str, tenant_id: str, session_factory=SessionLocal) -> Optional[str]:
    """Return the one-time secret and clear it."""
    with session_factory() as db:
        row = db.get(ApiKeyRow, key_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        secret = row.reveal_once
        if secret:
            row.reveal_once = None
            db.commit()
        return secret


def take_unrevealed(tenant_id: str, *, role: str, mode: str, session_factory=SessionLocal) -> Optional[str]:
    with session_factory() as db:
        row = db.execute(
            select(ApiKeyRow)
            .where(ApiKeyRow.tenant_id == tenant_id)
            .where(ApiKeyRow.role == role)
            .where(ApiKeyRow.mode == mode)
            .where(ApiKeyRow.revoked_at.is_(None))
            .where(ApiKeyRow.reveal_once.is_not(None))
            .order_by(ApiKeyRow.created_at.desc())
        ).scalars().first()
        if row is None:
            return None
        secret = row.reveal_once
        row.reveal_once = None
        db.commit()
        return secret


def _public_key(row: ApiKeyRow) -> dict:
    return {
        "id": row.id,
        "prefix": row.prefix,
        "role": row.role,
        "mode": row.mode,
        "revoked_at": None if row.revoked_at is None else row.revoked_at.isoformat(),
        "has_reveal": bool(row.reveal_once),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def tenant_record(tenant_id: str, session_factory=SessionLocal) -> Optional[TenantAccountRow]:
    with session_factory() as db:
        row = db.get(TenantAccountRow, tenant_id)
        if row is not None:
            db.expunge(row)
        return row


def set_killed(tenant_id: str, killed: bool, session_factory=SessionLocal) -> None:
    ensure_tenant(tenant_id, session_factory=session_factory)
    with session_factory() as db:
        row = db.get(TenantAccountRow, tenant_id)
        row.killed_at = datetime.utcnow() if killed else None
        db.commit()


def mark_sandbox_passed(tenant_id: str, session_factory=SessionLocal) -> datetime:
    ensure_tenant(tenant_id, session_factory=session_factory)
    with session_factory() as db:
        row = db.get(TenantAccountRow, tenant_id)
        if row.sandbox_passed_at is None:
            row.sandbox_passed_at = datetime.utcnow()
        stamp = row.sandbox_passed_at
        db.commit()
        return stamp
