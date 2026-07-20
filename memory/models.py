from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid


class SessionMemory(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    customer_id: str
    tenant_id: str
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    active_case_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CaseMemory(BaseModel):
    case_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    customer_id: str
    tenant_id: str
    order_id: Optional[str] = None
    issue_type: Optional[str] = None  # return | refund | cancel | track | general
    status: str = "open"  # open | waiting_customer | escalated | resolved
    missing_inputs: List[str] = Field(default_factory=list)
    photos_requested: bool = False
    photos_received: bool = False
    tools_executed: List[str] = Field(default_factory=list)
    tool_results_summary: Dict[str, Any] = Field(default_factory=dict)
    policy_citations: List[str] = Field(default_factory=list)
    escalation_reason: Optional[str] = None
    last_agent_action: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)