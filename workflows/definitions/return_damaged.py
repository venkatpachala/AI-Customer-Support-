"""Damaged return. Stops for photos or finishes with a next-step hint. No Stripe."""
from __future__ import annotations

from workflows.definitions.common import assert_auth, evaluate_action, fetch_order, gate_on_policy
from workflows.definitions.refund import WorkflowDefinition
from workflows.state import StepResult, StepRuntime


def _finish(rt: StepRuntime) -> StepResult:
    return gate_on_policy(rt, success_output={"next": "ask_photos_or_done"})


RETURN_DAMAGED = WorkflowDefinition(
    name="return_damaged",
    steps=[
        ("assert_auth", assert_auth("return")),
        ("fetch_order", fetch_order),
        ("evaluate_policy", evaluate_action("return")),
        ("collect_inputs", lambda rt: _collect_or_hint(rt)),
        ("finish", _finish),
    ],
)


def _collect_or_hint(rt: StepRuntime) -> StepResult:
    from workflows.definitions.common import collect_inputs

    result = collect_inputs(("photos",))(rt)
    if result.status != "success":
        output = dict(result.output)
        output["next"] = "ask_photos_or_done"
        result.output = output
    return result
