"""Frozen turn outcomes. No sentiment model and no LLM."""
from __future__ import annotations

from typing import Any, Optional, Sequence

OUTCOMES = (
    "answered",
    "waiting_customer",
    "waiting_approval",
    "waiting_auth",
    "resolved",
    "escalated",
    "blocked",
    "failed",
)

SUB_INTENTS = ("damaged", "preference", "missing_item", "late", "other")

_REASON_TOKENS = {
    "damaged": "damaged",
    "damage": "damaged",
    "broken": "damaged",
    "preference": "preference",
    "missing_item": "missing_item",
    "missingitem": "missing_item",
    "late": "late",
    "delayed": "late",
    "delay": "late",
}


def classify_outcome(
    *,
    blocked: bool = False,
    escalated: bool = False,
    status: Optional[str] = None,
    workflow_status: Optional[str] = None,
    case_status: Optional[str] = None,
    missing_inputs: Optional[Sequence[Any]] = None,
    photos_received: bool = False,
    pending_approval: bool = False,
) -> str:
    """Map flags the runtime already has onto the frozen outcome enum.

    First match wins: blocked, waiting_auth, waiting_approval, waiting on
    the customer, a finished workflow, a failed workflow, escalation,
    otherwise a normal reply.
    """
    workflow = str(workflow_status or "").strip()
    turn_status = str(status or "").strip()
    case = str(case_status or "").strip()
    if blocked or turn_status == "blocked":
        return "blocked"
    if workflow == "waiting_auth" or turn_status == "waiting_auth":
        return "waiting_auth"
    if workflow == "waiting_approval" or turn_status == "waiting_approval" or pending_approval:
        return "waiting_approval"
    inputs = [str(item) for item in (missing_inputs or [])]
    waiting_on_customer = (
        workflow in {"waiting_input", "waiting_customer"}
        or turn_status in {"waiting_input", "waiting_customer"}
        or case == "waiting_customer"
    )
    if waiting_on_customer or ("photos" in inputs and not photos_received):
        return "waiting_customer"
    if workflow == "succeeded" or case == "resolved" or turn_status == "resolved":
        return "resolved"
    if workflow in {"failed", "cancelled"} or turn_status in {"failed", "cancelled"}:
        return "failed"
    if escalated or turn_status == "escalated":
        return "escalated"
    return "answered"


def classify_sub_intent(message: Optional[str], reason: Optional[str] = None) -> str:
    """damaged, preference, missing_item, late, or other. Keyword match only."""
    token = str(reason or "").strip().lower().replace("-", "_").replace(" ", "_")
    if token in _REASON_TOKENS:
        return _REASON_TOKENS[token]
    text = str(message or "").lower()
    if any(
        phrase in text
        for phrase in (
            "didn't like",
            "didnt like",
            "don't like",
            "dont like",
            "do not like",
            "changed my mind",
            "don't want",
            "dont want",
            "preference",
        )
    ):
        return "preference"
    if any(phrase in text for phrase in ("missing item", "item is missing", "not in the bag", "missing_item")):
        return "missing_item"
    if any(phrase in text for phrase in ("damaged", "damage", "broken")):
        return "damaged"
    if any(phrase in text for phrase in ("late", "delayed", "delay")):
        return "late"
    return "other"
