"""Read-only copilot brief. No LLM and no gateway.main import."""
from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from db.session import init_db
from gateway.routers.copilot import router as copilot_router
from interactions.service import InteractionService
from memory.service import MemoryService
from tests.api.test_intelligence import FakeTools, _purge
from workflows.context import WorkflowContext
from workflows.engine import WorkflowEngine

app = FastAPI()
app.include_router(copilot_router)
client = TestClient(app)
HEADERS = {"X-Tenant-Id": "zepto"}


def test_copilot_summarizes_waiting_approval_and_rejects_other_tenant():
    init_db()
    memory = MemoryService()
    customer_id = "p1c" + uuid.uuid4().hex[:8]
    session = memory.create_session(customer_id=customer_id, tenant_id="zepto")
    case = memory.create_case(
        session_id=session.session_id,
        customer_id=customer_id,
        tenant_id="zepto",
        order_id="12345",
        issue_type="refund",
    )
    service = InteractionService()
    long_text = "damaged " + ("x" * 400)
    try:
        service.log_chat_turn(
            conversation_id=session.session_id,
            case_id=case.case_id,
            tenant_id="zepto",
            customer_id=customer_id,
            message=long_text,
            response="A human will review this refund.",
            intent="refund",
            risk_level="low",
            order_id="12345",
            missing_inputs=["photos"],
            photos_requested=True,
            photos_received=False,
            tool_results={},
            escalated=True,
            blocked=False,
            escalation_reason=None,
            citations=[],
            confidence=0.9,
            latency_ms=10.0,
            status="escalated",
            request_id="req-p1c",
            metadata={"channel": "chat", "workflow_status": "waiting_approval"},
        )
        view = WorkflowEngine(tool_registry=FakeTools(), sleeper=lambda _seconds: None).start(
            "refund",
            WorkflowContext(
                tenant_id="zepto",
                case_id=case.case_id,
                customer_id=customer_id,
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

        response = client.get(f"/v1/cases/{case.case_id}/copilot", headers=HEADERS)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["case_id"] == case.case_id
        assert body["pending_approval"] is True
        assert body["approval_task_id"]
        assert body["policy"]["outcome"] == "waiting_approval"
        assert body["missing_inputs"] == ["photos"]
        assert body["last_tool_status"]["step_name"]
        assert all(len(line) <= 240 for line in body["summary"])
        assert "re_live" not in "".join(body["summary"])

        other = client.get(
            f"/v1/cases/{case.case_id}/copilot",
            headers={"X-Tenant-Id": "other"},
        )
        assert other.status_code == 404
    finally:
        _purge(case.case_id, session.session_id)
