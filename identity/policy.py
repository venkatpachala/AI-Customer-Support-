from typing import List, Optional, Set

SENSITIVE_INTENTS = {
    "refund", "return", "cancel", "replacement", "replace"
}

def normalize_intent(intent: str) -> str:
    return (intent or "").lower().strip()


def is_sensitive_intent(intent: str) -> bool:
    intent = normalize_intent(intent)
    return any(s in intent for s in SENSITIVE_INTENTS)


def required_auth_level(intent: str, amount: float = 0.0, refund_limit: float = 2000.0) -> str:
    """
    Returns minimum auth level required.
    anonymous < identified < verified
    """
    if not is_sensitive_intent(intent):
        return "anonymous"

    # high-value always needs verified
    if amount and amount >= refund_limit:
        return "verified"

    # normal return/refund/cancel
    return "identified"


_LEVEL = {"anonymous": 0, "identified": 1, "verified": 2}


def has_sufficient_auth(current: str, required: str) -> bool:
    return _LEVEL.get((current or "anonymous").lower(), 0) >= _LEVEL.get(required, 0)


def order_is_verified(order_id: Optional[str], verified_order_ids: List[str] | None) -> bool:
    if not order_id:
        return False
    allowed: Set[str] = set(verified_order_ids or [])
    return str(order_id) in allowed