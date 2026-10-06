"""Product API. The bearer key is the tenant. Body tenant_id and auth_level are ignored."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from controlplane.http import bearer_principal, require_principal
from controlplane.keys import mark_sandbox_passed, set_killed, tenant_record
from controlplane.knowledge import list_documents, store_pdf, uploads_allowed
from controlplane.sandbox import STEPS, judge
from controlplane.turns import run_product_chat
from controlplane.webhooks import get_endpoint, save_endpoint
from identity.session import COOKIE_NAME, create_customer_session, load_customer_session

router = APIRouter(tags=["control-plane"])


class ChatBody(BaseModel):
    message: str
    customer_ref: Optional[str] = None
    tenant_id: Optional[str] = None
    auth_level: Optional[str] = None
    verified: Optional[bool] = None
    verified_customer: Optional[bool] = None
    verified_order_ids: Optional[list] = None


class WebhookBody(BaseModel):
    url: str


def _guard_chat(principal) -> None:
    if principal.killed_at is not None:
        raise HTTPException(status_code=403, detail="tenant chat is disabled")


@router.post("/v1/chat")
async def product_chat(body: ChatBody, request: Request):
    # Body tenant_id, auth_level, and verified are accepted and ignored.
    principal = bearer_principal(request)
    if principal is not None:
        _guard_chat(principal)
        tenant_id = principal.tenant_id
        customer_ref = (body.customer_ref or "").strip() or "widget"
        try:
            session = create_customer_session(tenant_id, customer_ref)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session_id = session.id
    else:
        loaded = load_customer_session(request.cookies.get(COOKIE_NAME))
        if loaded is None:
            raise HTTPException(status_code=401, detail="api key required")
        tenant_id = loaded.tenant_id
        customer_ref = loaded.customer_ref
        session_id = loaded.id
        row = tenant_record(tenant_id)
        if row is not None and row.killed_at is not None:
            raise HTTPException(status_code=403, detail="tenant chat is disabled")
    payload = await run_product_chat(
        request,
        tenant_id=tenant_id,
        customer_ref=customer_ref,
        message=body.message,
        session_cookie=session_id,
        force_mock=True,
    )
    if payload.get("detail") and not payload.get("response") and not payload.get("case_id"):
        raise HTTPException(status_code=400, detail=payload["detail"])
    payload["tenant_id"] = tenant_id
    payload.pop("verified", None)
    return payload


_turn_override = None


def set_turn_override(fn) -> None:
    global _turn_override
    _turn_override = fn


async def _sandbox_turn(request: Request, principal, message: str):
    if _turn_override is not None:
        return _turn_override(principal.tenant_id, message)
    session = create_customer_session(principal.tenant_id, "sandbox")
    return await run_product_chat(
        request,
        tenant_id=principal.tenant_id,
        customer_ref="sandbox",
        message=message,
        session_cookie=session.id,
        force_mock=True,
    )


@router.post("/v1/sandbox/run")
async def sandbox_run(request: Request):
    principal = require_principal(request)
    if principal.mode != "test":
        raise HTTPException(status_code=403, detail="sandbox runs on a test key")
    _guard_chat(principal)
    turns = []
    for step in STEPS:
        turns.append(await _sandbox_turn(request, principal, step["message"]))
    report = judge(turns)
    if report["passed"]:
        stamp = mark_sandbox_passed(principal.tenant_id)
        report["sandbox_passed_at"] = stamp.isoformat()
    else:
        row = tenant_record(principal.tenant_id)
        report["sandbox_passed_at"] = None if row is None or row.sandbox_passed_at is None else row.sandbox_passed_at.isoformat()
    report["turns"] = [
        {
            "message": STEPS[index]["message"],
            "workflow_status": turn.get("workflow_status"),
            "citations": turn.get("citations") or [],
            "missing_inputs": turn.get("missing_inputs") or [],
        }
        for index, turn in enumerate(turns)
    ]
    return report


@router.post("/v1/knowledge")
async def upload_knowledge(request: Request, file: UploadFile = File(...)):
    principal = require_principal(request)
    if principal.role != "supervisor":
        raise HTTPException(status_code=403, detail="supervisor key required")
    if not uploads_allowed(principal.tenant_id):
        raise HTTPException(
            status_code=403,
            detail="uploads are limited to tenant zepto until namespace isolation is proven",
        )
    data = await file.read()
    try:
        view = store_pdf(principal.tenant_id, file.filename or "upload.pdf", data)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return view


@router.get("/v1/knowledge")
def knowledge_list(request: Request):
    principal = require_principal(request)
    return {"documents": list_documents(principal.tenant_id), "uploads_open": uploads_allowed(principal.tenant_id)}


@router.post("/v1/webhooks")
def save_webhook(body: WebhookBody, request: Request):
    principal = require_principal(request)
    if principal.role != "supervisor":
        raise HTTPException(status_code=403, detail="supervisor key required")
    try:
        return save_endpoint(principal.tenant_id, body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/v1/webhooks")
def read_webhook(request: Request):
    principal = require_principal(request)
    return {"webhook": get_endpoint(principal.tenant_id)}


@router.post("/v1/tenant/kill")
def kill_tenant(request: Request):
    principal = require_principal(request)
    if principal.role != "supervisor":
        raise HTTPException(status_code=403, detail="supervisor key required")
    set_killed(principal.tenant_id, True)
    return {"killed": True, "tenant_id": principal.tenant_id}


@router.post("/v1/tenant/restore")
def restore_tenant(request: Request):
    principal = require_principal(request)
    if principal.role != "supervisor":
        raise HTTPException(status_code=403, detail="supervisor key required")
    set_killed(principal.tenant_id, False)
    return {"killed": False, "tenant_id": principal.tenant_id}
