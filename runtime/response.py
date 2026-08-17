from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RuntimeResponse:
    """
    Stable response contract for all channels.
    Chat maps this to existing JSON.
    Voice will later map text → TTS.
    """
    response: str
    confidence: float = 0.0
    citations: List[str] = field(default_factory=list)
    escalated: bool = False
    blocked: bool = False
    reason: Optional[str] = None
    tool_results: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    case_id: Optional[str] = None
    missing_inputs: List[str] = field(default_factory=list)
    auth_level: Optional[str] = None
    identity_blocked: bool = False
    intent: Optional[str] = None
    risk_level: Optional[str] = None
    status: Optional[str] = None
    order_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_chat_dict(self) -> Dict[str, Any]:
        if self.error:
            return {
                "error": self.error,
                "escalated": self.escalated,
                "request_id": self.request_id,
                "session_id": self.session_id,
            }
        return {
            "response": self.response,
            "confidence": self.confidence,
            "citations": self.citations,
            "escalated": self.escalated,
            "blocked": self.blocked,
            "reason": self.reason if self.escalated else None,
            "tool_results": self.tool_results,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "case_id": self.case_id,
            "missing_inputs": self.missing_inputs,
            "auth_level": self.auth_level,
            "identity_blocked": self.identity_blocked,
        }