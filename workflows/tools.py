"""Resolve a tool by name and call it. Workflows do not construct API clients."""
from __future__ import annotations

import os
from typing import Any, Dict

from tools.base.context import ToolContext

_RETRYABLE = {"timeout", "rate_limit", "unavailable", "temporarily_unavailable", "429", "503"}
_AUTH_ERRORS = {"unauthorized", "forbidden", "auth", "authentication", "not_authenticated"}


def invoke_tool(registry: Any, name: str, params: Dict[str, Any], *, request_id: str, tenant_id: str, customer_id: str, case_id: str, session_id: str | None) -> Dict[str, Any]:
    tool = _lookup(registry, name)
    if tool is None:
        return _missing_tool(name, params)

    context = ToolContext(
        request_id=request_id or "workflow",
        tenant_id=tenant_id,
        customer_id=customer_id,
        case_id=case_id,
        session_id=session_id,
    )
    try:
        if callable(tool) and not hasattr(tool, "execute"):
            raw = tool(params)
        else:
            try:
                raw = tool.execute(params, context)
            except TypeError:
                raw = tool.execute(params)
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "error_code": getattr(exc, "code", None) or "tool_exception",
            "retryable": bool(getattr(exc, "retryable", False)),
        }
    return _normalize(raw)


def is_retryable(result: Dict[str, Any]) -> bool:
    if result.get("retryable") is True:
        return True
    code = str(result.get("error_code") or "").lower()
    return code in _RETRYABLE


def is_auth_error(result: Dict[str, Any]) -> bool:
    code = str(result.get("error_code") or "").lower()
    if code in _AUTH_ERRORS:
        return True
    text = str(result.get("error") or result.get("error_message") or "").lower()
    return "unauthorized" in text or "forbidden" in text


def _lookup(registry: Any, name: str) -> Any:
    if registry is None:
        return None
    getter = getattr(registry, "get", None)
    if callable(getter):
        return getter(name)
    if isinstance(registry, dict):
        return registry.get(name)
    return None


def _missing_tool(name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    mode = os.getenv("TOOLS_MODE", "mock").strip().lower()
    if mode == "mock" and name == "shopify_get_order":
        order_id = str(params.get("order_id") or "")
        return {
            "status": "success",
            "mock": True,
            "data": {
                "order_id": order_id,
                "status": "delivered",
                "financial_status": "paid",
                "currency": "INR",
            },
        }
    if mode == "mock" and name == "stripe_refund":
        return {
            "status": "success",
            "mock": True,
            "data": {
                "refund_id": "re_mock",
                "order_id": params.get("order_id"),
                "amount": params.get("amount"),
                "idempotency_key": params.get("idempotency_key"),
                "mock": True,
            },
        }
    return {
        "status": "error",
        "error": f"Tool '{name}' not registered",
        "error_code": "tool_not_registered",
        "retryable": False,
    }


def _normalize(raw: Any) -> Dict[str, Any]:
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    elif hasattr(raw, "dict"):
        raw = raw.dict()
    if not isinstance(raw, dict):
        return {"status": "success", "data": {"value": raw}}
    result = dict(raw)
    if "status" not in result:
        result["status"] = "success" if result.get("success", True) else "error"
    if result.get("error") is None and result.get("error_message"):
        result["error"] = result["error_message"]
    return result
