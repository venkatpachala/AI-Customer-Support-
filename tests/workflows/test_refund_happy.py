"""A verified in-policy refund runs once and calls Stripe once."""
from sqlalchemy import select

from db.models import CaseRow, WorkflowRunRow, WorkflowStepRow
from db.session import SessionLocal
def test_verified_small_refund_succeeds_and_calls_stripe_once(world, refund_ctx):
    run = world["engine"].start("refund", refund_ctx())

    assert run.status == "succeeded"
    assert run.output["policy"]["allowed"] is True
    assert run.output["policy"]["policy_id"] == "refund"
    assert world["tools"].stripe_calls == 1
    assert world["tools"].order_calls == 1
    assert world["tools"].stripe_params[0]["idempotency_key"] == f"{run.run_id}:execute_refund"
    assert run.output["notify"]["skipped"] is True

    with SessionLocal() as db:
        case = db.get(CaseRow, world["case"].case_id)
        assert case.status == "resolved"
        steps = db.execute(
            select(WorkflowStepRow).where(WorkflowStepRow.run_id == run.run_id)
        ).scalars().all()
        names = [step.step_name for step in steps]
        assert len(names) == len(set(names))
        assert names == [
            "assert_auth",
            "fetch_order",
            "evaluate_policy",
            "collect_inputs",
            "require_approval",
            "execute_refund",
            "update_case",
            "notify",
        ]
        assert all(step.status == "success" for step in steps)
        stored = db.get(WorkflowRunRow, run.run_id)
        assert stored.status == "succeeded"
        assert stored.output_json["policy"]["allowed"] is True
