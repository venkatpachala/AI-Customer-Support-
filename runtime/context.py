from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AuthContext:
    auth_level: str = "anonymous"          # anonymous | identified | verified
    verified: bool = False
    verified_order_ids: List[str] = field(default_factory=list)
    verified_customer: bool = False
    contact: Optional[str] = None


@dataclass
class RequestContext:
    """
    Channel-agnostic request envelope.
    Chat, voice, and future WhatsApp all build this.
    """
    message: str
    tenant_id: str = "zepto"
    customer_id: str = "default"
    session_id: Optional[str] = None
    case_id: Optional[str] = None
    channel: str = "chat"                  # chat | voice | phone | whatsapp
    request_id: Optional[str] = None
    language: Optional[str] = None
    auth: AuthContext = field(default_factory=AuthContext)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_graph_seed(self) -> Dict[str, Any]:
        """Fields merged into LangGraph initial state."""
        return {
            "tenant_id": self.tenant_id,
            "customer_id": self.customer_id,
            "session_id": self.session_id,
            "case_id": self.case_id,
            "request_id": self.request_id,
            "channel": self.channel,
            "auth_level": self.auth.auth_level,
            "verified": self.auth.verified,
            "verified_order_ids": list(self.auth.verified_order_ids or []),
            "verified_customer": self.auth.verified_customer,
            "customer_contact": self.auth.contact,
            "language": self.language,
        }