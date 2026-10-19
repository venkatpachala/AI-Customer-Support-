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


def session_principal(request: Request) -> Optional[Principal]:
    """Bearer key wins. An owner cookie is that tenant's supervisor in test mode."""
    if request.headers.get("authorization", "").lower().startswith("session "):
        return None
    principal = bearer_principal(request)
    if principal is not None:
        return principal
    from identity.owner_session import COOKIE_NAME, read_owner
    from controlplane.keys import tenant_record

    tenant_id = read_owner(request.cookies.get(COOKIE_NAME))
    if not tenant_id:
        return None
    row = tenant_record(tenant_id)
    return Principal(
        key_id="owner-session",
        tenant_id=tenant_id,
        role="supervisor",
        mode="test",
        prefix="owner",
        sandbox_passed_at=None if row is None else row.sandbox_passed_at,
        killed_at=None if row is None else row.killed_at,
    )


def require_principal(request: Request) -> Principal:
    principal = session_principal(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="api key required")
    return principal
