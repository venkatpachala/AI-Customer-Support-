"""
voice/processors/thinking_utterance.py — "Let me check that for you." pre-tool phrases.

When a voice turn requires a tool call (Shopify, Stripe) the runtime may take 1–4 seconds.
Rather than silence, we immediately emit a natural thinking phrase to TTS as soon as we know
a tool is needed, before dispatching to SupportRuntime.

The runtime_responder reads THINKING_PHRASE_MAP and decides whether to push a thinking phrase.
The threshold is >1s expected wait (any tool-requiring intent).
"""
from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Intent → natural spoken phrase while runtime processes
# ---------------------------------------------------------------------------

THINKING_PHRASE_MAP: dict[str, str] = {
    # Order lookups
    "track": "Let me check your order status right now.",
    "order_status": "Let me pull up your order details.",

    # Return flows
    "return": "I'm processing your return request.",
    "damaged_return": "Let me look into your damaged item return.",

    # Refund
    "refund": "Let me verify your refund eligibility.",

    # Cancellation
    "cancel": "Let me check if your order is still eligible for cancellation.",

    # Identity challenge (not a tool, but takes time)
    "identity_challenge": "Let me verify your details.",

    # Default for any unrecognized intent that requires a tool
    "default": "One moment — let me check that for you.",
}

# Phrases for when we know which tool is running
TOOL_PHRASE_MAP: dict[str, str] = {
    "shopify_get_order": "Let me pull up that order.",
    "shopify_initiate_return": "I'm initiating the return for you.",
    "shopify_cancel_order": "Let me check if this order can be cancelled.",
    "stripe_refund": "Let me verify the refund with our payments system.",
    "search_policy": "Let me check our policy on that.",
}


def get_thinking_phrase(
    intent: Optional[str] = None,
    tool_name: Optional[str] = None,
    requires_tool: bool = False,
) -> Optional[str]:
    """
    Return the appropriate thinking phrase for TTS, or None if no phrase is needed.

    Called before dispatching to SupportRuntime when the turn is expected to invoke a tool.

    Args:
        intent: Classified intent from supervisor ("track", "return", etc.)
        tool_name: Specific tool name if known ("shopify_get_order", etc.)
        requires_tool: Whether this turn will invoke a tool

    Returns:
        Spoken phrase string, or None if no phrase is needed (e.g. pure policy questions answer instantly)
    """
    if not requires_tool:
        return None

    if tool_name and tool_name in TOOL_PHRASE_MAP:
        return TOOL_PHRASE_MAP[tool_name]

    if intent and intent in THINKING_PHRASE_MAP:
        return THINKING_PHRASE_MAP[intent]

    if requires_tool:
        return THINKING_PHRASE_MAP["default"]

    return None


def should_use_thinking_phrase(runtime_latency_threshold_ms: float = 1000.0) -> bool:
    """
    Always returns True for tool-requiring turns.
    The threshold check is handled by the caller — only use phrase for turns
    where a tool invocation is expected (latency naturally >1s).
    """
    return True
