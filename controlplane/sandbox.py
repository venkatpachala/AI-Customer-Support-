"""Pilot script. A pass is citation, a photo ask, and a held refund."""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from controlplane.keys import mark_sandbox_passed, tenant_record

POLICY_MESSAGE = "What is the return policy for damaged products?"
PHOTO_MESSAGE = "My order #12345 is damaged. I want to return it."
HOLD_MESSAGE = "Order 12345, phone 9999900000, refund 2500, photos uploaded."

STEPS = (
    {"id": "citation", "message": POLICY_MESSAGE},
    {"id": "photos", "message": PHOTO_MESSAGE},
    {"id": "hold", "message": HOLD_MESSAGE},
)


def _stripe_succeeded(turn: Dict[str, Any]) -> bool:
    if str(turn.get("stripe_status") or "").lower() == "success":
        return True
    tools = turn.get("tool_results") or {}
    if isinstance(tools, dict):
        for name, result in tools.items():
            if "stripe" not in str(name).lower() or not isinstance(result, dict):
                continue
            status = str(result.get("status") or "").lower()
            if status == "success":
                return True
    return False


def judge(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pass only when all three pilot checks hold. A miss does not stamp the tenant."""
    steps: List[Dict[str, Any]] = []
    if len(turns) < 3:
        return {"passed": False, "failures": ["incomplete script"], "steps": steps}

    policy, photo, hold = turns[0], turns[1], turns[2]
    citation_ok = bool(policy.get("citations"))
    missing = list(photo.get("missing_inputs") or [])
    photo_text = str(photo.get("response") or "").lower()
    photo_ok = "photos" in missing or "photo" in photo_text
    hold_ok = hold.get("workflow_status") == "waiting_approval" and not _stripe_succeeded(hold)

    steps.append({"id": "citation", "passed": citation_ok, "detail": "citation exists" if citation_ok else "citation missing"})
    steps.append({"id": "photos", "passed": photo_ok, "detail": "photo ask" if photo_ok else "photo ask missing"})
    detail = "waiting_approval"
    if hold.get("workflow_status") != "waiting_approval":
        detail = f"workflow_status={hold.get('workflow_status')}"
    elif _stripe_succeeded(hold):
        detail = "stripe success"
    steps.append({"id": "hold", "passed": hold_ok, "detail": detail})
    failures = [step["detail"] for step in steps if not step["passed"]]
    return {"passed": not failures, "failures": failures, "steps": steps}


def explicit_refund(message: str) -> bool:
    text = (message or "").lower()
    if "refund" not in text:
        return False
    if not re.search(r"\d{5,}", text):
        return False
    return bool(re.search(r"refund\D{0,20}(\d{3,6})", text))


def run_sandbox(
    tenant_id: str,
    sender: Callable[[str, str], Dict[str, Any]],
) -> Dict[str, Any]:
    turns = [sender(tenant_id, step["message"]) for step in STEPS]
    report = judge(turns)
    report["turns"] = [
        {
            "message": STEPS[index]["message"],
            "workflow_status": turn.get("workflow_status"),
            "citations": turn.get("citations") or [],
            "missing_inputs": turn.get("missing_inputs") or [],
        }
        for index, turn in enumerate(turns)
    ]
    if report["passed"]:
        stamp = mark_sandbox_passed(tenant_id)
        report["sandbox_passed_at"] = stamp.isoformat()
    else:
        row = tenant_record(tenant_id)
        report["sandbox_passed_at"] = None if row is None or row.sandbox_passed_at is None else row.sandbox_passed_at.isoformat()
    report["passed_now"] = bool(report["passed"])
    return report


_sender: Optional[Callable[[str, str], Dict[str, Any]]] = None


def set_sender(fn: Callable[[str, str], Dict[str, Any]]) -> None:
    global _sender
    _sender = fn


def default_sender(tenant_id: str, message: str) -> Dict[str, Any]:
    if _sender is None:
        raise RuntimeError("sandbox sender is not configured")
    return _sender(tenant_id, message)
