import hashlib
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, validator

from tools.base.tool import BaseTool
from tools.base.context import ToolContext
from tools.base.response import ToolResponse
from tools.base.rate_limit import TokenBucketRateLimiter
from tools.base.retry import RetryPolicy
from tools.base.exceptions import ValidationError, BusinessRuleError, ResourceNotFoundError
from tools.stripe.client import StripeClient


class CreateRefundRequest(BaseModel):
    order_id: str = Field(..., min_length=1)
    amount: int = Field(..., gt=0, description="Amount in minor units, e.g. paise/cents")
    currency: str = Field(default="inr")
    payment_intent_id: Optional[str] = None
    charge_id: Optional[str] = None
    reason: str = Field(default="requested_by_customer")
    high_value_limit: int = Field(default=200000, description="Minor units; 200000 = ₹2000 if INR paise")
    require_approval_above_limit: bool = True

    @validator("currency")
    def currency_lower(cls, v: str) -> str:
        return v.lower()

    @validator("reason")
    def validate_reason(cls, v: str) -> str:
        allowed = {
            "duplicate",
            "fraudulent",
            "requested_by_customer",
        }
        if v not in allowed:
            # Stripe accepts only specific reasons; keep safe default
            return "requested_by_customer"
        return v


def build_idempotency_key(
    tenant_id: str,
    case_id: Optional[str],
    order_id: str,
    amount: int,
    currency: str,
) -> str:
    raw = f"{tenant_id}:{case_id or 'no_case'}:{order_id}:{amount}:{currency}:refund"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_refund(refund: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "refund_id": refund.get("id"),
        "status": refund.get("status"),  # succeeded | pending | failed | canceled | requires_action
        "amount": refund.get("amount"),
        "currency": refund.get("currency"),
        "reason": refund.get("reason"),
        "payment_intent": refund.get("payment_intent"),
        "charge": refund.get("charge"),
        "created": refund.get("created"),
    }


class StripeCreateRefund(BaseTool):
    """
    Creates a Stripe refund.

    Notes:
    - amount is in minor units (paise for INR, cents for USD)
    - high-value can return requires_approval without calling Stripe
    - idempotency key protects against duplicate refunds
    """

    name = "stripe_refund"
    provider = "stripe"
    timeout_seconds = 15.0
    max_retries = 3
    idempotent = True
    request_model = CreateRefundRequest

    def __init__(self):
        super().__init__(
            rate_limiter=TokenBucketRateLimiter(rate_per_sec=5, burst=10),
            retry_policy=RetryPolicy(max_retries=self.max_retries),
        )
        self.client = StripeClient(timeout_seconds=self.timeout_seconds)

    def _run(self, request: Dict[str, Any], context: ToolContext):
        order_id = request["order_id"]
        amount = int(request["amount"])
        currency = request.get("currency", "inr")
        reason = request.get("reason", "requested_by_customer")
        payment_intent_id = request.get("payment_intent_id")
        charge_id = request.get("charge_id")
        high_value_limit = int(request.get("high_value_limit", 200000))
        require_approval_above_limit = bool(request.get("require_approval_above_limit", True))

        if not payment_intent_id and not charge_id:
            # In a full system, resolve from order mapping DB.
            # For now fail clearly if neither is provided.
            raise ValidationError(
                "payment_intent_id or charge_id is required for Stripe refunds"
            )

        # Safety gate: high value refund can require approval before money movement
        if require_approval_above_limit and amount >= high_value_limit:
            return ToolResponse.ok(
                provider=self.provider,
                operation=self.name,
                status="requires_approval",
                data={
                    "status": "requires_approval",
                    "order_id": order_id,
                    "amount": amount,
                    "currency": currency,
                    "message": f"Refund of {amount} {currency} requires manual approval",
                },
                latency_ms=0.0,
            )

        form_data: Dict[str, Any] = {
            "amount": str(amount),
            "reason": reason,
        }
        if payment_intent_id:
            form_data["payment_intent"] = payment_intent_id
        if charge_id:
            form_data["charge"] = charge_id

        # helpful metadata for audit
        form_data["metadata[order_id]"] = order_id
        form_data["metadata[tenant_id]"] = context.tenant_id
        if context.case_id:
            form_data["metadata[case_id]"] = context.case_id
        if context.customer_id:
            form_data["metadata[customer_id]"] = context.customer_id

        idem_key = build_idempotency_key(
            tenant_id=context.tenant_id,
            case_id=context.case_id,
            order_id=order_id,
            amount=amount,
            currency=currency,
        )

        refund = self.client.post_form(
            "/v1/refunds",
            context=context,
            form_data=form_data,
            idempotency_key=idem_key,
            timeout=self.timeout_seconds,
        )

        # Stripe error objects sometimes come with HTTP 200? usually non-2xx handled by HttpClient.
        if refund.get("error"):
            err = refund["error"]
            code = err.get("code") or "stripe_error"
            message = err.get("message") or "Stripe refund failed"

            if code in {"charge_already_refunded", "refund_already_canceled"}:
                raise BusinessRuleError(message)
            if code in {"resource_missing"}:
                raise ResourceNotFoundError(message)
            raise BusinessRuleError(f"{code}: {message}")

        normalized = _normalize_refund(refund)
        normalized["order_id"] = order_id
        normalized["idempotency_key"] = idem_key

        return normalized


class GetRefundRequest(BaseModel):
    refund_id: str = Field(..., min_length=3)


class StripeGetRefund(BaseTool):
    name = "stripe_get_refund"
    provider = "stripe"
    timeout_seconds = 10.0
    max_retries = 2
    idempotent = True
    request_model = GetRefundRequest

    def __init__(self):
        super().__init__(
            rate_limiter=TokenBucketRateLimiter(rate_per_sec=8, burst=16),
            retry_policy=RetryPolicy(max_retries=self.max_retries),
        )
        self.client = StripeClient(timeout_seconds=self.timeout_seconds)

    def _run(self, request: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
        refund_id = request["refund_id"]
        data = self.client.get(f"/v1/refunds/{refund_id}", context=context)
        if not data.get("id"):
            raise ResourceNotFoundError(f"Refund not found: {refund_id}")
        return _normalize_refund(data)