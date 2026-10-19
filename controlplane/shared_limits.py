"""Atomic fixed-window limits shared by multiple API processes."""
import hashlib
import time
from datetime import datetime, timedelta
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from db.models import RateLimitBucketRow
from db.session import SessionLocal


def allow(key: str, limit: int, window: int = 60) -> bool:
    now = int(time.time())
    identity = hashlib.sha256(f"{key}:{now // window}".encode()).hexdigest()
    with SessionLocal() as db:
        changed = db.execute(update(RateLimitBucketRow).where(RateLimitBucketRow.id == identity,
            RateLimitBucketRow.requests < limit).values(requests=RateLimitBucketRow.requests + 1)).rowcount
        if changed:
            db.commit()
            return True
        if db.get(RateLimitBucketRow, identity) is not None:
            return False
        db.add(RateLimitBucketRow(id=identity, requests=1,
            expires_at=datetime.utcnow() + timedelta(seconds=window * 2)))
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            changed = db.execute(update(RateLimitBucketRow).where(RateLimitBucketRow.id == identity,
                RateLimitBucketRow.requests < limit).values(requests=RateLimitBucketRow.requests + 1)).rowcount
            db.commit()
            return changed == 1
