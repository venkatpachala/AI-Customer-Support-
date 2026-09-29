"""Public policy entrypoint. Deterministic: YAML in, PolicyDecision out."""
from __future__ import annotations

from typing import Any, Dict, Optional

from policy.context import slots_from_mapping
from policy.decisions import PolicyDecision
from policy.evaluator import evaluate_action
from policy.loader import load_resolved_pack
from policy.rules import normalize_token

_KNOWN_ACTIONS = {
    "refund",
    "return",
    "cancel",
    "replacement",
    "order_status",
    "policy",
}


def evaluate(
    tenant_id: str,
    action: str,
    *,
    auth_level: str = "anonymous",
    slots: Optional[Dict[str, Any]] = None,
) -> PolicyDecision:
    """Decide whether this action may proceed for this tenant.

    No network and no model. Amount, photos, and order status come only
    from ``slots``.
    """
    pack = load_resolved_pack(tenant_id)
    action_name = normalize_token(action)
    parsed = slots_from_mapping(slots)
    if action_name not in _KNOWN_ACTIONS:
        return evaluate_action(pack, action_name, auth_level, parsed)
    return evaluate_action(pack, action_name, auth_level or "anonymous", parsed)
