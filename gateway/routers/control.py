"""Product API. The bearer key is the tenant. Body tenant_id and auth_level are ignored."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from controlplane.http import require_principal, session_principal
from controlplane.connections import list_cards
from controlplane.keys import mark_sandbox_passed, set_killed, tenant_record, tenant_tools_live
from controlplane.knowledge import list_documents, store_pdf, uploads_allowed
from controlplane.quota import consume_chat
from controlplane.sandbox import STEPS, judge
from controlplane.tenant_context import reject_body_tenant, use_tenant
from controlplane.turns import run_product_chat
from controlplane.webhooks import get_endpoint, save_endpoint
from identity.session import COOKIE_NAME, create_customer_session, load_customer_session
from observability.logging import log_event

router = APIRouter(tags=["control-plane"])


@router.get("/v1/me")
def whoami(request: Request):
    principal = session_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="sign in required")
    row = tenant_record(principal.tenant_id)
    sandbox_passed = bool(row and row.sandbox_passed_at)
    live_enabled = bool(row and row.live_enabled_at)
    return {
        "tenant_id": principal.tenant_id,
        "name": principal.tenant_id if row is None or not row.name else row.name,
        "role": principal.role,
        "mode": principal.mode,
        "killed": principal.killed_at is not None,
        "sandbox_passed_at": None if row is None or row.sandbox_passed_at is None else row.sandbox_passed_at.isoformat(),
        "live_enabled": live_enabled,
        "refund_cap": __import__("config.tenant_contract", fromlist=["load_platform_tenant"]).load_platform_tenant(principal.tenant_id).limits.auto_refund_max,
        "connections": list_cards(
            principal.tenant_id,
            sandbox_passed=sandbox_passed,
            live_enabled=live_enabled,
        ),
    }


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
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
    principal = session_principal(request)
    if principal is not None:
        _guard_chat(principal)
        tenant_id = principal.tenant_id
        customer_ref = (body.customer_ref or "").strip() or "widget"
        try:
            existing = load_customer_session(request.cookies.get(COOKIE_NAME))
            session = existing if existing and existing.tenant_id == tenant_id and existing.customer_ref == customer_ref else create_customer_session(tenant_id, customer_ref)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session_id = session.id
    else:
        from identity.session import request_session_token
        loaded = load_customer_session(request_session_token(request))
        if loaded is None:
            raise HTTPException(status_code=401, detail="api key required")
        tenant_id = loaded.tenant_id
        customer_ref = loaded.customer_ref
        session_id = loaded.id
        row = tenant_record(tenant_id)
        if row is not None and row.killed_at is not None:
            raise HTTPException(status_code=403, detail="tenant chat is disabled")
    # A JSON tenant_id cannot switch the brand. The key or cookie already chose it.
    mismatch = reject_body_tenant(body.tenant_id, tenant_id)
    if mismatch:
        log_event(
            "tenant_body_ignored",
            getattr(request.state, "request_id", "") or "",
            node="gateway",
            data={"edge_tenant": tenant_id, "body_tenant": body.tenant_id},
        )
    live = tenant_tools_live(tenant_id, key_mode=principal.mode if principal is not None else "live")
    with use_tenant(tenant_id, request_id=getattr(request.state, "request_id", "") or ""):
        payload = await run_product_chat(
            request,
            tenant_id=tenant_id,
            customer_ref=customer_ref,
            message=body.message,
            session_cookie=session_id,
            force_mock=not live,
        )
    if payload.get("case_id"):
        from controlplane.tenant_context import set_case_id

        set_case_id(str(payload["case_id"]))
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
    from controlplane.knowledge import MAX_PDF_BYTES
    data = await file.read(MAX_PDF_BYTES + 1)
    try:
        from starlette.concurrency import run_in_threadpool
        view = await run_in_threadpool(store_pdf, principal.tenant_id, file.filename or "upload.pdf", data)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return view


@router.get("/v1/knowledge")
def knowledge_list(request: Request):
    principal = require_principal(request)
    return {"documents": list_documents(principal.tenant_id), "uploads_open": uploads_allowed(principal.tenant_id)}


@router.delete("/v1/knowledge/{snapshot_id}")
def knowledge_delete(snapshot_id: str, request: Request):
    principal = require_principal(request)
    if principal.role != "supervisor":
        raise HTTPException(403, "supervisor required")
    from controlplane.knowledge import delete_snapshot
    try:
        delete_snapshot(principal.tenant_id, snapshot_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"deleted": True}


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
