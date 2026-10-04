"""Approve resumes the same run. Reject never calls Stripe."""
from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
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
from gateway.routers.approvals import engine_override, router as approvals_router
from gateway.routers.cases import router as cases_router
from gateway.routers.workflows import router as workflows_router
from memory.service import MemoryService
from workflows.context import WorkflowContext
from workflows.engine import WorkflowEngine

app = FastAPI()
app.include_router(approvals_router)
app.include_router(workflows_router)
app.include_router(cases_router)
client = TestClient(app)

HEADERS = {
    "X-Tenant-Id": "zepto",
    "X-Actor-Role": "supervisor",
    "X-Actor-Id": "supervisor_1",
}


class FakeTools:
    def __init__(self):
        self.stripe_calls = 0

    def get(self, name):
        if name == "shopify_get_order":
            return self.get_order
        if name == "stripe_refund":
            return self.create_refund
        return None

    def get_order(self, params):
        return {
            "status": "success",
            "data": {"order_id": str(params.get("order_id") or ""), "status": "delivered"},
        }

    def create_refund(self, params):
        self.stripe_calls += 1
        return {"status": "success", "data": {"refund_id": "re_approved", "amount": params.get("amount")}}


def _open(order_id="12345"):
    init_db()
    memory = MemoryService()
    customer_id = "p0e" + uuid.uuid4().hex[:8]
    session = memory.create_session(customer_id=customer_id, tenant_id="zepto")
    case = memory.create_case(
        session_id=session.session_id,
        customer_id=customer_id,
        tenant_id="zepto",
        order_id=order_id,
        issue_type="refund",
    )
    tools = FakeTools()
    engine = WorkflowEngine(tool_registry=tools, sleeper=lambda _seconds: None)
    return session, case, tools, engine


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


def _start(engine, case, session, **slots):
    base = {
        "order_id": "12345",
        "amount": 2500,
        "reason": "damaged",
        "photos_received": True,
    }
    base.update(slots)
    ctx = WorkflowContext(
        tenant_id="zepto",
        case_id=case.case_id,
        customer_id=case.customer_id,
        auth_level="verified",
        conversation_id=session.session_id,
        slots=base,
    )
    return engine.start("refund", ctx)


def _pending_task(run_id: str):
    with SessionLocal() as db:
        return db.execute(
            select(HumanTaskRow)
            .where(HumanTaskRow.workflow_run_id == run_id)
            .where(HumanTaskRow.status == "pending")
        ).scalars().first()


def test_approve_resumes_same_run_and_calls_stripe_once():
    session, case, tools, engine = _open()
    engine_override(engine)
    try:
        view = _start(engine, case, session)
        assert view.status == "waiting_approval"
        assert tools.stripe_calls == 0
        task = _pending_task(view.run_id)
        assert task is not None

        listed = client.get("/v1/approvals", params={"status": "pending"}, headers=HEADERS)
        assert listed.status_code == 200
        assert task.id in [item["id"] for item in listed.json()["approvals"]]

        approved = client.post(f"/v1/approvals/{task.id}/approve", headers=HEADERS, json={"note": "ok"})
        assert approved.status_code == 200
        body = approved.json()
        assert body["workflow_run_id"] == view.run_id
        assert body["workflow_status"] == "succeeded"
        assert tools.stripe_calls == 1

        again = client.post(f"/v1/approvals/{task.id}/approve", headers=HEADERS)
        assert again.status_code == 409
        assert tools.stripe_calls == 1

        workflow = client.get(f"/v1/workflows/{view.run_id}", headers=HEADERS)
        assert workflow.status_code == 200
        assert workflow.json()["status"] == "succeeded"
        assert any(step["name"] == "execute_refund" and step["status"] == "success" for step in workflow.json()["steps"])

        case_body = client.get(f"/v1/cases/{case.case_id}", headers=HEADERS).json()
        assert case_body["workflow_run_id"] == view.run_id
        assert case_body["status"] == "resolved"
        assert case_body["pending_tasks"] == []
    finally:
        engine_override(None)
        _purge(case.case_id, session.session_id)


def test_reject_cancels_without_stripe():
    session, case, tools, engine = _open()
    engine_override(engine)
    try:
        view = _start(engine, case, session)
        task = _pending_task(view.run_id)
        rejected = client.post(f"/v1/approvals/{task.id}/reject", headers=HEADERS, json={"note": "no"})
        assert rejected.status_code == 200
        assert rejected.json()["workflow_status"] == "cancelled"
        assert rejected.json()["workflow_run_id"] == view.run_id
        assert tools.stripe_calls == 0
        case_body = client.get(f"/v1/cases/{case.case_id}", headers=HEADERS).json()
        assert case_body["status"] == "escalated"
        assert case_body["escalation_reason"] == "approval_rejected"
        with SessionLocal() as db:
            event = db.execute(
                select(PlatformEventRow).where(PlatformEventRow.case_id == case.case_id)
            ).scalars().first()
        assert event is not None
        assert event.event_type == "approval.rejected"
    finally:
        engine_override(None)
        _purge(case.case_id, session.session_id)


def test_wrong_tenant_and_missing_task_and_missing_photos():
    session, case, tools, engine = _open()
    engine_override(engine)
    try:
        view = _start(engine, case, session)
        task = _pending_task(view.run_id)
        wrong = client.post(
            f"/v1/approvals/{task.id}/approve",
            headers={**HEADERS, "X-Tenant-Id": "other-tenant"},
        )
        assert wrong.status_code == 403
        assert tools.stripe_calls == 0

        missing = client.post("/v1/approvals/does-not-exist/approve", headers=HEADERS)
        assert missing.status_code == 404

        role = client.post(
            f"/v1/approvals/{task.id}/approve",
            headers={**HEADERS, "X-Actor-Role": "agent"},
        )
        assert role.status_code == 403
        assert tools.stripe_calls == 0
    finally:
        engine_override(None)
        _purge(case.case_id, session.session_id)

    session, case, tools, engine = _open()
    try:
        view = _start(engine, case, session, photos_received=False, amount=2500)
        assert view.status == "waiting_input"
        assert _pending_task(view.run_id) is None
        missing = client.post("/v1/approvals/no-task-for-photos/approve", headers=HEADERS)
        assert missing.status_code == 404
        assert tools.stripe_calls == 0
    finally:
        _purge(case.case_id, session.session_id)
