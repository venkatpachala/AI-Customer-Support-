from typing import Dict, Any


POLICY_INTENTS = {
    "policy",
    "general",
    "faq",
    "policy_question",
    "general_query",
}

ACTION_INTENTS = {
    "return",
    "refund",
    "cancel",
    "replacement",
    "track",
    "order_status",
}


def _last_user_text(state: Dict[str, Any]) -> str:
    messages = state.get("messages") or []
    if not messages:
        return ""
    last = messages[-1]
    return (last.content if hasattr(last, "content") else str(last)).lower()


def is_policy_fast_path(state: Dict[str, Any]) -> bool:
    if state.get("blocked"):
        return False
    if state.get("needs_escalation"):
        return False

    risk = (state.get("risk_level") or "low").lower().strip()
    if risk in ["high", "critical"]:
        return False

    intent = (state.get("intent") or "").lower().strip()
    if not intent:
        plan = state.get("current_plan") or {}
        intent = (plan.get("intent") or "").lower().strip()

    text = _last_user_text(state)

    # 1) Hard action signals (true operational requests)
    hard_action_signals = [
        "order #",
        "order id",
        "my order",
        "refund of",
        "i want a refund",
        "cancel my order",
        "initiate refund",
        "replace my",
        "arrived damaged",
        "is damaged",
        "received damaged",
        "wrong item received",
    ]
    if any(k in text for k in hard_action_signals):
        return False

    # 2) Clear policy/FAQ signals (override supervisor intent)
    policy_signals = [
        "policy",
        "return policy",
        "refund policy",
        "cancellation policy",
        "what is the",
        "how long does",
        "how many days",
        "do you accept returns",
        "terms of use",
        "according to policy",
    ]
    if any(k in text for k in policy_signals):
        return True

    # 3) Intent-based fallback
    if intent in POLICY_INTENTS:
        return True
    if intent in ACTION_INTENTS:
        return False

    return False

def after_supervisor_route(state: Dict[str, Any]) -> str:
    if state.get("blocked"):
        return "end"
    if is_policy_fast_path(state):
        return "hitl_check"
    return "planner"