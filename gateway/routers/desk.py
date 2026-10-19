"""Authenticated operator console. All tenant identity comes from the credential."""
from __future__ import annotations

from datetime import datetime, timedelta
from collections import Counter
from typing import Literal
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from decimal import Decimal
from sqlalchemy import select

from controlplane.http import require_principal
from db.models import CaseRow, MessageRow, OperatorCaseRow, PlatformEventRow, PlatformTenantRow, WorkflowRunRow, InteractionRow
from db.session import SessionLocal

router = APIRouter(prefix="/v1/desk", tags=["operator-desk"])


class SupportRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    note: str = Field(min_length=5, max_length=2000)


@router.post("/support", status_code=201)
def submit_support(body: SupportRequest, request: Request):
    principal = staff(request)
    from controlplane.shared_limits import allow
    from db.models import IntakeRequestRow
    if not allow("support:" + principal.tenant_id, 10, 3600):
        raise HTTPException(429, "Too many support requests. Please retry later.")
    identity = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(IntakeRequestRow(id=identity, kind="stuck_case", tenant_id=principal.tenant_id,
                               email=body.email.strip().lower(), note=body.note.strip()))
        db.commit()
    return {"id": identity, "status": "received"}


class BrandSettings(BaseModel):
    brand_name: str = Field(min_length=1, max_length=128)
    tone: str = Field(default="professional, polite, concise", max_length=256)
    support_email: str = Field(default="", max_length=256)
    auto_refund_max: Decimal = Field(default=Decimal("0"), ge=0, max_digits=8, decimal_places=2)
    manager_refund_max: Decimal = Field(default=Decimal("0"), ge=0, max_digits=8, decimal_places=2)


@router.get("/settings")
def settings(request: Request):
    principal = staff(request)
    from config.tenant_contract import load_platform_tenant
    from controlplane.keys import tenant_record
    contract = load_platform_tenant(principal.tenant_id)
    account = tenant_record(principal.tenant_id)
    with SessionLocal() as db:
        stored = db.get(PlatformTenantRow, principal.tenant_id)
        data = (stored.config_json or {}).get("brand_settings", {}) if stored else {}
    return {"brand_name": account.name if account else principal.tenant_id,
        "tone": contract.tone or "professional, polite, concise", "support_email": data.get("support_email", ""),
        "auto_refund_max": contract.limits.auto_refund_max, "manager_refund_max": contract.limits.manager_refund_max}


@router.put("/settings")
def save_settings(body: BrandSettings, request: Request):
    principal = staff(request)
    if body.manager_refund_max < body.auto_refund_max:
        raise HTTPException(400, "manager cap must be at least the automatic cap")
    from config.tenant_contract import platform_tenant_yaml_path
    if platform_tenant_yaml_path(principal.tenant_id).is_file():
        raise HTTPException(409, "reference tenants use versioned YAML; create your own brand to edit settings")
    from db.models import TenantAccountRow
    with SessionLocal() as db:
        account = db.get(TenantAccountRow, principal.tenant_id)
        account.name = body.brand_name.strip()
        row = db.get(PlatformTenantRow, principal.tenant_id)
        if row is None:
            row = PlatformTenantRow(tenant_id=principal.tenant_id, config_json={})
            db.add(row)
        config = dict(row.config_json or {})
        config["brand_settings"] = body.model_dump(mode="json")
        config["tenant_contract"] = {"id": principal.tenant_id, "brand": account.name, "tone": body.tone,
            "limits": {"auto_refund_max": float(body.auto_refund_max), "manager_refund_max": float(body.manager_refund_max)},
            "versions": {"policy_pack": uuid.uuid4().hex}}
        row.config_json = config
        db.commit()
    return {"ok": True}


def staff(request: Request):
    principal = require_principal(request)
    if principal.role != "supervisor":
        raise HTTPException(403, "operator credential required")
    return principal


def case_for(db, case_id: str, tenant: str) -> CaseRow:
    row = db.get(CaseRow, case_id)
    if row is None or row.tenant_id != tenant:
        raise HTTPException(404, "case not found")
    return row


def _case_view(db, case: CaseRow) -> dict:
    owner = db.get(OperatorCaseRow, case.case_id)
    latest = db.execute(select(MessageRow).where(MessageRow.case_id == case.case_id).order_by(MessageRow.id.desc()).limit(1)).scalar_one_or_none()
    run = db.execute(select(WorkflowRunRow).where(WorkflowRunRow.case_id == case.case_id,
        WorkflowRunRow.tenant_id == case.tenant_id).order_by(WorkflowRunRow.created_at.desc()).limit(1)).scalar_one_or_none()
    human = bool(owner and owner.human_owned)
    status = "resolved" if owner and owner.resolved else "human_owned" if human else case.status
    if run and not human and not (owner and owner.resolved):
        status = "waiting_customer" if run.status in {"waiting_input", "waiting_auth"} else run.status
    if status == "succeeded":
        status = "ai_resolved"
    amount = (run.input_json or {}).get("slots", {}).get("amount") if run else None
    try:
        amount = float(amount) if amount is not None else None
    except (TypeError, ValueError):
        amount = None
    return {"id": case.case_id, "brandId": case.tenant_id, "channel": "chat",
        "customerLabel": case.customer_id, "subject": (case.issue_type or "Support request").replace("_", " ").title(),
        "preview": latest.content[:240] if latest else "", "intent": case.issue_type or "other",
        "status": status, "priority": "high" if case.escalated or status == "waiting_approval" else "normal",
        "aiHandled": not human, "confidence": 0, "amountInr": amount, "orderRef": case.order_id,
        "assignee": owner.assigned_to if human else "AI", "updatedAt": case.updated_at.isoformat() + "Z"}


