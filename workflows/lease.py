"""Database execution leases shared across API processes and recovery workers."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from threading import Event, Thread

from sqlalchemy import delete, update, select
from sqlalchemy.exc import IntegrityError
from db.models import ExecutionLeaseRow


class ExecutionLease:
    def __init__(self, key: str, session_factory, ttl: int = 120):
        self.key, self.session_factory, self.ttl = key, session_factory, ttl
        self.owner = uuid.uuid4().hex
        self.acquired = False
        self.stop = Event()
        self.thread = None

    def __enter__(self):
        now = datetime.utcnow()
        with self.session_factory() as db:
            changed = db.execute(update(ExecutionLeaseRow).where(
                ExecutionLeaseRow.id == self.key, ExecutionLeaseRow.expires_at < now)
                .values(owner=self.owner, expires_at=now + timedelta(seconds=self.ttl))).rowcount
            if not changed:
                db.add(ExecutionLeaseRow(id=self.key, owner=self.owner, expires_at=now + timedelta(seconds=self.ttl)))
            try:
                db.commit()
                self.acquired = True
            except IntegrityError:
                db.rollback()
        if self.acquired:
            self.thread = Thread(target=self._heartbeat, daemon=True)
            self.thread.start()
        return self

    def _heartbeat(self):
        while not self.stop.wait(self.ttl / 3):
            try:
                with self.session_factory() as db:
                    changed = db.execute(update(ExecutionLeaseRow).where(
                        ExecutionLeaseRow.id == self.key, ExecutionLeaseRow.owner == self.owner,
                        ExecutionLeaseRow.expires_at > datetime.utcnow())
                        .values(expires_at=datetime.utcnow() + timedelta(seconds=self.ttl))).rowcount
                    db.commit()
                    if not changed:
                        return
            except Exception:
                return  # assert_owned prevents subsequent commits by a stale runner.

    def assert_owned(self):
        with self.session_factory() as db:
            owner = db.execute(select(ExecutionLeaseRow.owner).where(
                ExecutionLeaseRow.id == self.key, ExecutionLeaseRow.expires_at > datetime.utcnow())).scalar_one_or_none()
        if owner != self.owner:
            raise RuntimeError("execution lease lost; recovery required")

    def __exit__(self, *args):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        if self.acquired:
            with self.session_factory() as db:
                db.execute(delete(ExecutionLeaseRow).where(ExecutionLeaseRow.id == self.key, ExecutionLeaseRow.owner == self.owner))
                db.commit()
