"""Read a case with its latest workflow run and pending approval tasks."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select

from controlplane.http import bearer_principal
from db.models import CaseRow, HumanTaskRow, WorkflowRunRow
from db.session import SessionLocal

router = APIRouter(prefix="/v1/cases", tags=["cases"])


def _tenant(request: Request, x_tenant_id: Optional[str]) -> str:
    principal = bearer_principal(request)
    if principal is not None:
        return principal.tenant_id
    tenant = (x_tenant_id or "").strip()
    if not tenant:
        raise HTTPException(status_code=400, detail="X-Tenant-Id is required")
    return tenant


@router.get("/{case_id}")
def get_case(
    case_id: str,
    request: Request,
    x_tenant_id: Optional[str] = Header(default=None),
    x_actor_role: Optional[str] = Header(default=None),
):
    tenant = _tenant(request, x_tenant_id)
    if x_actor_role is not None and x_actor_role.strip().lower() not in {"supervisor", "admin"}:
        raise HTTPException(status_code=403, detail="supervisor role required")
    with SessionLocal() as db:
        case = db.get(CaseRow, case_id)
        if case is None or case.tenant_id != tenant:
            raise HTTPException(status_code=404, detail="case not found")
        run = db.execute(
            select(WorkflowRunRow)
            .where(WorkflowRunRow.case_id == case_id)
            .order_by(WorkflowRunRow.created_at.desc())
        ).scalars().first()
        tasks = db.execute(
            select(HumanTaskRow)
            .where(HumanTaskRow.case_id == case_id)
            .where(HumanTaskRow.status == "pending")
        ).scalars().all()
        return {
            "case_id": case.case_id,
            "tenant_id": case.tenant_id,
            "customer_id": case.customer_id,
            "status": case.status,
            "order_id": case.order_id,
            "escalated": bool(case.escalated),
            "escalation_reason": case.escalation_reason,
            "workflow_run_id": None if run is None else run.id,
            "workflow_status": None if run is None else run.status,
            "pending_tasks": [
                {
                    "id": task.id,
                    "type": task.task_type,
                    "run_id": task.workflow_run_id,
                    "amount": (task.payload_json or {}).get("amount"),
                    "order_id": (task.payload_json or {}).get("order_id"),
                }
                for task in tasks
            ],
        }
