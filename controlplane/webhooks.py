"""One delivery per decision. A failed POST is logged and is not a second charge."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from urllib import error, request

from sqlalchemy import select

from db.models import WebhookDeliveryRow, WebhookEndpointRow
from db.session import SessionLocal


def save_endpoint(tenant_id: str, url: str, session_factory=SessionLocal) -> Dict[str, Any]:
    target = (url or "").strip()
    from security.urls import validate_webhook_url
    validate_webhook_url(target)
    secret = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    with session_factory() as db:
        row = db.execute(
            select(WebhookEndpointRow).where(WebhookEndpointRow.tenant_id == tenant_id)
        ).scalars().first()
        if row is None:
            row = WebhookEndpointRow(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                url=target,
                secret=secret,
            )
            db.add(row)
        else:
            row.url = target
            if not row.secret:
                row.secret = secret
        db.commit()
        db.refresh(row)
        return _view(row)


def get_endpoint(tenant_id: str, session_factory=SessionLocal) -> Optional[Dict[str, Any]]:
    with session_factory() as db:
        row = db.execute(
            select(WebhookEndpointRow).where(WebhookEndpointRow.tenant_id == tenant_id)
        ).scalars().first()
        if row is None:
            return None
        return _view(row)


def deliver_decision(
    *,
    tenant_id: str,
    case_id: Optional[str],
    workflow_status: str,
    run_id: Optional[str],
    session_factory=SessionLocal,
) -> None:
    """Enqueue delivery; network failures never repeat the business operation."""
    from controlplane.outbox import enqueue
    with session_factory() as db:
        enqueue(db, tenant_id=tenant_id, key=f"decision:{run_id}:{workflow_status}", kind="webhook",
                payload={"case_id": case_id, "workflow_status": workflow_status, "run_id": run_id})
        db.commit()


def send_delivery(payload: dict, *, tenant_id: str, event_id: str, session_factory=SessionLocal) -> None:
    case_id, run_id = payload.get("case_id"), payload.get("run_id")
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    with session_factory() as db:
        row = db.execute(
            select(WebhookEndpointRow).where(WebhookEndpointRow.tenant_id == tenant_id)
        ).scalars().first()
        if row is None:
            return
        endpoint_id = row.id
        url = row.url
        secret = row.secret or ""
    from security.urls import validate_webhook_url
    validate_webhook_url(url)
    signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    status_code = None
    err = None
    try:
        req = request.Request(
            url,
            data=raw,
            headers={
                "Content-Type": "application/json",
                "X-D2C-Signature": signature,
                "X-D2C-Event-Id": event_id,
            },
            method="POST",
        )
        class NoRedirect(request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
        with opener.open(req, timeout=3) as response:
            status_code = int(response.status)
    except error.HTTPError as exc:
        status_code = int(exc.code)
        err = str(exc.reason or exc)[:500]
    except Exception as exc:
        err = str(exc)[:500]
    with session_factory() as db:
        db.add(
            WebhookDeliveryRow(
                id=str(uuid.uuid4()),
                endpoint_id=endpoint_id,
                tenant_id=tenant_id,
                case_id=case_id,
                run_id=run_id,
                status_code=status_code,
                error=err,
            )
        )
        endpoint = db.get(WebhookEndpointRow, endpoint_id)
        if endpoint is not None:
            endpoint.last_delivery_at = datetime.utcnow()
            if err or (status_code is not None and status_code >= 400):
                endpoint.last_status = "failed"
                endpoint.last_error = err or f"http {status_code}"
            else:
                endpoint.last_status = "delivered"
                endpoint.last_error = None
        db.commit()
    if err or status_code is None or not 200 <= status_code < 300:
        raise RuntimeError("webhook delivery failed")


def _view(row: WebhookEndpointRow) -> Dict[str, Any]:
    return {
        "id": row.id,
        "url": row.url,
        "last_status": row.last_status,
        "last_error": row.last_error,
        "last_delivery_at": None if row.last_delivery_at is None else row.last_delivery_at.isoformat(),
    }
