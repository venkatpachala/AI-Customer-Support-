"""Public widget session. Sets the httpOnly cookie /chat requires."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from controlplane.http import bearer_principal
from identity.session import COOKIE_NAME, SESSION_TTL, create_customer_session

router = APIRouter(tags=["sessions"])


class SessionBody(BaseModel):
    tenant_id: Optional[str] = None
    customer_ref: str


@router.post("/v1/sessions")
def open_session(body: SessionBody, request: Request):
    principal = bearer_principal(request)
    # A bearer key names the tenant. The body value is ignored when a key is present.
    tenant_id = principal.tenant_id if principal is not None else (body.tenant_id or "")
    try:
        row = create_customer_session(tenant_id, body.customer_ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = JSONResponse({"session_id": row.id, "tenant_id": row.tenant_id})
    response.set_cookie(
        key=COOKIE_NAME,
        value=row.id,
        httponly=True,
        samesite="lax",
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
    )
    return response
