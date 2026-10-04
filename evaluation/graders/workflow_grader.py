"""Read persisted workflow rows. Graders do not call Stripe."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from db.models import HumanTaskRow, WorkflowRunRow, WorkflowStepRow
from db.session import SessionLocal


def stripe_create_count(run_id: str, session_factory=SessionLocal) -> int:
    """Successful execute_refund steps. A retry that did not succeed is not a create."""
    with session_factory() as db:
        rows = db.execute(
            select(WorkflowStepRow)
            .where(WorkflowStepRow.run_id == run_id)
            .where(WorkflowStepRow.step_name == "execute_refund")
            .where(WorkflowStepRow.status == "success")
        ).scalars().all()
        return len(rows)


def run_status(run_id: str, session_factory=SessionLocal) -> Optional[str]:
    with session_factory() as db:
        row = db.get(WorkflowRunRow, run_id)
        return None if row is None else row.status


def has_pending_task(run_id: str, session_factory=SessionLocal) -> bool:
    with session_factory() as db:
        row = db.execute(
            select(HumanTaskRow)
            .where(HumanTaskRow.workflow_run_id == run_id)
            .where(HumanTaskRow.status == "pending")
        ).scalars().first()
        return row is not None


def pending_task_id(run_id: str, session_factory=SessionLocal) -> Optional[str]:
    with session_factory() as db:
        row = db.execute(
            select(HumanTaskRow)
            .where(HumanTaskRow.workflow_run_id == run_id)
            .where(HumanTaskRow.status == "pending")
        ).scalars().first()
        return None if row is None else row.id
