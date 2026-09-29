"""Action rules. Each function reads a resolved pack and the caller's slots."""
from __future__ import annotations

from typing import List, Optional

from policy.context import PolicySlots
from policy.decisions import PolicyDecision
from policy.loader import ActionPolicy, ResolvedPolicyPack
from policy.rules import amount_band, auth_satisfies, token_in


class _Draft:
    def __init__(self, spec: ActionPolicy):
        self.allowed = False
        self.requires_approval = False
        self.requires_strong_auth = False
        self.requires_inputs: List[str] = []
        self.max_amount: Optional[float] = spec.auto_max if spec.action == "refund" else None
        self.reasons: List[str] = []
        self.policy_id = spec.policy_id
        self.policy_version = spec.policy_version
        self.deny_code: Optional[str] = None

    def add_reason(self, code: str) -> None:
        if code not in self.reasons:
            self.reasons.append(code)

    def add_input(self, name: str) -> None:
        if name not in self.requires_inputs:
            self.requires_inputs.append(name)

    def freeze(self) -> PolicyDecision:
        return PolicyDecision(
            allowed=self.allowed,
            requires_approval=self.requires_approval,
            requires_strong_auth=self.requires_strong_auth,
            requires_inputs=list(self.requires_inputs),
            max_amount=self.max_amount,
            reasons=list(self.reasons),
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            deny_code=self.deny_code,  # type: ignore[arg-type]
        )


def evaluate_action(
    pack: ResolvedPolicyPack,
    action: str,
    auth_level: str,
    slots: PolicySlots,
) -> PolicyDecision:
    if action not in pack.actions:
        return _unknown(pack, action)
    spec = pack.action(action)
    if action == "refund":
        return _refund(spec, auth_level, slots)
    if action in ("return", "replacement"):
        return _return_like(spec, auth_level, slots)
    if action == "cancel":
        return _cancel(spec, auth_level, slots)
    if action == "order_status":
        return _order_status(spec, auth_level)
    if action == "policy":
        return _policy_question(spec, auth_level)
    return _unknown(pack, action)


def _unknown(pack: ResolvedPolicyPack, action: str) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        requires_approval=False,
        requires_strong_auth=False,
        requires_inputs=[],
        max_amount=None,
        reasons=["unknown_action"],
        policy_id="unknown",
        policy_version=pack.policy_pack_version,
        deny_code="OUT_OF_POLICY",
    )


def _auth_blocks(draft: _Draft, auth_level: str, spec: ActionPolicy) -> bool:
    if auth_satisfies(auth_level, spec.min_auth):
        draft.add_reason("auth_ok")
        return False
    draft.requires_strong_auth = True
    draft.allowed = False
    draft.deny_code = "AUTH"
    draft.add_reason("auth_insufficient")
    return True


def _out_of_policy(draft: _Draft, slots: PolicySlots, spec: ActionPolicy) -> bool:
    if not token_in(slots.reason, spec.out_of_policy_reasons):
        return False
    draft.allowed = False
    draft.requires_approval = False
    draft.deny_code = "OUT_OF_POLICY"
    if slots.reason == "preference":
        draft.add_reason("out_of_policy_preference")
    else:
        draft.add_reason(f"out_of_policy_{slots.reason}")
    return True


def _refund(spec: ActionPolicy, auth_level: str, slots: PolicySlots) -> PolicyDecision:
    draft = _Draft(spec)
    if _caps_invalid(spec):
        draft.allowed = False
        draft.deny_code = "OUT_OF_POLICY"
        draft.add_reason("cap_config_invalid")
        return draft.freeze()
    if _auth_blocks(draft, auth_level, spec):
        return draft.freeze()
    if _out_of_policy(draft, slots, spec):
        return draft.freeze()

    _apply_photos(draft, slots, spec)
    _apply_refund_amount(draft, slots, spec)

    if draft.requires_inputs:
        # Photos and a missing amount are collected before any human task.
        draft.allowed = False
        draft.requires_approval = False
        draft.deny_code = "MISSING_INPUT"
        return draft.freeze()

    if draft.deny_code is None:
        draft.allowed = True
    else:
        draft.allowed = False
    return draft.freeze()


