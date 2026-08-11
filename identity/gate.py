from typing import Dict, Any, List, Optional

from identity.models import AuthLevel
from common.messages import get_last_user_message

try:
    # optional helpers if present
    from identity.service import extract_order_id
except Exception:  # pragma: no cover
    import re

    def extract_order_id(text: str) -> Optional[str]:
        match = re.search(r"(?:order\s*#?|#)?(\d{5,})", text or "", re.IGNORECASE)
        return match.group(1) if match else None


SENSITIVE_KEYWORDS = [
    "return",
    "refund",
    "cancel",
    "replacement",
    "replace",
    "damaged",
    "order status",
    "track my order",
]

_LEVEL = {
    AuthLevel.ANONYMOUS.value: 0,
    "anonymous": 0,
    AuthLevel.IDENTIFIED.value: 1,
    "identified": 1,
    AuthLevel.VERIFIED.value: 2,
    "verified": 2,
}


def _message_looks_sensitive(message: str) -> bool:
    text = (message or "").lower()
    return any(k in text for k in SENSITIVE_KEYWORDS)


def _is_sensitive_intent(intent: str) -> bool:
    intent = (intent or "").lower()
    return any(k in intent for k in ["return", "refund", "cancel", "replace", "replacement"])


def _has_sufficient_auth(current: str, required: str) -> bool:
    return _LEVEL.get((current or "anonymous").lower(), 0) >= _LEVEL.get((required or "anonymous").lower(), 0)


def identity_gate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trusted-context identity gate.

    Production model:
    - Do NOT collect phone/email in free-text chat
    - Rely on gateway/backend auth context:
        auth_level: anonymous | identified | verified
        verified: bool
        verified_order_ids: list[str]
    - Sensitive actions require minimum auth
    - High-value actions require verified
    """
    intent = (state.get("intent") or "").lower().strip()
    risk_level = (state.get("risk_level") or "low").lower().strip()
    memory = state.get("memory_context") or {}
    message = get_last_user_message(state.get("messages", [])) or ""

    # Prefer explicit request auth context, then memory
    auth_level = (
        state.get("auth_level")
        or memory.get("auth_level")
        or AuthLevel.ANONYMOUS.value
    )
    auth_level = str(auth_level).lower().strip()

    verified = bool(state.get("verified") or auth_level == AuthLevel.VERIFIED.value)
    if verified:
        auth_level = AuthLevel.VERIFIED.value

    verified_order_ids: List[str] = list(
        state.get("verified_order_ids")
        or memory.get("verified_order_ids")
        or []
    )

    tenant_config = state.get("tenant_config") or {}
    refund_limit = float(tenant_config.get("refund_auto_limit", 2000))
    amount = float(state.get("refund_amount") or state.get("amount") or 0)

    order_id = (
        state.get("resolved_order_id")
        or memory.get("active_order_id")
        or extract_order_id(message)
    )

    sensitive = _is_sensitive_intent(intent) or _message_looks_sensitive(message)

    print(
        f"[IDENTITY] intent={intent!r} risk={risk_level!r} auth={auth_level!r} "
        f"verified={verified} sensitive={sensitive} amount={amount} order_id={order_id!r}"
    )

    # Non-sensitive (policy FAQs etc.) → pass
    if not sensitive:
        return {
            "needs_identity": False,
            "identity_blocked": False,
            "auth_level": auth_level,
            "identity_challenge": None,
            "resolved_order_id": order_id,
        }

    # Already good enough and no order mismatch checks needed
    # Determine required auth
    if amount >= refund_limit or risk_level in ("high", "critical"):
        required = AuthLevel.VERIFIED.value
    else:
        required = AuthLevel.IDENTIFIED.value

    # High-value / high-risk must be verified
    if required == AuthLevel.VERIFIED.value and not _has_sufficient_auth(auth_level, required):
        msg = (
            "For security, high-value or high-risk refund/return requests require a verified account. "
            "Please continue from your logged-in account or contact support."
        )
        print("[IDENTITY] blocked: verified required")
        return {
            "needs_identity": True,
            "identity_blocked": True,
            "needs_escalation": True,
            "escalation_reason": "Sensitive high-value action requires verified customer context",
            "auth_level": auth_level,
            "resolved_order_id": order_id,
            "identity_challenge": {
                "type": "verification_required",
                "message": msg,
            },
        }

    # Normal sensitive actions require at least identified
    if not _has_sufficient_auth(auth_level, required):
        msg = (
            "To proceed with this request, please continue from your logged-in account "
            "so we can securely match your order."
        )
        print("[IDENTITY] blocked: identified required")
        return {
            "needs_identity": True,
            "identity_blocked": True,
            "needs_escalation": False,
            "auth_level": auth_level,
            "resolved_order_id": order_id,
            "missing_inputs": ["login"],
            "identity_challenge": {
                "type": "login_required",
                "message": msg,
            },
        }

    # If backend provided verified order list, enforce membership when order_id known
    if order_id and verified_order_ids:
        if str(order_id) not in set(str(x) for x in verified_order_ids):
            msg = (
                "We could not match that order to your verified account. "
                "Please check the order ID or contact support."
            )
            print("[IDENTITY] blocked: order not in verified_order_ids")
            return {
                "needs_identity": True,
                "identity_blocked": True,
                "needs_escalation": True,
                "escalation_reason": "Order not linked to verified customer context",
                "auth_level": auth_level,
                "resolved_order_id": order_id,
                "identity_challenge": {
                    "type": "order_mismatch",
                    "message": msg,
                },
            }

    # If sensitive but no order id yet, allow flow to continue and ask for order id
    # (do not ask for phone/email contact in chat)
    missing: List[str] = []
    if not order_id:
        missing.append("order_id")

    if missing:
        print(f"[IDENTITY] pass with missing inputs: {missing}")
        return {
            "needs_identity": False,
            "identity_blocked": False,
            "auth_level": auth_level,
            "resolved_order_id": order_id,
            "missing_inputs": missing,
            "identity_challenge": {
                "type": "missing_order_id",
                "message": "Please share your Order ID so we can continue with this request.",
            },
        }

    print(f"[IDENTITY] pass auth_level={auth_level}")
    return {
        "needs_identity": False,
        "identity_blocked": False,
        "auth_level": auth_level,
        "identity_challenge": None,
        "resolved_order_id": order_id,
        "verified_order_ids": verified_order_ids,
    }