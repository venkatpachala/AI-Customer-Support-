"""Steps shared by the workflow definitions. Policy comes from policy.evaluate."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from policy import evaluate
from workflows.idempotency import stripe_step_key
from workflows.state import (
    STEP_FAILED,
    STEP_RETRY,
    STEP_SUCCESS,
    STEP_WAIT_APPROVAL,
    STEP_WAIT_AUTH,
    STEP_WAIT_INPUT,
    StepResult,
    StepRuntime,
)
from workflows.tools import is_auth_error, is_retryable

_INPUT_FIELDS = ("photos", "amount", "order_id", "order_status")


def decision_payload(decision: Any) -> Dict[str, Any]:
    if hasattr(decision, "model_dump"):
        return decision.model_dump()
    return decision.dict()


def assert_auth(action: str):
    def step(rt: StepRuntime) -> StepResult:
        decision = evaluate(
            rt.ctx.tenant_id,
            action,
            auth_level=rt.ctx.auth_level,
            slots=dict(rt.ctx.slots),
        )
        payload = decision_payload(decision)
        if decision.requires_strong_auth:
            return StepResult(
                status=STEP_WAIT_AUTH,
                output={"policy": payload},
                error="AUTH",
            )
        return StepResult(status=STEP_SUCCESS, output={"auth_level": rt.ctx.auth_level})

    return step


def fetch_order(rt: StepRuntime) -> StepResult:
    order_id = str(rt.ctx.slots.get("order_id") or "").strip()
    if not order_id:
        return StepResult(
            status=STEP_WAIT_INPUT,
            output={"requires_inputs": ["order_id"]},
            error="order_id",
        )
    result = rt.call_tool("shopify_get_order", {"order_id": order_id})
    status = str(result.get("status") or "")
    if status != "success":
        if is_retryable(result):
            return StepResult(status=STEP_RETRY, output={"tool": result}, error=result.get("error"))
        if is_auth_error(result):
            return StepResult(status=STEP_WAIT_AUTH, output={"tool": result}, error="AUTH")
        return StepResult(
            status=STEP_FAILED,
            output={"tool": result},
            error=str(result.get("error") or result.get("error_code") or "fetch_order_failed"),
        )
    order = dict(result.get("data") or {})
    if not order.get("order_id"):
        order["order_id"] = order_id
    return StepResult(status=STEP_SUCCESS, output={"order": order})


def evaluate_action(action: str, *, order_status_wins: bool = False):
    def step(rt: StepRuntime) -> StepResult:
        slots = dict(rt.ctx.slots)
        order = dict((rt.prior("fetch_order").get("order") or {}))
        fetched_status = order.get("status")
        if fetched_status:
            if order_status_wins or not slots.get("order_status"):
                slots["order_status"] = fetched_status
        decision = evaluate(
            rt.ctx.tenant_id,
            action,
            auth_level=rt.ctx.auth_level,
            slots=slots,
        )
        payload = decision_payload(decision)
        return StepResult(status=STEP_SUCCESS, output={"policy": payload, "slots": slots})

    return step


def collect_inputs(fields: tuple[str, ...] = ("photos", "amount")):
    wanted = set(fields)

    def step(rt: StepRuntime) -> StepResult:
        policy = dict(rt.policy or {})
        required = [name for name in policy.get("requires_inputs") or [] if name in wanted]
        if required:
            return StepResult(
                status=STEP_WAIT_INPUT,
                output={"requires_inputs": required, "policy": policy},
                error=",".join(required),
            )
        return StepResult(status=STEP_SUCCESS, output={"requires_inputs": []})

    return step


def require_refund_approval(rt: StepRuntime) -> StepResult:
    policy = dict(rt.policy or {})
    if policy.get("requires_approval") is not True:
        return StepResult(status=STEP_SUCCESS, output={"approval": "not_required"})
    slots = dict(rt.ctx.slots)
    task = {
        "type": "refund_approval",
        "payload": {
            "amount": slots.get("amount"),
            "order_id": slots.get("order_id"),
            "reason": slots.get("reason"),
            "customer_id": rt.ctx.customer_id,
            "reasons": list(policy.get("reasons") or []),
            "policy_id": policy.get("policy_id"),
            "policy_version": policy.get("policy_version"),
            "deny_code": policy.get("deny_code"),
            "max_amount": policy.get("max_amount"),
        },
    }
    return StepResult(
        status=STEP_WAIT_APPROVAL,
        output={"policy": policy},
        human_task=task,
        error="AMOUNT",
    )


def execute_refund(rt: StepRuntime) -> StepResult:
    """Stripe runs only when the stored policy snapshot says allowed is True."""
    policy = dict(rt.policy or {})
    if policy.get("allowed") is not True:
        return StepResult(
            status=STEP_FAILED,
            output={"denied": True, "stripe_called": False, "policy": policy},
            error=str(policy.get("deny_code") or "policy_not_allowed"),
        )
    if os.getenv("WORKFLOW_STRIPE_FAIL", "").strip() == "1" and rt.attempt < 3:
        return StepResult(
            status=STEP_RETRY,
            output={"stripe_called": False, "attempt": rt.attempt},
            error="stripe_forced_failure",
        )
    slots = dict(rt.ctx.slots)
    params = {
        "order_id": slots.get("order_id"),
        "amount": slots.get("amount"),
        "currency": "inr",
        "reason": "requested_by_customer",
        "idempotency_key": stripe_step_key(rt.run_id),
    }
    result = rt.call_tool("stripe_refund", params)
    status = str(result.get("status") or "")
    if status != "success":
        if is_retryable(result):
            return StepResult(status=STEP_RETRY, output={"tool": result, "stripe_called": True}, error=result.get("error"))
        return StepResult(
            status=STEP_FAILED,
            output={"tool": result, "stripe_called": True, "denied": False},
            error=str(result.get("error") or "stripe_failed"),
        )
    return StepResult(
        status=STEP_SUCCESS,
        output={"stripe": dict(result.get("data") or {}), "stripe_called": True, "denied": False},
    )


def update_case_resolved(rt: StepRuntime) -> StepResult:
    case_id = rt.ctx.case_id
    if not case_id:
        return StepResult(status=STEP_SUCCESS, output={"case_updated": False})
    from db.models import CaseRow
    from datetime import datetime

    with rt.session_factory() as db:
        row = db.get(CaseRow, case_id)
        if row is None:
            return StepResult(status=STEP_FAILED, error="case_not_found", output={"case_updated": False})
        row.status = "resolved"
        row.updated_at = datetime.utcnow()
        db.commit()
    return StepResult(status=STEP_SUCCESS, output={"case_status": "resolved", "case_updated": True})


def notify(rt: StepRuntime) -> StepResult:
    tool = None
    getter = getattr(rt.ctx.tool_registry, "get", None)
    if callable(getter):
        tool = getter("gmail_send_email")
    if tool is None:
        return StepResult(status=STEP_SUCCESS, output={"notify": {"skipped": True}})
    return StepResult(status=STEP_SUCCESS, output={"notify": {"skipped": True, "reason": "workflow_does_not_send_yet"}})


def gate_on_policy(rt: StepRuntime, *, success_output: Dict[str, Any] | None = None) -> StepResult:
    """Turn a stored decision into a stop or a terminal success. No side effects."""
    policy = dict(rt.policy or {})
    if policy.get("requires_strong_auth") is True:
        return StepResult(status=STEP_WAIT_AUTH, output={"policy": policy}, error="AUTH")
    required: List[str] = [name for name in policy.get("requires_inputs") or [] if name in _INPUT_FIELDS]
    if required:
        return StepResult(
            status=STEP_WAIT_INPUT,
            output={"requires_inputs": required, "policy": policy},
            error=",".join(required),
        )
    if policy.get("requires_approval") is True:
        return StepResult(status=STEP_WAIT_APPROVAL, output={"policy": policy}, error="approval")
    if policy.get("allowed") is not True:
        body = {"denied": True, "policy": policy}
        body.update(success_output or {})
        return StepResult(status=STEP_SUCCESS, output=body)
    body = {"denied": False, "policy": policy}
    body.update(success_output or {})
    return StepResult(status=STEP_SUCCESS, output=body)
