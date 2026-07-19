from typing import Dict, Callable, Any
from pydantic import BaseModel
from tools.shopify import get_order_details, initiate_return
from tools.stripe import process_refund

class ToolSpec(BaseModel):
    name: str
    description: str
    function: Callable
    required_params: list[str] = []
    timeout: int = 15
    max_retries: int = 2
    idempotent: bool = True

# Central Tool Registry
TOOL_REGISTRY: Dict[str, ToolSpec] = {
    "shopify_get_order": ToolSpec(
        name="shopify_get_order",
        description="Fetch order details from Shopify",
        function=get_order_details,
        required_params=["order_id"],
        timeout=10,
        max_retries=2,
        idempotent=True
    ),
    "shopify_initiate_return": ToolSpec(
        name="shopify_initiate_return",
        description="Initiate a return for an order",
        function=initiate_return,
        required_params=["order_id"],
        timeout=15,
        max_retries=1,
        idempotent=False
    ),
    "stripe_refund": ToolSpec(
        name="stripe_refund",
        description="Process a refund via Stripe",
        function=process_refund,
        required_params=["order_id"],
        timeout=20,
        max_retries=1,
        idempotent=False
    ),
    "rag_search": ToolSpec(
        name="rag_search",
        description="Search company policy",
        function=lambda query: {"message": "Policy retrieved via RAG"},
        required_params=[],
        timeout=10,
        max_retries=1,
        idempotent=True
    )
}