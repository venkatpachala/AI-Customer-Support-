from orchestration.state import AgentState
from typing import Dict, List

def verifier_node(state: AgentState) -> Dict:
    """
    Verifies that the execution was successful and complete
    before allowing the QA agent to respond.
    """
    plan = state.get("current_plan") or {}
    tool_results = state.get("tool_results") or {}
    steps = plan.get("steps") or []

    print("\n=== Verifier Started ===")

    issues: List[str] = []
    required_tools = []
    executed_tools = set(tool_results.keys())

    # Collect required tools from the plan
    for step in steps:
        if isinstance(step, dict) and step.get("required", True):
            tool = step.get("tool")
            if tool:
                required_tools.append(tool)

    # Check each required tool
    for tool in required_tools:
        result = tool_results.get(tool)

        if result is None:
            issues.append(f"Required tool '{tool}' was never executed")
            continue

        status = result.get("status") if isinstance(result, dict) else "unknown"

        if status == "error":
            issues.append(f"Tool '{tool}' failed: {result.get('error')}")
        elif status == "skipped":
            issues.append(f"Tool '{tool}' was skipped: {result.get('reason')}")

    # Decision
    if issues:
        print("Verifier found issues:")
        for issue in issues:
            print(f"  - {issue}")

        return {
            "verification_passed": False,
            "verification_issues": issues,
            "needs_escalation": True,
            "escalation_reason": "Execution verification failed: " + "; ".join(issues)
        }

    print("Verifier passed — all required tools executed successfully")
    return {
        "verification_passed": True,
        "verification_issues": []
    }