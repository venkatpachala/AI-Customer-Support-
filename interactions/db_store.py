import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select, desc

from db.session import SessionLocal
from db.models import InteractionRow


class InteractionRecord:
    def __init__(self, row: InteractionRow):
        self.interaction_id = row.interaction_id
        self.conversation_id = row.conversation_id
        self.case_id = row.case_id
        self.tenant_id = row.tenant_id
        self.customer_id = row.customer_id
        self.channel = row.channel
        self.message = row.message
        self.response = row.response
        self.intent = row.intent
        self.risk_level = row.risk_level
        self.order_id = row.order_id
        self.missing_inputs = list(row.missing_inputs or [])
        self.photos_requested = bool(row.photos_requested)
        self.photos_received = bool(row.photos_received)
        self.tools_used = list(row.tools_used or [])
        self.tool_statuses = dict(row.tool_statuses or {})
        self.tool_results_summary = dict(row.tool_results_summary or {})
        self.escalated = bool(row.escalated)
        self.blocked = bool(row.blocked)
        self.escalation_reason = row.escalation_reason
        self.citations = list(row.citations or [])
        self.confidence = float(row.confidence or 0.0)
        self.latency_ms = float(row.latency_ms or 0.0)
        self.status = row.status
        self.request_id = row.request_id
        self.created_at = row.created_at.isoformat() if row.created_at else None
        self.metadata = dict(row.metadata_json or {})

    def dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


class InteractionDBStore:
    def log_chat_turn(self, **kwargs) -> InteractionRecord:
        tool_results = kwargs.get("tool_results") or {}
        tools_used = list(tool_results.keys())
        tool_statuses = {
            k: (v.get("status") if isinstance(v, dict) else None)
            for k, v in tool_results.items()
        }
        tool_results_summary = {
            k: {
                "status": (v.get("status") if isinstance(v, dict) else None),
                "error_code": (v.get("error_code") if isinstance(v, dict) else None),
                "latency_ms": (v.get("latency_ms") if isinstance(v, dict) else None),
            }
            for k, v in tool_results.items()
        }

        row = InteractionRow(
            interaction_id=str(uuid.uuid4()),
            conversation_id=kwargs.get("conversation_id"),
            case_id=kwargs.get("case_id"),
            tenant_id=kwargs.get("tenant_id"),
            customer_id=kwargs.get("customer_id"),
            channel=kwargs.get("channel", "chat"),
            message=kwargs.get("message") or "",
            response=kwargs.get("response") or "",
            intent=kwargs.get("intent"),
            risk_level=kwargs.get("risk_level"),
            order_id=kwargs.get("order_id"),
            missing_inputs=kwargs.get("missing_inputs") or [],
            photos_requested=bool(kwargs.get("photos_requested")),
            photos_received=bool(kwargs.get("photos_received")),
            tools_used=tools_used,
            tool_statuses=tool_statuses,
            tool_results_summary=tool_results_summary,
            escalated=bool(kwargs.get("escalated")),
            blocked=bool(kwargs.get("blocked")),
            escalation_reason=kwargs.get("escalation_reason"),
            citations=kwargs.get("citations") or [],
            confidence=float(kwargs.get("confidence") or 0.0),
            latency_ms=float(kwargs.get("latency_ms") or 0.0),
            status=kwargs.get("status") or "open",
            request_id=kwargs.get("request_id"),
            metadata_json=kwargs.get("metadata") or {},
        )

        with SessionLocal() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return InteractionRecord(row)

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
                stmt = stmt.where(InteractionRow.escalated.is_(escalated))
            stmt = stmt.order_by(desc(InteractionRow.created_at)).limit(limit)
            rows = db.execute(stmt).scalars().all()
            return [InteractionRecord(r) for r in rows]

    def list_by_conversation(self, conversation_id: str) -> List[InteractionRecord]:
        with SessionLocal() as db:
            stmt = (
                select(InteractionRow)
                .where(InteractionRow.conversation_id == conversation_id)
                .order_by(InteractionRow.created_at.asc())
            )
            rows = db.execute(stmt).scalars().all()
            return [InteractionRecord(r) for r in rows]