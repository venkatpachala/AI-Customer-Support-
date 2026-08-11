import os
import re
import time
from typing import Any, Dict, Optional

from tools.base.tool import BaseTool


MOCK_ORDERS = {
    "12345": {
        "phone": "9999999999",
        "email": "customer@example.com",
        "customer_ref": "cust_mock_12345",
        "status": "delivered",
    }
}


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 10 else digits


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def parse_contact(contact: str) -> Dict[str, Optional[str]]:
    c = (contact or "").strip()
    if not c:
        return {"phone": None, "email": None}
    if "@" in c:
        return {"phone": None, "email": normalize_email(c)}
    return {"phone": normalize_phone(c), "email": None}


def mock_identify(order_id: str, contact: str) -> Dict[str, Any]:
    order = MOCK_ORDERS.get(str(order_id))
    if not order:
        return {
            "success": False,
            "auth_level": "anonymous",
            "order_id": str(order_id),
            "matched_on": None,
            "method": "order_contact_match",
            "customer_ref": None,
            "error_code": "order_not_found",
            "error": f"Order {order_id} not found",
        }

    parsed = parse_contact(contact)

    if parsed["phone"] and parsed["phone"] == order["phone"]:
        return {
            "success": True,
            "auth_level": "identified",
            "order_id": str(order_id),
            "matched_on": "phone",
            "method": "order_contact_match",
            "customer_ref": order["customer_ref"],
            "error_code": None,
            "error": None,
        }

    if parsed["email"] and parsed["email"] == order["email"]:
        return {
            "success": True,
            "auth_level": "identified",
            "order_id": str(order_id),
            "matched_on": "email",
            "method": "order_contact_match",
            "customer_ref": order["customer_ref"],
            "error_code": None,
            "error": None,
        }

    return {
        "success": False,
        "auth_level": "anonymous",
        "order_id": str(order_id),
        "matched_on": None,
        "method": "order_contact_match",
        "customer_ref": None,
        "error_code": "ownership_mismatch",
        "error": "Order contact does not match provided phone/email",
    }


def live_identify(order_id: str, contact: str) -> Dict[str, Any]:
    return {
        "success": False,
        "auth_level": "anonymous",
        "order_id": str(order_id),
        "matched_on": None,
        "method": "order_contact_match",
        "customer_ref": None,
        "error_code": "live_not_configured",
        "error": "Live Shopify identify is not configured",
    }


def shopify_identify_customer(order_id: str, contact: str, **kwargs) -> Dict[str, Any]:
    """Direct function API used by identity.service"""
    start = time.time()
    mode = os.getenv("TOOLS_MODE", "mock").lower()

    if not order_id or not contact:
        return {
            "status": "error",
            "data": None,
            "error": "order_id and contact are required",
            "error_code": "invalid_input",
            "provider": "shopify",
            "operation": "shopify_identify_customer",
            "latency_ms": round((time.time() - start) * 1000, 2),
            "meta": {"mode": mode},
        }

    result = live_identify(str(order_id), str(contact)) if mode == "live" else mock_identify(str(order_id), str(contact))

    return {
        "status": "success" if result.get("success") else "error",
        "data": result,
        "error": result.get("error"),
        "error_code": result.get("error_code"),
        "provider": "shopify",
        "operation": "shopify_identify_customer",
        "latency_ms": round((time.time() - start) * 1000, 2),
        "meta": {"mode": mode},
    }


class ShopifyIdentifyCustomer(BaseTool):
    name = "shopify_identify_customer"
    description = "Verify order ownership using order_id and phone/email"

    def _run(self, order_id: str = None, contact: str = None, **kwargs) -> Dict[str, Any]:
        return shopify_identify_customer(
            order_id=order_id or kwargs.get("order_id"),
            contact=contact or kwargs.get("contact"),
        )