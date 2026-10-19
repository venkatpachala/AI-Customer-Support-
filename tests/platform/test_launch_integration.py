"""Customer journeys use real persistence/parser/retrieval; only model/provider IO is faked."""
import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from sqlalchemy import select

from controlplane.keys import ensure_tenant, issue_key
from controlplane.knowledge import store_pdf, delete_snapshot, latest_snapshot_id
from db.models import CaseRow, MessageRow, HumanTaskRow, OutboxRow
from db.session import SessionLocal, init_db
from gateway.main import app
from memory.service import MemoryService
from rag.managed import TenantRetriever


def pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
        NameObject("/F1"): DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def brand():
    init_db()
    tenant = "launch" + uuid.uuid4().hex[:10]
    ensure_tenant(tenant, "Launch brand")
    _, key = issue_key(tenant, role="supervisor", mode="test")
    return tenant, {"Authorization": "Bearer " + key}


def open_case(tenant):
    memory = MemoryService()
    session = memory.create_session(customer_id=uuid.uuid4().hex, tenant_id=tenant)
    case = memory.create_case(session_id=session.session_id, customer_id=session.customer_id,
                              tenant_id=tenant, order_id="12345", issue_type="refund")
    return session, case


def test_new_signup_has_runtime_config_without_files():
    tenant, _ = brand()
    from config.loaders import load_tenant_config
    config = load_tenant_config(tenant)
    assert config.tenant_id == tenant
    assert config.brand.brand_name == "Launch brand"
    from controlplane.automations import automation_enabled
    assert automation_enabled(tenant, "refund") is False


def test_documents_survive_restart_and_collection_delete():
    tenant, _ = brand()
    one = store_pdf(tenant, "returns.pdf", pdf("1. Returns require clear photographs of damaged items within seven days."))
    before = latest_snapshot_id(tenant)
    two = store_pdf(tenant, "delivery.pdf", pdf("2. Delivery operates Monday to Friday excluding holidays."))
    assert latest_snapshot_id(tenant) != before
    retriever = TenantRetriever()
    assert retriever.retrieve("photographs damaged items", metadata_filter={"tenant_id": tenant})
    assert TenantRetriever().retrieve("delivery holidays", metadata_filter={"tenant_id": tenant})
    assert not retriever.retrieve("photographs", metadata_filter={"tenant_id": "anotherbrand"})
    delete_snapshot(tenant, one["id"])
    assert not TenantRetriever().retrieve("photographs damaged", metadata_filter={"tenant_id": tenant})
    assert TenantRetriever().retrieve("delivery holidays", metadata_filter={"tenant_id": tenant})
    with pytest.raises(ValueError):
        store_pdf(tenant, "bad.pdf", b"not pdf")


def test_policy_cache_invalidated_by_collection_changes():
    tenant, _ = brand()
    from rag.policy_cache import PolicyCache
    cache = PolicyCache()
    cache.set(tenant, "policy", {"response": "old"})
    assert cache.get(tenant, "policy")
    store_pdf(tenant, "policy.pdf", pdf("Returns require photographs."))
    assert cache.get(tenant, "policy") is None


def test_operator_reply_is_persisted_and_cannot_cross_tenants():
    tenant, headers = brand()
    session, case = open_case(tenant)
    client = TestClient(app)
    result = client.post(f"/v1/desk/cases/{case.case_id}/reply", headers=headers, json={"body": "A person will review your photos."})
    assert result.status_code == 200
    assert result.json()["status"] == "human_owned"
    history = client.get(f"/v1/desk/cases/{case.case_id}", headers=headers).json()
    assert history["messages"][-1]["author"] == "operator"
    assert history["messages"][-1]["body"] == "A person will review your photos."
    _, other = brand()
    assert client.get(f"/v1/desk/cases/{case.case_id}", headers=other).status_code == 404
    assert client.get("/v1/desk/quality", headers=headers).status_code == 200


def test_spoofed_headers_and_widget_credentials_cannot_read_cases(monkeypatch):
    tenant, headers = brand()
    _, case = open_case(tenant)
    monkeypatch.setenv("ALLOW_LEGACY_ACTOR_HEADERS", "0")
    client = TestClient(app)
    forged = {"X-Tenant-Id": tenant, "X-Actor-Role": "admin"}
    assert client.get(f"/v1/cases/{case.case_id}", headers=forged).status_code == 401
    _, widget = issue_key(tenant, role="widget", mode="test")
    assert client.get(f"/v1/cases/{case.case_id}", headers={"Authorization": "Bearer " + widget}).status_code == 403


