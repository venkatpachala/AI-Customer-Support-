from orchestration.state import AgentState
from observability.logging import log_event
from typing import Dict, List


def verifier_node(state: AgentState) -> Dict:
    """
    Practical verifier:
    - Hard failures => escalate
    - Missing photos / missing order_id => soft pass, let QA ask user
    - General/policy questions can pass without tools
    """
    request_id = state.get("request_id", "unknown")
    log_event("verifier_started", request_id, node="verifier")

    plan = state.get("current_plan") or {}
    tool_results = state.get("tool_results") or {}
    steps = plan.get("steps") or []
    missing_inputs = set(plan.get("missing_inputs") or [])
    intent = (plan.get("intent") or "").lower()
    memory_context = state.get("memory_context") or {}

    hard_issues: List[str] = []
    soft_issues: List[str] = []

    required_tools = []
    for step in steps:
        if isinstance(step, dict) and step.get("required", True):
            tool = step.get("tool")
            if tool:
                required_tools.append(tool)

    # Inspect required tools
    for tool in required_tools:
        result = tool_results.get(tool)

        # Tool never executed
        if result is None:
            # For general/policy questions, tools may be unnecessary
            if intent in ["general"]:
                soft_issues.append(f"Tool '{tool}' not executed for general intent")
            else:
                hard_issues.append(f"Required tool '{tool}' was never executed")
            continue

        status = result.get("status") if isinstance(result, dict) else "unknown"
        reason = (result.get("reason") or "") if isinstance(result, dict) else ""
        reason_l = reason.lower()

        if status == "error":
            hard_issues.append(f"Tool '{tool}' failed: {result.get('error')}")
            continue

        if status == "skipped":
            # Soft skips: missing user inputs or already executed
            if (
                "photos" in reason_l
                or "order_id" in reason_l
                or "already executed" in reason_l
                or "missing required input" in reason_l
            ):
                soft_issues.append(f"{tool}: {reason}")
            else:
                hard_issues.append(f"Tool '{tool}' was skipped: {reason}")

    # If photos are known missing, force soft path
    if "photos" in missing_inputs or memory_context.get("photos_requested") and not memory_context.get("photos_received"):
        soft_issues.append("photos")

    # If order id missing, soft path
    if "order_id" in missing_inputs and not memory_context.get("active_order_id"):
        soft_issues.append("order_id")

    # Hard failures => escalate
    if hard_issues:
        log_event(
            "verifier_failed",
            request_id,
            node="verifier",
            data={"issues": hard_issues},
            level="warning"
        )
        return {
            "verification_passed": False,
            "verification_issues": hard_issues,
            "needs_escalation": True,
            "escalation_reason": "Execution verification failed: " + "; ".join(hard_issues),
            "missing_photos": "photos" in soft_issues or "photos" in missing_inputs
        }

    # Soft issues => do not escalate, let QA ask for info / answer policy
    if soft_issues:
        log_event(
            "verifier_soft_issue",
            request_id,
            node="verifier",
            data={"soft_issues": soft_issues}
        )
        return {
            "verification_passed": True,
            "verification_issues": [],
            "needs_escalation": False,
            "missing_photos": ("photos" in soft_issues or "photos" in missing_inputs)
        }

    # All good
    log_event("verifier_passed", request_id, node="verifier")
    return {
        "verification_passed": True,
        "verification_issues": [],
        "needs_escalation": False,
        "missing_photos": False
    }