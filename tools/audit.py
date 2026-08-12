import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select

from db.session import SessionLocal
from db.models import ToolCallRow


SIDE_EFFECTING_TOOLS = {
    "stripe_create_refund",
    "stripe.refund_payment",
    "shopify_initiate_return",
    "shopify_create_refund",
    "gmail_send_email",
    "gmail_send_escalation",
}


def is_side_effecting(tool_name: str) -> bool:
    return tool_name in SIDE_EFFECTING_TOOLS or "refund" in (tool_name or "").lower()


def stable_params_hash(params: Dict[str, Any]) -> str:
    payload = json.dumps(params or {}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def build_idempotency_key(
    tool_name: str,
    params: Dict[str, Any],
    tenant_id: str = "",
    customer_id: str = "",
    case_id: str = "",
) -> str:
    """
    For refunds: same tenant+customer+case+tool+critical params => same key.
    """
    critical = {
        "tool": tool_name,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "case_id": case_id,
        "order_id": params.get("order_id"),
        "payment_intent_id": params.get("payment_intent_id"),
        "amount": params.get("amount"),
        "currency": params.get("currency"),
    }
    raw = json.dumps(critical, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ToolAuditService:
    def get_by_idempotency_key(self, key: str) -> Optional[ToolCallRow]:
        if not key:
            return None
        with SessionLocal() as db:
            stmt = (
                select(ToolCallRow)
                .where(ToolCallRow.idempotency_key == key)
                .where(ToolCallRow.status == "success")
                .order_by(ToolCallRow.id.desc())
                .limit(1)
            )
            return db.execute(stmt).scalars().first()

    def start(
        self,
        *,
        tool_name: str,
        params: Dict[str, Any],
        request_id: str = None,
        session_id: str = None,
        case_id: str = None,
        tenant_id: str = None,
        customer_id: str = None,
        provider: str = None,
        operation: str = None,
        idempotency_key: str = None,
        attempts: int = 1,
    ) -> str:
        tool_call_id = str(uuid.uuid4())
        with SessionLocal() as db:
            row = ToolCallRow(
                tool_call_id=tool_call_id,
                idempotency_key=idempotency_key,
                request_id=request_id,
                session_id=session_id,
                case_id=case_id,
                tenant_id=tenant_id,
                customer_id=customer_id,
                tool_name=tool_name,
                provider=provider,
                operation=operation or tool_name,
                params_json=params or {},
                status="started",
                result_json={},
                attempts=attempts,
                side_effecting=is_side_effecting(tool_name),
            )
            db.add(row)
            db.commit()
        return tool_call_id

    def finish(
        self,
        tool_call_id: str,
        *,
        status: str,
        result: Dict[str, Any] = None,
        error: str = None,
        error_code: str = None,
        latency_ms: float = 0.0,
        attempts: int = 1,
    ) -> None:
        with SessionLocal() as db:
            row = db.execute(
                select(ToolCallRow).where(ToolCallRow.tool_call_id == tool_call_id)
            ).scalars().first()
            if not row:
                return
            row.status = status
            row.result_json = result or {}
            row.error = error
            row.error_code = error_code
            row.latency_ms = float(latency_ms or 0.0)
            row.attempts = attempts
            row.updated_at = datetime.utcnow()
            db.commit()