def test_execution_lease_excludes_other_workers():
    init_db()
    from workflows.lease import ExecutionLease
    key = uuid.uuid4().hex
    with ExecutionLease(key, SessionLocal) as first:
        assert first.acquired
        with ExecutionLease(key, SessionLocal) as second:
            assert not second.acquired
        first.assert_owned()
    with ExecutionLease(key, SessionLocal) as third:
        assert third.acquired


def test_approval_decision_is_atomic_and_recoverable():
    tenant, _ = brand()
    _, case = open_case(tenant)
    from db.models import WorkflowRunRow
    run_id, task_id = uuid.uuid4().hex, uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(WorkflowRunRow(id=run_id, tenant_id=tenant, case_id=case.case_id,
            workflow_name="refund", status="waiting_approval", input_json={}))
        db.add(HumanTaskRow(id=task_id, tenant_id=tenant, case_id=case.case_id,
            workflow_run_id=run_id, task_type="refund_approval", status="pending"))
        db.commit()
    from workflows.approvals import _decide, ApprovalError
    def decide():
        try:
            _decide(SessionLocal, task_id, status="approved", actor_id="operator", note=None)
            return True
        except ApprovalError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: decide(), range(2))) == [False, True]
    with SessionLocal() as db:
        jobs = list(db.execute(select(OutboxRow).where(OutboxRow.dedup_key == f"resume:{task_id}")).scalars())
        assert len(jobs) == 1


def test_money_and_crypto_contracts(monkeypatch):
    from common.money import to_minor
    assert to_minor("12.34") == 1234
    for invalid in ("NaN", "12.345", "-1"):
        with pytest.raises(ValueError):
            to_minor(invalid)
    from controlplane.vault import seal, open_seal
    stored = seal("secret-value")
    assert stored.startswith("enc:v2:") and open_seal(stored) == "secret-value"
    with pytest.raises(ValueError):
        open_seal(stored[:-4] + "AAAA")


def test_required_http_eval_cannot_skip_dead_api(monkeypatch):
    from evaluation.release_gate import _maybe_http
    import re
    monkeypatch.setenv("REQUIRE_CHAT", "1")
    monkeypatch.setattr("evaluation.release_gate._health_up", lambda: False)
    assert _maybe_http("REQUIRE_CHAT", "unused", re.compile(""), "chat")["status"] == "fail"


def test_public_widget_cannot_choose_another_customer_identity():
    tenant, _ = brand()
    first, second = TestClient(app), TestClient(app)
    a = first.post(f"/w/{tenant}/session", json={"customer_ref": "same-customer"}).json()
    b = second.post(f"/w/{tenant}/session", json={"customer_ref": "same-customer"}).json()
    from identity.session import load_customer_session
    assert load_customer_session(a["session_id"]).customer_ref != load_customer_session(b["session_id"]).customer_ref


def test_customer_header_session_cannot_read_other_customers_messages():
    tenant, _ = brand()
    client = TestClient(app)
    token = client.post(f"/w/{tenant}/session", json={"customer_ref": "visitor"}).json()["session_id"]
    _, case = open_case(tenant)
    assert client.get(f"/v1/customer/cases/{case.case_id}/messages",
        headers={"Authorization": "Session " + token}).status_code == 404


def test_chat_receipt_replays_only_identical_input():
    import asyncio
    from identity.session import create_customer_session
    from runtime.chat_command import ChatCommand
    from runtime.chat_service import ChatService
    tenant, _ = brand()
    session = create_customer_session(tenant, uuid.uuid4().hex)
    called = []
    async def handler(command):
        called.append(command.body)
        return {"response": "Stored answer", "case_id": "receipt-test"}
    service = ChatService(handler)
    command = ChatCommand(body={"message": "hello"}, session_id=session.id, idempotency_key="request1")
    assert asyncio.run(service.handle(command)) == asyncio.run(service.handle(command))
    assert len(called) == 1
    changed = ChatCommand(body={"message": "different"}, session_id=session.id, idempotency_key="request1")
    assert asyncio.run(service.handle(changed)).status_code == 409


