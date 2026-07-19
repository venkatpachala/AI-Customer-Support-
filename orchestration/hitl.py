from orchestration.state import AgentState
from typing import Dict

def check_escalation(state: AgentState) -> Dict:
    """
    Decide whether the case should be escalated to a human agent.
    Uses both plan signals and tenant configuration.
    """
    plan = state.get("current_plan") or {}
    tool_results = state.get("tool_results") or {}
    tenant_config = state.get("tenant_config") or {}
    risk_level = state.get("risk_level", "low")

    approval = tenant_config.get("approval", {})
    escalation_cfg = tenant_config.get("escalation", {})

    high_value_limit = approval.get("high_value_refund_limit", 2000)
    escalate_on = escalation_cfg.get("escalate_on", [])

    needs_escalation = False
    reason = ""

    # 1. High value refund from tool result
    stripe_result = tool_results.get("stripe_refund", {})
    if isinstance(stripe_result, dict):
        data = stripe_result.get("data", {})
        if isinstance(data, dict) and data.get("status") == "requires_approval":
            needs_escalation = True
            reason = "High value refund requires manual approval"

    # 2. Planner explicitly requested human approval
    approval_rules = plan.get("approval_rules", {})
    if not needs_escalation and approval_rules.get("requires_human_approval", False):
        needs_escalation = True
        reason = approval_rules.get("reason") or "Planner flagged this case for human review"

    # 3. High risk from Supervisor
    if not needs_escalation and risk_level in ["high", "critical"]:
        if "fraud" in escalate_on or "high_risk" in escalate_on:
            needs_escalation = True
            reason = f"High risk level detected ({risk_level})"

    # 4. Config-driven triggers
    if not needs_escalation and "low_confidence" in escalate_on:
        confidence = state.get("confidence", 1.0)
        if confidence < 0.6:
            needs_escalation = True
            reason = "Low confidence in the response"

    return {
        "needs_escalation": needs_escalation,
        "escalation_reason": reason
    }