"""Executor must not call Stripe. Refunds go through WorkflowEngine."""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from db.models import (
    CaseRow,
    HumanTaskRow,
    MessageRow,
    PlatformConversationRow,
    SessionRow,
    WorkflowRunRow,
    WorkflowStepRow,
)
from db.session import SessionLocal, init_db
from memory.service import MemoryService
from orchestration.execution import execution_engine_node
from orchestration.hitl import check_escalation
from orchestration.planner import normalize_action_plan
from orchestration.plans import ExecutionPlan, PlanStep
from orchestration.verifier import verifier_node
from workflows.engine import WorkflowEngine


class FakeTools:
    def __init__(self):
        self.order_calls = 0
        self.stripe_calls = 0

    def get(self, name):
        if name == "shopify_get_order":
            return self.get_order
        if name == "stripe_refund":
            return self.create_refund
        return None

    def get_order(self, params):
        self.order_calls += 1
        return {
            "status": "success",
            "data": {
                "order_id": str(params.get("order_id") or ""),
                "status": "delivered",
                "financial_status": "paid",
                "currency": "INR",
            },
        }

    def create_refund(self, params):
        self.stripe_calls += 1
        return {"status": "success", "data": {"refund_id": "re_should_not_come_from_executor"}}


def _world():
    init_db()
    memory = MemoryService()
    customer_id = "p0d" + uuid.uuid4().hex[:8]
    session = memory.create_session(customer_id=customer_id, tenant_id="zepto")
    case = memory.create_case(
        session_id=session.session_id,
        customer_id=customer_id,
        tenant_id="zepto",
        order_id="12345",
        issue_type="refund",
    )
    tools = FakeTools()
    engine = WorkflowEngine(tool_registry=tools, sleeper=lambda _seconds: None)
    return memory, session, case, tools, engine


def _purge(case_id: str, session_id: str):
    with SessionLocal() as db:
        run_ids = list(
            db.execute(
                select(WorkflowRunRow.id).where(WorkflowRunRow.case_id == case_id)
            ).scalars()
        )
        if run_ids:
            db.execute(delete(WorkflowStepRow).where(WorkflowStepRow.run_id.in_(run_ids)))
            db.execute(delete(HumanTaskRow).where(HumanTaskRow.workflow_run_id.in_(run_ids)))
            db.execute(delete(WorkflowRunRow).where(WorkflowRunRow.id.in_(run_ids)))
        db.execute(delete(PlatformConversationRow).where(PlatformConversationRow.session_id == session_id))
        db.execute(delete(MessageRow).where(MessageRow.session_id == session_id))
        db.execute(delete(CaseRow).where(CaseRow.case_id == case_id))
        db.execute(delete(SessionRow).where(SessionRow.session_id == session_id))
        db.commit()


def _state(case, session, tools, engine, slots, *, memory_extra=None):
    plan = {
        "intent": "refund",
        "workflow": "refund",
        "slots": dict(slots),
        "missing_inputs": [],
        "steps": [
            {"step": 1, "tool": "shopify_get_order", "required": True, "depends_on": []},
            {"step": 2, "tool": "stripe_refund", "required": True, "depends_on": [1]},
        ],
    }
    memory = {
        "case_id": case.case_id,
        "session_id": session.session_id,
        "active_order_id": "12345",
        "photos_received": bool(slots.get("photos_received")),
        "auth_level": "verified",
    }
    if memory_extra:
        memory.update(memory_extra)
    return {
        "messages": [],
        "tenant_id": "zepto",
        "customer_id": case.customer_id,
        "case_id": case.case_id,
        "session_id": session.session_id,
        "auth_level": "verified",
        "request_id": "p0d",
        "current_plan": plan,
        "memory_context": memory,
        "tool_registry": tools,
        "workflow_engine": engine,
    }


