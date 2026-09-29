"""Cancel. Order snapshot wins over the caller's status. No cancel-order tool."""
from __future__ import annotations

from workflows.definitions.common import evaluate_action, fetch_order, gate_on_policy
from workflows.definitions.refund import WorkflowDefinition
from workflows.state import StepResult, StepRuntime


def _finish(rt: StepRuntime) -> StepResult:
    result = gate_on_policy(rt, success_output={"cancel_tool": False})
    if result.status == "success" and result.output.get("denied") is not True:
        # Policy allowed a cancel and this repo has no cancel-order tool.
        result.output = dict(result.output)
        result.output["denied"] = False
        result.output["skipped_tool"] = True
    return result


CANCEL = WorkflowDefinition(
    name="cancel",
    steps=[
        ("fetch_order", fetch_order),
        ("evaluate_policy", evaluate_action("cancel", order_status_wins=True)),
        ("finish", _finish),
    ],
)
