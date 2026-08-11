from typing import Dict, Any, List
from identity.service import (
    identity_required,
    build_challenge,
    extract_order_id,
    extract_contact,
    identify_order_ownership,
)
from identity.models import AuthLevel
from common.messages import get_last_user_message


def _message_looks_sensitive(message: str) -> bool:
    text = (message or "").lower()
    keywords = [
        "return",
        "refund",
        "cancel",
        "replacement",
        "replace",
        "damaged",
        "order status",
        "track my order",
    ]
    return any(k in text for k in keywords)


def identity_gate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    intent = (state.get("intent") or "").lower().strip()
    risk_level = (state.get("risk_level") or "low").lower().strip()
    memory = state.get("memory_context") or {}
    auth_level = (memory.get("auth_level") or state.get("auth_level") or AuthLevel.ANONYMOUS.value)
    auth_level = str(auth_level).lower().strip()

    message = get_last_user_message(state.get("messages", [])) or ""

    # Already identified in this case/session
    if auth_level in (AuthLevel.IDENTIFIED.value, AuthLevel.VERIFIED.value):
        print(f"[IDENTITY] skip: already {auth_level}")
        return {
            "needs_identity": False,
            "auth_level": auth_level,
            "identity_challenge": None,
        }

    required = identity_required(intent, risk_level, auth_level)
    if not required and _message_looks_sensitive(message):
        # fallback when supervisor intent is composite/noisy
        required = True

    print(
        f"[IDENTITY] intent={intent!r} risk={risk_level!r} auth={auth_level!r} required={required}"
    )

    if not required:
        return {
            "needs_identity": False,
            "auth_level": auth_level,
            "identity_challenge": None,
        }

    order_id = (
        state.get("resolved_order_id")
        or memory.get("active_order_id")
        or extract_order_id(message)
    )
    contact = (
        state.get("customer_contact")
        or memory.get("customer_contact")
        or extract_contact(message)
    )

    print(f"[IDENTITY] order_id={order_id!r} contact={contact!r}")

    missing: List[str] = []
    if not order_id:
        missing.append("order_id")
    if not contact:
        missing.append("contact")

    if missing:
        challenge = build_challenge("missing_identity_fields")
        print(f"[IDENTITY] challenge missing fields: {missing}")
        return {
            "needs_identity": True,
            "identity_challenge": challenge.dict(),
            "missing_inputs": missing,
            "auth_level": AuthLevel.ANONYMOUS.value,
            "resolved_order_id": order_id,
            "customer_contact": contact,
        }

    result = identify_order_ownership(order_id, contact)
    print(
        f"[IDENTITY] ownership success={result.success} "
        f"error_code={result.error_code} matched_on={result.matched_on}"
    )

    if not result.success:
        challenge = build_challenge(result.error_code or "ownership_failed")
        challenge.message = (
            "We could not verify order ownership with the details provided. "
            "Please re-check your Order ID and the phone/email used while placing the order."
        )
        return {
            "needs_identity": True,
            "identity_result": result.dict(),
            "identity_challenge": challenge.dict(),
            "auth_level": AuthLevel.ANONYMOUS.value,
            "resolved_order_id": order_id,
            "customer_contact": contact,
        }

    return {
        "needs_identity": False,
        "identity_result": result.dict(),
        "identity_challenge": None,
        "auth_level": AuthLevel.IDENTIFIED.value,
        "resolved_order_id": order_id,
        "customer_contact": contact,
    }