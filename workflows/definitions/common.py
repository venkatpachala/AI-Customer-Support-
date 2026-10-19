"""Steps shared by the workflow definitions. Policy comes from policy.evaluate."""
from __future__ import annotations

import os
import hashlib
import json
from common.money import to_minor
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
    from controlplane.mode import current_tools_mode
    if current_tools_mode() == "live":
        from identity.verification import verified_order
        if not verified_order(rt.ctx.case_id, order_id):
            return StepResult(status=STEP_WAIT_AUTH, output={"requires_inputs": ["verification_code"]}, error="strong_verification_required")
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
        if row is None:
            return None
        fingerprint = (row.payload_json or {}).get("action_fingerprint")
        if fingerprint and fingerprint != _action_fingerprint(rt):
            return None
        return row.status


def _action_fingerprint(rt: StepRuntime) -> str:
    from workflows.idempotency import approval_fingerprint
    return approval_fingerprint(rt.ctx.slots)


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
                "action_fingerprint": _action_fingerprint(rt),
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
    """Reserve before Stripe; concurrent workflows cannot oversubscribe the cap."""
    from config.tenant_contract import load_platform_tenant
    from workflows.refund_budget import reserve
    try:
        cap = to_minor(load_platform_tenant(rt.ctx.tenant_id).limits.live_refund_cap_inr)
        amount = to_minor(rt.ctx.slots.get("amount"))
    except (ValueError, TypeError):
        return True
    return not reserve(rt.ctx.tenant_id, rt.run_id, amount, cap, rt.session_factory)


def execute_refund(rt: StepRuntime) -> StepResult:
    """Stripe runs when the snapshot allows it, or when a supervisor approved a manager-band refund."""
    policy = dict(rt.policy or {})
    if policy.get("allowed") is not True and not _approval_override(rt, policy):
        return StepResult(
            status=STEP_FAILED,
            output={"denied": True, "stripe_called": False, "policy": policy},
            error=str(policy.get("deny_code") or "policy_not_allowed"),
        )
    from controlplane.mode import current_tools_mode

    tools_live = current_tools_mode() == "live"
    if tools_live:
        from identity.verification import verified_order
        if not verified_order(rt.ctx.case_id, str(rt.ctx.slots.get("order_id") or "")):
            return StepResult(status=STEP_WAIT_AUTH, error="strong_verification_required",
                              output={"stripe_called": False, "requires_inputs": ["verification_code"]})
    if tools_live and os.getenv("LIVE_REFUNDS_ENABLED") != "1":
        return StepResult(status=STEP_WAIT_APPROVAL,
                          output={"stripe_called": False, "policy": policy},
                          error="live_refunds_disabled")
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
    payment_intent_id = slots.get("payment_intent_id")
    if tools_live:
        from datetime import datetime, timedelta
        from sqlalchemy import select
        from db.models import OrderPaymentRow
        with rt.session_factory() as db:
            mapping = db.execute(select(OrderPaymentRow).where(OrderPaymentRow.tenant_id == rt.ctx.tenant_id,
                OrderPaymentRow.order_id == str(slots.get("order_id") or ""),
                OrderPaymentRow.verified_at > datetime.utcnow() - timedelta(minutes=5))).scalars().first()
            if mapping is None or mapping.currency.lower() != "inr" or to_minor(slots.get("amount")) > mapping.refundable_minor:
                return StepResult(status=STEP_WAIT_APPROVAL, error="verified_payment_mapping_required",
                                  output={"stripe_called": False, "policy": policy})
            payment_intent_id = mapping.payment_intent_id
    params = {
        "order_id": slots.get("order_id"),
        "amount": to_minor(slots.get("amount")),
        "currency": "inr",
        "reason": "requested_by_customer",
        "idempotency_key": stripe_step_key(rt.run_id),
        "require_approval_above_limit": False,
        "payment_intent_id": payment_intent_id,
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
    provider_status = str((result.get("data") or {}).get("status") or "")
    if provider_status and provider_status != "succeeded":
        return StepResult(status=STEP_WAIT_APPROVAL,
                          output={"stripe": dict(result.get("data") or {}), "stripe_called": True},
                          error="provider_confirmation_required")
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
    from controlplane.webhooks import deliver_decision
    deliver_decision(tenant_id=rt.ctx.tenant_id, case_id=rt.ctx.case_id,
                     workflow_status="succeeded", run_id=rt.run_id,
                     session_factory=rt.session_factory)
    tool = None
    getter = getattr(rt.ctx.tool_registry, "get", None)
    if callable(getter):
        tool = getter("gmail_send_email")
    if tool is None:
        return StepResult(status=STEP_SUCCESS, output={"notify": {"skipped": True}})
    return StepResult(status=STEP_SUCCESS, output={"notify": {"queued": True, "channel": "webhook"}})


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
