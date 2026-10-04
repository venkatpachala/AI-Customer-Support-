"""Steps shared by the workflow definitions. Policy comes from policy.evaluate."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

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


def _auth_for_step(rt: StepRuntime, action: str) -> str:
    """Public ownership on the case wins. Engine callers keep ctx until then."""
    from identity.ownership import case_auth

    level, orders, checked = case_auth(rt.ctx.case_id, rt.session_factory)
    order_id = str(rt.ctx.slots.get("order_id") or "")
    if checked:
        if action == "refund" and (level != "verified" or not order_id or order_id not in orders):
            return "anonymous"
        return level
    return rt.ctx.auth_level


def assert_auth(action: str):
    def step(rt: StepRuntime) -> StepResult:
        level = _auth_for_step(rt, action)
        decision = evaluate(
            rt.ctx.tenant_id,
            action,
            auth_level=level,
            slots=dict(rt.ctx.slots),
        )
        payload = decision_payload(decision)
        if decision.requires_strong_auth:
            return StepResult(
                status=STEP_WAIT_AUTH,
                output={"policy": payload},
                error="AUTH",
            )
        return StepResult(status=STEP_SUCCESS, output={"auth_level": level})

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
            auth_level=_auth_for_step(rt, action),
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


def _refund_task_status(rt: StepRuntime) -> Optional[str]:
    """Latest refund_approval row for this run. pending, approved, or rejected."""
    from sqlalchemy import select

    from db.models import HumanTaskRow

    with rt.session_factory() as db:
        row = db.execute(
            select(HumanTaskRow)
            .where(HumanTaskRow.workflow_run_id == rt.run_id)
            .where(HumanTaskRow.task_type == "refund_approval")
            .order_by(HumanTaskRow.created_at.desc())
        ).scalars().first()
        return None if row is None else row.status


def require_refund_approval(rt: StepRuntime) -> StepResult:
    """Stop while a supervisor decision is pending.

    An approved refund_approval task continues the same run. A rejected task
    stops it. evaluate() is not asked again here; the stored snapshot stays
    the eligibility record, and execute_refund applies the approval override.
    """
    policy = dict(rt.policy or {})
    decision = _refund_task_status(rt)
    if decision == "approved":
        return StepResult(status=STEP_SUCCESS, output={"approval": "approved", "policy": policy})
    if decision == "rejected":
        return StepResult(
            status=STEP_FAILED,
            output={"denied": True, "approval": "rejected", "policy": policy},
            error="approval_rejected",
        )
    if decision == "pending" or policy.get("requires_approval") is True:
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
                "photos_received": bool(slots.get("photos_received")),
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
    return StepResult(status=STEP_SUCCESS, output={"approval": "not_required", "policy": policy})


def _approval_override(rt: StepRuntime, policy: Dict[str, Any]) -> bool:
    """Supervisor approval may move a manager-band refund.

    evaluate() still returns allowed False and requires_approval True for
    amounts between the auto cap and the manager cap. After the
    refund_approval task is approved, Stripe may run when photos and auth
    are already satisfied and the amount is still within manager_max.

    manager_max is the decision's max_amount. An amount above that cap, an
    OUT_OF_POLICY denial, a fraud denial, missing photos, or missing auth
    are not overridden.
    """
    if policy.get("deny_code") == "OUT_OF_POLICY":
        return False
    if policy.get("requires_strong_auth") is True:
        return False
    if list(policy.get("requires_inputs") or []):
        return False
    if policy.get("deny_code") not in (None, "AMOUNT"):
        return False
    if _refund_task_status(rt) != "approved":
        return False
    try:
        amount = float(rt.ctx.slots.get("amount"))
        cap = float(policy.get("max_amount"))
    except (TypeError, ValueError):
        return False
    return amount > 0 and amount <= cap


def _over_daily_cap(rt: StepRuntime) -> bool:
    """Sum today's succeeded refund amounts. Over the tenant cap stays in approval."""
    from datetime import datetime

    from sqlalchemy import select

    from config.tenant_contract import load_platform_tenant
    from db.models import WorkflowRunRow

    try:
        cap = float(load_platform_tenant(rt.ctx.tenant_id).limits.live_refund_cap_inr)
    except Exception:
        cap = 20000.0
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0.0
    with rt.session_factory() as db:
        rows = db.execute(
            select(WorkflowRunRow)
            .where(WorkflowRunRow.tenant_id == rt.ctx.tenant_id)
            .where(WorkflowRunRow.workflow_name == "refund")
            .where(WorkflowRunRow.status == "succeeded")
        ).scalars().all()
        for row in rows:
            finished = row.finished_at or row.updated_at or row.created_at
            if finished is None or finished < start:
                continue
            slots = dict((row.input_json or {}).get("slots") or {})
            try:
                total += float(slots.get("amount") or 0)
            except (TypeError, ValueError):
                continue
    try:
        incoming = float(rt.ctx.slots.get("amount") or 0)
    except (TypeError, ValueError):
        incoming = 0.0
    return total + incoming > cap


def execute_refund(rt: StepRuntime) -> StepResult:
    """Stripe runs when the snapshot allows it, or when a supervisor approved a manager-band refund."""
    policy = dict(rt.policy or {})
    if policy.get("allowed") is not True and not _approval_override(rt, policy):
        return StepResult(
            status=STEP_FAILED,
            output={"denied": True, "stripe_called": False, "policy": policy},
            error=str(policy.get("deny_code") or "policy_not_allowed"),
        )
    tools_live = os.getenv("TOOLS_MODE", "mock").strip().lower() == "live"
    stripe_mode = os.getenv("STRIPE_MODE", "test").strip().lower()
    force_fail = os.getenv("WORKFLOW_STRIPE_FAIL", "").strip() == "1"
    if force_fail and not (tools_live and stripe_mode in {"test", "live"}) and rt.attempt < 3:
        return StepResult(
            status=STEP_RETRY,
            output={"stripe_called": False, "attempt": rt.attempt},
            error="stripe_forced_failure",
        )
    if tools_live and _over_daily_cap(rt):
        slots = dict(rt.ctx.slots)
        return StepResult(
            status=STEP_WAIT_APPROVAL,
            output={"policy": policy, "daily_cap": True, "stripe_called": False},
            human_task={
                "type": "refund_approval",
                "payload": {
                    "amount": slots.get("amount"),
                    "order_id": slots.get("order_id"),
                    "reason": slots.get("reason"),
                    "policy_version": policy.get("policy_version"),
                    "daily_cap": True,
                },
            },
            error="daily_cap",
        )
    slots = dict(rt.ctx.slots)
    params = {
        "order_id": slots.get("order_id"),
        "amount": slots.get("amount"),
        "currency": "inr",
        "reason": "requested_by_customer",
        "idempotency_key": stripe_step_key(rt.run_id),
        "require_approval_above_limit": False,
        "payment_intent_id": slots.get("payment_intent_id"),
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
