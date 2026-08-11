from enum import Enum
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class AuthLevel(str, Enum):
    ANONYMOUS = "anonymous"
    IDENTIFIED = "identified"
    VERIFIED = "verified"


class IdentityChallenge(BaseModel):
    required: bool = True
    reason: str = "order_ownership_required"
    required_fields: List[str] = Field(default_factory=lambda: ["order_id", "contact"])
    message: str = (
        "To proceed with this request, please share your Order ID and the phone number "
        "or email used while placing the order so we can verify ownership."
    )


class IdentityResult(BaseModel):
    success: bool
    auth_level: AuthLevel = AuthLevel.ANONYMOUS
    order_id: Optional[str] = None
    customer_ref: Optional[str] = None
    method: Optional[str] = None
    matched_on: Optional[str] = None
    error_code: Optional[str] = None
    error: Optional[str] = None
    checked_at: datetime = Field(default_factory=datetime.utcnow)