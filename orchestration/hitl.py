from orchestration.state import AgentState
from observability.logging import log_event
from typing import Dict
import re


def extract_amount_from_messages(messages) -> int:
    """
    Safe amount extraction.
    Do not treat order IDs like #12345 as refund amounts.
    """
    if not messages:
        return 0

    last = messages[-1]
    text = last.content if hasattr(last, "content") else str(last)
    text = text.lower().replace(",", "")

    patterns = [
        r'(?:refund|amount|pay|paid|worth|value)\s*(?:of|is|for)?\s*(?:₹|rs\.?|inr)?\s*(\d{3,6})',
        r'(?:₹|rs\.?|inr)\s*(\d{3,6})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))

    return 0


def check_escalation(state: AgentState) -> Dict:
    """
    Escalate only for strong reasons:
    - already escalated case
    - high-value refund
    - stripe requires approval
    - true high risk
    - planner approval only when reason is serious
    """
    request_id = state.get("request_id", "unknown")
    log_event("hitl_started", request_id, node="hitl")

    plan = state.get("current_plan") or {}
    tool_results = state.get("tool_results") or {}
    tenant_config = state.get("tenant_config") or {}
    risk_level = state.get("risk_level", "low")
    missing_photos = state.get("missing_photos", False)
    memory_context = state.get("memory_context") or {}
    messages = state.get("messages", [])

    approval = tenant_config.get("approval", {})
    high_value_limit = approval.get("high_value_refund_limit", 2000)

    needs_escalation = False
    reason = ""
    amount = 0

    # 1) Already escalated in memory
    if memory_context.get("case_status") == "escalated":
        log_event("hitl_completed", request_id, node="hitl", data={
            "needs_escalation": True,
            "reason": "Case already escalated",
            "amount": 0
        })
        return {
            "needs_escalation": True,
            "escalation_reason": memory_context.get("escalation_reason") or "Case already escalated"
        }

    # 2) Stripe explicit requires_approval
    stripe_result = tool_results.get("stripe_refund", {})
    if isinstance(stripe_result, dict):
        data = stripe_result.get("data", {})
        if isinstance(data, dict):
            amount = data.get("amount", 0) or 0
            if data.get("status") == "requires_approval":
                needs_escalation = True
                reason = f"High value refund of ₹{amount} requires manual approval"

    # 3) Safe amount extraction from user text
    if not amount:
        amount = extract_amount_from_messages(messages)

    if not needs_escalation and amount >= high_value_limit:
        needs_escalation = True
        reason = (
            f"High value refund of ₹{amount} requires manual approval "
            f"(limit: ₹{high_value_limit})"
        )

    # 4) True high risk only
    if not needs_escalation and risk_level in ["high", "critical"]:
        needs_escalation = True
        reason = f"High risk level detected ({risk_level})"

    # 5) Planner approval only for serious reasons
    if not needs_escalation:
        approval_rules = plan.get("approval_rules", {})
        planner_wants_approval = approval_rules.get("requires_human_approval", False)
        planner_reason = (approval_rules.get("reason") or "").lower()

        serious_markers = [
            "fraud",
            "abuse",
            "chargeback",
            "high value",
            "manual review required",
            "suspicious",
            "unsafe"
        ]

        if planner_wants_approval and any(marker in planner_reason for marker in serious_markers):
            needs_escalation = True
            reason = approval_rules.get("reason") or "Planner flagged serious case for human review"

    # 6) Missing photos / preference / FAQ should never escalate alone
    if missing_photos and not needs_escalation:
        needs_escalation = False
        reason = ""

    log_event("hitl_completed", request_id, node="hitl", data={
        "needs_escalation": needs_escalation,
        "reason": reason,
        "amount": amount,
        "risk_level": risk_level
    })

    return {
        "needs_escalation": needs_escalation,
        "escalation_reason": reason
    }