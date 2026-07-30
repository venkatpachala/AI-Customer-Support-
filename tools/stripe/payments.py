from typing import Any, Dict
from pydantic import BaseModel, Field

from tools.base.tool import BaseTool
from tools.base.context import ToolContext
from tools.base.rate_limit import TokenBucketRateLimiter
from tools.base.retry import RetryPolicy
from tools.base.exceptions import ResourceNotFoundError
from tools.stripe.client import StripeClient


class GetPaymentIntentRequest(BaseModel):
    payment_intent_id: str = Field(..., min_length=3)


class StripeGetPaymentIntent(BaseTool):
    name = "stripe_get_payment_intent"
    provider = "stripe"
    timeout_seconds = 10.0
    max_retries = 2
    idempotent = True
    request_model = GetPaymentIntentRequest

    def __init__(self):
        super().__init__(
            rate_limiter=TokenBucketRateLimiter(rate_per_sec=8, burst=16),
            retry_policy=RetryPolicy(max_retries=self.max_retries),
        )
        self.client = StripeClient(timeout_seconds=self.timeout_seconds)

    def _run(self, request: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
        pi_id = request["payment_intent_id"]
        data = self.client.get(f"/v1/payment_intents/{pi_id}", context=context)
        if not data.get("id"):
            raise ResourceNotFoundError(f"PaymentIntent not found: {pi_id}")

        return {
            "payment_intent_id": data.get("id"),
            "status": data.get("status"),
            "amount": data.get("amount"),
            "currency": data.get("currency"),
            "customer": data.get("customer"),
            "latest_charge": data.get("latest_charge"),
        }