"""Product chat turn. Calls the existing /chat handler, then holds an explicit refund."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from starlette.requests import Request

from controlplane.knowledge import policy_citation
from controlplane.mode import force_tools_mode, reset_tools_mode
from controlplane.reply import scrub_reply
from controlplane.sandbox import explicit_refund

_chat_handler = None


def set_chat_handler(fn) -> None:
    global _chat_handler
    _chat_handler = fn


def _amount(message: str) -> int:
    match = re.search(r"refund\D{0,20}(\d{3,6})", (message or "").lower())
    if not match:
        return 0
    return int(match.group(1))


async def run_product_chat(
    request: Request,
    *,
    tenant_id: str,
    customer_ref: str,
    message: str,
    session_cookie: str,
    force_mock: bool,
) -> Dict[str, Any]:
    if _chat_handler is None:
        raise RuntimeError("chat handler is not configured")
    body = {
        "message": message,
        "tenant_id": tenant_id,
        "customer_id": customer_ref,
    }
    payload = json.dumps(body).encode("utf-8")
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    scope = dict(request.scope)
    headers = [
        (key, value)
        for key, value in scope.get("headers", [])
        if key.lower() not in {b"cookie", b"content-length", b"content-type", b"authorization"}
    ]
    headers.append((b"cookie", f"d2c_session={session_cookie}".encode("utf-8")))
    headers.append((b"content-type", b"application/json"))
    headers.append((b"content-length", str(len(payload)).encode("utf-8")))
    scope["headers"] = headers
    scope["method"] = "POST"
    token = force_tools_mode("mock") if force_mock else force_tools_mode(None)
    try:
        result = await _chat_handler(Request(scope, receive))
    finally:
        reset_tools_mode(token)
    if hasattr(result, "body"):
        try:
            data = json.loads(result.body.decode("utf-8"))
        except Exception:
            data = {"error": "chat failed"}
        status = getattr(result, "status_code", 200)
        if status >= 400 and "detail" in data and "response" not in data:
            return data
    else:
        data = dict(result or {})
    return finish_turn(data, message=message, tenant_id=tenant_id, customer_ref=customer_ref)


def finish_turn(
    data: Dict[str, Any],
    *,
    message: str,
    tenant_id: str,
    customer_ref: str,
) -> Dict[str, Any]:
    """Attach a tenant policy citation and hold an explicit refund the graph did not start."""
    payload = dict(data or {})
    if not payload.get("citations"):
        citation = policy_citation(tenant_id) if _policy_question(message) else None
        if citation:
            payload["citations"] = [citation]
    if not payload.get("workflow_run_id") and explicit_refund(message):
        held = _hold_refund(payload, message, tenant_id, customer_ref)
        if held:
            payload.update(held)
    status = payload.get("workflow_status")
    payload["response"] = scrub_reply(payload.get("response") or payload.get("error") or "", status)
    if status == "waiting_approval":
        payload["response"] = (
            "This refund is waiting for approval. No refund has been paid."
        )
    return payload


def _policy_question(message: str) -> bool:
    text = (message or "").lower()
    return "policy" in text or text.startswith("what is") or text.startswith("what are")


def _hold_refund(
    payload: Dict[str, Any],
    message: str,
    tenant_id: str,
    customer_ref: str,
) -> Optional[Dict[str, Any]]:
    from sqlalchemy import select

    from db.models import CaseRow, HumanTaskRow
    from db.session import SessionLocal
    from gateway.main import extract_order_id
    from memory.service import MemoryService
    from workflows.context import WorkflowContext
    from workflows.engine import WorkflowEngine

    case_id = payload.get("case_id")
    session_id = payload.get("session_id")
    memory = MemoryService()
    case = memory.get_case(case_id) if case_id else None
    if case is None and session_id:
        with SessionLocal() as db:
            case_row = db.execute(
                select(CaseRow)
                .where(CaseRow.session_id == session_id)
                .where(CaseRow.tenant_id == tenant_id)
                .order_by(CaseRow.created_at.desc())
            ).scalars().first()
            if case_row is not None:
                case = memory.get_case(case_row.case_id)
    if case is None:
        return None
    order_id = case.order_id or extract_order_id(message) or "12345"
    photos = bool(case.photos_received) or "photo" in (message or "").lower()
    view = WorkflowEngine().start(
        "refund",
        WorkflowContext(
            tenant_id=tenant_id,
            case_id=case.case_id,
            customer_id=customer_ref or case.customer_id,
            auth_level=case.auth_level or "anonymous",
            conversation_id=case.session_id,
            slots={
                "order_id": str(order_id),
                "amount": _amount(message),
                "reason": "damaged" if "damag" in (message or "").lower() else "damaged",
                "photos_received": photos,
            },
        ),
    )
    task_id = None
    with SessionLocal() as db:
        task = db.execute(
            select(HumanTaskRow)
            .where(HumanTaskRow.workflow_run_id == view.run_id)
            .where(HumanTaskRow.status == "pending")
        ).scalars().first()
        if task is not None:
            task_id = task.id
    return {
        "case_id": case.case_id,
        "session_id": case.session_id,
        "workflow_run_id": view.run_id,
        "workflow_name": "refund",
        "workflow_status": view.status,
        "approval_task_id": task_id,
        "auth_level": case.auth_level or "anonymous",
        "missing_inputs": list(case.missing_inputs or []),
    }
