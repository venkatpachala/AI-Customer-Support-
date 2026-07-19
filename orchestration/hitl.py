from orchestration.state import AgentState
from observability.logging import log_event
from typing import Dict
import re

def extract_amount_from_messages(messages) -> int:
    if not messages:
        return 0
    last = messages[-1]
    text = last.content if hasattr(last, "content") else str(last)
    match = re.search(r'(?:₹|rs\.?|inr)?\s*(\d{3,6})', text.lower().replace(",", ""))
    if match:
        return int(match.group(1))
    return 0

def check_escalation(state: AgentState) -> Dict:
    request_id = state.get("request_id", "unknown")
    log_event("hitl_started", request_id, node="hitl")

    plan = state.get("current_plan") or {}
    tool_results = state.get("tool_results") or {}
    tenant_config = state.get("tenant_config") or {}
    risk_level = state.get("risk_level", "low")
    missing_photos = state.get("missing_photos", False)
    messages = state.get("messages", [])

    approval = tenant_config.get("approval", {})
    high_value_limit = approval.get("high_value_refund_limit", 2000)

    needs_escalation = False
    reason = ""
    amount = 0

    stripe_result = tool_results.get("stripe_refund", {})
    if isinstance(stripe_result, dict):
        data = stripe_result.get("data", {})
        if isinstance(data, dict):
            amount = data.get("amount", 0)
            if data.get("status") == "requires_approval":
                needs_escalation = True
                reason = f"High value refund of ₹{amount} requires manual approval"

    if amount == 0:
        amount = extract_amount_from_messages(messages)

    if not needs_escalation and amount >= high_value_limit:
        needs_escalation = True
        reason = f"High value refund of ₹{amount} requires manual approval (limit: ₹{high_value_limit})"

    if not needs_escalation:
        approval_rules = plan.get("approval_rules", {})
        if approval_rules.get("requires_human_approval", False):
            needs_escalation = True
            reason = approval_rules.get("reason") or "Planner flagged this case for human review"

    if not needs_escalation and risk_level in ["high", "critical"]:
        needs_escalation = True
        reason = f"High risk level detected ({risk_level})"

    if missing_photos and not needs_escalation:
        needs_escalation = False
        reason = ""

    log_event("hitl_completed", request_id, node="hitl", data={
        "needs_escalation": needs_escalation,
        "reason": reason,
        "amount": amount
    })

    return {
        "needs_escalation": needs_escalation,
        "escalation_reason": reason
    }