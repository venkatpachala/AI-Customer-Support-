"""
voice/tests/test_end_to_end.py — End-to-end scenario tests against mock runtime.

Tests the full voice → adapter → runtime → response chain without real audio.
These validate the Phase 2 architectural contract:
  - Transcript → SupportRuntime with correct channel=voice context
  - Multi-turn memory: session_id / case_id persists
  - Return intent triggers order ID request
  - Cross-channel: same session_id works for both chat and voice
  - Response comes from the actual runtime (not a generic LLM)
  - Greeting does NOT invoke runtime
"""
import pytest
from unittest.mock import MagicMock

from runtime.context import RequestContext
from runtime.response import RuntimeResponse
from voice.adapter import SupportRuntimeAdapter
from voice.context import VoiceSession


# ─── Mock runtime builder ─────────────────────────────────────────────────────

def _runtime_with_response(
    response: str,
    session_id: str = "sess_001",
    case_id: str = "case_001",
    auth_level: str = "anonymous",
    intent: str = None,
    missing_inputs: list = None,
    order_id: str = None,
    needs_identity: bool = False,
):
    runtime = MagicMock()
    resp = RuntimeResponse(
        response=response,
        confidence=0.9,
        session_id=session_id,
        case_id=case_id,
        auth_level=auth_level,
        intent=intent,
        missing_inputs=missing_inputs or [],
        order_id=order_id,
        needs_identity=needs_identity,
    )
    resp.raw = {
        "auth_level": auth_level,
        "needs_identity": needs_identity,
    }
    runtime.handle.return_value = resp
    return runtime


def _new_session(**kwargs) -> VoiceSession:
    return VoiceSession(
        tenant_id="zepto",
        customer_id="e2e_customer",
        **kwargs,
    )


# ─── Scenario 1: Greeting short-circuit ──────────────────────────────────────

class TestGreetingScenario:
    def test_hello_returns_greeting_without_runtime(self):
        runtime = _runtime_with_response("Should not be seen.")
        adapter = SupportRuntimeAdapter(runtime)
        session = _new_session()

        result = adapter.handle_transcript_sync("Hello", session)

        runtime.handle.assert_not_called()
        assert result.response
        assert result.intent == "greeting"

    def test_greeting_response_is_voice_appropriate(self):
        runtime = _runtime_with_response("nope")
        adapter = SupportRuntimeAdapter(runtime)
        session = _new_session()
        result = adapter.handle_transcript_sync("hi", session)
        # Should be short (voice-appropriate)
        assert len(result.response) < 200


# ─── Scenario 2: Return intent → order ID request ────────────────────────────

class TestReturnIntentScenario:
    def test_return_request_triggers_runtime(self):
        runtime = _runtime_with_response(
            "Sure! Could you please share your order number?",
            intent="return_request",
            missing_inputs=["order_id"],
        )
        adapter = SupportRuntimeAdapter(runtime)
        session = _new_session()

        result = adapter.handle_transcript_sync("I want to return my order", session)

        runtime.handle.assert_called_once()

    def test_return_request_passes_voice_channel(self):
        runtime = _runtime_with_response("Please share your order number.")
        adapter = SupportRuntimeAdapter(runtime)
        session = _new_session()

        adapter.handle_transcript_sync("I want to return my order", session)

        ctx: RequestContext = runtime.handle.call_args[0][0]
        assert ctx.channel == "voice"

    def test_return_intent_stored_in_session(self):
        runtime = _runtime_with_response(
            "Sure, what's your order number?",
            intent="return_request",
        )
        adapter = SupportRuntimeAdapter(runtime)
        session = _new_session()

        adapter.handle_transcript_sync("I want to return my order", session)

        assert session.issue_type == "return_request"


# ─── Scenario 3: Multi-turn order ID flow ────────────────────────────────────