def test_webhook_rejects_unapproved_or_internal_targets(monkeypatch):
    from security.urls import validate_webhook_url
    for target in ("http://example.com", "https://localhost", "https://169.254.169.254", "https://user:pass@example.com"):
        with pytest.raises(ValueError):
            validate_webhook_url(target)
    monkeypatch.setenv("WEBHOOK_ALLOWED_HOSTS", "hooks.example.test")
    monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError):
        validate_webhook_url("https://hooks.example.test/callback")


def test_live_record_match_is_not_strong_verification(monkeypatch):
    tenant, _ = brand()
    _, case = open_case(tenant)
    monkeypatch.setattr("identity.ownership.prove", lambda *_args: {"ok": True, "customer_id": "owner", "matched_on": "email"})
    from controlplane.mode import force_tools_mode, reset_tools_mode
    from identity.ownership import apply_ownership, case_auth
    token = force_tools_mode("live")
    try:
        apply_ownership(case.case_id, tenant, "12345", "owner@example.test")
        assert case_auth(case.case_id)[0] == "identified"
    finally:
        reset_tools_mode(token)


def test_verification_is_bound_to_session_order_and_expires():
    from db.models import VerificationChallengeRow
    from gateway.routers.customer import _digest
    from identity.session import create_customer_session
    from identity.verification import verified_order
    tenant, _ = brand()
    internal, case = open_case(tenant)
    session = create_customer_session(tenant, internal.customer_id)
    challenge_id = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(VerificationChallengeRow(id=challenge_id, tenant_id=tenant, session_id=session.id,
            case_id=case.case_id, order_id="12345", code_hash=_digest(challenge_id, "123456"),
            expires_at=datetime.utcnow() + timedelta(minutes=5)))
        db.commit()
    client = TestClient(app)
    headers = {"Authorization": "Session " + session.id}
    assert client.post(f"/v1/customer/verification/{challenge_id}", json={"code": "000000"}, headers=headers).status_code == 400
    assert not verified_order(case.case_id, "12345")
    assert client.post(f"/v1/customer/verification/{challenge_id}", json={"code": "123456"}, headers=headers).status_code == 200
    assert verified_order(case.case_id, "12345")
    assert not verified_order(case.case_id, "99999")
    assert client.post(f"/v1/customer/verification/{challenge_id}", json={"code": "123456"}, headers=headers).status_code == 400


def test_outbox_retries_do_not_repeat_business_action(monkeypatch):
    from controlplane.outbox import enqueue, drain
    tenant, _ = brand()
    with SessionLocal() as db:
        enqueue(db, tenant_id=tenant, key="webhook:" + tenant, kind="webhook", payload={"run_id": "existing-run"})
        db.commit()
    attempts = []
    def failed(*args, **kwargs):
        attempts.append("delivery")
        raise RuntimeError("provider down")
    monkeypatch.setattr("controlplane.webhooks.send_delivery", failed)
    assert drain(tenant) == 0
    with SessionLocal() as db:
        row = db.execute(select(OutboxRow).where(OutboxRow.tenant_id == tenant)).scalar_one()
        assert row.status == "pending" and row.attempts == 1
        assert row.available_at > datetime.utcnow()
    assert attempts == ["delivery"]


def test_production_startup_fails_without_secrets(monkeypatch):
    from controlplane.settings import validate_environment
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="CREDENTIAL_ENCRYPTION_KEYS"):
        validate_environment()


def test_executor_threads_keep_tenant_and_tools_mode():
    from common.concurrency import submit_with_context
    from controlplane.tenant_context import use_tenant, current_scope
    from controlplane.mode import force_tools_mode, reset_tools_mode, current_tools_mode
    token = force_tools_mode("live")
    try:
        with use_tenant("thread-tenant"), ThreadPoolExecutor(max_workers=1) as pool:
            future = submit_with_context(pool, lambda: (current_scope().tenant_id, current_tools_mode()))
            assert future.result() == ("thread-tenant", "live")
    finally:
        reset_tools_mode(token)


def test_daily_refund_budget_reserves_atomically_and_replays():
    from workflows.refund_budget import reserve
    tenant, _ = brand()
    def claim(index):
        return reserve(tenant, f"{tenant}-{index}", 600, 1000, SessionLocal)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, [1, 2]))
    assert results.count(True) == 1
    winner = 1 if results[0] else 2
    assert reserve(tenant, f"{tenant}-{winner}", 600, 1000, SessionLocal)
    assert not reserve(tenant, f"{tenant}-{winner}", 700, 1000, SessionLocal)


