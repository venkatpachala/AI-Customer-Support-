"""Per-tenant daily chat cap so one brand cannot empty the model key."""
from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import select

from db.models import DailyUsageRow
from db.session import SessionLocal


def daily_request_cap() -> int:
    raw = os.getenv("DAILY_REQUEST_CAP", "2000").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 2000


def _day() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def consume_chat(tenant_id: str, session_factory=SessionLocal) -> bool:
    """Return False when this tenant is over the daily request cap."""
    tenant = (tenant_id or "").strip()
    if not tenant:
        return False
    cap = daily_request_cap()
    day = _day()
    with session_factory() as db:
        row = db.execute(
            select(DailyUsageRow)
            .where(DailyUsageRow.tenant_id == tenant)
            .where(DailyUsageRow.day == day)
        ).scalars().first()
        if row is None:
            row = DailyUsageRow(tenant_id=tenant, day=day, requests=0)
            db.add(row)
        if int(row.requests or 0) >= cap:
            db.commit()
            return False
        row.requests = int(row.requests or 0) + 1
        db.commit()
        return True
