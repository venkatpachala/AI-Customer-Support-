"""Read-only case brief for a human. No new agent."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select

from db.models import InteractionRow
from db.session import SessionLocal
from interactions.intelligence import IntelligenceError, case_timeline

router = APIRouter(tags=["copilot"])
_LIMIT = 240


def _tenant(header: Optional[str]) -> str:
    tenant = (header or "").strip()
    if not tenant:
        raise HTTPException(status_code=400, detail="X-Tenant-Id is required")
    return tenant


def _clip(text: Any) -> str:
    body = str(text or "")
    return body if len(body) <= _LIMIT else body[:_LIMIT]


@router.get("/v1/cases/{case_id}/copilot")
def get_copilot(case_id: str, x_tenant_id: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    tenant = _tenant(x_tenant_id)
    try:
        timeline = case_timeline(case_id, tenant)
    except IntelligenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    messages = [item for item in timeline["items"] if item["kind"] == "message"]
    steps = [item for item in timeline["items"] if item["kind"] == "step"]
    approvals = [item for item in timeline["items"] if item["kind"] == "approval"]
    pending = [item for item in approvals if (item.get("data") or {}).get("status") == "pending"]
    last_step = steps[-1] if steps else None

    with SessionLocal() as db:
        row = db.execute(
            select(InteractionRow)
            .where(InteractionRow.case_id == case_id)
            .where(InteractionRow.tenant_id == tenant)
            .order_by(InteractionRow.created_at.desc())
        ).scalars().first()
    meta = dict(row.metadata_json or {}) if row is not None else {}
    missing = list(row.missing_inputs or []) if row is not None else []

    return {
        "case_id": case_id,
        "tenant_id": tenant,
        "summary": [_clip((item.get("data") or {}).get("text")) for item in messages[-6:]],
        "policy": {
            "allowed": meta.get("policy_decision", {}).get("allowed") if isinstance(meta.get("policy_decision"), dict) else None,
            "deny_code": meta.get("policy_deny_code"),
            "policy_version": meta.get("policy_version"),
            "outcome": meta.get("outcome"),
            "workflow_status": meta.get("workflow_status"),
        },
        "missing_inputs": missing,
        "pending_approval": bool(pending),
        "approval_task_id": None if not pending else pending[-1].get("ref"),
        "last_tool_status": None if last_step is None else {
            "step_name": (last_step.get("data") or {}).get("step_name"),
            "status": (last_step.get("data") or {}).get("status"),
        },
    }
