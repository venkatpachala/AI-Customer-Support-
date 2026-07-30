from tools.registry import TOOL_REGISTRY
from tools.health import HealthTool
from tools.shopify.orders import ShopifyGetOrder
from tools.stripe.refunds import StripeCreateRefund, StripeGetRefund
from tools.stripe.payments import StripeGetPaymentIntent
from tools.gmail.send import GmailSendEmail
from tools.gmail.escalation import GmailSendEscalation


def register_default_tools():
    TOOL_REGISTRY.register(HealthTool())
    TOOL_REGISTRY.register(ShopifyGetOrder())
    TOOL_REGISTRY.register(StripeCreateRefund())
    TOOL_REGISTRY.register(StripeGetRefund())
    TOOL_REGISTRY.register(StripeGetPaymentIntent())
    TOOL_REGISTRY.register(GmailSendEmail())
    TOOL_REGISTRY.register(GmailSendEscalation())