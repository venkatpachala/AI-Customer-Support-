"""Supervisor approval queue. Mutate routes require a supervisor or admin."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from identity.ops_session import COOKIE_NAME, ops_role
from workflows.approvals import ApprovalError, approve_task, list_tasks, reject_task
from workflows.engine import WorkflowEngine

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])

# Tests point this at the engine that owns their fake Stripe tool.
# Production leaves it empty and approve builds a normal WorkflowEngine.
_engine_override: Optional[WorkflowEngine] = None


def engine_override(engine: Optional[WorkflowEngine]) -> None:
    global _engine_override
    _engine_override = engine


class DecisionBody(BaseModel):
    note: Optional[str] = None


def _tenant(x_tenant_id: Optional[str]) -> str:
    tenant = (x_tenant_id or "").strip()
    if not tenant:
        raise HTTPException(status_code=400, detail="X-Tenant-Id is required")
    return tenant


def _supervisor(x_actor_role: Optional[str], request: Request) -> str:
    role = (x_actor_role or "").strip().lower()
    if role in {"supervisor", "admin"}:
        return role
    cookie_role = ops_role(request.cookies.get(COOKIE_NAME))
    if cookie_role == "supervisor":
        return cookie_role
    raise HTTPException(status_code=403, detail="supervisor role required")


def _call(fn):
    try:
        return fn()
    except ApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("")
def list_approvals(
    request: Request,
    status: str = "pending",
    tenant_id: Optional[str] = None,
    limit: int = 50,
    x_tenant_id: Optional[str] = Header(default=None),
    x_actor_role: Optional[str] = Header(default=None),
):
    tenant = _tenant(x_tenant_id)
    _supervisor(x_actor_role, request)
    if tenant_id and tenant_id != tenant:
        raise HTTPException(status_code=403, detail="tenant header does not match tenant_id")
    return {"approvals": list_tasks(tenant_id=tenant, status=status, limit=limit)}


@router.post("/{task_id}/approve")
def approve(
    task_id: str,
    request: Request,
    body: Optional[DecisionBody] = None,
    x_tenant_id: Optional[str] = Header(default=None),
    x_actor_role: Optional[str] = Header(default=None),
    x_actor_id: Optional[str] = Header(default=None),
):
    tenant = _tenant(x_tenant_id)
    _supervisor(x_actor_role, request)
    actor = (x_actor_id or "").strip() or "supervisor"
    note = None if body is None else body.note
    return _call(
        lambda: approve_task(
            task_id,
            tenant_id=tenant,
            actor_id=actor,
            note=note,
            engine=_engine_override,
        )
    )


@router.post("/{task_id}/reject")
def reject(
    task_id: str,
    request: Request,
    body: Optional[DecisionBody] = None,
    x_tenant_id: Optional[str] = Header(default=None),
    x_actor_role: Optional[str] = Header(default=None),
    x_actor_id: Optional[str] = Header(default=None),
):
    tenant = _tenant(x_tenant_id)
    _supervisor(x_actor_role, request)
    actor = (x_actor_id or "").strip() or "supervisor"
    note = None if body is None else (body.note or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="reject note is required")
    return _call(lambda: reject_task(task_id, tenant_id=tenant, actor_id=actor, note=note))
