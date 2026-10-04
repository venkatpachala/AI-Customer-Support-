"""Public widget session. Sets the httpOnly cookie /chat requires."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from identity.session import COOKIE_NAME, SESSION_TTL, create_customer_session

router = APIRouter(tags=["sessions"])


class SessionBody(BaseModel):
    tenant_id: str
    customer_ref: str


@router.post("/v1/sessions")
def open_session(body: SessionBody):
    try:
        row = create_customer_session(body.tenant_id, body.customer_ref)
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
