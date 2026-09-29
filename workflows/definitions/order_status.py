"""Order status. Identity is required before the Shopify read, not before an FAQ."""
from __future__ import annotations

from workflows.definitions.common import assert_auth, fetch_order
from workflows.definitions.refund import WorkflowDefinition

ORDER_STATUS = WorkflowDefinition(
    name="order_status",
    steps=[
        ("assert_auth", assert_auth("order_status")),
        ("fetch_order", fetch_order),
    ],
)
