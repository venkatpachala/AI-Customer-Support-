"""Supervisor queue page. The customer widget does not link here."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from identity.ops_session import COOKIE_NAME, TTL_SECONDS, credentials_match, issue_ops_token

router = APIRouter(tags=["ops"])
_PAGE = Path(__file__).resolve().parents[2] / "ops" / "index.html"


class LoginBody(BaseModel):
    username: str
    password: str


@router.get("/ops")
def ops_page():
    if not _PAGE.is_file():
        raise HTTPException(status_code=404, detail="ops page missing")
    return FileResponse(_PAGE)


@router.post("/v1/ops/login")
def ops_login(body: LoginBody):
    if not credentials_match(body.username, body.password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    response = JSONResponse({"role": "supervisor"})
    response.set_cookie(
        key=COOKIE_NAME,
        value=issue_ops_token(),
        httponly=True,
        samesite="lax",
        max_age=TTL_SECONDS,
        path="/",
    )
    return response