def _caps_invalid(spec: ActionPolicy) -> bool:
    if spec.auto_max is None or spec.manager_max is None:
        return True
    if spec.auto_max < 0 or spec.manager_max < 0:
        return True
    return spec.manager_max < spec.auto_max


def _apply_photos(draft: _Draft, slots: PolicySlots, spec: ActionPolicy) -> None:
    if not token_in(slots.reason, spec.photo_required_for):
        draft.add_reason("photos_not_required")
        return
    if slots.photos_received:
        draft.add_reason("photos_ok")
        return
    draft.add_input("photos")
    draft.add_reason("photos_required")


def _apply_refund_amount(draft: _Draft, slots: PolicySlots, spec: ActionPolicy) -> None:
    amount = slots.amount
    if amount is None:
        draft.add_input("amount")
        draft.add_reason("amount_missing")
        draft.max_amount = spec.auto_max
        return
    if amount <= 0:
        draft.add_input("amount")
        draft.add_reason("amount_invalid")
        draft.max_amount = spec.auto_max
        return

    band = amount_band(amount, spec.auto_max or 0, spec.manager_max or 0)
    if band == "auto":
        draft.add_reason("amount_within_auto")
        draft.max_amount = spec.auto_max
        return
    if band == "manager":
        draft.add_reason("amount_requires_manager")
        draft.max_amount = spec.manager_max
        draft.requires_approval = True
        draft.deny_code = "AMOUNT"
        draft.allowed = False
        return
    draft.add_reason("amount_above_manager")
    draft.max_amount = spec.manager_max
    draft.requires_approval = True
    draft.deny_code = "AMOUNT"
    draft.allowed = False


def _return_like(spec: ActionPolicy, auth_level: str, slots: PolicySlots) -> PolicyDecision:
    """Return and replacement. No amount cap and no money movement."""
    draft = _Draft(spec)
    draft.max_amount = None
    if _auth_blocks(draft, auth_level, spec):
        return draft.freeze()
    if _out_of_policy(draft, slots, spec):
        return draft.freeze()
    _apply_photos(draft, slots, spec)
    if draft.requires_inputs:
        draft.allowed = False
        draft.deny_code = "MISSING_INPUT"
        return draft.freeze()
    draft.allowed = True
    return draft.freeze()


def _cancel(spec: ActionPolicy, auth_level: str, slots: PolicySlots) -> PolicyDecision:
    draft = _Draft(spec)
    if _auth_blocks(draft, auth_level, spec):
        return draft.freeze()
    status = slots.order_status or ""
    if not status:
        draft.allowed = False
        draft.deny_code = "MISSING_INPUT"
        draft.add_input("order_status")
        draft.add_reason("order_status_required")
        return draft.freeze()
    if token_in(status, spec.blocked_order_statuses):
        draft.allowed = False
        draft.deny_code = "OUT_OF_POLICY"
        draft.add_reason("cancel_too_late")
        return draft.freeze()
    draft.allowed = True
    draft.add_reason("cancel_allowed")
    return draft.freeze()


def _order_status(spec: ActionPolicy, auth_level: str) -> PolicyDecision:
    """Knowledge may continue. A tool fetch still needs the auth ladder."""
    draft = _Draft(spec)
    draft.allowed = True
    draft.max_amount = None
    if auth_satisfies(auth_level, spec.min_auth):
        draft.add_reason("auth_ok")
    else:
        draft.requires_strong_auth = True
        draft.add_reason("tool_requires_auth")
    return draft.freeze()


def _policy_question(spec: ActionPolicy, auth_level: str) -> PolicyDecision:
    """Policy answers are not a tool call. Anonymous is enough for Zepto."""
    draft = _Draft(spec)
    draft.allowed = True
    draft.max_amount = None
    draft.add_reason("knowledge_ok")
    if not auth_satisfies(auth_level, spec.min_auth):
        draft.requires_strong_auth = True
        draft.add_reason("auth_insufficient")
    return draft.freeze()
