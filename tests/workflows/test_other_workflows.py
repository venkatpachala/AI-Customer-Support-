"""Return, cancel, and order-status definitions. None of them call Stripe."""
from db.models import CaseRow
from db.session import SessionLocal


def test_return_without_photos_waits_and_does_not_call_stripe(world, refund_ctx):
    run = world["engine"].start(
        "return_damaged",
        refund_ctx(auth_level="identified", photos_received=False, reason="damaged"),
    )
    assert run.status == "waiting_input"
    assert run.output["requires_inputs"] == ["photos"]
    assert run.output["next"] == "ask_photos_or_done"
    assert world["tools"].stripe_calls == 0
    assert world["tools"].order_calls == 1


def test_return_with_photos_finishes_without_stripe(world, refund_ctx):
    run = world["engine"].start(
        "return_damaged",
        refund_ctx(auth_level="identified", photos_received=True, reason="damaged"),
    )
    assert run.status == "succeeded"
    assert run.output["next"] == "ask_photos_or_done"
    assert run.output["denied"] is False
    assert world["tools"].stripe_calls == 0
    with SessionLocal() as db:
        case = db.get(CaseRow, world["case"].case_id)
        assert case.status == "open"


def test_delivered_cancel_is_denied_without_a_cancel_tool(world, refund_ctx):
    world["tools"].order_status = "delivered"
    run = world["engine"].start("cancel", refund_ctx(auth_level="identified"))
    assert run.status == "succeeded"
    assert run.output["denied"] is True
    assert run.output["policy"]["deny_code"] == "OUT_OF_POLICY"
    assert world["tools"].stripe_calls == 0
    assert world["tools"].order_calls == 1


def test_anonymous_order_status_does_not_fetch(world, refund_ctx):
    run = world["engine"].start("order_status", refund_ctx(auth_level="anonymous"))
    assert run.status == "waiting_auth"
    assert run.output["policy"]["requires_strong_auth"] is True
    assert world["tools"].order_calls == 0
    assert world["tools"].stripe_calls == 0
