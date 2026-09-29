"""Caller-supplied facts. The engine does not look anything else up."""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from policy.rules import coerce_bool, normalize_token, parse_amount


class PolicySlots(BaseModel):
    """Facts already known about the order. Missing facts stay None."""

    model_config = ConfigDict(extra="ignore")

    order_id: Optional[str] = None
    amount: Optional[float] = None
    reason: Optional[str] = None
    photos_received: bool = False
    order_status: Optional[str] = None
    days_since_delivery: Optional[int] = None
    product_category: Optional[str] = None


class PolicyInput(BaseModel):
    """One evaluation request. Built by the engine from evaluate() arguments."""

    model_config = ConfigDict(extra="ignore")

    tenant_id: str
    action: str
    auth_level: str = "anonymous"
    slots: PolicySlots = Field(default_factory=PolicySlots)


def slots_from_mapping(raw: Optional[Dict[str, Any]]) -> PolicySlots:
    """Accept the loose dict callers pass and coerce amount, reason, and photos."""
    if not raw:
        return PolicySlots()
    data = dict(raw)
    if "amount" in data:
        data["amount"] = parse_amount(data.get("amount"))
    if "reason" in data and data["reason"] is not None:
        data["reason"] = normalize_token(data["reason"]) or None
    if "order_status" in data and data["order_status"] is not None:
        data["order_status"] = normalize_token(data["order_status"]) or None
    if "photos_received" in data:
        data["photos_received"] = coerce_bool(data.get("photos_received"))
    if "order_id" in data and data["order_id"] is not None:
        text = str(data["order_id"]).strip()
        data["order_id"] = text or None
    if "product_category" in data and data["product_category"] is not None:
        data["product_category"] = normalize_token(data["product_category"]) or None
    days = data.get("days_since_delivery")
    if days is None or days == "":
        data["days_since_delivery"] = None
    elif isinstance(days, bool):
        data["days_since_delivery"] = None
    else:
        try:
            data["days_since_delivery"] = int(days)
        except (TypeError, ValueError):
            data["days_since_delivery"] = None
    return PolicySlots.model_validate(data)
