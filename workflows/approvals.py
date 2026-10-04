"""Human approval rows that continue or cancel a workflow run.

Approve calls WorkflowEngine.resume on the same run_id. It does not invoke
the LangGraph graph. Reject marks the run cancelled and does not call Stripe.

The decision is stored on human_tasks.resolution_json. The table has no
decision_json column; resolution_json is that record.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from db.models import CaseRow, HumanTaskRow, PlatformEventRow, WorkflowRunRow
from db.session import SessionLocal
from workflows.engine import WorkflowEngine
from workflows.state import RUN_CANCELLED, RUN_WAITING_INPUT


class ApprovalError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def approve_task(
    task_id: str,
    *,
    tenant_id: str,
    actor_id: str,
    note: Optional[str] = None,
    engine: Optional[WorkflowEngine] = None,
    session_factory=SessionLocal,
) -> Dict[str, Any]:
    engine = engine or WorkflowEngine()
    task = _load_task(session_factory, task_id, tenant_id)
    _ensure_pending(task)
    run = _load_run(session_factory, task.workflow_run_id)
    if run.status == RUN_WAITING_INPUT:
        raise ApprovalError(409, "workflow is waiting for customer input")
    _decide(
        session_factory,
        task.id,
        status="approved",
        actor_id=actor_id,
        note=note,
    )
    view = engine.resume(task.workflow_run_id)
    _record_event(
        session_factory,
        tenant_id=tenant_id,
        case_id=task.case_id,
        event_type="approval.completed",
        payload={
            "task_id": task.id,
            "workflow_run_id": view.run_id,
            "workflow_status": view.status,
            "actor_id": actor_id,
            "note": note,
        },
    )
    return {
        "task": _task_view(_reload(session_factory, task.id)),
        "workflow_run_id": view.run_id,
        "workflow_status": view.status,
    }


def reject_task(
    task_id: str,
    *,
    tenant_id: str,
    actor_id: str,
    note: Optional[str] = None,
    session_factory=SessionLocal,
) -> Dict[str, Any]:
    task = _load_task(session_factory, task_id, tenant_id)
    _ensure_pending(task)
    run = _load_run(session_factory, task.workflow_run_id)
    if run.status == RUN_WAITING_INPUT:
        raise ApprovalError(409, "workflow is waiting for customer input")
    _decide(
        session_factory,
        task.id,
        status="rejected",
        actor_id=actor_id,
        note=note,
    )
    _cancel_run(session_factory, run.id, task.case_id)
    _record_event(
        session_factory,
        tenant_id=tenant_id,
        case_id=task.case_id,
        event_type="approval.rejected",
        payload={
            "task_id": task.id,
            "workflow_run_id": run.id,
            "workflow_status": RUN_CANCELLED,
            "actor_id": actor_id,
            "note": note,
        },
    )
    return {
        "task": _task_view(_reload(session_factory, task.id)),
        "workflow_run_id": run.id,
        "workflow_status": RUN_CANCELLED,
    }


def list_tasks(
    *,
    tenant_id: str,
    status: str = "pending",
    limit: int = 50,
    session_factory=SessionLocal,
) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 50), 200))
    with session_factory() as db:
        rows = db.execute(
            select(HumanTaskRow)
            .where(HumanTaskRow.tenant_id == tenant_id)
            .where(HumanTaskRow.status == status)
            .order_by(HumanTaskRow.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [_task_queue_item(row) for row in rows]


def get_task(task_id: str, *, tenant_id: str, session_factory=SessionLocal) -> Dict[str, Any]:
    return _task_view(_load_task(session_factory, task_id, tenant_id))


def _load_task(session_factory, task_id: str, tenant_id: str) -> HumanTaskRow:
    with session_factory() as db:
        row = db.get(HumanTaskRow, task_id)
        if row is None:
            raise ApprovalError(404, "approval task not found")
        if row.tenant_id != tenant_id:
            raise ApprovalError(403, "approval task is not in this tenant")
        db.expunge(row)
        return row


def _load_run(session_factory, run_id: Optional[str]) -> WorkflowRunRow:
    if not run_id:
        raise ApprovalError(409, "approval task has no workflow run")
    with session_factory() as db:
        row = db.get(WorkflowRunRow, run_id)
        if row is None:
            raise ApprovalError(404, "workflow run not found")
        db.expunge(row)
        return row


def _ensure_pending(task: HumanTaskRow) -> None:
    if task.status != "pending":
        raise ApprovalError(409, f"approval task is {task.status}")


def _decide(session_factory, task_id: str, *, status: str, actor_id: str, note: Optional[str]) -> None:
    with session_factory() as db:
        row = db.get(HumanTaskRow, task_id)
        if row is None:
            raise ApprovalError(404, "approval task not found")
        if row.status != "pending":
            raise ApprovalError(409, f"approval task is {row.status}")
        row.status = status
        row.decided_by = actor_id
        row.decided_at = datetime.utcnow()
        row.resolution_json = {"note": note, "actor": actor_id, "decision": status}
        row.updated_at = datetime.utcnow()
        db.commit()


def _cancel_run(session_factory, run_id: str, case_id: Optional[str]) -> None:
    with session_factory() as db:
        run = db.get(WorkflowRunRow, run_id)
        if run is not None:
            run.status = RUN_CANCELLED
            run.error = "approval_rejected"
            run.finished_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
        if case_id:
            case = db.get(CaseRow, case_id)
            if case is not None:
                case.status = "escalated"
                case.escalated = True
                case.escalation_reason = "approval_rejected"
                case.updated_at = datetime.utcnow()
        db.commit()


def _record_event(session_factory, *, tenant_id: str, case_id: Optional[str], event_type: str, payload: Dict[str, Any]) -> None:
    with session_factory() as db:
        db.add(
            PlatformEventRow(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                case_id=case_id,
                event_type=event_type,
                payload_json=payload,
            )
        )
        db.commit()


def _reload(session_factory, task_id: str) -> HumanTaskRow:
    with session_factory() as db:
        row = db.get(HumanTaskRow, task_id)
        if row is None:
            raise ApprovalError(404, "approval task not found")
        db.expunge(row)
        return row


def _task_view(row: HumanTaskRow) -> Dict[str, Any]:
    payload = dict(row.payload_json or {})
    return {
        "id": row.id,
        "type": row.task_type,
        "status": row.status,
        "tenant_id": row.tenant_id,
        "case_id": row.case_id,
        "workflow_run_id": row.workflow_run_id,
        "amount": payload.get("amount"),
        "order_id": payload.get("order_id"),
        "reasons": list(payload.get("reasons") or []),
        "decided_by": row.decided_by,
        "decided_at": _iso(row.decided_at),
        "decision": dict(row.resolution_json or {}),
        "created_at": _iso(row.created_at),
    }


def _task_queue_item(row: HumanTaskRow) -> Dict[str, Any]:
    payload = dict(row.payload_json or {})
    return {
        "id": row.id,
        "type": row.task_type,
        "case_id": row.case_id,
        "run_id": row.workflow_run_id,
        "amount": payload.get("amount"),
        "order_id": payload.get("order_id"),
        "reason": payload.get("reason"),
        "policy_version": payload.get("policy_version"),
        "photos_received": bool(payload.get("photos_received")),
        "reasons": list(payload.get("reasons") or []),
        "created_at": _iso(row.created_at),
    }


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()
