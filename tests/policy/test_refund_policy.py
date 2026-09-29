"""Zepto refund decisions from tenants/zepto/policies/refund.yaml. No model, no API."""
from policy import PolicyDecision, evaluate


def _refund(**slots) -> PolicyDecision:
    defaults = {"amount": 500, "reason": "damaged", "photos_received": True}
    defaults.update(slots)
    return evaluate("zepto", "refund", auth_level="verified", slots=defaults)


def test_small_damaged_refund_with_photos_may_execute():
    decision = _refund(amount=500, reason="damaged", photos_received=True)
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.requires_strong_auth is False
    assert decision.requires_inputs == []
    assert decision.deny_code is None
    assert "auth_ok" in decision.reasons
    assert "amount_within_auto" in decision.reasons
    assert "photos_ok" in decision.reasons
    assert decision.max_amount == 2000


def test_auto_cap_boundary_is_inclusive():
    decision = _refund(amount=2000)
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.deny_code is None


def test_between_auto_and_manager_needs_a_human():
    decision = _refund(amount=2500, photos_received=True)
    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.requires_strong_auth is False
    assert decision.deny_code == "AMOUNT"
    assert decision.requires_inputs == []
    assert "amount_requires_manager" in decision.reasons
    assert decision.max_amount == 10000


def test_manager_cap_boundary_still_needs_approval():
    decision = _refund(amount=10000)
    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.deny_code == "AMOUNT"
    assert "amount_requires_manager" in decision.reasons


def test_above_manager_cap_is_not_auto_run():
    decision = _refund(amount=50000, photos_received=True, reason="damaged")
    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.deny_code == "AMOUNT"
    assert "amount_above_manager" in decision.reasons
    assert decision.max_amount == 10000


def test_currency_string_uses_the_same_caps():
    decision = _refund(amount="₹2,500")
    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.deny_code == "AMOUNT"


def test_anonymous_refund_requires_strong_auth():
    decision = evaluate(
        "zepto",
        "refund",
        auth_level="anonymous",
        slots={"amount": 500, "reason": "damaged", "photos_received": True},
    )
    assert decision.requires_strong_auth is True
    assert decision.allowed is False
    assert decision.deny_code == "AUTH"
    assert decision.requires_approval is False


def test_identified_does_not_satisfy_verified_refund():
    decision = evaluate(
        "zepto",
        "refund",
        auth_level="identified",
        slots={"amount": 500, "reason": "damaged", "photos_received": True},
    )
    assert decision.requires_strong_auth is True
    assert decision.allowed is False
    assert decision.deny_code == "AUTH"


def test_damaged_without_photos_asks_before_any_execution():
    decision = _refund(amount=500, reason="damaged", photos_received=False)
    assert decision.requires_inputs == ["photos"]
    assert decision.allowed is False
    assert decision.requires_approval is False
    assert decision.deny_code == "MISSING_INPUT"
    assert "photos_required" in decision.reasons


def test_missing_photos_block_even_when_amount_needs_a_manager():
    decision = _refund(amount=2500, reason="missing_item", photos_received=False)
    assert decision.requires_inputs == ["photos"]
    assert decision.allowed is False
    assert decision.requires_approval is False
    assert decision.deny_code == "MISSING_INPUT"


def test_missing_amount_is_an_input_not_a_zero_refund():
    decision = _refund(amount=None, reason="late", photos_received=False)
    assert decision.requires_inputs == ["amount"]
    assert decision.allowed is False
    assert decision.deny_code == "MISSING_INPUT"
    assert decision.requires_approval is False


def test_preference_refund_is_out_of_policy():
    decision = _refund(amount=500, reason="preference", photos_received=True)
    assert decision.allowed is False
    assert decision.deny_code == "OUT_OF_POLICY"
    assert decision.requires_approval is False
    assert decision.requires_inputs == []
    assert "out_of_policy_preference" in decision.reasons
