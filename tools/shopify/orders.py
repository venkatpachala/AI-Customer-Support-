import os
import re

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from tools.base.tool import BaseTool
from tools.base.context import ToolContext
from tools.base.rate_limit import TokenBucketRateLimiter
from tools.base.retry import RetryPolicy
from tools.base.exceptions import ResourceNotFoundError, ValidationError
from observability.logging import log_event
from tools.shopify.client import ShopifyClient


class GetOrderRequest(BaseModel):
    order_id: str = Field(..., min_length=1)


def _mask_contact(value: Optional[str]) -> str:
    text = str(value or "")
    if "@" in text:
        name, _, domain = text.partition("@")
        return f"{name[:1]}***@{domain}" if name else f"***@{domain}"
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 2:
        return ("*" * (len(digits) - 2)) + digits[-2:]
    return ""


def _normalize_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert Shopify order payload into agent-friendly schema.
    """
    fulfillments = order.get("fulfillments") or []
    fulfillment_status = order.get("fulfillment_status") or "unfulfilled"

    # best-effort delivered detection
    status = "open"
    if order.get("cancelled_at"):
        status = "cancelled"
    elif any(item.get("shipment_status") == "delivered" for item in fulfillments):
        status = "delivered"
    elif fulfillment_status == "fulfilled":
        status = "fulfilled"
    elif fulfillment_status == "partial":
        status = "partially_fulfilled"

    line_items = []
    for item in order.get("line_items") or []:
        line_items.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "quantity": item.get("quantity"),
            "sku": item.get("sku"),
            "price": item.get("price"),
        })

    customer = order.get("customer") or {}

    return {
        "order_id": str(order.get("id")),
        "order_number": order.get("order_number") or order.get("name"),
        "status": status,
        "financial_status": order.get("financial_status"),
        "fulfillment_status": fulfillment_status,
        "total_price": float(order.get("total_price") or 0),
        "currency": order.get("currency") or order.get("presentment_currency") or "INR",
        "created_at": order.get("created_at"),
        "cancelled_at": order.get("cancelled_at"),
        "line_items": line_items,
        "customer": {
            "id": customer.get("id"),
            "email": customer.get("email"),
            "phone": customer.get("phone"),
            "first_name": customer.get("first_name"),
            "last_name": customer.get("last_name"),
        },
        "raw_name": order.get("name"),
        "tags": order.get("tags"),
        "note": order.get("note"),
        "fulfillments_count": len(fulfillments),
    }


_ORDER_FIELDS = """
    id name email phone createdAt cancelledAt displayFinancialStatus
    displayFulfillmentStatus totalPriceSet { shopMoney { amount currencyCode } }
    customer { id firstName lastName }
