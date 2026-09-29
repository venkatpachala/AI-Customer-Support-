"""One in-flight or finished run per tenant, case, workflow, and order."""
from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy import select

from db.models import WorkflowRunRow
from workflows.state import REUSABLE_RUN_STATUSES


def build_idempotency_key(
    tenant_id: str,
    case_id: str,
    workflow_name: str,
    order_id: Optional[str],
) -> str:
    raw = f"{tenant_id}:{case_id}:{workflow_name}:{order_id or ''}"
    if len(raw) <= 128:
        return raw
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stripe_step_key(run_id: str) -> str:
    """Side-effect key for the refund create inside one run."""
    return f"{run_id}:execute_refund"


def find_reusable_run(db, idempotency_key: str) -> Optional[WorkflowRunRow]:
    if not idempotency_key:
        return None
    row = db.execute(
        select(WorkflowRunRow).where(WorkflowRunRow.idempotency_key == idempotency_key)
    ).scalars().first()
    if row is None:
        return None
    if row.status in REUSABLE_RUN_STATUSES:
        return row
    # Failed and cancelled rows still own the unique key. Returning them
    # prevents a second insert from crashing on the unique constraint.
    return row
