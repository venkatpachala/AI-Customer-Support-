"""Compare a stored policy snapshot with what the scenario expected."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def policy_mismatches(policy: Optional[Dict[str, Any]], expect: Dict[str, Any]) -> List[str]:
    policy = policy or {}
    failures: List[str] = []
    if "allowed" in expect and policy.get("allowed") is not expect["allowed"]:
        failures.append(f"allowed expected {expect['allowed']} got {policy.get('allowed')}")
    if "deny_code" in expect and policy.get("deny_code") != expect["deny_code"]:
        failures.append(f"deny_code expected {expect['deny_code']} got {policy.get('deny_code')}")
    return failures
