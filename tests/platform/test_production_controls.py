"""Production controls: sealed credentials, isolation, and the live-tool gate."""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("OPS_PASSWORD", "test-ops-password")
os.environ.setdefault("OPS_SESSION_SECRET", "test-ops-secret")

import pytest
from fastapi.testclient import TestClient

from controlplane.connections import list_cards, save_connection
from controlplane.credentials import credential_for, resolve_stripe_secret, scrub_tool_params
from controlplane.keys import set_live_enabled, tenant_tools_live
from controlplane.knowledge import MAX_PDF_BYTES, store_pdf, use_sample_pack
from controlplane.ratelimit import reset_auth_limits
from controlplane.vault import open_seal, seal
from db.session import SessionLocal, init_db
from gateway.main import app
from rag.tenant_filter import select_tenant_docs
from langchain_core.documents import Document
from tools.base.context import ToolContext
from tools.stripe.refunds import StripeCreateRefund

client = TestClient(app)
init_db()


def test_seal_hides_the_token_from_cards():
    token = "sk_test_brand_secret_value_8844"
    assert open_seal(seal(token)) == token
    tenant = "seal" + uuid.uuid4().hex[:8]
    saved = save_connection(tenant, "stripe", shop_domain="", token=token)
    assert saved["token_last4"] == "8844"
    assert token not in str(saved)
    cards = list_cards(tenant, sandbox_passed=True, live_enabled=False)
    blob = str(cards)
    assert token not in blob
    assert "8844" in blob
    assert credential_for(tenant, "stripe") == token
    cleaned = scrub_tool_params(
        {"order_id": "12345", "stripe_secret": token, "idempotency_key": "run:execute_refund"}
    )
    assert "stripe_secret" not in cleaned
    assert cleaned["idempotency_key"] == "run:execute_refund"


def test_forged_body_key_is_ignored(monkeypatch):
    monkeypatch.setenv("TOOLS_MODE", "live")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_hostkey")
    tenant = "forge" + uuid.uuid4().hex[:8]
    tool = StripeCreateRefund()
    seen = {}

    def post_form(path, context, form_data, idempotency_key, timeout):
        seen["auth"] = tool.client.auth.token
        return {"id": "re_real", "status": "succeeded", "amount": 100, "currency": "inr"}

    tool.client.post_form = post_form
    tool._run(
        {
            "order_id": "12345",
            "amount": 100,
            "currency": "inr",
            "payment_intent_id": "pi_test",
            "stripe_secret": "sk_test_forged_from_chat",
            "require_approval_above_limit": False,
        },
        ToolContext(request_id="prod", tenant_id=tenant),
    )
    assert seen["auth"] == "sk_test_hostkey"
    assert resolve_stripe_secret(tenant) == "sk_test_hostkey"


def test_tenant_stripe_secret_beats_the_host_key(monkeypatch):
    monkeypatch.setenv("TOOLS_MODE", "live")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_hostkey")
    tenant = "own" + uuid.uuid4().hex[:8]
    save_connection(tenant, "stripe", shop_domain="", token="sk_test_tenant_key_2211")
    tool = StripeCreateRefund()
    seen = {}

    def post_form(path, context, form_data, idempotency_key, timeout):
        seen["auth"] = tool.client.auth.token
        return {"id": "re_tenant", "status": "succeeded", "amount": 100, "currency": "inr"}

    tool.client.post_form = post_form
    tool._run(
        {
            "order_id": "55",
            "amount": 100,
            "currency": "inr",
            "payment_intent_id": "pi_tenant",
            "stripe_secret": "sk_test_forged_from_chat",
            "require_approval_above_limit": False,
        },
        ToolContext(request_id="prod", tenant_id=tenant),
    )
    assert seen["auth"] == "sk_test_tenant_key_2211"


def test_sample_pack_and_size_limit_stay_on_the_tenant():
    with pytest.raises(PermissionError):
        use_sample_pack("brand" + uuid.uuid4().hex[:6])
    with pytest.raises(ValueError):
        store_pdf("zepto", "too-big.pdf", b"x" * (MAX_PDF_BYTES + 1))


def test_shared_question_does_not_cross_snapshots():
    zepto = Document(
        page_content="zepto damaged window",
        metadata={"tenant_id": "zepto", "knowledge_snapshot": "snap-a", "source": "policy"},
    )
    other = Document(
        page_content="other brand window",
        metadata={"tenant_id": "otherbrand", "knowledge_snapshot": "snap-b", "source": "policy"},
    )
    assert [doc.page_content for doc in select_tenant_docs([zepto, other], "otherbrand", snapshot_id="snap-b")] == [
        "other brand window"
    ]
    assert select_tenant_docs([zepto, other], "zepto", snapshot_id="snap-b") == []


