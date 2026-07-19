from orchestration.state import AgentState
from typing import Dict
import re

def extract_amount_from_messages(messages) -> int:
    """Fallback amount extraction from user messages"""
    if not messages:
        return 0

    last = messages[-1]
    text = last.content if hasattr(last, "content") else str(last)

    match = re.search(r'(?:₹|rs\.?|inr)?\s*(\d{3,6})', text.lower().replace(",", ""))
    if match:
        return int(match.group(1))
    return 0

def check_escalation(state: AgentState) -> Dict:
    """
    Decide whether the case should be escalated to a human agent.
    High value refunds always escalate, even if tools were skipped.
    """
    plan = state.get("current_plan") or {}
    tool_results = state.get("tool_results") or {}
    tenant_config = state.get("tenant_config") or {}
    risk_level = state.get("risk_level", "low")
    missing_photos = state.get("missing_photos", False)
    messages = state.get("messages", [])

    approval = tenant_config.get("approval", {})
    escalation_cfg = tenant_config.get("escalation", {})

    high_value_limit = approval.get("high_value_refund_limit", 2000)
    escalate_on = escalation_cfg.get("escalate_on", [])

    needs_escalation = False
    reason = ""

    # ============================================
    # 1. High value refund (highest priority)
    # ============================================
    amount = 0

    # Try to get amount from Stripe tool result
    stripe_result = tool_results.get("stripe_refund", {})
    if isinstance(stripe_result, dict):
        data = stripe_result.get("data", {})
        if isinstance(data, dict):
            amount = data.get("amount", 0)
            if data.get("status") == "requires_approval":
                needs_escalation = True
                reason = f"High value refund of ₹{amount} requires manual approval"

    # Fallback: extract amount from user message
    if amount == 0:
        amount = extract_amount_from_messages(messages)

    # Force escalation if amount exceeds high value limit
    if not needs_escalation and amount >= high_value_limit:
        needs_escalation = True
        reason = f"High value refund of ₹{amount} requires manual approval (limit: ₹{high_value_limit})"

    # ============================================
    # 2. Planner explicitly requested approval
    # ============================================
    if not needs_escalation:
        approval_rules = plan.get("approval_rules", {})
        if approval_rules.get("requires_human_approval", False):
            needs_escalation = True
            reason = approval_rules.get("reason") or "Planner flagged this case for human review"

    # ============================================
    # 3. High risk from Supervisor
    # ============================================
    if not needs_escalation and risk_level in ["high", "critical"]:
        needs_escalation = True
        reason = f"High risk level detected ({risk_level})"

    # ============================================
    # 4. Missing photos should NOT escalate
    # ============================================
    if missing_photos and not needs_escalation:
        # Soft issue only
        needs_escalation = False
        reason = ""

    return {
        "needs_escalation": needs_escalation,
        "escalation_reason": reason
    }