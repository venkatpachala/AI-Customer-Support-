"""Prove a customer owns an order. The chat body cannot grant this."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from db.models import CaseRow
from db.session import SessionLocal

_ROOT = Path(__file__).resolve().parents[1]


def contact_hash(contact: str) -> str:
    return hashlib.sha256(normalize_contact(contact).encode("utf-8")).hexdigest()


def normalize_phone(value: Optional[str]) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) >= 10:
        return digits[-10:]
    return digits


def normalize_contact(contact: Optional[str]) -> str:
    text = (contact or "").strip()
    if "@" in text:
        return text.lower()
    return normalize_phone(text)


def extract_contact(message: Optional[str], explicit: Optional[str] = None) -> Optional[str]:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    text = message or ""
    email = re.search(r"[\w.+\-]+@[\w.\-]+\.[A-Za-z]{2,}", text)
    if email:
        return email.group(0)
    phones = re.findall(r"\d[\d\s\-]{8,}\d", text)
    for raw in phones:
        phone = normalize_phone(raw)
        if len(phone) == 10:
            return phone
    return None


def _fixture_path(tenant_id: str) -> Path:
    return _ROOT / "tenants" / tenant_id / "identity_fixture.yaml"


def _load_fixture(tenant_id: str) -> Dict[str, Any]:
    path = _fixture_path(tenant_id)
    if not path.is_file():
        return {}
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return document if isinstance(document, dict) else {}


def _match_pair(contact: str, phone: Optional[str], email: Optional[str]) -> Optional[str]:
    token = normalize_contact(contact)
    if not token:
        return None
    if "@" in token and token == (email or "").strip().lower():
        return "email"
    if "@" not in token and token == normalize_phone(phone):
        return "phone"
    return None


def _prove_fixture(tenant_id: str, order_id: str, contact: str) -> Dict[str, Any]:
    orders = (_load_fixture(tenant_id).get("orders") or {})
    row = orders.get(str(order_id)) or orders.get(order_id)
    if not isinstance(row, dict):
        return {"ok": False, "matched_on": None, "customer_id": None}
    matched = _match_pair(contact, row.get("phone"), row.get("email"))
    if not matched:
        return {"ok": False, "matched_on": None, "customer_id": None}
    return {
        "ok": True,
        "matched_on": matched,
        "customer_id": str(row.get("customer_id") or f"{tenant_id}:{order_id}"),
    }


def _contact_fields(data: Dict[str, Any]) -> tuple[list, list]:
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    shipping = data.get("shipping_address") if isinstance(data.get("shipping_address"), dict) else {}
    phones = [customer.get("phone"), shipping.get("phone"), data.get("phone")]
    emails = [customer.get("email"), data.get("email"), shipping.get("email")]
    return phones, emails


def _prove_live(tenant_id: str, order_id: str, contact: str) -> Dict[str, Any]:
    from tools.base.context import ToolContext
    from tools.registry import TOOL_REGISTRY

    tool = TOOL_REGISTRY.get("shopify_get_order")
    if tool is None or not hasattr(tool, "execute"):
        return {"ok": False, "matched_on": None, "customer_id": None}
    try:
        result = tool.execute(
            {"order_id": order_id},
            ToolContext(request_id="ownership", tenant_id=tenant_id),
        )
    except Exception:
        return {"ok": False, "matched_on": None, "customer_id": None}
    data = getattr(result, "data", None)
    if not isinstance(data, dict) or getattr(result, "status", None) != "success":
        return {"ok": False, "matched_on": None, "customer_id": None}
    phones, emails = _contact_fields(data)
    matched = None
    for phone in phones:
        matched = _match_pair(contact, phone, None)
        if matched:
            break
    if matched is None:
        for email in emails:
            matched = _match_pair(contact, None, email)
            if matched:
                break
    if not matched:
        return {"ok": False, "matched_on": None, "customer_id": None}
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    customer_id = customer.get("id") or data.get("customer_id") or f"{tenant_id}:{order_id}"
    return {"ok": True, "matched_on": matched, "customer_id": str(customer_id)}


def prove(tenant_id: str, order_id: str, contact: str) -> Dict[str, Any]:
    """Return ok, matched_on, and customer_id. Never echo the stored phone or email."""
    order = str(order_id or "").strip()
    if not order or not (contact or "").strip():
        return {"ok": False, "matched_on": None, "customer_id": None}
    mode = os.getenv("TOOLS_MODE", "mock").strip().lower()
    if mode == "live":
        proof = _prove_live(tenant_id, order, contact)
    else:
        proof = _prove_fixture(tenant_id, order, contact)
    return {
        "ok": bool(proof.get("ok")),
        "matched_on": proof.get("matched_on"),
        "customer_id": proof.get("customer_id"),
    }


def case_auth(case_id: str, session_factory=SessionLocal) -> tuple[str, List[str], bool]:
    """Server auth for a case. checked is true after a public ownership attempt."""
    with session_factory() as db:
        case = db.get(CaseRow, case_id)
        if case is None:
            return "anonymous", [], False
        summary = dict(case.tool_results_summary or {})
        orders = [str(item) for item in (summary.get("verified_order_ids") or [])]
        checked = bool(summary.get("ownership_checked"))
        level = str(case.auth_level or "anonymous")
        return level, orders, checked


def apply_ownership(case_id: str, tenant_id: str, order_id: str, contact: str) -> Dict[str, Any]:
    """Record a match on the case. Verified is set only when prove() succeeds."""
    proof = prove(tenant_id, order_id, contact)
    digest = contact_hash(contact) if (contact or "").strip() else None
    with SessionLocal() as db:
        case = db.get(CaseRow, case_id)
        if case is None or case.tenant_id != tenant_id:
            return {"ok": False, "matched_on": None, "customer_id": None, "detail": "could not verify this order"}
        summary = dict(case.tool_results_summary or {})
        summary["ownership_checked"] = True
        if digest:
            summary["customer_contact_hash"] = digest
        orders = [str(item) for item in (summary.get("verified_order_ids") or [])]
        if proof["ok"]:
            if str(order_id) not in orders:
                orders.append(str(order_id))
            summary["verified_order_ids"] = orders
            case.auth_level = "verified"
            if proof.get("customer_id"):
                summary["owner_customer_id"] = proof["customer_id"]
        else:
            summary["verified_order_ids"] = [item for item in orders if item != str(order_id)]
            if not summary["verified_order_ids"]:
                case.auth_level = "anonymous"
        case.tool_results_summary = summary
        db.commit()
    result = dict(proof)
    if not result["ok"]:
        result["detail"] = "could not verify this order"
    return result