def test_shopify_graphql_exact_match_and_errors():
    from tools.shopify.orders import read_graphql_order, _normalize_order
    from tools.base.context import ToolContext
    from tools.base.exceptions import ProviderUnavailableError, ResourceNotFoundError
    class Client:
        payload = {"data": {"orders": {"nodes": [{"id": "gid://shopify/Order/123", "name": "#1001",
            "email": "merchant-customer@example.test", "displayFulfillmentStatus": "FULFILLED",
            "totalPriceSet": {"shopMoney": {"amount": "12.50", "currencyCode": "INR"}}}]}}}
        def post(self, path, **kwargs):
            assert path == "/graphql.json"
            assert kwargs["json"]["variables"]["query"] == 'name:"1001"'
            return self.payload
    client = Client()
    context = ToolContext(request_id="test", tenant_id="merchant")
    order = _normalize_order(read_graphql_order(client, "1001", context))
    assert order["status"] == "fulfilled"
    assert order["customer"]["email"] == "merchant-customer@example.test"
    client.payload = {"data": {"orders": {"nodes": [{"id": "other", "name": "#10010"}]}}}
    with pytest.raises(ResourceNotFoundError):
        read_graphql_order(client, "1001", context)
    client.payload = {"errors": [{"message": "denied"}]}
    with pytest.raises(ProviderUnavailableError):
        read_graphql_order(client, "1001", context)


def test_support_intake_is_authenticated_and_persistent():
    from db.models import IntakeRequestRow
    tenant, headers = brand()
    client = TestClient(app)
    body = {"email": "owner@example.test", "note": "Case is waiting and needs investigation"}
    assert client.post("/v1/desk/support", json=body).status_code == 401
    response = client.post("/v1/desk/support", json=body, headers=headers)
    assert response.status_code == 201
    with SessionLocal() as db:
        row = db.get(IntakeRequestRow, response.json()["id"])
        assert row.tenant_id == tenant and row.note == body["note"]


def test_unknown_policy_abstains_without_model_call():
    from agents.qa import qa_node
    from langchain_core.messages import HumanMessage
    tenant, _ = brand()
    result = qa_node({"tenant_id": tenant, "request_id": "abstain",
        "messages": [HumanMessage(content="Do you offer tours to Jupiter?")],
        "current_plan": {"intent": "policy_query"}})
    assert result["abstained"] is True
    assert result["citations"] == []
    assert "does not specify" in result["messages"][0].content


def test_chat_service_returns_503_for_runtime_failure():
    import asyncio
    from runtime.chat_service import ChatService
    from runtime.chat_command import ChatCommand
    from identity.session import create_customer_session
    tenant, _ = brand()
    session = create_customer_session(tenant, "synthetic")
    async def failed(command):
        return {"error": "temporarily unavailable", "response": "Please retry"}
    response = asyncio.run(ChatService(failed).handle(ChatCommand(body={"message": "hello"}, session_id=session.id)))
    assert response.status_code == 503


def test_signup_without_signing_secret_returns_configuration_error(monkeypatch):
    monkeypatch.delenv("OPS_SESSION_SECRET", raising=False)
    monkeypatch.delenv("OPS_PASSWORD", raising=False)
    response = TestClient(app).post("/signup", json={"email": "not-created@example.test", "password": "synthetic-only"})
    assert response.status_code == 503
    assert "OPS_SESSION_SECRET" in response.json()["detail"]


def test_local_setup_preserves_an_existing_secret(tmp_path, monkeypatch):
    from controlplane.dev_setup import ensure_local_secret
    from dotenv import dotenv_values
    monkeypatch.delenv("OPS_SESSION_SECRET", raising=False)
    monkeypatch.delenv("OPS_PASSWORD", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    path = tmp_path / ".env"
    assert ensure_local_secret(path)
    first = dotenv_values(path)["OPS_SESSION_SECRET"]
    assert len(first) >= 32
    assert not ensure_local_secret(path)
    assert dotenv_values(path)["OPS_SESSION_SECRET"] == first
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError):
        ensure_local_secret(tmp_path / "production.env")
