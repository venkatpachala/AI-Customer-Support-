import re
from typing import Optional, Dict, Any, List

from identity.models import AuthLevel, IdentityChallenge, IdentityResult
from tools.shopify.identify import shopify_identify_customer


SENSITIVE_INTENTS = {
    "return",
    "refund",
    "cancel",
    "replacement",
    "order_status",
    "track",
}


def extract_order_id(text: str) -> Optional[str]:
    if not text:
        return None

    patterns = [
        r"(?:order\s*(?:id|number|#)?\s*(?:is|=|:)?\s*)(\d{4,})",
        r"(?:order\s*#?|#)\s*(\d{4,})",
        r"\border\b.*?(\d{4,})",
        r"\b(\d{5,})\b",
    ]
    for p in patterns:
        match = re.search(p, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def extract_contact(text: str) -> Optional[str]:
    if not text:
        return None

    email = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    if email:
        return email.group(0).lower()

    phone = re.search(r"(?:\+?91[\s-]?)?[6-9]\d{9}\b", text)
    if phone:
        digits = re.sub(r"\D", "", phone.group(0))
        return digits[-10:]
    return None


def user_has_no_order_id(text: str) -> bool:
    t = (text or "").lower()
    phrases = [
        "don't have order",
        "dont have order",
        "no order id",
        "no order number",
        "order id is not there",
        "don't know order",
        "dont know order",
        "lost my order",
        "no orderid",
        "i don't have",
        "i dont have",
    ]
    return any(p in t for p in phrases)


def identity_required(
    intent: str,
    risk_level: str,
    auth_level: str,
    message: str = "",
) -> bool:
    intent = (intent or "").lower().strip()
    auth_level = (auth_level or "anonymous").lower().strip()
    risk_level = (risk_level or "low").lower().strip()
    message = (message or "").lower()

    if auth_level in ("identified", "verified"):
        return False

    if any(s in intent for s in SENSITIVE_INTENTS):
        return True

    # Fallback when supervisor intent is missing/empty at gate time
    if any(
        k in message
        for k in (
            "return",
            "refund",
            "cancel",
            "replacement",
            "replace",
            "damaged",
            "order status",
            "track my order",
        )
    ):
        return True

    if risk_level in ("high", "critical"):
        return True

    return False


def build_challenge(reason: str = "order_ownership_required") -> IdentityChallenge:
    messages = {
        "order_ownership_required": (
            "To proceed with this request, please share your Order ID and the phone number "
            "or email used while placing the order so we can verify ownership."
        ),
        "missing_identity_fields": (
            "To proceed with this request, please share your Order ID and the phone number "
            "or email used while placing the order so we can verify ownership."
        ),
        "ownership_failed": (
            "We could not verify order ownership with those details. "
            "Please re-check the Order ID and the phone/email used on the order."
        ),
        "no_order_id": (
            "No problem. Without an order ID I can't complete a return automatically. "
            "Please share the phone or email used on the order, or ask to speak with support."
        ),
    }
    return IdentityChallenge(
        required=True,
        reason=reason,
        required_fields=["order_id", "contact"],
        message=messages.get(reason, messages["order_ownership_required"]),
    )


def identify_order_ownership(order_id: str, contact: str) -> IdentityResult:
    raw = shopify_identify_customer(order_id=order_id, contact=contact)
    data = raw.get("data") or {}

    return IdentityResult(
        success=bool(data.get("success")),
        auth_level=AuthLevel(data.get("auth_level") or AuthLevel.ANONYMOUS.value),
        order_id=data.get("order_id") or order_id,
        customer_ref=data.get("customer_ref"),
        method=data.get("method"),
        matched_on=data.get("matched_on"),
        error_code=raw.get("error_code") or data.get("error_code"),
        error=raw.get("error") or data.get("error"),
    )