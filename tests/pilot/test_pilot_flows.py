"""Pilot exits that sit on top of the release gate."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from sqlalchemy import func, select

from db.models import CaseRow, InteractionRow, WorkflowRunRow
from db.session import SessionLocal, init_db
from gateway.limits import allow_chat, reset_limits
from gateway.routers.approvals import engine_override, router as approvals_router
from gateway.routers.ops import router as ops_router
from gateway.routers.widget import router as widget_router
from identity.ownership import contact_hash
from interactions.retention import sweep_interaction_text
from memory.service import MemoryService
from rag.ingestion import normalize_chunks
from rag.tenant_filter import select_tenant_docs
from tools.base.context import ToolContext
from tools.base.exceptions import BusinessRuleError
from tools.stripe.refunds import StripeCreateRefund
from workflows.context import WorkflowContext
from workflows.engine import WorkflowEngine

app = FastAPI()
app.include_router(approvals_router)
app.include_router(ops_router)
app.include_router(widget_router)
client = TestClient(app)


class FakeTools:
    def __init__(self):
        self.stripe_calls = 0
        self.params = None

    def get(self, name):
        if name == "shopify_get_order":
            return self.get_order
        if name == "stripe_refund":
            return self.create_refund
        return None

    def get_order(self, params):
        return {"status": "success", "data": {"order_id": "12345", "status": "delivered"}}

    def create_refund(self, params):
        self.stripe_calls += 1
        self.params = dict(params)
        return {"status": "success", "data": {"refund_id": "re_test", "amount": params.get("amount")}}


def test_live_stripe_posts_paise_and_run_key(monkeypatch):
    monkeypatch.setenv("TOOLS_MODE", "live")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_pilot")
    tool = StripeCreateRefund()
    seen = {}

    def post_form(path, context, form_data, idempotency_key, timeout):
        seen["path"] = path
        seen["form"] = form_data
        seen["key"] = idempotency_key
        return {"id": "re_test_1", "status": "succeeded", "amount": 250000, "currency": "inr"}

    tool.client.post_form = post_form
    tool._run(
        {
            "order_id": "12345",
            "amount": 2500,
            "currency": "inr",
            "payment_intent_id": "pi_test",
            "idempotency_key": "run1:execute_refund",
            "require_approval_above_limit": False,
        },
        ToolContext(request_id="pilot", tenant_id="zepto"),
    )
    assert seen["form"]["amount"] == "250000"
    assert seen["form"]["currency"] == "inr"
    assert seen["key"] == "run1:execute_refund"


def test_live_secret_requires_explicit_live_mode(monkeypatch):
    monkeypatch.setenv("TOOLS_MODE", "live")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_refused")
    tool = StripeCreateRefund()
    with pytest.raises(BusinessRuleError):
        tool._run(
            {"order_id": "12345", "amount": 500, "currency": "inr", "payment_intent_id": "pi_test"},
            ToolContext(request_id="pilot", tenant_id="zepto"),
        )


def test_daily_cap_stays_waiting_without_stripe(monkeypatch):
    monkeypatch.setenv("TOOLS_MODE", "live")
    init_db()
    memory = MemoryService()
    customer = "cap" + uuid.uuid4().hex[:6]
    session = memory.create_session(customer_id=customer, tenant_id="zepto")
    prior = memory.create_case(session.session_id, customer, "zepto", order_id="12345", issue_type="refund")
    case = memory.create_case(session.session_id, customer, "zepto", order_id="12345", issue_type="refund")
    with SessionLocal() as db:
        db.add(WorkflowRunRow(
            id=str(uuid.uuid4()),
            tenant_id="zepto",
            case_id=prior.case_id,
            workflow_name="refund",
            status="succeeded",
            input_json={"slots": {"amount": 20000, "order_id": "12345"}},
            output_json={"stripe_called": True},
            idempotency_key="cap-" + uuid.uuid4().hex,
            finished_at=datetime.utcnow(),
        ))
        db.commit()
    tools = FakeTools()
    view = WorkflowEngine(tool_registry=tools, sleeper=lambda _s: None).start(
        "refund",
        WorkflowContext(
            tenant_id="zepto",
            case_id=case.case_id,
            customer_id=customer,
            auth_level="verified",
            slots={"order_id": "12345", "amount": 500, "reason": "damaged", "photos_received": True},
        ),
    )
    assert view.status == "waiting_approval"
    assert tools.stripe_calls == 0


def test_ops_approve_once_and_customer_cookie_cannot(monkeypatch):
    monkeypatch.setenv("OPS_USER", "sup")
    monkeypatch.setenv("OPS_PASSWORD", "secret-pass")
    monkeypatch.setenv("TOOLS_MODE", "mock")
    init_db()
    memory = MemoryService()
    customer = "ops" + uuid.uuid4().hex[:6]
    session = memory.create_session(customer_id=customer, tenant_id="zepto")
    case = memory.create_case(session.session_id, customer, "zepto", order_id="12345", issue_type="refund")
    tools = FakeTools()
    engine = WorkflowEngine(tool_registry=tools, sleeper=lambda _s: None)
    engine_override(engine)
    try:
        view = engine.start(
            "refund",
            WorkflowContext(
                tenant_id="zepto",
                case_id=case.case_id,
                customer_id=customer,
                auth_level="verified",
                slots={"order_id": "12345", "amount": 2500, "reason": "damaged", "photos_received": True},
            ),
        )
        assert view.status == "waiting_approval"
        from sqlalchemy import select as sel
        from db.models import HumanTaskRow
        with SessionLocal() as db:
            task = db.execute(sel(HumanTaskRow).where(HumanTaskRow.workflow_run_id == view.run_id)).scalars().first()
            task_id = task.id
        customer_client = TestClient(app)
        from identity.session import create_customer_session
        cust = create_customer_session("zepto", customer)
        customer_client.cookies.set("d2c_session", cust.id)
        denied = customer_client.post(
            f"/v1/approvals/{task_id}/approve",
            headers={"X-Tenant-Id": "zepto"},
        )
        assert denied.status_code == 403
        logged = client.post("/v1/ops/login", json={"username": "sup", "password": "secret-pass"})
        assert logged.status_code == 200
        assert "d2c_ops" in logged.cookies
        approved = client.post(
            f"/v1/approvals/{task_id}/approve",
            headers={"X-Tenant-Id": "zepto"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["workflow_status"] == "succeeded"
        assert tools.stripe_calls == 1
        assert tools.params["idempotency_key"].endswith(":execute_refund")
        again = client.post(
            f"/v1/approvals/{task_id}/approve",
            headers={"X-Tenant-Id": "zepto"},
        )
        assert again.status_code == 409
        assert tools.stripe_calls == 1
    finally:
        engine_override(None)


def test_rate_limit_does_not_insert_a_workflow(monkeypatch):
    monkeypatch.setenv("TOOLS_MODE", "mock")
    init_db()
    reset_limits()
    from identity.session import create_customer_session
    from gateway.main import app as gateway_app

    row = create_customer_session("zepto", "rate-customer")
    for _ in range(20):
        assert allow_chat(row.id, "testclient")
    http = TestClient(gateway_app)
    http.cookies.set("d2c_session", row.id)
    with SessionLocal() as db:
        before = db.execute(select(func.count()).select_from(WorkflowRunRow)).scalar()
    response = http.post("/chat", json={"message": "refund order 12345", "tenant_id": "zepto", "auth_level": "verified"})
    assert response.status_code == 429
    with SessionLocal() as db:
        after = db.execute(select(func.count()).select_from(WorkflowRunRow)).scalar()
    assert after == before
    reset_limits()


def test_retention_clears_message_and_contact_is_hashed():
    init_db()
    old = InteractionRow(
        interaction_id=str(uuid.uuid4()),
        conversation_id="c1",
        tenant_id="zepto",
        customer_id="cust",
        message="call me at 9999900000",
        response="ok",
        created_at=datetime.utcnow() - timedelta(days=91),
    )
    with SessionLocal() as db:
        db.add(old)
        db.commit()
        interaction_id = old.interaction_id
    assert sweep_interaction_text() >= 1
    with SessionLocal() as db:
        row = db.get(InteractionRow, interaction_id)
        assert row.message is None
        assert row.response is None
        assert db.get(WorkflowRunRow, "missing") is None
    assert contact_hash("9999900000") != "9999900000"
    assert "9999900000" not in contact_hash("9999900000")


def test_widget_posts_message_only_and_tenants_do_not_share_chunks():
    response = client.get("/widget.js", params={"tenant": "zepto"})
    assert response.status_code == 200
    script = response.text
    assert "auth_level" not in script
    assert "JSON.stringify({ message: message, tenant_id: tenant })" in script
    zepto = normalize_chunks(
        [Document(page_content="zepto clause", metadata={"clause": "4.1"})],
        tenant_id="zepto",
        source_id="zepto_terms_v1",
    )
    other = normalize_chunks(
        [Document(page_content="other clause", metadata={"clause": "1"})],
        tenant_id="otherbrand",
        source_id="otherbrand_terms_v1",
        knowledge_snapshot="other-terms-2026-10",
    )
    kept = [doc.metadata["chunk_id"] for doc in select_tenant_docs(zepto + other, "zepto")]
    assert kept == ["zepto_terms_v1:c0"]


def test_fifty_thousand_approve_does_not_pay():
    init_db()
    memory = MemoryService()
    customer = "big" + uuid.uuid4().hex[:6]
    session = memory.create_session(customer_id=customer, tenant_id="zepto")
    case = memory.create_case(session.session_id, customer, "zepto", order_id="12345", issue_type="refund")
    tools = FakeTools()
    engine = WorkflowEngine(tool_registry=tools, sleeper=lambda _s: None)
    view = engine.start(
        "refund",
        WorkflowContext(
            tenant_id="zepto",
            case_id=case.case_id,
            customer_id=customer,
            auth_level="verified",
            slots={"order_id": "12345", "amount": 50000, "reason": "damaged", "photos_received": True},
        ),
    )
    from sqlalchemy import select as sel
    from db.models import HumanTaskRow
    from workflows.approvals import approve_task
    with SessionLocal() as db:
        task = db.execute(sel(HumanTaskRow).where(HumanTaskRow.workflow_run_id == view.run_id)).scalars().first()
        task_id = task.id
    approved = approve_task(task_id, tenant_id="zepto", actor_id="supervisor_1", engine=engine)
    assert approved["workflow_status"] == "failed"
    assert tools.stripe_calls == 0