def test_live_tools_need_admin_enable():
    tenant = "live" + uuid.uuid4().hex[:8]
    assert tenant_tools_live(tenant, key_mode="live") is False
    assert tenant_tools_live(tenant, key_mode="test") is False
    with pytest.raises(ValueError):
        set_live_enabled(tenant, True)


def test_login_locks_after_repeated_failures():
    reset_auth_limits()
    email = f"lock-{uuid.uuid4().hex[:8]}@brand.test"
    created = client.post("/signup", data={"email": email, "password": "correct-horse"}, follow_redirects=False)
    assert created.status_code == 303
    for _ in range(8):
        denied = client.post("/login", data={"email": email, "password": "wrong-password"})
        assert denied.status_code == 401
    locked = client.post("/login", data={"email": email, "password": "correct-horse"})
    assert locked.status_code == 429


def test_retrieval_without_a_tenant_filter_is_empty():
    from rag.retrieval import AdvancedRAGRetriever

    retriever = AdvancedRAGRetriever.__new__(AdvancedRAGRetriever)
    retriever.last_retrieval = {}
    assert retriever.retrieve("what is the return policy") == []
    assert retriever.retrieve("policy", metadata_filter={"knowledge_snapshot": "snap"}) == []


def test_forged_tenant_cannot_read_another_case():
    email_a = f"iso-a-{uuid.uuid4().hex[:8]}@brand.test"
    email_b = f"iso-b-{uuid.uuid4().hex[:8]}@brand.test"
    created_a = client.post(
        "/signup",
        json={"email": email_a, "password": "correct-horse"},
        headers={"accept": "application/json"},
    )
    created_b = client.post(
        "/signup",
        json={"email": email_b, "password": "correct-horse"},
        headers={"accept": "application/json"},
    )
    assert created_a.status_code == 201
    assert created_b.status_code == 201
    tenant_a = created_a.json()["tenant_id"]
    key_b = created_b.json()["widget_key"]
    from db.models import CaseRow, SessionRow

    case_id = "case-" + uuid.uuid4().hex[:10]
    with SessionLocal() as db:
        db.add(SessionRow(session_id="sess-" + case_id, tenant_id=tenant_a, customer_id="cust-a"))
        db.add(CaseRow(case_id=case_id, session_id="sess-" + case_id, tenant_id=tenant_a, customer_id="cust-a"))
        db.commit()
    denied = client.get(
        f"/v1/cases/{case_id}",
        headers={"Authorization": f"Bearer {key_b}", "X-Tenant-Id": tenant_a},
    )
    assert denied.status_code == 403
    forged = client.post(
        "/w/zepto/session",
        json={"customer_ref": "widget", "tenant_id": tenant_a},
    )
    assert forged.status_code == 400


def test_rotate_revokes_the_previous_key():
    from controlplane.keys import authenticate, rotate_key
    from controlplane.keys import AuthError

    tenant = "rot" + uuid.uuid4().hex[:8]
    _row, first = rotate_key(tenant, role="widget", mode="test")
    _row, second = rotate_key(tenant, role="widget", mode="test")
    with pytest.raises(AuthError):
        authenticate(first)
    assert authenticate(second).tenant_id == tenant


def test_sqlite_backup_restores_a_tenant_row(tmp_path):
    import sqlite3

    source = tmp_path / "source.db"
    restored = tmp_path / "restored.db"
    origin = sqlite3.connect(source)
    origin.execute("CREATE TABLE tenants (id TEXT PRIMARY KEY, name TEXT)")
    origin.execute("INSERT INTO tenants (id, name) VALUES ('brand', 'Brand')")
    origin.commit()
    copy = sqlite3.connect(restored)
    origin.backup(copy)
    origin.close()
    copy.commit()
    found = copy.execute("SELECT name FROM tenants WHERE id = 'brand'").fetchone()
    copy.close()
    assert found == ("Brand",)


def test_connections_page_does_not_render_the_secret():
    email = f"html-{uuid.uuid4().hex[:8]}@brand.test"
    created = client.post("/signup", data={"email": email, "password": "correct-horse"}, follow_redirects=False)
    cookie = {"d2c_owner": created.cookies.get("d2c_owner")}
    token = "sk_test_page_secret_should_not_appear_7733"
    saved = client.post(
        "/app/connections/stripe",
        data={"shop_domain": "", "token": token},
        cookies=cookie,
        follow_redirects=False,
    )
    assert saved.status_code == 303
    page = client.get("/app/connections", cookies=cookie)
    assert page.status_code == 200
    assert token not in page.text
    assert "7733" in page.text
    assert "WhatsApp" in page.text
    assert 'action="/app/connections/whatsapp"' not in page.text
