"""The client cannot grant itself verified. Ownership is server-side."""
from __future__ import annotations

import os
import uuid

os.environ["TOOLS_MODE"] = "mock"
for _name in (
    "SHOPIFY_SHOP_DOMAIN",
    "SHOPIFY_ACCESS_TOKEN",
    "SHOPIFY_SHOP_URL",
    "STRIPE_SECRET_KEY",
    "GMAIL_SENDER",
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
):
    os.environ.pop(_name, None)

from fastapi.testclient import TestClient

from db.models import CaseRow
from db.session import SessionLocal, init_db
from gateway.main import app
from identity.ownership import apply_ownership
from memory.service import MemoryService
from workflows.context import WorkflowContext
from workflows.engine import WorkflowEngine

client = TestClient(app)


class _Tools:
    def __init__(self):
        self.stripe_calls = 0

    def get(self, name):
        if name == "shopify_get_order":
            return self.get_order
        if name == "stripe_refund":
            return self.create_refund
        return None

    def get_order(self, params):
        return {"status": "success", "data": {"order_id": str(params.get("order_id") or ""), "status": "delivered"}}

    def create_refund(self, params):
        self.stripe_calls += 1
        return {"status": "success", "data": {"refund_id": "re_should_not_run"}}


def _refund(case, customer_id, auth_level):
    tools = _Tools()
    view = WorkflowEngine(tool_registry=tools, sleeper=lambda _seconds: None).start(
        "refund",
        WorkflowContext(
            tenant_id="zepto",
            case_id=case.case_id,
            customer_id=customer_id,
            auth_level=auth_level,
            slots={
                "order_id": "12345",
                "amount": 2500,
                "reason": "damaged",
                "photos_received": True,
            },
        ),
    )
    return view, tools


def test_verified_body_without_session_is_401():
    client.cookies.clear()
    response = client.post(
        "/chat",
        json={"message": "refund order 12345", "tenant_id": "zepto", "auth_level": "verified", "verified": True},
    )
    assert response.status_code == 401
    assert "workflow_run_id" not in response.json()


def test_session_tenant_mismatch_is_403():
    init_db()
    opened = client.post("/v1/sessions", json={"tenant_id": "zepto", "customer_ref": "pilot-a"})
    assert opened.status_code == 200
    assert opened.json()["session_id"]
    assert "d2c_session" in opened.cookies
    mismatched = client.post("/chat", json={"message": "hello", "tenant_id": "other-brand"})
    assert mismatched.status_code == 403


def test_wrong_contact_waits_for_auth_and_does_not_call_stripe():
    init_db()
    memory = MemoryService()
    customer_id = "own" + uuid.uuid4().hex[:8]
    session = memory.create_session(customer_id=customer_id, tenant_id="zepto")
    case = memory.create_case(
        session_id=session.session_id,
        customer_id=customer_id,
        tenant_id="zepto",
        order_id="12345",
        issue_type="refund",
    )
    proof = apply_ownership(case.case_id, "zepto", "12345", "1111100000")
    assert proof["ok"] is False
    assert proof["detail"] == "could not verify this order"
    assert "9999900000" not in str(proof)
    assert "pilot@zepto.test" not in str(proof)
    view, tools = _refund(case, customer_id, "verified")
    assert view.status == "waiting_auth"
    assert tools.stripe_calls == 0


def test_fixture_contact_records_the_order_as_verified():
    init_db()
    memory = MemoryService()
    customer_id = "own" + uuid.uuid4().hex[:8]
    session = memory.create_session(customer_id=customer_id, tenant_id="zepto")
    case = memory.create_case(
        session_id=session.session_id,
        customer_id=customer_id,
        tenant_id="zepto",
        order_id="12345",
        issue_type="refund",
    )
    phone = apply_ownership(case.case_id, "zepto", "12345", "+91 99999 00000")
    assert phone["ok"] is True
    assert phone["matched_on"] == "phone"
    email = apply_ownership(case.case_id, "zepto", "12345", "Pilot@Zepto.test")
    assert email["ok"] is True
    assert email["matched_on"] == "email"
    with SessionLocal() as db:
        row = db.get(CaseRow, case.case_id)
        summary = dict(row.tool_results_summary or {})
    assert summary["verified_order_ids"] == ["12345"]
    assert row.auth_level == "verified"
    assert "9999900000" not in str(summary["customer_contact_hash"])
    view, tools = _refund(case, customer_id, "anonymous")
    assert view.status == "waiting_approval"
    assert tools.stripe_calls == 0
