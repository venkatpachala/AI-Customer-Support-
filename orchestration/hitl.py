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

from orchestration.escalation_policy import evaluate_escalation

def _refund_amount(state: AgentState) -> int:
    plan = state.get("current_plan") or {}
    slots = plan.get("slots") or {}
    raw = slots.get("amount")
    if raw:
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            pass
    return extract_amount_from_messages(state.get("messages") or [])


def check_escalation(state: AgentState) -> Dict:
    """Escalate from the workflow snapshot when one exists.

    Amount caps live in the policy YAML. A missing-photo wait stays on the
    QA ask path. Identity waits stay off the supervisor queue.
    """
    request_id = state.get("request_id", "unknown")
    log_event("hitl_started", request_id, node="hitl")

    memory_context = state.get("memory_context") or {}
    workflow_status = str(state.get("workflow_status") or "")
    policy = state.get("policy_decision") if isinstance(state.get("policy_decision"), dict) else {}
    missing_photos = bool(state.get("missing_photos"))
    run_id = state.get("workflow_run_id")
    amount = _refund_amount(state)

    def finish(needs: bool, reason: str, codes: list) -> Dict:
        log_event("hitl_completed", request_id, node="hitl", data={
            "needs_escalation": needs,
            "reason": reason,
            "amount": amount,
            "workflow_status": workflow_status,
            "codes": codes,
        })
        return {
            "needs_escalation": bool(needs),
            "escalation_reason": reason,
            "escalation_codes": codes,
        }

    if memory_context.get("case_status") == "escalated":
        return finish(
            True,
            memory_context.get("escalation_reason") or "Case already escalated",
            ["preexisting"],
        )

    if workflow_status == "waiting_auth":
        return finish(False, "", [])

    photos_blocking = workflow_status == "waiting_input" or (
        missing_photos and workflow_status != "waiting_approval"
    )
    pending_approval = (
        workflow_status == "waiting_approval" or policy.get("requires_approval") is True
    )
    if pending_approval and not photos_blocking:
        reason = (
            f"High value refund of ₹{amount} requires manual approval; "
            f"pending refund approval; workflow_run_id={run_id}"
        )
        return finish(True, reason, ["high_value_refund"])

    needs, reason, codes = evaluate_escalation(state)
    codes = list(codes or [])
    policy_present = bool(policy) or bool(workflow_status)
    if photos_blocking or (policy_present and policy.get("requires_approval") is not True):
        if "high_value_refund" in codes:
            codes = [code for code in codes if code != "high_value_refund"]
            if reason and str(reason).startswith("High value"):
                reason = ""
    if not codes:
        return finish(False, "", [])
    if not reason:
        reason = f"Human review required ({codes[0]})"
    if missing_photos and codes == ["high_value_refund"]:
        return finish(False, "", [])
    return finish(bool(needs and codes), reason or "", codes)