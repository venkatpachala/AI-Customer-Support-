"""Journey read APIs. No LLM and no Pinecone."""
from __future__ import annotations

import json
import uuid
from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from db.models import (
    CaseRow,
    HumanTaskRow,
    InteractionRow,
    MessageRow,
    PlatformConversationRow,
    PlatformEventRow,
    SessionRow,
    WorkflowRunRow,
    WorkflowStepRow,
)
from db.session import SessionLocal, init_db
from gateway.routers.intelligence import router as intelligence_router
from interactions.outcomes import classify_outcome, classify_sub_intent
from interactions.service import InteractionService
from memory.service import MemoryService
from workflows.context import WorkflowContext
from workflows.engine import WorkflowEngine

app = FastAPI()
app.include_router(intelligence_router)
client = TestClient(app)

HEADERS = {"X-Tenant-Id": "zepto", "X-Actor-Role": "agent"}


class FakeTools:
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
        return {"status": "success", "data": {"refund_id": "re_should_not_run"}}


def _case():
    init_db()
    memory = MemoryService()
    customer_id = "p1a" + uuid.uuid4().hex[:8]
    session = memory.create_session(customer_id=customer_id, tenant_id="zepto")
    case = memory.create_case(
        session_id=session.session_id,
        customer_id=customer_id,
        tenant_id="zepto",
        order_id="12345",
        issue_type="refund",
    )
    return session, case


def _purge(case_id: str, session_id: str):
    with SessionLocal() as db:
        run_ids = list(
            db.execute(select(WorkflowRunRow.id).where(WorkflowRunRow.case_id == case_id)).scalars()
        )
        if run_ids:
            db.execute(delete(WorkflowStepRow).where(WorkflowStepRow.run_id.in_(run_ids)))
            db.execute(delete(HumanTaskRow).where(HumanTaskRow.workflow_run_id.in_(run_ids)))
            db.execute(delete(WorkflowRunRow).where(WorkflowRunRow.id.in_(run_ids)))
        db.execute(delete(InteractionRow).where(InteractionRow.case_id == case_id))
        db.execute(delete(PlatformEventRow).where(PlatformEventRow.case_id == case_id))
        db.execute(delete(PlatformConversationRow).where(PlatformConversationRow.session_id == session_id))
        db.execute(delete(MessageRow).where(MessageRow.session_id == session_id))
        db.execute(delete(CaseRow).where(CaseRow.case_id == case_id))
        db.execute(delete(SessionRow).where(SessionRow.session_id == session_id))
        db.commit()


def _log(service, session, case, **kwargs):
    payload = dict(
        conversation_id=session.session_id,
        case_id=case.case_id,
        tenant_id="zepto",
        customer_id=case.customer_id,
        message="the item arrived damaged",
        response="I can help with that.",
        intent="refund",
        risk_level="low",
        order_id="12345",
        missing_inputs=[],
        photos_requested=False,
        photos_received=True,
        tool_results={},
        escalated=False,
        blocked=False,
        escalation_reason=None,
        citations=[],
        confidence=0.9,
        latency_ms=12.0,
        status="open",
        request_id="req-p1a",
        metadata={"channel": "chat"},
    )
    payload.update(kwargs)
    return service.log_chat_turn(**payload)


