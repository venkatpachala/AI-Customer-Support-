from orchestration.state import AgentState
from typing import Dict

def check_escalation(state: AgentState) -> Dict:
    """
    Decide if the conversation should be escalated to a human agent.
    """
    plan = state.get("current_plan", {})
    confidence = state.get("confidence", 0.7)
    tool_results = state.get("tool_results", {})
    risk_level = state.get("risk_level", "low")

    needs_escalation = False
    reason = ""

    # Rule 1: High value refund
    # Rule 1: High value refund (highest priority)
    stripe_result = tool_results.get("stripe_refund", {})
    if isinstance(stripe_result, dict):
        data = stripe_result.get("data", {})
        if data.get("status") == "requires_approval":
            needs_escalation = True
        reason = "Refund amount requires manual approval (high value)"
    # Rule 2: Low confidence
    if confidence < 0.65:
        needs_escalation = True
        reason = "Low confidence in the generated response"

    # Rule 3: Planner requested human approval
    if plan.get("requires_human_approval", False):
        needs_escalation = True
        reason = "Planner flagged this case for human review"

    # Rule 4: High risk from supervisor
    if risk_level in ["high", "critical"]:
        needs_escalation = True
        reason = f"High risk level detected: {risk_level}"

    return {
        "needs_escalation": needs_escalation,
        "escalation_reason": reason
    }