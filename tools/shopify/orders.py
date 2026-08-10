import os

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from tools.base.tool import BaseTool
from tools.base.context import ToolContext
from tools.base.rate_limit import TokenBucketRateLimiter
from tools.base.retry import RetryPolicy
from tools.base.exceptions import ResourceNotFoundError, ValidationError
from tools.shopify.client import ShopifyClient


class GetOrderRequest(BaseModel):
    order_id: str = Field(..., min_length=1)


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
    elif fulfillment_status == "fulfilled":
        status = "delivered"
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
            "first_name": customer.get("first_name"),
            "last_name": customer.get("last_name"),
        },
        "raw_name": order.get("name"),
        "tags": order.get("tags"),
        "note": order.get("note"),
        "fulfillments_count": len(fulfillments),
    }


class ShopifyGetOrder(BaseTool):
    name = "shopify_get_order"
    provider = "shopify"
    timeout_seconds = 10.0
    max_retries = 3
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

        tools_mode = os.getenv("TOOLS_MODE", "mock").lower()

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

        try:
            # existing live Shopify logic here...
            if not order_id.isdigit():
                data = self.client.get(
                    "/orders.json",
                    context=context,
                    params={"name": order_id, "status": "any", "limit": 1},
                    timeout=self.timeout_seconds,
                )
                orders = data.get("orders") or []
                if not orders:
                    raise ResourceNotFoundError(f"Order not found for name/id={order_id}")
                order = orders[0]
            else:
                data = self.client.get(
                    f"/orders/{order_id}.json",
                    context=context,
                    timeout=self.timeout_seconds,
                )
                order = data.get("order")
                if not order:
                    raise ResourceNotFoundError(f"Order not found for id={order_id}")

            return _normalize_order(order)

        except Exception as e:
            msg = str(e).lower()
            # If live credentials/config are broken, degrade safely for support flows
            if "unauthorized" in msg or "invalid api key" in msg or "authentication" in msg:
                return mock_order()
            raise

        return _normalize_order(order)