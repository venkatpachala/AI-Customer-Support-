from __future__ import annotations

from typing import Any, Dict, List, Optional

from identity.models import AuthLevel
from identity.service import (
    identity_required,
    build_challenge,
    extract_order_id,
    extract_contact,
    identify_order_ownership,
    user_has_no_order_id,
    is_policy_or_info_query,
    is_action_request,
)
from common.messages import get_last_user_message


def _challenge_dict(challenge) -> Dict[str, Any]:
    if hasattr(challenge, "dict"):
        return challenge.dict()
    if hasattr(challenge, "model_dump"):
        return challenge.model_dump()
    return {
        "required": getattr(challenge, "required", True),
        "reason": getattr(challenge, "reason", ""),
        "required_fields": getattr(challenge, "required_fields", []),
        "message": getattr(challenge, "message", ""),
    }


def identity_gate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phase 2.3 multi-turn order ownership gate.
    """
    memory = state.get("memory_context") or {}
    message = get_last_user_message(state.get("messages", [])) or ""

    intent = (
        state.get("intent")
        or (state.get("current_plan") or {}).get("intent")
        or memory.get("issue_type")
        or memory.get("intent")
        or ""
    )
    intent = str(intent).lower().strip()

    risk_level = str(state.get("risk_level") or memory.get("risk_level") or "low").lower().strip()

    auth_level = str(
        state.get("auth_level")
        or memory.get("auth_level")
        or AuthLevel.ANONYMOUS.value
    ).lower().strip()

    # Resolve fields first (this turn + sticky memory)
    order_id = (
        extract_order_id(message)
        or state.get("resolved_order_id")
        or memory.get("active_order_id")
        or memory.get("pending_order_id")
    )
    contact = (
        extract_contact(message)
        or state.get("customer_contact")
        or memory.get("customer_contact")
        or memory.get("pending_contact")
    )

    pending = bool(
        state.get("needs_identity")
        or memory.get("needs_identity")
        or state.get("identity_challenge")
        or memory.get("identity_challenge")
        or memory.get("pending_order_id")
        or memory.get("pending_contact")
    )

    is_policy = is_policy_or_info_query(message, intent)

    # CRITICAL: must run BEFORE "if not required" return
    if auth_level in (AuthLevel.ANONYMOUS.value, "anonymous") and not is_policy:
        if order_id or contact:
            pending = True

    if is_policy:
        pending = False

    print(
        f"[IDENTITY] intent={intent!r} risk={risk_level!r} auth={auth_level!r} "
        f"pending={pending} is_policy={is_policy} order_id={order_id!r} contact={contact!r} "
        f"msg={message[:80]!r}"
    )

    if auth_level in (AuthLevel.IDENTIFIED.value, AuthLevel.VERIFIED.value):
        print(f"[IDENTITY] skip: already {auth_level}")
        return {
            "needs_identity": False,
            "identity_blocked": False,
            "auth_level": auth_level,
            "identity_challenge": None,
            "resolved_order_id": order_id,
        }

    if pending and user_has_no_order_id(message):
        challenge = build_challenge("no_order_id")
        print("[IDENTITY] user has no order id → escalate")
        return {
            "needs_identity": True,
            "identity_blocked": True,
            "needs_escalation": True,
            "escalation_reason": "Customer cannot provide order ID for ownership verification",
            "identity_challenge": _challenge_dict(challenge),
            "auth_level": AuthLevel.ANONYMOUS.value,
            "missing_inputs": ["order_id"],
        }

    required = (identity_required(
        intent,
        risk_level,
        auth_level,
        message=message,
    ) or pending) and not is_policy

    if not required:
        print("[IDENTITY] not required")
        return {
            "needs_identity": False,
            "identity_blocked": False,
            "auth_level": auth_level,
            "identity_challenge": None,
        }

    missing: List[str] = []
    if not order_id:
        missing.append("order_id")
    if not contact:
        missing.append("contact")

    if missing:
        challenge = build_challenge("missing_identity_fields")
        if missing == ["contact"]:
            challenge.message = (
                f"Thanks, I have order {order_id}. "
                "Please share the phone number or email used when placing the order."
            )
        elif missing == ["order_id"]:
            challenge.message = (
                "Please share your Order ID "
                "(and the phone or email used on the order if you haven't already)."
            )
        else:
            challenge.message = (
                "To continue with your return, please provide your Order ID "
                "and the phone number or email used for the order."
            )

        print(f"[IDENTITY] still missing: {missing}")
        return {
            "needs_identity": True,
            "identity_blocked": True,
            "identity_challenge": _challenge_dict(challenge),
            "missing_inputs": missing,
            "auth_level": AuthLevel.ANONYMOUS.value,
            "resolved_order_id": order_id,
            "customer_contact": contact,
            "pending_order_id": order_id,
            "pending_contact": contact,
        }

    result = identify_order_ownership(order_id, contact)
    print(f"[IDENTITY] ownership success={result.success} error={result.error_code}")

    identity_payload = (
        result.dict()
        if hasattr(result, "dict")
        else (result.model_dump() if hasattr(result, "model_dump") else result.__dict__)
    )

    if not result.success:
        challenge = build_challenge(result.error_code or "ownership_failed")
        challenge.message = (
            "We could not verify order ownership with those details. "
            "Please re-check the Order ID and the phone/email used on the order."
        )
        return {
            "needs_identity": True,
            "identity_blocked": True,
            "identity_result": identity_payload,
            "identity_challenge": _challenge_dict(challenge),
            "auth_level": AuthLevel.ANONYMOUS.value,
            "resolved_order_id": order_id,
            "customer_contact": contact,
            "pending_order_id": order_id,
            "pending_contact": contact,
        }

    return {
        "needs_identity": False,
        "identity_blocked": False,
        "identity_result": identity_payload,
        "identity_challenge": None,
        "auth_level": AuthLevel.IDENTIFIED.value,
        "resolved_order_id": order_id,
        "customer_contact": contact,
        "missing_inputs": [],
        "pending_order_id": None,
        "pending_contact": None,
    }