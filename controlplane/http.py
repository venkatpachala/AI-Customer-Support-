"""Bearer resolution for /v1 routes. Header auth stays when no key is sent."""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request

from controlplane.keys import AuthError, Principal, authenticate


def bearer_principal(request: Request) -> Optional[Principal]:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return None
    token = header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="invalid api key")
    try:
        return authenticate(token)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def require_principal(request: Request) -> Principal:
    principal = bearer_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="api key required")
    return principal