def test_planner_strips_stripe_and_names_workflow():
    plan = ExecutionPlan(
        plan_id="plan_refund",
        intent="refund",
        steps=[
            PlanStep(step=1, description="Create refund", tool="stripe_refund", required=True),
            PlanStep(step=2, description="Start return", tool="shopify_initiate_return", required=True),
        ],
    )
    normalized = normalize_action_plan(
        plan,
        query="Please refund ₹2500 for damaged order 12345",
        memory={"active_order_id": "12345", "photos_received": False},
        state_intent="refund",
    )
    tools = [step.tool for step in normalized.steps]
    assert normalized.workflow == "refund"
    assert "stripe_refund" not in tools
    assert "shopify_initiate_return" not in tools
    assert "shopify_get_order" in tools
    assert normalized.slots["order_id"] == "12345"
    assert normalized.slots["amount"] == 2500
    assert normalized.slots["reason"] == "damaged"
    assert normalized.slots["photos_received"] is False


def test_policy_question_does_not_start_refund():
    plan = ExecutionPlan(
        plan_id="plan_faq",
        intent="refund",
        steps=[PlanStep(step=1, description="Refund", tool="stripe_refund", required=True)],
    )
    normalized = normalize_action_plan(
        plan,
        query="What is your refund policy?",
        memory={},
        state_intent="policy_query",
    )
    assert normalized.workflow is None
    assert all(step.tool != "stripe_refund" for step in normalized.steps)


def test_executor_high_value_waits_without_stripe():
    _memory, session, case, tools, engine = _world()
    try:
        result = execution_engine_node(
            _state(
                case,
                session,
                tools,
                engine,
                {"order_id": "12345", "amount": 2500, "reason": "damaged", "photos_received": True},
            )
        )
        assert result["workflow_status"] == "waiting_approval"
        assert result["workflow_run_id"]
        assert result["policy_decision"]["allowed"] is False
        assert result["policy_decision"]["requires_approval"] is True
        assert tools.stripe_calls == 0
        stripe = result["tool_results"]["stripe_refund"]
        assert stripe["status"] == "skipped"
        assert stripe["reason"] == "redirected_to_workflow"
        with SessionLocal() as db:
            tasks = list(
                db.execute(
                    select(HumanTaskRow).where(
                        HumanTaskRow.workflow_run_id == result["workflow_run_id"]
                    )
                ).scalars()
            )
        assert len(tasks) == 1
    finally:
        _purge(case.case_id, session.session_id)


def test_executor_missing_photos_waits_for_input():
    _memory, session, case, tools, engine = _world()
    try:
        result = execution_engine_node(
            _state(
                case,
                session,
                tools,
                engine,
                {"order_id": "12345", "amount": 2500, "reason": "damaged", "photos_received": False},
            )
        )
        assert result["workflow_status"] == "waiting_input"
        assert "photos" in (result.get("missing_inputs") or [])
        assert result["missing_photos"] is True
        assert tools.stripe_calls == 0
        with SessionLocal() as db:
            tasks = list(
                db.execute(
                    select(HumanTaskRow).where(
                        HumanTaskRow.workflow_run_id == result["workflow_run_id"]
                    )
                ).scalars()
            )
        assert tasks == []
    finally:
        _purge(case.case_id, session.session_id)


def test_second_turn_resumes_same_run_after_photos():
    _memory, session, case, tools, engine = _world()
    try:
        first = execution_engine_node(
            _state(
                case,
                session,
                tools,
                engine,
                {"order_id": "12345", "amount": 500, "reason": "damaged", "photos_received": False},
            )
        )
        assert first["workflow_status"] == "waiting_input"
        assert tools.stripe_calls == 0
        second = execution_engine_node(
            _state(
                case,
                session,
                tools,
                engine,
                {"order_id": "12345", "amount": 500, "reason": "damaged", "photos_received": True},
                memory_extra={
                    "photos_received": True,
                    "tool_results_summary": {
                        "workflow_run_id": first["workflow_run_id"],
                        "workflow_status": first["workflow_status"],
                    },
                },
            )
        )
        assert second["workflow_run_id"] == first["workflow_run_id"]
        assert second["workflow_status"] == "succeeded"
        assert second["policy_decision"]["allowed"] is True
        assert tools.stripe_calls == 1
        assert second["tool_results"]["stripe_refund"]["status"] == "skipped"
    finally:
        _purge(case.case_id, session.session_id)


