from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime
import uuid


class InteractionRecord(BaseModel):
    interaction_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str  # session_id
    case_id: Optional[str] = None
    tenant_id: str
    customer_id: str
    channel: str = "chat"

    message: str
    response: str

    intent: Optional[str] = None
    risk_level: Optional[str] = None
    order_id: Optional[str] = None

    missing_inputs: List[str] = Field(default_factory=list)
    photos_requested: bool = False
    photos_received: bool = False

    tools_used: List[str] = Field(default_factory=list)
    tool_statuses: Dict[str, str] = Field(default_factory=dict)
    tool_results_summary: Dict[str, Any] = Field(default_factory=dict)

    escalated: bool = False
    blocked: bool = False
    escalation_reason: Optional[str] = None

    citations: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    latency_ms: float = 0.0

    status: str = "open"  # open | waiting_customer | escalated | blocked | resolved
    request_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)