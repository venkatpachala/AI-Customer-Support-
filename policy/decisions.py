"""Structured result of a policy evaluation. No prose, no model output."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

DenyCode = Literal["AUTH", "AMOUNT", "OUT_OF_POLICY", "FRAUD", "MISSING_INPUT"]


class PolicyDecision(BaseModel):
    """What a later workflow is allowed to do. The engine never executes it.

    allowed and requires_approval can both be false-and-true together when the
    amount is above the manager cap: a human must see it, and nothing may
    auto-run. requires_inputs means ask the customer first. requires_strong_auth
    means challenge identity first. allowed False means do not move money.
    """

    model_config = ConfigDict(extra="ignore")

    allowed: bool
    requires_approval: bool = False
    requires_strong_auth: bool = False
    requires_inputs: List[str] = Field(default_factory=list)
    max_amount: Optional[float] = None
    reasons: List[str] = Field(default_factory=list)
    policy_id: str
    policy_version: str
    deny_code: Optional[DenyCode] = None
