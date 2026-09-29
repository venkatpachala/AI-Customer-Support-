"""Step and run values the engine persists. Status strings match the P0-A tables."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


STEP_SUCCESS = "success"
STEP_RETRY = "retry"
STEP_FAILED = "failed"
STEP_WAIT_APPROVAL = "wait_approval"
STEP_WAIT_INPUT = "wait_input"
STEP_WAIT_AUTH = "wait_auth"

# Run rows use `succeeded` (the column comment on workflow_runs). Waiting
# states are the engine's pause points. waiting_input and waiting_auth are
# stored as status text; the column is a string, not a closed enum.
RUN_PENDING = "pending"
RUN_RUNNING = "running"
RUN_RETRYING = "retrying"
RUN_WAITING_APPROVAL = "waiting_approval"
RUN_WAITING_INPUT = "waiting_input"
RUN_WAITING_AUTH = "waiting_auth"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"

# start() returns these instead of inserting another row.
REUSABLE_RUN_STATUSES = frozenset(
    {
        RUN_PENDING,
        RUN_RUNNING,
        RUN_RETRYING,
        RUN_WAITING_APPROVAL,
        RUN_WAITING_INPUT,
        RUN_WAITING_AUTH,
        RUN_SUCCEEDED,
    }
)

STEP_TO_RUN_STATUS = {
    STEP_WAIT_APPROVAL: RUN_WAITING_APPROVAL,
    STEP_WAIT_INPUT: RUN_WAITING_INPUT,
    STEP_WAIT_AUTH: RUN_WAITING_AUTH,
    STEP_RETRY: RUN_RETRYING,
    STEP_FAILED: RUN_FAILED,
}

# Customer reply can change these. Resume recomputes policy from here down
# and does not call Shopify again unless the order id itself changed.
POLICY_RESET_STEPS = frozenset(
    {
        "evaluate_policy",
        "collect_inputs",
        "require_approval",
        "execute_refund",
        "finish",
        "update_case",
        "notify",
    }
)


@dataclass
class StepResult:
    status: str
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    human_task: Optional[Dict[str, Any]] = None


@dataclass
class WorkflowRunView:
    run_id: str
    status: str
    workflow_name: str
    current_step: Optional[str]
    output: Dict[str, Any]
    error: Optional[str]
    idempotency_key: Optional[str] = None


@dataclass
class StepRuntime:
    """What one step can see. Tools are reached only through ``call_tool``."""

    ctx: Any
    run_id: str
    attempt: int
    outputs: Dict[str, Dict[str, Any]]
    policy: Dict[str, Any]
    call_tool: Callable[[str, Dict[str, Any]], Dict[str, Any]]
    session_factory: Callable[[], Any]

    def prior(self, step_name: str) -> Dict[str, Any]:
        raw = self.outputs.get(step_name) or {}
        return dict(raw)
