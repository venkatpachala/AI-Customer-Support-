"""Hosted control plane. Keys, sandbox stamp, and tenant walls."""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("TOOLS_MODE", "mock")
os.environ.setdefault("OPS_PASSWORD", "owner-secret")
os.environ.setdefault("OPS_SESSION_SECRET", "owner-secret")

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from controlplane.keys import ensure_tenant, issue_key, tenant_record
from controlplane.sandbox import HOLD_MESSAGE, PHOTO_MESSAGE, POLICY_MESSAGE, run_sandbox
from db.models import CaseRow, ToolCallRow
from db.session import SessionLocal, init_db
from gateway.main import app
from gateway.routers.approvals import engine_override
from gateway.routers.control import set_turn_override
from memory.service import MemoryService
from workflows.context import WorkflowContext
from workflows.engine import WorkflowEngine

client = TestClient(app)


def _silence_llm(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("llm disabled for the control-plane test")

    monkeypatch.setattr("langchain_ollama.ChatOllama.invoke", boom, raising=False)
    monkeypatch.setattr("langchain_openai.ChatOpenAI.invoke", boom, raising=False)


def _auth(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}"}


def test_missing_key_is_401():
    response = client.post("/v1/chat", json={"message": "hello"})
    assert response.status_code == 401


def test_body_auth_level_does_not_verify(monkeypatch):
    _silence_llm(monkeypatch)
    init_db()
    _row, secret = issue_key("zepto", role="widget", mode="test")
    response = client.post(
        "/v1/chat",
        headers=_auth(secret),
        json={
            "message": "hello there",
            "tenant_id": "otherbrand",
            "auth_level": "verified",
            "verified": True,
            "verified_customer": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("auth_level") != "verified"
    assert body.get("tenant_id") == "zepto"


def test_test_key_refund_stays_waiting_and_stripe_is_not_success(monkeypatch):
    _silence_llm(monkeypatch)
    init_db()
    _row, secret = issue_key("zepto", role="widget", mode="test")
    with SessionLocal() as db:
        before = db.execute(
            select(func.count()).select_from(ToolCallRow).where(ToolCallRow.tool_name.like("%stripe%")).where(ToolCallRow.status == "success")
        ).scalar() or 0
    response = client.post(
        "/v1/chat",
        headers=_auth(secret),
        json={
            "message": "Order 12345, phone 9999900000, refund 2500, photos uploaded.",
            "customer_ref": "pilot",
            "auth_level": "verified",
            "verified": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["workflow_status"] == "waiting_approval"
    assert "refund completed" not in (body.get("response") or "").lower()
    with SessionLocal() as db:
        after = db.execute(
            select(func.count()).select_from(ToolCallRow).where(ToolCallRow.tool_name.like("%stripe%")).where(ToolCallRow.status == "success")
        ).scalar() or 0
    assert after == before


def test_widget_key_cannot_approve_and_second_approve_is_already_decided():
    init_db()
    tenant = "zepto"
    ensure_tenant(tenant)
    _widget, widget_secret = issue_key(tenant, role="widget", mode="test")
    _supervisor, supervisor_secret = issue_key(tenant, role="supervisor", mode="test")
    memory = MemoryService()
    customer_id = "hold" + uuid.uuid4().hex[:8]
    session = memory.create_session(customer_id=customer_id, tenant_id=tenant)
    case = memory.create_case(
        session_id=session.session_id,
        customer_id=customer_id,
        tenant_id=tenant,
        order_id="12345",
        issue_type="refund",
    )
    with SessionLocal() as db:
        row = db.get(CaseRow, case.case_id)
        row.auth_level = "verified"
        row.photos_received = True
        db.commit()

    class FakeTools:
        def __init__(self):
            self.stripe_calls = 0

        def get(self, name):
            if name == "shopify_get_order":
                return lambda params: {"status": "success", "data": {"order_id": "12345", "status": "delivered"}}
            if name == "stripe_refund":
                return self.create_refund
            return None

        def create_refund(self, params):
            self.stripe_calls += 1
            return {"status": "success", "data": {"refund_id": "re_once"}}

    tools = FakeTools()
    engine = WorkflowEngine(tool_registry=tools, sleeper=lambda _seconds: None)
    engine_override(engine)
    try:
        view = engine.start(
            "refund",
            WorkflowContext(
                tenant_id=tenant,
                case_id=case.case_id,
                customer_id=customer_id,
                auth_level="verified",
                slots={"order_id": "12345", "amount": 2500, "reason": "damaged", "photos_received": True},
            ),
        )
        assert view.status == "waiting_approval"
        from db.models import HumanTaskRow

        with SessionLocal() as db:
            task = db.execute(
                select(HumanTaskRow).where(HumanTaskRow.workflow_run_id == view.run_id).where(HumanTaskRow.status == "pending")
            ).scalars().first()
            task_id = task.id
        denied = client.post(f"/v1/approvals/{task_id}/approve", headers=_auth(widget_secret), json={})
        assert denied.status_code == 403
        assert tools.stripe_calls == 0
        approved = client.post(
            f"/v1/approvals/{task_id}/approve",
            headers=_auth(supervisor_secret),
            json={"note": "ok"},
        )
        assert approved.status_code == 200
        assert tools.stripe_calls == 1
        again = client.post(f"/v1/approvals/{task_id}/approve", headers=_auth(supervisor_secret), json={})
        assert again.status_code == 409
        assert again.json()["detail"] == "already decided"
        assert tools.stripe_calls == 1
    finally:
        engine_override(None)


def test_live_key_before_sandbox_is_403():
    init_db()
    tenant = "live" + uuid.uuid4().hex[:8]
    _row, secret = issue_key(tenant, role="widget", mode="live")
    response = client.post("/v1/chat", headers=_auth(secret), json={"message": "hello"})
    assert response.status_code == 403
    assert tenant_record(tenant).sandbox_passed_at is None


def test_sandbox_sets_timestamp_only_on_pass():
    init_db()
    passed_tenant = "pass" + uuid.uuid4().hex[:6]
    failed_tenant = "fail" + uuid.uuid4().hex[:6]
    ensure_tenant(passed_tenant)
    ensure_tenant(failed_tenant)

    def good(_tenant, message):
        if message == POLICY_MESSAGE:
            return {"citations": ["zepto refund policy"], "response": "See the policy.", "missing_inputs": []}
        if message == PHOTO_MESSAGE:
            return {"citations": [], "response": "Please upload photos of the damage.", "missing_inputs": ["photos"]}
        return {"workflow_status": "waiting_approval", "response": "Waiting for approval", "tool_results": {}, "citations": []}

    def bad(_tenant, _message):
        return {"response": "no", "citations": [], "missing_inputs": [], "workflow_status": "failed", "tool_results": {"stripe_refund": {"status": "success"}}}

    report = run_sandbox(passed_tenant, good)
    assert report["passed"] is True
    assert tenant_record(passed_tenant).sandbox_passed_at is not None
    failed = run_sandbox(failed_tenant, bad)
    assert failed["passed"] is False
    assert tenant_record(failed_tenant).sandbox_passed_at is None


def test_http_sandbox_pass_sets_timestamp():
    init_db()
    tenant = "http" + uuid.uuid4().hex[:6]
    _row, secret = issue_key(tenant, role="widget", mode="test")

    def scripted(_tenant, message):
        if "policy" in message:
            return {"citations": ["policy clause"], "response": "policy", "missing_inputs": []}
        if "damaged" in message and "refund" not in message:
            return {"response": "upload photos", "missing_inputs": ["photos"], "citations": []}
        return {"workflow_status": "waiting_approval", "response": "held", "citations": [], "tool_results": {}}

    set_turn_override(scripted)
    try:
        response = client.post("/v1/sandbox/run", headers=_auth(secret))
    finally:
        set_turn_override(None)
    assert response.status_code == 200
    assert response.json()["passed"] is True
    assert tenant_record(tenant).sandbox_passed_at is not None


def test_tenant_cannot_read_another_timeline():
    init_db()
    tenant_a = "aaaa" + uuid.uuid4().hex[:6]
    tenant_b = "bbbb" + uuid.uuid4().hex[:6]
    _row, secret_a = issue_key(tenant_a, role="supervisor", mode="test")
    memory = MemoryService()
    session = memory.create_session(customer_id="b-customer", tenant_id=tenant_b)
    case = memory.create_case(
        session_id=session.session_id,
        customer_id="b-customer",
        tenant_id=tenant_b,
        order_id="55555",
        issue_type="refund",
    )
    response = client.get(f"/v1/cases/{case.case_id}/timeline", headers=_auth(secret_a))
    assert response.status_code == 404


def test_widget_html_has_no_verified_input():
    response = client.get("/w/zepto")
    assert response.status_code == 200
    html = response.text.lower()
    assert "auth_level" not in html
    assert "verified" not in html
    assert "<iframe" not in html or "widget" in html


def test_homepage_claims_stay_inside_the_contract():
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "Refunds stop until a human allows them." in html
    lowered = html.lower()
    assert "whatsapp" not in lowered
    assert "live refund" not in lowered


def test_health_without_shopify_env(monkeypatch):
    monkeypatch.delenv("SHOPIFY_SHOP_DOMAIN", raising=False)
    monkeypatch.delenv("SHOPIFY_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["tools_mode"] == "mock"


def test_widget_script_injects_iframe():
    response = client.get("/widget.js?tenant=zepto")
    assert response.status_code == 200
    assert "iframe" in response.text
    assert "/w/" in response.text
    assert "verified" not in response.text.lower()
