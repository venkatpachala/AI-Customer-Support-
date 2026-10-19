"""Public widget session. Sets the httpOnly cookie /chat requires."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from controlplane.http import bearer_principal
from controlplane.tenant_context import reject_body_tenant, use_tenant
from identity.session import COOKIE_NAME, SESSION_TTL, create_customer_session

router = APIRouter(tags=["sessions"])


class SessionBody(BaseModel):
    tenant_id: Optional[str] = None
    customer_ref: str


def _session_response(row):
    response = JSONResponse({"session_id": row.id, "tenant_id": row.tenant_id})
    response.set_cookie(
        key=COOKIE_NAME,
        value=row.id,
        httponly=True,
        samesite="lax",
        secure=__import__("controlplane.settings", fromlist=["cookie_secure"]).cookie_secure(),
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
    )
    return response


@router.post("/v1/sessions")
def open_session(body: SessionBody, request: Request):
    principal = bearer_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="api key required")
    if principal.killed_at is not None:
        raise HTTPException(status_code=403, detail="tenant chat is disabled")
    mismatch = reject_body_tenant(body.tenant_id, principal.tenant_id)
    if mismatch:
        raise HTTPException(status_code=400, detail=mismatch)
    with use_tenant(principal.tenant_id):
        try:
            row = create_customer_session(principal.tenant_id, body.customer_ref)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _session_response(row)


@router.post("/w/{tenant}/session")
def open_widget_session(tenant: str, body: SessionBody, request: Request):
    """The iframe path is the tenant. A body tenant_id cannot point somewhere else."""
    safe = "".join(ch for ch in tenant if ch.isalnum() or ch in {"_", "-"})
    if not safe:
        raise HTTPException(status_code=400, detail="tenant is required")
    from controlplane.shared_limits import allow
    if not allow("widget-session:" + (request.client.host if request.client else "unknown"), 30):
        raise HTTPException(429, "session creation limit reached")
    from controlplane.keys import tenant_record
    row = tenant_record(safe)
    if row is None or row.killed_at is not None:
        raise HTTPException(status_code=404, detail="brand is unavailable")
    mismatch = reject_body_tenant(body.tenant_id, safe)
    if mismatch:
        raise HTTPException(status_code=400, detail=mismatch)
    with use_tenant(safe):
        try:
            import secrets
            # An anonymous visitor may not select another customer's memory key.
            row = create_customer_session(safe, "visitor_" + secrets.token_urlsafe(18))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _session_response(row)
