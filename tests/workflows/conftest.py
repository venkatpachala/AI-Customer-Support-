"""SQLite cases for workflow tests. Tools are in-process fakes, not Shopify."""
from __future__ import annotations

import uuid

import pytest
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
from workflows.context import WorkflowContext
from workflows.engine import WorkflowEngine


class FakeTools:
    def __init__(self):
        self.order_calls = 0
        self.stripe_calls = 0
        self.stripe_params = []
        self.order_status = "delivered"

    def get(self, name):
        if name == "shopify_get_order":
            return self.get_order
        if name == "stripe_refund":
            return self.create_refund
        return None

    def get_order(self, params):
        self.order_calls += 1
        order_id = str(params.get("order_id") or "")
        return {
            "status": "success",
            "data": {
                "order_id": order_id,
                "status": self.order_status,
                "financial_status": "paid",
                "currency": "INR",
            },
        }

    def create_refund(self, params):
        self.stripe_calls += 1
        self.stripe_params.append(dict(params))
        return {
            "status": "success",
            "data": {
                "refund_id": "re_test",
                "order_id": params.get("order_id"),
                "amount": params.get("amount"),
                "idempotency_key": params.get("idempotency_key"),
            },
        }


@pytest.fixture
def world():
    init_db()
    tenant_id = "p0c" + uuid.uuid4().hex[:10]
    customer_id = "cust" + uuid.uuid4().hex[:10]
    memory = MemoryService()
    session = memory.create_session(customer_id=customer_id, tenant_id=tenant_id)
    case = memory.create_case(
        session_id=session.session_id,
        customer_id=customer_id,
        tenant_id=tenant_id,
        order_id="12345",
        issue_type="refund",
    )
    tools = FakeTools()
    engine = WorkflowEngine(tool_registry=tools, sleeper=lambda _seconds: None)
    yield {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "session": session,
        "case": case,
        "tools": tools,
        "engine": engine,
        "memory": memory,
    }
    _purge(tenant_id, case.case_id, session.session_id)


@pytest.fixture
def refund_ctx(world):
    def build(*, auth_level: str = "verified", **slots) -> WorkflowContext:
        return make_ctx(world, auth_level=auth_level, **slots)
    return build


def make_ctx(world, *, auth_level: str = "verified", **slots) -> WorkflowContext:
    base = {
        "order_id": "12345",
        "amount": 500,
        "reason": "damaged",
        "photos_received": True,
    }
    base.update(slots)
    return WorkflowContext(
        tenant_id=world["tenant_id"],
        case_id=world["case"].case_id,
        customer_id=world["customer_id"],
        conversation_id=world["session"].session_id,
        auth_level=auth_level,
        slots=base,
        tool_registry=world["tools"],
    )


def _purge(tenant_id: str, case_id: str, session_id: str) -> None:
    with SessionLocal() as db:
        run_ids = list(
            db.execute(select(WorkflowRunRow.id).where(WorkflowRunRow.case_id == case_id)).scalars()
        )
        if run_ids:
            db.execute(delete(WorkflowStepRow).where(WorkflowStepRow.run_id.in_(run_ids)))
            db.execute(delete(HumanTaskRow).where(HumanTaskRow.workflow_run_id.in_(run_ids)))
        db.execute(delete(WorkflowRunRow).where(WorkflowRunRow.case_id == case_id))
        db.execute(delete(HumanTaskRow).where(HumanTaskRow.case_id == case_id))
        db.execute(delete(PlatformConversationRow).where(PlatformConversationRow.tenant_id == tenant_id))
        db.execute(delete(MessageRow).where(MessageRow.session_id == session_id))
        db.execute(delete(CaseRow).where(CaseRow.case_id == case_id))
        db.execute(delete(SessionRow).where(SessionRow.session_id == session_id))
        db.commit()
