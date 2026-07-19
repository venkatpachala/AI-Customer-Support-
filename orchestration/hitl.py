from orchestration.state import AgentState
from typing import Dict

def check_escalation(state: AgentState) -> Dict:
    """
    Decide whether to escalate to a human agent.
    """
    plan = state.get("current_plan", {}) or {}
    tool_results = state.get("tool_results", {}) or {}
    risk_level = state.get("risk_level", "low")

    needs_escalation = False
    reason = ""

    # Priority 1: High value refund
    stripe_result = tool_results.get("stripe_refund", {})
    if isinstance(stripe_result, dict):
        data = stripe_result.get("data", {})
        if isinstance(data, dict) and data.get("status") == "requires_approval":
            needs_escalation = True
            reason = "High value refund requires manual approval"

    # Priority 2: Planner explicitly requested approval
    if not needs_escalation and plan.get("requires_human_approval", False):
        needs_escalation = True
        reason = "Planner flagged this case for human review"

    # Priority 3: High risk from Supervisor
    if not needs_escalation and risk_level in ["high", "critical"]:
        needs_escalation = True
        reason = f"High risk level detected ({risk_level})"

    # Note: We are temporarily removing the low confidence check
    # because confidence is only available after QA node runs.

    return {
        "needs_escalation": needs_escalation,
        "escalation_reason": reason
    }