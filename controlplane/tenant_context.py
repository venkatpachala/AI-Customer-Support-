"""Tenant identity for one request. The model and the JSON body do not set it."""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class TenantScope:
    tenant_id: str = ""
    request_id: str = ""
    case_id: str = ""


_scope: contextvars.ContextVar[TenantScope] = contextvars.ContextVar(
    "d2c_tenant_scope",
    default=TenantScope(),
)


def current_scope() -> TenantScope:
    return _scope.get()


def bind_scope(
    *,
    tenant_id: str = "",
    request_id: str = "",
    case_id: str = "",
):
    return _scope.set(
        TenantScope(
            tenant_id=tenant_id or "",
            request_id=request_id or "",
            case_id=case_id or "",
        )
    )


def reset_scope(token) -> None:
    _scope.reset(token)


def set_case_id(case_id: str) -> None:
    current = _scope.get()
    _scope.set(
        TenantScope(
            tenant_id=current.tenant_id,
            request_id=current.request_id,
            case_id=case_id or "",
        )
    )


@contextmanager
def use_tenant(tenant_id: str, *, request_id: str = "", case_id: str = "") -> Iterator[TenantScope]:
    token = bind_scope(tenant_id=tenant_id, request_id=request_id, case_id=case_id)
    try:
        yield _scope.get()
    finally:
        reset_scope(token)


def reject_body_tenant(body_tenant: Optional[str], tenant_id: str) -> Optional[str]:
    """Return an error when the body tries to name a different tenant."""
    supplied = str(body_tenant or "").strip()
    if not supplied or supplied == tenant_id:
        return None
    return "tenant_id is taken from the key or session"
