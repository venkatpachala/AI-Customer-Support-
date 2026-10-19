"""Per-tenant daily chat cap so one brand cannot empty the model key."""
from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

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
        changed = db.execute(update(DailyUsageRow).where(DailyUsageRow.tenant_id == tenant,
            DailyUsageRow.day == day, DailyUsageRow.requests < cap)
            .values(requests=DailyUsageRow.requests + 1)).rowcount
        if changed:
            db.commit()
            return True
        row = db.execute(select(DailyUsageRow.id).where(DailyUsageRow.tenant_id == tenant,
            DailyUsageRow.day == day)).scalar_one_or_none()
        if row is not None:
            return False
        db.add(DailyUsageRow(tenant_id=tenant, day=day, requests=1))
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            changed = db.execute(update(DailyUsageRow).where(DailyUsageRow.tenant_id == tenant,
                DailyUsageRow.day == day, DailyUsageRow.requests < cap)
                .values(requests=DailyUsageRow.requests + 1)).rowcount
            db.commit()
            return changed == 1
