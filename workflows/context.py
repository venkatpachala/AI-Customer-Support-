"""Inputs a workflow run is started with. Slots are caller facts, not lookups."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from db.session import SessionLocal
from tools.registry import TOOL_REGISTRY


@dataclass
class WorkflowContext:
    tenant_id: str
    case_id: str
    customer_id: str
    auth_level: str = "anonymous"
    conversation_id: Optional[str] = None
    slots: Dict[str, Any] = field(default_factory=dict)
    tool_registry: Any = None
    session_factory: Callable[[], Any] = SessionLocal

    def __post_init__(self) -> None:
        if self.tool_registry is None:
            self.tool_registry = TOOL_REGISTRY
        self.slots = dict(self.slots or {})
        self.auth_level = (self.auth_level or "anonymous").strip().lower()

    def snapshot(self, workflow_name: str) -> Dict[str, Any]:
        """JSON stored on the run so resume does not need the original object."""
        return {
            "workflow": workflow_name,
            "tenant_id": self.tenant_id,
            "case_id": self.case_id,
            "customer_id": self.customer_id,
            "conversation_id": self.conversation_id,
            "auth_level": self.auth_level,
            "slots": dict(self.slots),
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: Dict[str, Any],
        *,
        tool_registry: Any,
        session_factory: Callable[[], Any],
    ) -> "WorkflowContext":
        return cls(
            tenant_id=str(payload.get("tenant_id") or ""),
            case_id=str(payload.get("case_id") or ""),
            customer_id=str(payload.get("customer_id") or ""),
            auth_level=str(payload.get("auth_level") or "anonymous"),
            conversation_id=payload.get("conversation_id"),
            slots=dict(payload.get("slots") or {}),
            tool_registry=tool_registry,
            session_factory=session_factory,
        )
