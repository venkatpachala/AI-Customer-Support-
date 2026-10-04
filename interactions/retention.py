"""Drop raw chat text after 90 days. Workflow and approval rows stay."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_, update

from db.models import InteractionRow
from db.session import SessionLocal


def sweep_interaction_text(days: int = 90) -> int:
    cutoff = datetime.utcnow() - timedelta(days=days)
    with SessionLocal() as db:
        result = db.execute(
            update(InteractionRow)
            .where(InteractionRow.created_at < cutoff)
            .where(or_(InteractionRow.message.is_not(None), InteractionRow.response.is_not(None)))
            .values(message=None, response=None)
        )
        db.commit()
        return int(result.rowcount or 0)
