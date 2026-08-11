from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select, desc

from interactions.models import InteractionRecord
from db.session import SessionLocal
from db.models import InteractionRow


class InteractionService:
    """
    Durable interaction logging service.
    Keeps the same public API; storage is SQLite/Postgres.
    """

    def __init__(self):
        # keep attribute for compatibility with gateway code that uses interaction_service.store
        self.store = self

    def _row_to_record(self, row: InteractionRow) -> InteractionRecord:
        data = {
            "interaction_id": row.interaction_id,
            "conversation_id": row.conversation_id,
            "case_id": row.case_id,
            "tenant_id": row.tenant_id,
            "customer_id": row.customer_id,
            "channel": row.channel or "chat",
            "message": row.message or "",
            "response": row.response or "",
            "intent": row.intent,
            "risk_level": row.risk_level,
            "order_id": row.order_id,
            "missing_inputs": list(row.missing_inputs or []),
            "photos_requested": bool(row.photos_requested),
            "photos_received": bool(row.photos_received),
            "tools_used": list(row.tools_used or []),
            "tool_statuses": dict(row.tool_statuses or {}),
            "tool_results_summary": dict(row.tool_results_summary or {}),
            "escalated": bool(row.escalated),
            "blocked": bool(row.blocked),
            "escalation_reason": row.escalation_reason,
            "citations": list(row.citations or []),
            "confidence": float(row.confidence or 0.0),
            "latency_ms": float(row.latency_ms or 0.0),
            "status": row.status or "open",
            "request_id": row.request_id,
            "metadata": dict(row.metadata_json or {}),
            "created_at": row.created_at,
        }
        try:
            return InteractionRecord(**data)
        except TypeError:
            # fallback if model auto-generates some fields
            record = InteractionRecord(
                conversation_id=row.conversation_id,
                case_id=row.case_id,
                tenant_id=row.tenant_id,
                customer_id=row.customer_id,
                channel=row.channel or "chat",
                message=row.message or "",
                response=row.response or "",
                intent=row.intent,
                risk_level=row.risk_level,
                order_id=row.order_id,
                missing_inputs=list(row.missing_inputs or []),
                photos_requested=bool(row.photos_requested),
                photos_received=bool(row.photos_received),
                tools_used=list(row.tools_used or []),
                tool_statuses=dict(row.tool_statuses or {}),
                tool_results_summary=dict(row.tool_results_summary or {}),
                escalated=bool(row.escalated),
                blocked=bool(row.blocked),
                escalation_reason=row.escalation_reason,
                citations=list(row.citations or []),
                confidence=float(row.confidence or 0.0),
                latency_ms=float(row.latency_ms or 0.0),
                status=row.status or "open",
                request_id=row.request_id,
                metadata=dict(row.metadata_json or {}),
            )
            if hasattr(record, "interaction_id"):
                record.interaction_id = row.interaction_id
            return record

    def log_chat_turn(
        self,
        *,
        conversation_id: str,
        case_id: Optional[str],
        tenant_id: str,
        customer_id: str,
        message: str,
        response: str,
        intent: Optional[str],
        risk_level: Optional[str],
        order_id: Optional[str],
        missing_inputs: List[str],
        photos_requested: bool,
        photos_received: bool,
        tool_results: Dict[str, Any],
        escalated: bool,
        blocked: bool,
        escalation_reason: Optional[str],
        citations: List[str],
        confidence: float,
        latency_ms: float,
        status: str,
        request_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> InteractionRecord:
        tool_statuses: Dict[str, str] = {}
        for k, v in (tool_results or {}).items():
            if isinstance(v, dict):
                tool_statuses[k] = str(v.get("status", "unknown"))
            else:
                tool_statuses[k] = "unknown"

        tool_summary: Dict[str, Any] = {}
        for k, v in (tool_results or {}).items():
            if isinstance(v, dict):
                tool_summary[k] = {
                    "status": v.get("status"),
                    "error_code": v.get("error_code"),
                    "latency_ms": v.get("latency_ms"),
                }

        interaction_id = str(uuid.uuid4())
        row = InteractionRow(
            interaction_id=interaction_id,
            conversation_id=conversation_id,
            case_id=case_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel="chat",
            message=message or "",
            response=response or "",
            intent=intent,
            risk_level=risk_level,
            order_id=order_id,
            missing_inputs=missing_inputs or [],
            photos_requested=bool(photos_requested),
            photos_received=bool(photos_received),
            tools_used=list((tool_results or {}).keys()),
            tool_statuses=tool_statuses,
            tool_results_summary=tool_summary,
            escalated=bool(escalated),
            blocked=bool(blocked),
            escalation_reason=escalation_reason,
            citations=citations or [],
            confidence=float(confidence or 0.0),
            latency_ms=float(latency_ms or 0.0),
            status=status or "open",
            request_id=request_id,
            metadata_json=metadata or {},
        )

        with SessionLocal() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._row_to_record(row)

    def get_recent(
        self,
        limit: int = 20,
        tenant_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        escalated: Optional[bool] = None,
    ) -> List[InteractionRecord]:
        with SessionLocal() as db:
            stmt = select(InteractionRow)
            if tenant_id:
                stmt = stmt.where(InteractionRow.tenant_id == tenant_id)
            if customer_id:
                stmt = stmt.where(InteractionRow.customer_id == customer_id)
            if escalated is not None:
                stmt = stmt.where(InteractionRow.escalated.is_(bool(escalated)))
            stmt = stmt.order_by(desc(InteractionRow.created_at)).limit(limit)
            rows = db.execute(stmt).scalars().all()
            return [self._row_to_record(r) for r in rows]

    # Compatibility methods previously used via interaction_service.store
    def append(self, record: InteractionRecord) -> InteractionRecord:
        """
        Optional compatibility path if older code calls store.append(record).
        Prefer log_chat_turn().
        """
        return self.log_chat_turn(
            conversation_id=record.conversation_id,
            case_id=getattr(record, "case_id", None),
            tenant_id=record.tenant_id,
            customer_id=record.customer_id,
            message=record.message,
            response=record.response,
            intent=getattr(record, "intent", None),
            risk_level=getattr(record, "risk_level", None),
            order_id=getattr(record, "order_id", None),
            missing_inputs=list(getattr(record, "missing_inputs", []) or []),
            photos_requested=bool(getattr(record, "photos_requested", False)),
            photos_received=bool(getattr(record, "photos_received", False)),
            tool_results={
                k: {"status": v}
                for k, v in dict(getattr(record, "tool_statuses", {}) or {}).items()
            },
            escalated=bool(getattr(record, "escalated", False)),
            blocked=bool(getattr(record, "blocked", False)),
            escalation_reason=getattr(record, "escalation_reason", None),
            citations=list(getattr(record, "citations", []) or []),
            confidence=float(getattr(record, "confidence", 0.0) or 0.0),
            latency_ms=float(getattr(record, "latency_ms", 0.0) or 0.0),
            status=getattr(record, "status", "open") or "open",
            request_id=getattr(record, "request_id", None),
            metadata=dict(getattr(record, "metadata", {}) or {}),
        )

    def list_recent(self, limit: int = 50) -> List[InteractionRecord]:
        return self.get_recent(limit=limit)

    def list_by_conversation(self, conversation_id: str) -> List[InteractionRecord]:
        with SessionLocal() as db:
            stmt = (
                select(InteractionRow)
                .where(InteractionRow.conversation_id == conversation_id)
                .order_by(InteractionRow.created_at.asc())
            )
            rows = db.execute(stmt).scalars().all()
            return [self._row_to_record(r) for r in rows]