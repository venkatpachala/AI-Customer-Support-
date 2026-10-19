"""Product chat turn. Calls the existing /chat handler, then holds an explicit refund."""
from __future__ import annotations

from typing import Any, Dict, Optional

from starlette.requests import Request

from controlplane.mode import force_tools_mode, reset_tools_mode
from controlplane.reply import scrub_reply

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
    from runtime.chat_command import ChatCommand
    command = ChatCommand(body=body, session_id=session_cookie,
                          request_id=getattr(request.state, "request_id", ""),
                          client_host=request.client.host if request.client else "unknown",
                          idempotency_key=request.headers.get("Idempotency-Key", ""))
    token = force_tools_mode("mock" if force_mock else "live")
    try:
        result = await _chat_handler(command)
    finally:
        reset_tools_mode(token)
    if hasattr(result, "body"):
        try:
            import json
            data = json.loads(result.body.decode("utf-8"))
        except Exception:
            data = {"error": "chat failed"}
        status = getattr(result, "status_code", 200)
        if status >= 400:
            from fastapi import HTTPException
            raise HTTPException(status_code=status, detail=data.get("detail") or "support request failed")
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
    # A response wrapper must never create evidence or initiate a second workflow.
    status = payload.get("workflow_status")
    payload["response"] = scrub_reply(payload.get("response") or payload.get("error") or "", status)
    if status == "waiting_approval":
        payload["response"] = (
            "This refund is waiting for approval. No refund has been paid."
        )
    return payload
