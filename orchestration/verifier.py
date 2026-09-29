from orchestration.planner import BANNED_EXECUTOR_TOOLS
from orchestration.state import AgentState
from observability.logging import log_event
from typing import Dict, List

_POLICY_DENIALS = {"OUT_OF_POLICY", "AUTH", "AMOUNT", "MISSING_INPUT", "FRAUD"}
_WAITING_STATUSES = {"waiting_input", "waiting_auth", "waiting_approval"}


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
    workflow_status = str(state.get("workflow_status") or "")
    policy = state.get("policy_decision") if isinstance(state.get("policy_decision"), dict) else {}
    workflow_ran = bool(state.get("workflow_run_id"))
    requires_inputs = list(policy.get("requires_inputs") or [])
    if workflow_status == "waiting_input":
        for name in requires_inputs:
            missing_inputs.add(name)

    if workflow_status in _WAITING_STATUSES:
        missing_photos = workflow_status == "waiting_input" and (
            "photos" in missing_inputs or "photos" in requires_inputs
        )
        log_event("verifier_passed", request_id, node="verifier", data={
            "workflow_status": workflow_status,
            "missing_photos": missing_photos,
        })
        return {
            "verification_passed": True,
            "verification_issues": [],
            "needs_escalation": False,
            "missing_photos": missing_photos,
            "missing_inputs": sorted(missing_inputs),
        }

    if workflow_status == "failed":
        deny = str(policy.get("deny_code") or "")
        if deny in _POLICY_DENIALS or policy.get("allowed") is False:
            log_event("verifier_passed", request_id, node="verifier", data={
                "workflow_status": workflow_status,
                "deny_code": deny,
            })
            return {
                "verification_passed": True,
                "verification_issues": [],
                "needs_escalation": False,
                "missing_photos": False,
            }
        error = state.get("workflow_error") or deny or "workflow failed"
        log_event("verifier_failed", request_id, node="verifier", data={"issues": [error]}, level="warning")
        return {
            "verification_passed": False,
            "verification_issues": [str(error)],
            "needs_escalation": True,
            "escalation_reason": f"Execution verification failed: {error}",
            "missing_photos": False,
        }

    required_tools = []
    for step in steps:
        if isinstance(step, dict) and step.get("required", True):
            tool = step.get("tool")
            if tool:
                if workflow_ran and tool in BANNED_EXECUTOR_TOOLS:
                    continue
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
                or "redirected_to_workflow" in reason_l
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