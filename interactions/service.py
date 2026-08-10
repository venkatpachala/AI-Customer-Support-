from typing import Any, Dict, List, Optional
from interactions.models import InteractionRecord
from interactions.store import InteractionStore


class InteractionService:
    def __init__(self):
        self.store = InteractionStore()

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
        tool_statuses = {}
        for k, v in (tool_results or {}).items():
            if isinstance(v, dict):
                tool_statuses[k] = str(v.get("status", "unknown"))
            else:
                tool_statuses[k] = "unknown"

        # keep summary small
        tool_summary = {}
        for k, v in (tool_results or {}).items():
            if isinstance(v, dict):
                tool_summary[k] = {
                    "status": v.get("status"),
                    "error_code": v.get("error_code"),
                    "latency_ms": v.get("latency_ms"),
                }

        record = InteractionRecord(
            conversation_id=conversation_id,
            case_id=case_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            channel="chat",
            message=message,
            response=response,
            intent=intent,
            risk_level=risk_level,
            order_id=order_id,
            missing_inputs=missing_inputs or [],
            photos_requested=photos_requested,
            photos_received=photos_received,
            tools_used=list((tool_results or {}).keys()),
            tool_statuses=tool_statuses,
            tool_results_summary=tool_summary,
            escalated=escalated,
            blocked=blocked,
            escalation_reason=escalation_reason,
            citations=citations or [],
            confidence=confidence or 0.0,
            latency_ms=latency_ms,
            status=status,
            request_id=request_id,
            metadata=metadata or {},
        )
        self.store.append(record)
        return record