"""Run one refund workflow per scenario. No uvicorn and no second order."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from sqlalchemy import delete, select

from db.models import (
    CaseRow,
    HumanTaskRow,
    MessageRow,
    PlatformConversationRow,
    PlatformEventRow,
    SessionRow,
    WorkflowRunRow,
    WorkflowStepRow,
)
from db.session import SessionLocal, init_db
from evaluation.graders.policy_grader import policy_mismatches
from evaluation.graders.safety_grader import unauthorized_side_effect
from evaluation.graders.workflow_grader import (
    has_pending_task,
    pending_task_id,
    run_status,
    stripe_create_count,
)
from memory.service import MemoryService
from workflows.approvals import ApprovalError, approve_task, reject_task
from workflows.context import WorkflowContext
from workflows.engine import WorkflowEngine

SCENARIO_PATH = Path(__file__).resolve().parents[1] / "scenarios" / "p0_platform.yaml"


class CountingTools:
    """Stand-in registry. Counts creates. Does not talk to Stripe or Shopify."""

    def __init__(self):
        self.stripe_calls = 0
        self.shopify_calls = 0
        self.order_ids: List[str] = []

    def get(self, name: str):
        if name == "shopify_get_order":
            return self.get_order
        if name == "stripe_refund":
            return self.create_refund
        return None

    def get_order(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.shopify_calls += 1
        order_id = str(params.get("order_id") or "")
        self.order_ids.append(order_id)
        return {"status": "success", "data": {"order_id": order_id, "status": "delivered"}}

    def create_refund(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.stripe_calls += 1
        order_id = str(params.get("order_id") or "")
        if order_id:
            self.order_ids.append(order_id)
        return {"status": "success", "data": {"refund_id": "re_sim", "amount": params.get("amount")}}


@dataclass
class ScenarioResult:
    id: str
    passed: bool
    status: Optional[str] = None
    stripe: int = 0
    shopify: int = 0
    stripe_before_approve: int = 0
    status_after_start: Optional[str] = None
    pending_tasks: int = 0
    approved_task: bool = False
    policy: Dict[str, Any] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)
    unauthorized: int = 0
    run_id: Optional[str] = None


def load_scenarios(path: Path = SCENARIO_PATH) -> List[Dict[str, Any]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = dict(document.get("defaults") or {})
    scenarios = []
    for raw in document.get("scenarios") or []:
        item = dict(defaults)
        item.update(raw)
        slots = dict(item.get("slots") or {})
        slots.setdefault("order_id", item.get("order_id"))
        item["slots"] = slots
        scenarios.append(item)
    return scenarios


def run_platform_scenarios(ids: Optional[List[str]] = None) -> List[ScenarioResult]:
    os.environ.setdefault("TOOLS_MODE", "mock")
    init_db()
    wanted = set(ids or [])
    results: List[ScenarioResult] = []
    for scenario in load_scenarios():
        if wanted and scenario["id"] not in wanted:
            continue
        results.append(_run_one(scenario))
    return results


def _run_one(scenario: Dict[str, Any]) -> ScenarioResult:
    memory = MemoryService()
    customer_id = "p0f" + uuid.uuid4().hex[:8]
    session = memory.create_session(customer_id=customer_id, tenant_id=scenario["tenant_id"])
    case = memory.create_case(
        session_id=session.session_id,
        customer_id=customer_id,
        tenant_id=scenario["tenant_id"],
        order_id=str(scenario["slots"].get("order_id") or ""),
        issue_type="refund",
    )
    tools = CountingTools()
    observations: List[Dict[str, Any]] = []

    def _watch(_seconds: float) -> None:
        with SessionLocal() as db:
            run = db.execute(
                select(WorkflowRunRow).where(WorkflowRunRow.case_id == case.case_id)
            ).scalars().first()
            case_row = db.get(CaseRow, case.case_id)
            output = dict(run.output_json or {}) if run is not None else {}
            observations.append({
                "status": None if run is None else run.status,
                "case_status": None if case_row is None else case_row.status,
                "refunded": output.get("refunded"),
                "stripe_called": output.get("stripe_called"),
            })

    engine = WorkflowEngine(tool_registry=tools, sleeper=_watch)
    previous_fail = os.environ.get("WORKFLOW_STRIPE_FAIL")
    env = scenario.get("env") or {}
    result = ScenarioResult(id=scenario["id"], passed=False)
    try:
        for key, value in env.items():
            os.environ[str(key)] = str(value)
        if "WORKFLOW_STRIPE_FAIL" not in env and previous_fail is not None:
            os.environ.pop("WORKFLOW_STRIPE_FAIL", None)
        view = engine.start(
            scenario.get("workflow") or "refund",
            WorkflowContext(
                tenant_id=scenario["tenant_id"],
                case_id=case.case_id,
                customer_id=customer_id,
                auth_level=scenario.get("auth_level") or "anonymous",
                conversation_id=session.session_id,
                slots=dict(scenario["slots"]),
            ),
        )
        result.run_id = view.run_id
        result.stripe_before_approve = tools.stripe_calls
        result.status_after_start = view.status
        result.status = view.status
        second_code = None
        acted_task_id = None
        for action in scenario.get("actions") or []:
            task_id = acted_task_id or pending_task_id(view.run_id)
            if action == "approve":
                if task_id is None:
                    result.failures.append("approve found no pending task")
                    continue
                acted_task_id = task_id
                try:
                    approved = approve_task(
                        task_id,
                        tenant_id=scenario["tenant_id"],
                        actor_id="supervisor_1",
                        engine=engine,
                    )
                    result.status = approved["workflow_status"]
                except ApprovalError as exc:
                    second_code = exc.status_code
            elif action == "reject":
                if task_id is None:
                    result.failures.append("reject found no pending task")
                else:
                    rejected = reject_task(
                        task_id,
                        tenant_id=scenario["tenant_id"],
                        actor_id="supervisor_1",
                    )
                    result.status = rejected["workflow_status"]
        result.status = run_status(view.run_id) or result.status
        result.stripe = max(tools.stripe_calls, stripe_create_count(view.run_id))
        result.shopify = tools.shopify_calls
        result.pending_tasks = 1 if has_pending_task(view.run_id) else 0
        with SessionLocal() as db:
            run = db.get(WorkflowRunRow, view.run_id)
            output = dict(run.output_json or {}) if run is not None else {}
            approved = db.execute(
                select(HumanTaskRow)
                .where(HumanTaskRow.workflow_run_id == view.run_id)
                .where(HumanTaskRow.status == "approved")
            ).scalars().first()
        result.policy = dict(output.get("policy") or {})
        result.approved_task = approved is not None
        result.unauthorized = unauthorized_side_effect(
            stripe_calls=result.stripe,
            status=result.status,
            policy=result.policy,
            approved_task=result.approved_task,
            amount=scenario["slots"].get("amount"),
        )
        if len(set(tools.order_ids)) > 1:
            result.failures.append(f"fan-out across orders {tools.order_ids}")
        result.failures.extend(_injection_guard(scenario))
        result.failures.extend(_expect(scenario.get("expect") or {}, result, observations, second_code))
        if result.unauthorized:
            result.failures.append(f"unauthorized_side_effect={result.unauthorized}")
        result.passed = not result.failures
        return result
    finally:
        if previous_fail is None:
            os.environ.pop("WORKFLOW_STRIPE_FAIL", None)
        else:
            os.environ["WORKFLOW_STRIPE_FAIL"] = previous_fail
        _purge(case.case_id, session.session_id)


def _injection_guard(scenario: Dict[str, Any]) -> List[str]:
    """A verified refund with an ignore-policy reason must match reason=other.

    The workflow itself stays on the scenario's auth level. This call only
    proves the instruction text does not open a separate allow path.
    """
    reason = str((scenario.get("slots") or {}).get("reason") or "")
    if "ignore" not in reason.lower():
        return []
    from policy import evaluate

    slots = dict(scenario["slots"])
    ordinary = dict(slots)
    ordinary["reason"] = "other"
    action = scenario.get("workflow") or "refund"
    injected = evaluate(scenario["tenant_id"], action, auth_level="verified", slots=slots)
    baseline = evaluate(scenario["tenant_id"], action, auth_level="verified", slots=ordinary)
    if injected.allowed == baseline.allowed and injected.deny_code == baseline.deny_code:
        return []
    return [
        "injection changed the verified refund decision "
        f"allowed={injected.allowed} baseline={baseline.allowed} "
        f"deny={injected.deny_code} baseline_deny={baseline.deny_code}"
    ]


def _expect(expect: Dict[str, Any], result: ScenarioResult, observations: List[Dict[str, Any]], second_code: Optional[int]) -> List[str]:
    failures: List[str] = []
    if "status" in expect and result.status != expect["status"]:
        failures.append(f"status expected {expect['status']} got {result.status}")
    if "status_after_start" in expect and result.status_after_start != expect["status_after_start"]:
        failures.append(
            f"status_after_start expected {expect['status_after_start']} got {result.status_after_start}"
        )
    if "stripe" in expect and result.stripe != expect["stripe"]:
        failures.append(f"stripe expected {expect['stripe']} got {result.stripe}")
    if "stripe_before_approve" in expect and result.stripe_before_approve != expect["stripe_before_approve"]:
        failures.append(
            f"stripe_before_approve expected {expect['stripe_before_approve']} got {result.stripe_before_approve}"
        )
    if "shopify" in expect and result.shopify != expect["shopify"]:
        failures.append(f"shopify expected {expect['shopify']} got {result.shopify}")
    if "pending_task" in expect:
        pending = result.pending_tasks > 0
        if pending is not bool(expect["pending_task"]):
            failures.append(f"pending_task expected {expect['pending_task']} got {pending}")
    if "second_approve_status" in expect and second_code != expect["second_approve_status"]:
        failures.append(f"second approve expected {expect['second_approve_status']} got {second_code}")
    if expect.get("saw_retry_before_success"):
        if not observations:
            failures.append("stripe retry did not pause before success")
        for item in observations:
            if item.get("status") == "succeeded" or item.get("refunded") is True or item.get("case_status") == "resolved":
                failures.append(f"customer-facing success persisted during retry: {item}")
    failures.extend(policy_mismatches(result.policy, expect))
    return failures


def _purge(case_id: str, session_id: str) -> None:
    with SessionLocal() as db:
        run_ids = list(
            db.execute(select(WorkflowRunRow.id).where(WorkflowRunRow.case_id == case_id)).scalars()
        )
        if run_ids:
            db.execute(delete(WorkflowStepRow).where(WorkflowStepRow.run_id.in_(run_ids)))
            db.execute(delete(HumanTaskRow).where(HumanTaskRow.workflow_run_id.in_(run_ids)))
            db.execute(delete(WorkflowRunRow).where(WorkflowRunRow.id.in_(run_ids)))
        db.execute(delete(PlatformEventRow).where(PlatformEventRow.case_id == case_id))
        db.execute(delete(PlatformConversationRow).where(PlatformConversationRow.session_id == session_id))
        db.execute(delete(MessageRow).where(MessageRow.session_id == session_id))
        db.execute(delete(CaseRow).where(CaseRow.case_id == case_id))
        db.execute(delete(SessionRow).where(SessionRow.session_id == session_id))
        db.commit()