"""


def read_graphql_order(client: ShopifyClient, order_id: str, context: ToolContext,
                       timeout: float = 8.0) -> Dict[str, Any]:
    """Treat human order numbers as names, not Shopify's internal numeric IDs.

    Search results are checked for an exact match before returning any contact data.
    Carrier delivery is deliberately unknown: fulfilled does not mean delivered.
    """
    from tools.base.exceptions import ProviderUnavailableError
    if re.fullmatch(r"gid://shopify/Order/\d+", order_id):
        query = "query($id: ID!) { order(id: $id) { " + _ORDER_FIELDS + " } }"
        variables = {"id": order_id}
    else:
        if not re.fullmatch(r"#?[A-Za-z0-9_-]{1,64}", order_id):
            raise ValidationError("invalid order number")
        query = "query($query: String!) { orders(first: 2, query: $query) { nodes { " + _ORDER_FIELDS + " } } }"
        variables = {"query": 'name:"' + order_id + '"'}
    payload = client.post("/graphql.json", context=context,
                          json={"query": query, "variables": variables}, timeout=timeout)
    if payload.get("errors"):
        raise ProviderUnavailableError("Shopify order query failed; check connection scopes")
    data = payload.get("data") or {}
    if "id" in variables:
        node = data.get("order")
    else:
        matches = [n for n in (data.get("orders") or {}).get("nodes", [])
                   if str(n.get("name", "")).lstrip("#").lower() == order_id.lstrip("#").lower()]
        node = matches[0] if len(matches) == 1 else None
    if not node:
        raise ResourceNotFoundError("Order not found or not uniquely identified")
    money = (node.get("totalPriceSet") or {}).get("shopMoney") or {}
    customer = node.get("customer") or {}
    fulfillment = str(node.get("displayFulfillmentStatus") or "UNFULFILLED").lower()
    return {"id": node["id"], "name": node["name"], "order_number": node["name"],
            "financial_status": str(node.get("displayFinancialStatus") or "unknown").lower(),
            "fulfillment_status": "partial" if fulfillment == "partially_fulfilled" else fulfillment,
            "total_price": money.get("amount"), "currency": money.get("currencyCode"),
            "created_at": node.get("createdAt"), "cancelled_at": node.get("cancelledAt"),
            "customer": {"id": customer.get("id"), "first_name": customer.get("firstName"),
                         "last_name": customer.get("lastName"), "email": node.get("email"),
                         "phone": node.get("phone")}}


class ShopifyGetOrder(BaseTool):
    name = "shopify_get_order"
    provider = "shopify"
    timeout_seconds = 8.0
    max_retries = 2
    idempotent = True
    request_model = GetOrderRequest

    def __init__(self):
        super().__init__(
            rate_limiter=TokenBucketRateLimiter(rate_per_sec=5, burst=10),
            retry_policy=RetryPolicy(max_retries=self.max_retries),
        )
        self.client = ShopifyClient(timeout_seconds=self.timeout_seconds)

    def _run(self, request: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
        order_id = str(request.get("order_id", "")).strip()
        if not order_id:
            raise ValidationError("order_id is required")

        from controlplane.mode import current_tools_mode

        tools_mode = current_tools_mode()

        def mock_order():
            return {
                "order_id": order_id,
                "order_number": order_id,
                "status": "delivered",
                "financial_status": "paid",
                "fulfillment_status": "fulfilled",
                "total_price": 500.0,
                "currency": "INR",
                "created_at": None,
                "cancelled_at": None,
                "line_items": [],
                "customer": {},
                "raw_name": f"#{order_id}",
                "tags": "",
                "note": "mock_fallback",
                "fulfillments_count": 0,
                "mock": True,
            }

        if tools_mode != "live":
            return mock_order()

        from controlplane.credentials import shopify_for_tenant
        from tools.base.exceptions import BusinessRuleError

        creds = shopify_for_tenant(context.tenant_id)
        client = self.client
        if creds:
            client = ShopifyClient(
                timeout_seconds=self.timeout_seconds,
                token=creds["token"],
                domain=creds["domain"],
            )
        elif __import__("controlplane.settings", fromlist=["production"]).production() or os.getenv("TOOLS_MODE", "mock").strip().lower() != "live":
            raise BusinessRuleError("shopify credential is not stored for this tenant")

        try:
            order = read_graphql_order(client, order_id, context, self.timeout_seconds)
            normalized = _normalize_order(order)
            customer = order.get("customer") or {}
            shipping = {}
            log_event(
                "shopify_order_loaded",
                context.request_id,
                node="tool",
                data={
                    "order_id": str(order.get("id") or order_id),
                    "email": _mask_contact(customer.get("email")),
                    "phone": _mask_contact(customer.get("phone") or shipping.get("phone")),
                },
            )
            return normalized

        except Exception as e:
            msg = str(e).lower()
            # A live authentication failure is never converted into fictitious data.
            if "unauthorized" in msg or "invalid api key" in msg or "authentication" in msg:
                from tools.base.exceptions import AuthenticationError
                raise AuthenticationError("Shopify connection needs to be reconnected") from e
            raise

        return _normalize_order(order)
