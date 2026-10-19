"""Short-lived proof of control of the contact already held by the merchant."""
from datetime import datetime
from sqlalchemy import select
from db.models import VerificationChallengeRow
from db.session import SessionLocal


def verified_order(case_id: str, order_id: str) -> bool:
    with SessionLocal() as db:
        return db.execute(select(VerificationChallengeRow.id).where(
            VerificationChallengeRow.case_id == case_id,
            VerificationChallengeRow.order_id == order_id,
            VerificationChallengeRow.verified_at.is_not(None),
            VerificationChallengeRow.expires_at > datetime.utcnow()).limit(1)).scalar_one_or_none() is not None
