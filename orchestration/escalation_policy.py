from typing import Any, Dict, List, Optional, Tuple


ESCALATION_CODES = {
    "high_value_refund",
    "low_confidence",
    "repeated_failure",
    "policy_ambiguity",
    "fraud_suspicion",
    "legal_or_safety",
    "vip_customer",
    "identity_unverified",
    "angry_customer",
    "human_requested",
}


LEGAL_SAFETY_SIGNALS = [
    "lawyer", "legal action", "consumer court", "police", "sue",
    "harassment", "threaten", "kill", "suicide", "bomb",
]

ANGRY_SIGNALS = [
    "worst service", " dispensing", "angry", "frustrated", "pathetic",
    "useless", "scam", "fraud", "cheat", "robbery", "never ordering",
]

HUMAN_REQUEST_SIGNALS = [
    "talk to human", "speak to agent", "customer care executive",
    "real person", "human support", "connect me to agent",
]

FRAUD_SIGNALS = [
    "not my order", "someone else ordered", "unauthorized",
    "stolen card", "i did not place", "fraudulent",
]


def _text(state: Dict[str, Any]) -> str:
    messages = state.get("messages") or []
    if not messages:
        return ""
    last = messages[-1]
    return (last.content if hasattr(last, "content") else str(last)).lower()


def _amount(state: Dict[str, Any]) -> float:
    # prefer explicit state values if executor/planner set them
    for key in ("refund_amount", "amount"):
        try:
            val = float(state.get(key) or 0)
            if val > 0:
                return val
        except Exception:
            pass
    # lightweight parse
    import re
    t = _text(state).replace(",", "")
    m = re.search(r'(?:refund|amount|pay|paid|worth|value)\s*(?:of|is|for)?\s*(?:₹|rs\.?|inr)?\s*(\d{3,6})', t)
    if not m:
        m = re.search(r'(?:₹|rs\.?|inr)\s*(\d{3,6})', t)
    return float(m.group(1)) if m else 0.0


def evaluate_escalation(state: Dict[str, Any]) -> Tuple[bool, Optional[str], List[str]]:
    """
    Returns: (needs_escalation, primary_reason, all_matched_codes)
    """
    if state.get("needs_escalation") and state.get("escalation_reason"):
        # preserve earlier hard decisions (identity/verifier)
        return True, state.get("escalation_reason"), ["preexisting"]

    text = _text(state)
    matched: List[str] = []
    tenant = state.get("tenant_config") or {}
    approval = tenant.get("approval") or {}
    high_value_limit = float(approval.get("high_value_refund_limit", 2000))
    amount = _amount(state)

    intent = (state.get("intent") or "").lower()
    risk = (state.get("risk_level") or "low").lower()
    confidence = float(state.get("confidence") or 0.0)
    memory = state.get("memory_context") or {}
    customer_ctx = state.get("customer_context") or {}

    # 1) human requested
    if any(s in text for s in HUMAN_REQUEST_SIGNALS):
        matched.append("human_requested")

    # 2) legal/safety
    if any(s in text for s in LEGAL_SAFETY_SIGNALS):
        matched.append("legal_or_safety")

    # 3) angry customer
    if any(s in text for s in ANGRY_SIGNALS):
        matched.append("angry_customer")

    # 4) fraud suspicion
    if any(s in text for s in FRAUD_SIGNALS):
        matched.append("fraud_suspicion")

    # 5) high value refund
    if amount >= high_value_limit and any(k in intent for k in ["refund", "return", "cancel"]):
        matched.append("high_value_refund")
    elif amount >= high_value_limit and any(k in text for k in ["refund", "return"]):
        matched.append("high_value_refund")

    # 6) VIP
    if customer_ctx.get("vip") or memory.get("vip_status") or risk == "vip":
        matched.append("vip_customer")

    # 7) identity unverified sensitive
    if state.get("identity_blocked") and state.get("needs_escalation"):
        matched.append("identity_unverified")

    # 8) low confidence (only when we have a score)
    if confidence and confidence < float(tenant.get("min_confidence_to_auto_resolve", 0.45)):
        matched.append("low_confidence")

    # 9) policy ambiguity: action/policy answer with no citations and no tools
    citations = state.get("citations") or []
    tool_results = state.get("tool_results") or {}
    if not citations and not tool_results and any(k in text for k in ["policy", "allowed", "can i return", "refund policy"]):
        matched.append("policy_ambiguity")

    # 10) repeated failure from memory/tools
    fail_count = int(memory.get("tool_failure_count") or 0)
    hard_fails = [
        v for v in tool_results.values()
        if isinstance(v, dict) and v.get("status") == "error"
    ]
    if fail_count >= 2 or len(hard_fails) >= 2:
        matched.append("repeated_failure")

    if not matched:
        return False, None, []

    # priority order for primary reason
    priority = [
        "legal_or_safety",
        "fraud_suspicion",
        "identity_unverified",
        "high_value_refund",
        "vip_customer",
        "human_requested",
        "angry_customer",
        "repeated_failure",
        "low_confidence",
        "policy_ambiguity",
    ]
    primary = next((p for p in priority if p in matched), matched[0])
    reason_map = {
        "high_value_refund": f"High value refund of ₹{int(amount)} requires manual approval (limit: ₹{int(high_value_limit)})",
        "low_confidence": "AI confidence below threshold; human review required",
        "repeated_failure": "Repeated tool/process failures require human review",
        "policy_ambiguity": "Policy evidence insufficient; human review required",
        "fraud_suspicion": "Potential fraud/unauthorized activity signals detected",
        "legal_or_safety": "Legal/safety concern detected; escalating to human agent",
        "vip_customer": "VIP customer case requires human assistance",
        "identity_unverified": "Sensitive action requires verified customer context",
        "angry_customer": "Customer frustration signals require human assistance",
        "human_requested": "Customer requested a human support agent",
    }
    return True, reason_map.get(primary, primary), matched