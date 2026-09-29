"""Case reuse: one open journey per tenant + customer + order, across sessions."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from db.models import (
    OPEN_CASE_STATUSES,
    CaseRow,
    MessageRow,
    PlatformConversationRow,
    SessionRow,
)
from db.session import SessionLocal, init_db
from memory.service import MemoryService, find_open_case


@pytest.fixture
def svc():
    init_db()
    tenant_id = "p0a" + uuid.uuid4().hex[:12]
    customer_id = "cust-" + uuid.uuid4().hex[:12]
    service = MemoryService()
    yield service, tenant_id, customer_id
    _purge_tenant(tenant_id)


def _purge_tenant(tenant_id: str) -> None:
    with SessionLocal() as db:
        session_ids = list(
            db.execute(select(SessionRow.session_id).where(SessionRow.tenant_id == tenant_id)).scalars()
        )
        if session_ids:
            db.execute(delete(MessageRow).where(MessageRow.session_id.in_(session_ids)))
        db.execute(delete(PlatformConversationRow).where(PlatformConversationRow.tenant_id == tenant_id))
        db.execute(delete(CaseRow).where(CaseRow.tenant_id == tenant_id))
        db.execute(delete(SessionRow).where(SessionRow.tenant_id == tenant_id))
        db.commit()


def test_open_statuses_cover_the_journey():
    assert OPEN_CASE_STATUSES == (
        "open",
        "waiting_customer",
        "waiting_approval",
        "running_workflow",
        "escalated",
    )
    assert "resolved" not in OPEN_CASE_STATUSES


def test_same_customer_and_order_reuses_one_case_across_sessions(svc):
    service, tenant_id, customer_id = svc
    first = service.create_session(customer_id=customer_id, tenant_id=tenant_id)
    opened = service.get_or_create_case(first, order_id="12345", issue_type="return")

    second = service.create_session(customer_id=customer_id, tenant_id=tenant_id)
    again = service.get_or_create_case(second, order_id="12345")

    assert again.case_id == opened.case_id
    assert again.order_id == "12345"
    assert second.active_case_id == opened.case_id
    # The case stays owned by the session that opened it.
    assert again.session_id == first.session_id

    reloaded = service.get_session(second.session_id)
    assert reloaded is not None
    assert reloaded.active_case_id == opened.case_id
    assert find_open_case(tenant_id, customer_id, "12345").case_id == opened.case_id


def test_different_orders_get_different_cases(svc):
    service, tenant_id, customer_id = svc
    first = service.create_session(customer_id=customer_id, tenant_id=tenant_id)
    order_a = service.get_or_create_case(first, order_id="12345", issue_type="return")

    second = service.create_session(customer_id=customer_id, tenant_id=tenant_id)
    order_b = service.get_or_create_case(second, order_id="99999", issue_type="refund")

    assert order_a.case_id != order_b.case_id
    assert order_a.order_id == "12345"
    assert order_b.order_id == "99999"

    # Same session must not glue a second order onto the first case.
    switched = service.get_or_create_case(first, order_id="99999")
    assert switched.case_id == order_b.case_id
    still_first = service.get_case(order_a.case_id)
    assert still_first.order_id == "12345"


def test_resolved_case_is_not_reused(svc):
    service, tenant_id, customer_id = svc
    first = service.create_session(customer_id=customer_id, tenant_id=tenant_id)
    opened = service.get_or_create_case(first, order_id="12345", issue_type="refund")
    opened.status = "resolved"
    service.save_case(opened)

    assert find_open_case(tenant_id, customer_id, "12345") is None

    second = service.create_session(customer_id=customer_id, tenant_id=tenant_id)
    fresh = service.get_or_create_case(second, order_id="12345")
    assert fresh.case_id != opened.case_id
    assert fresh.status == "open"

    # The original session still points at the resolved case. That pointer
    # must not win over "resolved is closed".
    first.active_case_id = opened.case_id
    retried = service.get_or_create_case(first, order_id="12345")
    assert retried.case_id == fresh.case_id


def test_other_tenant_does_not_share_the_case(svc):
    service, tenant_id, customer_id = svc
    owner = service.create_session(customer_id=customer_id, tenant_id=tenant_id)
    opened = service.get_or_create_case(owner, order_id="12345")

    other_tenant = "p0a" + uuid.uuid4().hex[:12]
    try:
        stranger = service.create_session(customer_id=customer_id, tenant_id=other_tenant)
        separate = service.get_or_create_case(stranger, order_id="12345")
        assert separate.case_id != opened.case_id
    finally:
        _purge_tenant(other_tenant)


def test_order_fills_an_open_case_that_had_none(svc):
    service, tenant_id, customer_id = svc
    session = service.create_session(customer_id=customer_id, tenant_id=tenant_id)
    opened = service.get_or_create_case(session)
    assert opened.order_id is None

    filled = service.get_or_create_case(session, order_id="12345", issue_type="return")
    assert filled.case_id == opened.case_id
    assert filled.order_id == "12345"
    assert filled.issue_type == "return"