def test_timeline_joins_chat_workflow_and_approval():
    session, case = _case()
    service = InteractionService()
    try:
        first = _log(service, session, case, message="the item arrived damaged")
        second = _log(
            service,
            session,
            case,
            message="please refund order 12345, it is damaged",
            response="This refund is pending review. No refund has been issued yet.",
            escalated=True,
            status="escalated",
            metadata={
                "channel": "chat",
                "workflow_status": "waiting_approval",
                "reason": "damaged",
                "client_secret": "sk_live_should_not_leak",
                "stripe_secret": "rk_live_should_not_leak",
            },
        )
        with SessionLocal() as db:
            row = db.get(InteractionRow, second.interaction_id)
            row.created_at = first.created_at + timedelta(seconds=2)
            db.commit()
            stamped = dict(row.metadata_json or {})
        assert stamped["outcome"] == "waiting_approval"
        assert stamped["sub_intent"] == "damaged"
        assert stamped["agent_version"] == "1.0.0"
        assert stamped["knowledge_snapshot"] == "zepto-terms-2026-08"
        assert stamped["policy_version"]

        engine = WorkflowEngine(tool_registry=FakeTools(), sleeper=lambda _seconds: None)
        view = engine.start(
            "refund",
            WorkflowContext(
                tenant_id="zepto",
                case_id=case.case_id,
                customer_id=case.customer_id,
                auth_level="verified",
                conversation_id=session.session_id,
                slots={
                    "order_id": "12345",
                    "amount": 2500,
                    "reason": "damaged",
                    "photos_received": True,
                },
            ),
        )
        assert view.status == "waiting_approval"

        timeline = client.get(f"/v1/cases/{case.case_id}/timeline", headers=HEADERS)
        assert timeline.status_code == 200, timeline.text
        items = timeline.json()["items"]
        kinds = [item["kind"] for item in items]
        assert kinds.count("message") >= 2
        assert "workflow" in kinds
        assert "approval" in kinds
        assert items[0]["kind"] == "message"
        assert items[0]["data"]["role"] == "user"
        step_items = [item for item in items if item["kind"] == "step"]
        assert step_items
        assert set(step_items[0]["data"]) == {"step_name", "status", "attempt"}

        listed = client.get(
            "/v1/interactions",
            headers=HEADERS,
            params={"tenant_id": "zepto", "customer_id": case.customer_id, "limit": 5},
        )
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert body["order"] == "newest_first"
        assert body["items"][0]["id"] == second.interaction_id
        assert body["items"][0]["outcome"] == "waiting_approval"
        assert body["items"][0]["intent"] == "refund"
        raw = json.dumps(body)
        assert "sk_live_should_not_leak" not in raw
        assert "rk_live_should_not_leak" not in raw
        assert "client_secret" not in raw
        assert "tool_results" not in body["items"][0]
        assert "stripe" not in body["items"][0]
    finally:
        _purge(case.case_id, session.session_id)


def test_intent_rollup_counts_refund_and_hides_other_tenants():
    session, case = _case()
    service = InteractionService()
    try:
        before = client.get(
            "/v1/analytics/intents",
            headers=HEADERS,
            params={"tenant_id": "zepto"},
        )
        assert before.status_code == 200, before.text
        prior = before.json()
        _log(
            service,
            session,
            case,
            intent="refund",
            escalated=True,
            status="escalated",
            metadata={"channel": "chat", "workflow_status": "waiting_approval", "reason": "damaged"},
        )
        after = client.get(
            "/v1/analytics/intents",
            headers=HEADERS,
            params={"tenant_id": "zepto"},
        )
        assert after.status_code == 200, after.text
        rollup = after.json()
        assert rollup["tenant_id"] == "zepto"
        assert rollup["n"] == prior["n"] + 1
        assert rollup["by_intent"].get("refund", 0) == prior["by_intent"].get("refund", 0) + 1
        assert rollup["by_outcome"].get("waiting_approval", 0) == prior["by_outcome"].get("waiting_approval", 0) + 1
        assert rollup["waiting_approval"] == prior["waiting_approval"] + 1

        missing = client.get(
            f"/v1/cases/{case.case_id}/timeline",
            headers={"X-Tenant-Id": "blinkit", "X-Actor-Role": "supervisor"},
        )
        assert missing.status_code == 404
        assert rollup["by_intent"].get("refund", 0) >= 1
    finally:
        _purge(case.case_id, session.session_id)


def test_outcome_priority_and_other_sub_intent():
    assert classify_outcome(blocked=True, workflow_status="waiting_auth") == "blocked"
    assert classify_outcome(workflow_status="waiting_auth", pending_approval=True) == "waiting_auth"
    assert classify_outcome(workflow_status="waiting_approval", escalated=True) == "waiting_approval"
    assert classify_outcome(workflow_status="succeeded", escalated=True) == "resolved"
    assert classify_outcome(workflow_status="cancelled", escalated=True) == "failed"
    assert classify_outcome(escalated=True) == "escalated"
    assert classify_outcome() == "answered"
    assert classify_sub_intent("hello there") == "other"
    assert classify_sub_intent("it arrived damaged", reason="preference") == "preference"
