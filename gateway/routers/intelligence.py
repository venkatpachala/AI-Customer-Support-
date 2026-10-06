"""Read APIs for journey records. Newest interactions first. Timeline is oldest first."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request

from controlplane.http import bearer_principal
from interactions.intelligence import (
    IntelligenceError,
    case_timeline,
    intent_rollup,
    list_interactions,
)

router = APIRouter(tags=["intelligence"])


def _tenant(request: Request, header: Optional[str], query: Optional[str]) -> str:
    principal = bearer_principal(request)
    if principal is not None:
        tenant = principal.tenant_id
    else:
        tenant = (header or "").strip()
        if not tenant:
            raise HTTPException(status_code=400, detail="X-Tenant-Id is required")
    if query and query.strip() and query.strip() != tenant:
        raise HTTPException(status_code=403, detail="tenant header does not match tenant_id")
    return tenant


def _call(fn):
    try:
        return fn()
    except IntelligenceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/v1/interactions")
def get_interactions(
    request: Request,
    tenant_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    case_id: Optional[str] = None,
    outcome: Optional[str] = None,
    intent: Optional[str] = None,
    escalated: Optional[bool] = None,
    limit: int = Query(20, ge=1, le=100),
    x_tenant_id: Optional[str] = Header(default=None),
):
    """Newest first. Does not return tool payloads or secrets."""
    tenant = _tenant(request, x_tenant_id, tenant_id)
    items = list_interactions(
        tenant_id=tenant,
        customer_id=customer_id,
        case_id=case_id,
        outcome=outcome,
        intent=intent,
        escalated=escalated,
        limit=limit,
    )
    return {"items": items, "count": len(items), "order": "newest_first"}


@router.get("/v1/cases/{case_id}/timeline")
def get_case_timeline(
    case_id: str,
    request: Request,
    x_tenant_id: Optional[str] = Header(default=None),
):
    """Oldest first. 404 when the case is missing or belongs to another tenant."""
    tenant = _tenant(request, x_tenant_id, None)
    return _call(lambda: case_timeline(case_id, tenant))


@router.get("/v1/analytics/intents")
def get_intent_rollup(
    request: Request,
    tenant_id: Optional[str] = None,
    since: Optional[str] = None,
    x_tenant_id: Optional[str] = Header(default=None),
):
    """Counts for one tenant since an ISO timestamp. Default window is 7 days."""
    tenant = _tenant(request, x_tenant_id, tenant_id)
    return _call(lambda: intent_rollup(tenant, since))
