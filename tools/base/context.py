from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class ToolContext(BaseModel):
    request_id: str
    tenant_id: str
    customer_id: Optional[str] = None
    case_id: Optional[str] = None
    session_id: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)