"""Refund workflow. Stripe is the sixth step and only runs when policy allowed it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Tuple

from workflows.definitions.common import (
    assert_auth,
    collect_inputs,
    evaluate_action,
    execute_refund,
    fetch_order,
    notify,
    require_refund_approval,
    update_case_resolved,
)

StepFn = Callable
Steps = List[Tuple[str, StepFn]]


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    steps: Steps


REFUND = WorkflowDefinition(
    name="refund",
    steps=[
        ("assert_auth", assert_auth("refund")),
        ("fetch_order", fetch_order),
        ("evaluate_policy", evaluate_action("refund")),
        ("collect_inputs", collect_inputs(("photos", "amount"))),
        ("require_approval", require_refund_approval),
        ("execute_refund", execute_refund),
        ("update_case", update_case_resolved),
        ("notify", notify),
    ],
)