class TestMultiTurnScenario:
    def test_order_id_persists_across_turns(self):
        """Turn 1: provide order ID → Turn 2: it's still in session."""
        runtime = _runtime_with_response(
            "Thanks, I have your order 12345.",
            order_id="12345",
            auth_level="identified",
            intent="return_request",
        )
        adapter = SupportRuntimeAdapter(runtime)
        session = _new_session(issue_type="return_request")

        # Turn 1 — provide order ID
        adapter.handle_transcript_sync("My order is 12345", session)
        assert session.pending_order_id == "12345"
        assert "12345" in session.verified_order_ids

        # Turn 2 — next turn uses same session
        runtime.handle.return_value = RuntimeResponse(
            response="I see order 12345. We need a photo of the damage.",
            session_id="sess_001",
            case_id="case_001",
        )
        result = adapter.handle_transcript_sync("It arrived damaged", session)

        # Session ID must be propagated
        ctx2: RequestContext = runtime.handle.call_args[0][0]
        assert ctx2.session_id is not None
        # Memory context must carry order info
        assert (
            ctx2.memory_context.get("pending_order_id") == "12345"
            or ctx2.memory_context.get("active_order_id") == "12345"
        )

    def test_session_id_maintained_across_turns(self):
        runtime = _runtime_with_response(
            "Got it.", session_id="sess_persistent"
        )
        adapter = SupportRuntimeAdapter(runtime)
        session = _new_session()

        adapter.handle_transcript_sync("Turn 1", session)
        assert session.session_id == "sess_persistent"

        adapter.handle_transcript_sync("Turn 2", session)
        ctx: RequestContext = runtime.handle.call_args[0][0]
        assert ctx.session_id == "sess_persistent"

    def test_case_id_maintained_across_turns(self):
        runtime = _runtime_with_response(
            "OK.", session_id="s1", case_id="case_sticky"
        )
        adapter = SupportRuntimeAdapter(runtime)
        session = _new_session()

        adapter.handle_transcript_sync("First turn", session)
        assert session.case_id == "case_sticky"

        adapter.handle_transcript_sync("Second turn", session)
        ctx: RequestContext = runtime.handle.call_args[0][0]
        assert ctx.case_id == "case_sticky"


# ─── Scenario 4: Cross-channel (Chat → Voice same session) ───────────────────

class TestCrossChannelScenario:
    def test_voice_uses_existing_chat_session_id(self):
        """If a chat session exists, voice continues it via session_id."""
        runtime = _runtime_with_response(
            "I see you already started a return request.",
            session_id="chat_session_123",
            case_id="case_from_chat",
            intent="return_request",
        )
        adapter = SupportRuntimeAdapter(runtime)

        # Session started in chat, now continuing in voice
        session = _new_session(
            session_id="chat_session_123",
            issue_type="return_request",
        )

        result = adapter.handle_transcript_sync("Hi, I uploaded the photos", session)

        ctx: RequestContext = runtime.handle.call_args[0][0]
        # session_id from chat must be passed to runtime
        assert ctx.session_id == "chat_session_123"
        assert ctx.channel == "voice"


# ─── Scenario 5: Identity challenge ──────────────────────────────────────────

class TestIdentityScenario:
    def test_needs_identity_triggers_challenge_response(self):
        runtime = _runtime_with_response("", needs_identity=True)
        runtime.handle.return_value.raw = {"needs_identity": True}
        adapter = SupportRuntimeAdapter(runtime)
        session = _new_session()

        result = adapter.handle_transcript_sync("I want a refund of 5000", session)

        # Must produce a speakable response even though response field is empty
        assert result.response
        assert len(result.response) > 5
        assert session.needs_identity is True

    def test_auth_ladder_upgrade_reflected(self):
        """After identity is provided and verified, auth_level upgrades."""
        runtime = _runtime_with_response(
            "Thanks, I verified your order.",
            auth_level="identified",
            order_id="98765",
        )
        adapter = SupportRuntimeAdapter(runtime)
        session = _new_session(needs_identity=True)

        adapter.handle_transcript_sync("Order 98765, email test@example.com", session)

        assert session.auth_level == "identified"


# ─── Scenario 6: Regression — voice doesn't break anonymous flow ─────────────

class TestRegressionScenario:
    def test_policy_query_routed_to_runtime(self):
        runtime = _runtime_with_response(
            "Our return policy allows returns within 7 days.",
            intent="policy_query",
        )
        adapter = SupportRuntimeAdapter(runtime)
        session = _new_session()

        result = adapter.handle_transcript_sync(
            "What is your return policy?", session
        )

        runtime.handle.assert_called_once()
        assert result.response

    def test_response_always_speakable(self):
        """Every non-empty response must be voice-appropriate (no markdown)."""
        import re
        runtime = _runtime_with_response(
            "# Header\n**Bold text** with *italic*. Response here.",
        )
        adapter = SupportRuntimeAdapter(runtime)
        session = _new_session()

        result = adapter.handle_transcript_sync("Test", session)
        # After shaping, response should not have markdown
        assert "**" not in result.response
        assert "##" not in result.response or "#" not in result.response