def test_preference_refund_does_not_call_stripe():
    _memory, session, case, tools, engine = _world()
    try:
        result = execution_engine_node(
            _state(
                case,
                session,
                tools,
                engine,
                {"order_id": "12345", "amount": 500, "reason": "preference", "photos_received": True},
            )
        )
        assert result["workflow_status"] == "failed"
        assert result["policy_decision"]["deny_code"] == "OUT_OF_POLICY"
        assert tools.stripe_calls == 0
    finally:
        _purge(case.case_id, session.session_id)


def test_verifier_treats_waiting_and_policy_denial_as_expected():
    waiting = verifier_node({
        "request_id": "v1",
        "workflow_status": "waiting_approval",
        "workflow_run_id": "run-1",
        "policy_decision": {"requires_approval": True, "allowed": False, "deny_code": "AMOUNT"},
        "current_plan": {
            "intent": "refund",
            "steps": [{"tool": "stripe_refund", "required": True}],
        },
        "tool_results": {},
    })
    assert waiting["verification_passed"] is True
    assert waiting["needs_escalation"] is False

    photos = verifier_node({
        "request_id": "v2",
        "workflow_status": "waiting_input",
        "workflow_run_id": "run-2",
        "policy_decision": {"requires_inputs": ["photos"], "allowed": False},
        "current_plan": {"intent": "refund", "steps": [], "missing_inputs": []},
        "tool_results": {},
    })
    assert photos["verification_passed"] is True
    assert photos["missing_photos"] is True

    denied = verifier_node({
        "request_id": "v3",
        "workflow_status": "failed",
        "workflow_run_id": "run-3",
        "policy_decision": {"allowed": False, "deny_code": "OUT_OF_POLICY"},
        "current_plan": {"intent": "refund", "steps": []},
        "tool_results": {},
    })
    assert denied["verification_passed"] is True
    assert denied["needs_escalation"] is False


class _Msg:
    def __init__(self, content):
        self.content = content


def test_hitl_uses_workflow_flags_not_the_amount_shortcut():
    approval = check_escalation({
        "request_id": "h1",
        "workflow_status": "waiting_approval",
        "workflow_run_id": "run-9",
        "policy_decision": {"requires_approval": True, "allowed": False, "deny_code": "AMOUNT"},
        "current_plan": {"intent": "refund", "slots": {"amount": 2500}},
        "messages": [],
        "intent": "refund",
    })
    assert approval["needs_escalation"] is True
    assert "run-9" in approval["escalation_reason"]
    assert "pending refund approval" in approval["escalation_reason"]

    photos = check_escalation({
        "request_id": "h2",
        "workflow_status": "waiting_input",
        "workflow_run_id": "run-8",
        "missing_photos": True,
        "policy_decision": {
            "requires_approval": False,
            "requires_inputs": ["photos"],
            "allowed": False,
            "deny_code": "MISSING_INPUT",
        },
        "current_plan": {"intent": "refund", "slots": {"amount": 2500}},
        "messages": [_Msg("Please refund ₹2500 for my damaged order")],
        "intent": "refund",
        "tenant_config": {"approval": {"high_value_refund_limit": 2000}},
    })
    assert photos["needs_escalation"] is False

    auth = check_escalation({
        "request_id": "h3",
        "workflow_status": "waiting_auth",
        "workflow_run_id": "run-7",
        "policy_decision": {"requires_strong_auth": True, "deny_code": "AUTH"},
        "messages": [],
    })
    assert auth["needs_escalation"] is False
