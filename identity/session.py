"""HttpOnly widget sessions. Auth level is not part of this record."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from db.models import CustomerSessionRow
from db.session import SessionLocal

COOKIE_NAME = "d2c_session"
SESSION_TTL = timedelta(hours=12)


def create_customer_session(tenant_id: str, customer_ref: str, *, now: Optional[datetime] = None) -> CustomerSessionRow:
    tenant = (tenant_id or "").strip()
    ref = (customer_ref or "").strip()
    if not tenant or not ref:
        raise ValueError("tenant_id and customer_ref are required")
    current = now or datetime.utcnow()
    row = CustomerSessionRow(
        id=str(uuid.uuid4()),
        tenant_id=tenant,
        customer_ref=ref,
        expires_at=current + SESSION_TTL,
        created_at=current,
    )
    with SessionLocal() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        db.expunge(row)
    return row


def load_customer_session(session_id: Optional[str], *, now: Optional[datetime] = None) -> Optional[CustomerSessionRow]:
    token = (session_id or "").strip()
    if not token:
        return None
    current = now or datetime.utcnow()
    with SessionLocal() as db:
        row = db.get(CustomerSessionRow, token)
        if row is None or row.expires_at <= current:
            return None
        db.expunge(row)
        return row
