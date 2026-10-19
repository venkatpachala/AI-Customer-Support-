"""Read a persisted workflow run and its steps. Does not resume it."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select

from controlplane.http import session_principal
from db.models import WorkflowRunRow, WorkflowStepRow
from db.session import SessionLocal

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


def _tenant(request: Request, x_tenant_id: Optional[str]) -> str:
    principal = session_principal(request)
    if principal is not None:
        if principal.role != "supervisor":
            raise HTTPException(status_code=403, detail="operator credential required")
        supplied = (x_tenant_id or "").strip()
        if supplied and supplied != principal.tenant_id:
            raise HTTPException(status_code=403, detail="tenant mismatch")
        return principal.tenant_id
    from controlplane.settings import legacy_headers_allowed
    if not legacy_headers_allowed():
        raise HTTPException(status_code=401, detail="authenticated credential required")
    tenant = (x_tenant_id or "").strip()
    if not tenant:
        raise HTTPException(status_code=400, detail="X-Tenant-Id is required")
    return tenant


@router.get("/{run_id}")
def get_workflow(
    run_id: str,
    request: Request,
    x_tenant_id: Optional[str] = Header(default=None),
    x_actor_role: Optional[str] = Header(default=None),
):
    tenant = _tenant(request, x_tenant_id)
    if x_actor_role is not None and x_actor_role.strip().lower() not in {"supervisor", "admin"}:
        raise HTTPException(status_code=403, detail="supervisor role required")
    with SessionLocal() as db:
        run = db.get(WorkflowRunRow, run_id)
        if run is None or run.tenant_id != tenant:
            raise HTTPException(status_code=404, detail="workflow run not found")
        steps = db.execute(
            select(WorkflowStepRow)
            .where(WorkflowStepRow.run_id == run_id)
            .order_by(WorkflowStepRow.step_index.asc())
        ).scalars().all()
        return {
            "run_id": run.id,
            "tenant_id": run.tenant_id,
            "case_id": run.case_id,
            "workflow_name": run.workflow_name,
            "status": run.status,
            "current_step": run.current_step,
            "error": run.error,
            "output": dict(run.output_json or {}),
            "steps": [
                {
                    "name": step.step_name,
                    "status": step.status,
                    "attempt": step.attempt,
                    "error": step.error,
                }
                for step in steps
            ],
        }
