from pydantic import BaseModel, Field
from typing import List, Dict, Optional

class ApprovalThresholds(BaseModel):
    refund_auto_approve_limit: float = 500.0
    high_value_refund_limit: float = 2000.0
    require_photos_for_return: bool = True

class BrandConfig(BaseModel):
    brand_name: str
    support_email: str
    tone: str = "professional, polite, concise"
    language: str = "en"

class ToolEndpoints(BaseModel):
    shopify_base_url: Optional[str] = None
    stripe_api_key_env: str = "STRIPE_API_KEY"
    custom_tools: Dict[str, str] = Field(default_factory=dict)

class EscalationConfig(BaseModel):
    contacts: List[str] = Field(default_factory=list)
    slack_webhook: Optional[str] = None
    escalate_on: List[str] = Field(default_factory=lambda: ["high_value_refund", "fraud", "low_confidence"])

class TenantConfig(BaseModel):
    tenant_id: str
    brand: BrandConfig
    approval: ApprovalThresholds
    tools: ToolEndpoints
    escalation: EscalationConfig
    policy_namespace: str = "default"
    active: bool = True