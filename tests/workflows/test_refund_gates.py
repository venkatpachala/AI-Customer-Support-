"""Refund stops where policy says so. Stripe stays at zero."""
from sqlalchemy import func, select

from db.models import HumanTaskRow, WorkflowStepRow
from db.session import SessionLocal
def _tasks(run_id: str):
    with SessionLocal() as db:
        return db.execute(
            select(HumanTaskRow).where(HumanTaskRow.workflow_run_id == run_id)
        ).scalars().all()


def _step_names(run_id: str):
    with SessionLocal() as db:
        rows = db.execute(
            select(WorkflowStepRow).where(WorkflowStepRow.run_id == run_id)
        ).scalars().all()
        return [row.step_name for row in rows]


def test_manager_amount_waits_for_approval_without_stripe(world, refund_ctx):
    run = world["engine"].start(
        "refund",
        refund_ctx(amount=2500, photos_received=True, reason="damaged"),
    )
    assert run.status == "waiting_approval"
    assert run.output["policy"]["allowed"] is False
    assert run.output["policy"]["requires_approval"] is True
    assert run.output["policy"]["deny_code"] == "AMOUNT"
    assert world["tools"].stripe_calls == 0
    tasks = _tasks(run.run_id)
    assert len(tasks) == 1
    assert tasks[0].status == "pending"
    assert tasks[0].task_type == "refund_approval"
    assert tasks[0].payload_json["amount"] == 2500
    assert tasks[0].payload_json["order_id"] == "12345"
    assert "execute_refund" not in _step_names(run.run_id)


def test_missing_photos_stops_before_approval(world, refund_ctx):
    run = world["engine"].start(
        "refund",
        refund_ctx(amount=2500, photos_received=False, reason="damaged"),
    )
    assert run.status == "waiting_input"
    assert "photos" in run.output["requires_inputs"]
    assert world["tools"].stripe_calls == 0
    assert _tasks(run.run_id) == []
    names = _step_names(run.run_id)
    assert "fetch_order" in names
    assert "require_approval" not in names
    assert "execute_refund" not in names


def test_anonymous_refund_waits_for_auth_before_shopify(world, refund_ctx):
    run = world["engine"].start("refund", refund_ctx(auth_level="anonymous", amount=500))
    assert run.status == "waiting_auth"
    assert run.output["policy"]["requires_strong_auth"] is True
    assert run.output["policy"]["deny_code"] == "AUTH"
    assert world["tools"].stripe_calls == 0
    assert world["tools"].order_calls == 0
    assert _tasks(run.run_id) == []


def test_preference_finishes_without_stripe(world, refund_ctx):
    run = world["engine"].start(
        "refund",
        refund_ctx(reason="preference", amount=500, photos_received=True),
    )
    assert run.status == "failed"
    assert run.output["policy"]["deny_code"] == "OUT_OF_POLICY"
    assert run.output["denied"] is True
    assert world["tools"].stripe_calls == 0
    assert _tasks(run.run_id) == []
    with SessionLocal() as db:
        count = db.execute(
            select(func.count()).select_from(HumanTaskRow).where(HumanTaskRow.workflow_run_id == run.run_id)
        ).scalar_one()
        assert count == 0
