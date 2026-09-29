"""Return, replacement, and cancel. These actions do not authorize a refund."""
from policy import evaluate


def test_damaged_return_without_photos_asks_for_photos():
    decision = evaluate(
        "zepto",
        "return",
        auth_level="identified",
        slots={"reason": "damaged", "photos_received": False, "order_id": "12345"},
    )
    assert decision.requires_inputs == ["photos"]
    assert decision.allowed is False
    assert decision.deny_code == "MISSING_INPUT"
    assert decision.requires_approval is False
    assert decision.max_amount is None
    assert decision.policy_id == "return"


def test_identified_return_with_photos_may_proceed():
    decision = evaluate(
        "zepto",
        "return",
        auth_level="identified",
        slots={"reason": "damaged", "photos_received": True},
    )
    assert decision.allowed is True
    assert decision.requires_inputs == []
    assert decision.deny_code is None
    assert decision.requires_approval is False


def test_return_amount_does_not_open_a_refund_cap():
    decision = evaluate(
        "zepto",
        "return",
        auth_level="identified",
        slots={"reason": "late", "photos_received": False, "amount": 50000},
    )
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.max_amount is None
    assert decision.deny_code is None


def test_anonymous_return_requires_strong_auth():
    decision = evaluate(
        "zepto",
        "return",
        auth_level="anonymous",
        slots={"reason": "damaged", "photos_received": True},
    )
    assert decision.requires_strong_auth is True
    assert decision.allowed is False
    assert decision.deny_code == "AUTH"


def test_preference_return_is_out_of_policy():
    decision = evaluate(
        "zepto",
        "return",
        auth_level="identified",
        slots={"reason": "preference", "photos_received": True},
    )
    assert decision.allowed is False
    assert decision.deny_code == "OUT_OF_POLICY"
    assert decision.requires_inputs == []


def test_delivered_cancel_is_too_late():
    decision = evaluate(
        "zepto",
        "cancel",
        auth_level="identified",
        slots={"order_status": "delivered", "order_id": "12345"},
    )
    assert decision.allowed is False
    assert decision.deny_code == "OUT_OF_POLICY"
    assert "cancel_too_late" in decision.reasons
    assert decision.requires_approval is False
    assert decision.policy_id == "cancel"


def test_fulfilled_cancel_is_too_late():
    decision = evaluate(
        "zepto",
        "cancel",
        auth_level="identified",
        slots={"order_status": "Fulfilled"},
    )
    assert decision.deny_code == "OUT_OF_POLICY"
    assert decision.allowed is False


def test_cancel_without_order_status_asks_for_it():
    decision = evaluate(
        "zepto",
        "cancel",
        auth_level="identified",
        slots={"order_id": "12345"},
    )
    assert decision.requires_inputs == ["order_status"]
    assert decision.allowed is False
    assert decision.deny_code == "MISSING_INPUT"


def test_cancel_before_delivery_is_allowed():
    decision = evaluate(
        "zepto",
        "cancel",
        auth_level="identified",
        slots={"order_status": "out_for_delivery"},
    )
    assert decision.allowed is True
    assert decision.deny_code is None
    assert "cancel_allowed" in decision.reasons


def test_replacement_uses_return_photo_and_auth_rules():
    missing = evaluate(
        "zepto",
        "replacement",
        auth_level="identified",
        slots={"reason": "damaged", "photos_received": False},
    )
    assert missing.requires_inputs == ["photos"]
    assert missing.allowed is False
    assert missing.policy_id == "replacement"
    assert missing.max_amount is None

    anonymous = evaluate(
        "zepto",
        "replacement",
        auth_level="anonymous",
        slots={"reason": "damaged", "photos_received": True},
    )
    assert anonymous.requires_strong_auth is True
    assert anonymous.deny_code == "AUTH"
