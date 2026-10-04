"""An approved manager-band refund continues. An amount above the cap does not."""
from __future__ import annotations

import uuid

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
from memory.service import MemoryService
from workflows.approvals import approve_task
from workflows.context import WorkflowContext
from workflows.engine import WorkflowEngine


class FakeTools:
    def __init__(self):
        self.stripe_calls = 0

    def get(self, name):
        if name == "shopify_get_order":
            return lambda params: {
                "status": "success",
                "data": {"order_id": str(params.get("order_id") or ""), "status": "delivered"},
            }
        if name == "stripe_refund":
            return self.create_refund
        return None

    def create_refund(self, params):
        self.stripe_calls += 1
        return {"status": "success", "data": {"refund_id": "re_override"}}


def _run(amount: int):
    init_db()
    memory = MemoryService()
    customer_id = "ovr" + uuid.uuid4().hex[:8]
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
    view = engine.start(
        "refund",
        WorkflowContext(
            tenant_id="zepto",
            case_id=case.case_id,
            customer_id=customer_id,
            auth_level="verified",
            conversation_id=session.session_id,
            slots={
                "order_id": "12345",
                "amount": amount,
                "reason": "damaged",
                "photos_received": True,
            },
        ),
    )
    return session, case, tools, engine, view


def _purge(case_id: str, session_id: str):
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


def test_approved_manager_band_refund_does_not_wait_again():
    session, case, tools, engine, view = _run(2500)
    try:
        assert view.status == "waiting_approval"
        assert tools.stripe_calls == 0
        with SessionLocal() as db:
            task_id = db.execute(
                select(HumanTaskRow.id).where(HumanTaskRow.workflow_run_id == view.run_id)
            ).scalar_one()
        result = approve_task(task_id, tenant_id="zepto", actor_id="supervisor_1", engine=engine)
        assert result["workflow_run_id"] == view.run_id
        assert result["workflow_status"] == "succeeded"
        assert tools.stripe_calls == 1
        with SessionLocal() as db:
            case_row = db.get(CaseRow, case.case_id)
            assert case_row.status == "resolved"
            steps = db.execute(
                select(WorkflowStepRow).where(WorkflowStepRow.run_id == view.run_id)
            ).scalars().all()
        approval = [step for step in steps if step.step_name == "require_approval"]
        assert approval[-1].status == "success"
    finally:
        _purge(case.case_id, session.session_id)


def test_amount_above_manager_is_not_overridden():
    session, case, tools, engine, view = _run(50000)
    try:
        assert view.status == "waiting_approval"
        with SessionLocal() as db:
            task_id = db.execute(
                select(HumanTaskRow.id).where(HumanTaskRow.workflow_run_id == view.run_id)
            ).scalar_one()
        result = approve_task(task_id, tenant_id="zepto", actor_id="supervisor_1", engine=engine)
        assert result["workflow_run_id"] == view.run_id
        assert result["workflow_status"] == "failed"
        assert tools.stripe_calls == 0
    finally:
        _purge(case.case_id, session.session_id)
