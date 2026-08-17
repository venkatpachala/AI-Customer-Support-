from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
import uuid


class RuntimeEventType(str, Enum):
    SESSION_STARTED = "session_started"
    REQUEST_RECEIVED = "request_received"
    GUARDRAILS_COMPLETED = "guardrails_completed"
    IDENTITY_COMPLETED = "identity_completed"
    SUPERVISOR_COMPLETED = "supervisor_completed"
    PLANNER_COMPLETED = "planner_completed"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    VERIFIER_COMPLETED = "verifier_completed"
    HITL_COMPLETED = "hitl_completed"
    QA_COMPLETED = "qa_completed"
    ESCALATION_REQUESTED = "escalation_requested"
    RESPONSE_READY = "response_ready"
    REQUEST_FAILED = "request_failed"
    SESSION_ENDED = "session_ended"

    # Voice-ready (unused in Phase 0, reserved)
    USER_STARTED_SPEAKING = "user_started_speaking"
    USER_STOPPED_SPEAKING = "user_stopped_speaking"
    TRANSCRIPT_PARTIAL = "transcript_partial"
    TRANSCRIPT_FINAL = "transcript_final"
    ASSISTANT_STARTED = "assistant_started"
    ASSISTANT_FINISHED = "assistant_finished"
    ASSISTANT_INTERRUPTED = "assistant_interrupted"


@dataclass
class RuntimeEvent:
    type: RuntimeEventType
    request_id: str
    session_id: Optional[str] = None
    tenant_id: Optional[str] = None
    channel: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type.value,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "channel": self.channel,
            "ts": self.ts,
            "data": self.data,
        }