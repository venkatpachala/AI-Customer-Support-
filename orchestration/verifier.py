from orchestration.state import AgentState
from typing import Dict, List

def verifier_node(state: AgentState) -> Dict:
    """
    Verifies execution results.
    - Hard failures (tool errors) → escalate
    - Soft issues (missing photos) → ask customer, do not escalate
    """
    plan = state.get("current_plan") or {}
    tool_results = state.get("tool_results") or {}
    steps = plan.get("steps") or []
    missing_inputs = set(plan.get("missing_inputs") or [])

    print("\n=== Verifier Started ===")

    hard_issues: List[str] = []
    soft_issues: List[str] = []
    required_tools = []

    # Collect required tools from the plan
    for step in steps:
        if isinstance(step, dict) and step.get("required", True):
            tool = step.get("tool")
            if tool:
                required_tools.append(tool)

    # Inspect each required tool
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
            if "photos" in reason.lower() or "missing required input: photos" in reason.lower():
                soft_issues.append("photos")
            else:
                hard_issues.append(f"Tool '{tool}' was skipped: {reason}")

    # Case 1: Hard failures → escalate
    if hard_issues:
        print("Verifier found hard issues:")
        for issue in hard_issues:
            print(f"  - {issue}")

        return {
            "verification_passed": False,
            "verification_issues": hard_issues,
            "needs_escalation": True,
            "escalation_reason": "Execution verification failed: " + "; ".join(hard_issues),
            "missing_photos": False
        }

    # Case 2: Soft issues (missing photos) → do not escalate
    if soft_issues or "photos" in missing_inputs:
        print("Verifier: Missing photos detected. Will ask customer instead of escalating.")
        return {
            "verification_passed": True,
            "verification_issues": [],
            "needs_escalation": False,
            "missing_photos": True
        }

    # Case 3: Everything fine
    print("Verifier passed")
    return {
        "verification_passed": True,
        "verification_issues": [],
        "needs_escalation": False,
        "missing_photos": False
    }