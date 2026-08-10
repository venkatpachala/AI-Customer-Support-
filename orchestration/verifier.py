from orchestration.state import AgentState
from observability.logging import log_event
from typing import Dict, List


def verifier_node(state: AgentState) -> Dict:
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

    for tool in required_tools:
        result = tool_results.get(tool)

        if result is None:
            if intent in ["general"]:
                soft_issues.append(f"Tool '{tool}' not executed for general intent")
            else:
                # if photos/order missing, prefer soft path
                if "photos" in missing_inputs or "order_id" in missing_inputs:
                    soft_issues.append(f"Tool '{tool}' not executed due to missing inputs")
                else:
                    hard_issues.append(f"Required tool '{tool}' was never executed")
            continue

        status = result.get("status") if isinstance(result, dict) else "unknown"
        reason = (result.get("reason") or "") if isinstance(result, dict) else ""
        error = (result.get("error") or "") if isinstance(result, dict) else ""
        error_code = (result.get("error_code") or "") if isinstance(result, dict) else ""
        reason_l = f"{reason} {error} {error_code}".lower()

        if status == "error":
            # Soft-fail auth/config issues on read enrichment tools
            if tool in ["shopify_get_order"] and (
                "unauthorized" in reason_l
                or "invalid api key" in reason_l
                or "authentication" in reason_l
                or error_code in ["authentication_error", "authorization_error"]
            ):
                soft_issues.append(f"{tool}: auth/config failure")
                continue

            hard_issues.append(f"Tool '{tool}' failed: {result.get('error')}")
            continue

        if status == "skipped":
            if (
                "photos" in reason_l
                or "order_id" in reason_l
                or "already executed" in reason_l
                or "missing required input" in reason_l
                or "payment_intent" in reason_l
                or "charge_id" in reason_l
            ):
                soft_issues.append(f"{tool}: {reason}")
            else:
                hard_issues.append(f"Tool '{tool}' was skipped: {reason}")

    if "photos" in missing_inputs or (
        memory_context.get("photos_requested") and not memory_context.get("photos_received")
    ):
        soft_issues.append("photos")

    if "order_id" in missing_inputs and not memory_context.get("active_order_id"):
        soft_issues.append("order_id")

    if hard_issues:
        log_event("verifier_failed", request_id, node="verifier", data={"issues": hard_issues}, level="warning")
        return {
            "verification_passed": False,
            "verification_issues": hard_issues,
            "needs_escalation": True,
            "escalation_reason": "Execution verification failed: " + "; ".join(hard_issues),
            "missing_photos": "photos" in soft_issues or "photos" in missing_inputs,
        }

    if soft_issues:
        log_event("verifier_soft_issue", request_id, node="verifier", data={"soft_issues": soft_issues})
        return {
            "verification_passed": True,
            "verification_issues": [],
            "needs_escalation": False,
            "missing_photos": ("photos" in soft_issues or "photos" in missing_inputs),
        }

    log_event("verifier_passed", request_id, node="verifier")
    return {
        "verification_passed": True,
        "verification_issues": [],
        "needs_escalation": False,
        "missing_photos": False,
    }