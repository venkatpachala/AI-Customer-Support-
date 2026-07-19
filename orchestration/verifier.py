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
            hard_issues.append(f"Required tool '{tool}' was never executed")
            continue

        status = result.get("status") if isinstance(result, dict) else "unknown"
        reason = result.get("reason", "") if isinstance(result, dict) else ""

        if status == "error":
            hard_issues.append(f"Tool '{tool}' failed: {result.get('error')}")
        elif status == "skipped":
            if "photos" in reason.lower():
                soft_issues.append("photos")
            else:
                hard_issues.append(f"Tool '{tool}' was skipped: {reason}")

    if hard_issues:
        log_event("verifier_failed", request_id, node="verifier", data={"issues": hard_issues}, level="warning")
        return {
            "verification_passed": False,
            "verification_issues": hard_issues,
            "needs_escalation": True,
            "escalation_reason": "Execution verification failed: " + "; ".join(hard_issues),
            "missing_photos": False
        }

    if soft_issues or "photos" in missing_inputs:
        log_event("verifier_soft_issue", request_id, node="verifier", data={"soft_issues": soft_issues})
        return {
            "verification_passed": True,
            "verification_issues": [],
            "needs_escalation": False,
            "missing_photos": True
        }

    log_event("verifier_passed", request_id, node="verifier")
    return {
        "verification_passed": True,
        "verification_issues": [],
        "needs_escalation": False,
        "missing_photos": False
    }