@router.get("/cases")
def cases(request: Request, limit: int = 100):
    principal = staff(request)
    with SessionLocal() as db:
        rows = db.execute(select(CaseRow).where(CaseRow.tenant_id == principal.tenant_id)
            .order_by(CaseRow.updated_at.desc()).limit(max(1, min(limit, 500)))).scalars().all()
        return {"items": [_case_view(db, case) for case in rows]}


@router.get("/cases/{case_id}")
def case_detail(case_id: str, request: Request):
    principal = staff(request)
    with SessionLocal() as db:
        case = case_for(db, case_id, principal.tenant_id)
        messages = db.execute(select(MessageRow).where(MessageRow.case_id == case_id)
            .order_by(MessageRow.id)).scalars().all()
        return {"conversation": _case_view(db, case), "messages": [
            {"id": row.id, "author": row.role, "body": row.content, "citation": None,
             "createdAt": row.created_at.isoformat() + "Z"} for row in messages]}


class ReplyBody(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class ActionBody(BaseModel):
    action: Literal["claim", "release", "resolve"]


def _operator(db, case: CaseRow, actor: str) -> OperatorCaseRow:
    owner = db.get(OperatorCaseRow, case.case_id)
    if owner is None:
        owner = OperatorCaseRow(id=case.case_id, tenant_id=case.tenant_id, assigned_to=actor)
        db.add(owner)
    return owner


@router.post("/cases/{case_id}/reply")
def reply(case_id: str, body: ReplyBody, request: Request):
    principal = staff(request)
    with SessionLocal() as db:
        case = case_for(db, case_id, principal.tenant_id)
        owner = _operator(db, case, principal.key_id)
        owner.human_owned = True
        owner.resolved = False
        owner.assigned_to = principal.key_id
        case.status = "waiting_customer"
        case.updated_at = datetime.utcnow()
        message = MessageRow(session_id=case.session_id, case_id=case_id, role="operator", content=body.body.strip())
        db.add(message)
        db.add(PlatformEventRow(id=uuid.uuid4().hex, tenant_id=case.tenant_id, case_id=case_id,
            event_type="operator.reply", payload_json={"actor_id": principal.key_id}))
        db.commit()
        return {"ok": True, "status": "human_owned"}


@router.post("/cases/{case_id}/action")
def case_action(case_id: str, body: ActionBody, request: Request):
    principal = staff(request)
    with SessionLocal() as db:
        case = case_for(db, case_id, principal.tenant_id)
        owner = _operator(db, case, principal.key_id)
        owner.assigned_to = principal.key_id
        owner.human_owned = body.action != "release"
        owner.resolved = body.action == "resolve"
        case.status = "resolved" if owner.resolved else "open"
        case.updated_at = datetime.utcnow()
        db.add(PlatformEventRow(id=uuid.uuid4().hex, tenant_id=case.tenant_id, case_id=case_id,
            event_type=f"operator.{body.action}", payload_json={"actor_id": principal.key_id}))
        db.commit()
        return {"ok": True, "status": case.status}


_ACTIONS = {"policy": "Answer policy questions", "order_status": "Read verified order status",
            "refund": "Process supervised refund requests", "return_damaged": "Collect damaged-return requests"}


from controlplane.automations import automation_enabled


@router.get("/automations")
def automations(request: Request):
    principal = staff(request)
    with SessionLocal() as db:
        runs = db.execute(select(WorkflowRunRow.workflow_name).where(WorkflowRunRow.tenant_id == principal.tenant_id,
            WorkflowRunRow.created_at > datetime.utcnow() - timedelta(days=7))).scalars().all()
        counts = Counter(runs)
    return {"items": [{"id": action, "name": name, "triggerText": name,
        "actionText": "Subject to identity, policy and human approval gates", "enabled": automation_enabled(principal.tenant_id, action),
        "runs7d": counts.get(action, 0)} for action, name in _ACTIONS.items()]}


@router.post("/automations/{action}/toggle")
def toggle(action: str, request: Request):
    principal = staff(request)
    if action not in _ACTIONS:
        raise HTTPException(404, "automation not found")
    enabled = not automation_enabled(principal.tenant_id, action)
    with SessionLocal() as db:
        row = db.get(PlatformTenantRow, principal.tenant_id)
        if row is None:
            row = PlatformTenantRow(tenant_id=principal.tenant_id, name=principal.tenant_id, config_json={})
            db.add(row)
        config = dict(row.config_json or {})
        values = dict(config.get("automations") or {})
        values[action] = enabled
        config["automations"] = values
        row.config_json = config
        db.commit()
    return {"ok": True, "enabled": enabled}


@router.get("/quality")
def quality(request: Request):
    principal = staff(request)
    from evaluation.autoqa import score_turn
    with SessionLocal() as db:
        rows = db.execute(select(InteractionRow).where(InteractionRow.tenant_id == principal.tenant_id)
            .order_by(InteractionRow.created_at.desc()).limit(100)).scalars().all()
        items = []
        for row in rows:
            if not row.case_id:
                continue
            score = score_turn({"id": row.interaction_id, "intent": row.intent, "response": row.response,
                "citations": row.citations, "metadata": row.metadata_json or {}})
            items.append({"id": row.interaction_id, "conversationId": row.case_id, "subject": row.intent or "Support",
                "agentKind": "ai", "policyScore": 100 if score["citation_ok"] else 0,
                "toneScore": 100 if score["refund_claim_ok"] else 0,
                "resolutionScore": 100 if score["outcome_ok"] else 0,
                "note": "Deterministic checks: citation presence, refund claims and outcome consistency. Semantic correctness is not scored."})
        return {"items": items}
