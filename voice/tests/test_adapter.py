"""
voice/tests/test_adapter.py — Unit tests for SupportRuntimeAdapter.

Tests:
  - Greeting short-circuit (no runtime call)
  - Empty transcript guard
  - Context building (channel=voice, correct tenant_id/customer_id)
  - Session write-back (auth_level, order_id, needs_identity)
  - TTS text shaping (_shape_for_tts)
  - _ensure_response_text fallbacks
"""
import pytest
from unittest.mock import MagicMock, patch

from runtime.response import RuntimeResponse
from voice.adapter import SupportRuntimeAdapter
from voice.context import VoiceSession


def _mock_runtime(response_text="Test response from LangGraph."):
    """Create a mock SupportRuntime that returns a given response."""
    runtime = MagicMock()
    runtime.handle.return_value = RuntimeResponse(
        response=response_text,
        confidence=0.9,
        session_id="sess_test",
        case_id="case_001",
        auth_level="anonymous",
        intent="test_intent",
    )
    return runtime


def _make_session(**kwargs) -> VoiceSession:
    defaults = dict(
        tenant_id="zepto",
        customer_id="test_customer",
        auth_level="anonymous",
    )
    defaults.update(kwargs)
    return VoiceSession(**defaults)


class TestGreetingShortCircuit:
    """Greetings should NOT hit SupportRuntime."""

    @pytest.mark.parametrize("greeting", [
        "hi", "hello", "hey", "Hi!", "Hello!", "Hey!",
        "good morning", "good afternoon", "good evening",
    ])
    def test_greeting_returns_without_runtime(self, greeting):
        runtime = _mock_runtime()
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session()

        result = adapter.handle_transcript_sync(greeting, session)

        runtime.handle.assert_not_called()
        assert result.response
        assert result.intent == "greeting"

    def test_non_greeting_hits_runtime(self):
        runtime = _mock_runtime()
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session()

        adapter.handle_transcript_sync("I want to return my order", session)
        runtime.handle.assert_called_once()


class TestEmptyTranscriptGuard:
    def test_empty_string_returns_error_message(self):
        runtime = _mock_runtime()
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session()

        result = adapter.handle_transcript_sync("", session)

        runtime.handle.assert_not_called()
        assert "didn't catch that" in result.response.lower()

    def test_whitespace_only_returns_error_message(self):
        runtime = _mock_runtime()
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session()

        result = adapter.handle_transcript_sync("   ", session)
        runtime.handle.assert_not_called()


class TestContextBuilding:
    def test_channel_is_voice(self):
        runtime = _mock_runtime()
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session(tenant_id="zepto", customer_id="cust_xyz")

        adapter.handle_transcript_sync("I need help", session)

        call_ctx = runtime.handle.call_args[0][0]
        assert call_ctx.channel == "voice"

    def test_tenant_id_propagated(self):
        runtime = _mock_runtime()
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session(tenant_id="zepto")

        adapter.handle_transcript_sync("I need help", session)
        ctx = runtime.handle.call_args[0][0]
        assert ctx.tenant_id == "zepto"

    def test_customer_id_propagated(self):
        runtime = _mock_runtime()
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session(customer_id="cust_456")

        adapter.handle_transcript_sync("I need help", session)
        ctx = runtime.handle.call_args[0][0]
        assert ctx.customer_id == "cust_456"

    def test_session_id_propagated(self):
        runtime = _mock_runtime()
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session(session_id="sess_abc123")

        adapter.handle_transcript_sync("I need help", session)
        ctx = runtime.handle.call_args[0][0]
        assert ctx.session_id == "sess_abc123"

    def test_auth_level_propagated(self):
        runtime = _mock_runtime()
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session(auth_level="identified")
        session.normalize_auth()

        adapter.handle_transcript_sync("I need help", session)
        ctx = runtime.handle.call_args[0][0]
        assert ctx.auth.auth_level == "identified"


class TestSessionWriteback:
    def test_session_id_written_back(self):
        runtime = MagicMock()
        runtime.handle.return_value = RuntimeResponse(
            response="OK", session_id="sess_from_runtime"
        )
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session(session_id=None)

        adapter.handle_transcript_sync("I need help", session)
        assert session.session_id == "sess_from_runtime"

    def test_case_id_written_back(self):
        runtime = MagicMock()
        runtime.handle.return_value = RuntimeResponse(
            response="OK", session_id="s1", case_id="case_99"
        )
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session()

        adapter.handle_transcript_sync("I need help", session)
        assert session.case_id == "case_99"

    def test_auth_level_written_back(self):
        runtime = MagicMock()
        runtime.handle.return_value = RuntimeResponse(
            response="Thanks", auth_level="identified"
        )
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session(auth_level="anonymous")

        adapter.handle_transcript_sync("My order is 12345", session)
        assert session.auth_level == "identified"

    def test_order_id_written_back(self):
        runtime = MagicMock()
        runtime.handle.return_value = RuntimeResponse(
            response="Checking your order",
            order_id="12345",
            auth_level="identified",
        )
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session()

        adapter.handle_transcript_sync("My order is 12345", session)
        assert session.pending_order_id == "12345"
        assert "12345" in session.verified_order_ids

    def test_needs_identity_written_back(self):
        runtime = MagicMock()
        resp = RuntimeResponse(response="Please verify")
        resp.needs_identity = True
        resp.raw = {"needs_identity": True}
        runtime.handle.return_value = resp
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session()

        adapter.handle_transcript_sync("Return my order", session)
        assert session.needs_identity is True

    def test_issue_type_written_back(self):
        runtime = MagicMock()
        resp = RuntimeResponse(response="I can help with that", intent="return_request")
        resp.raw = {}
        runtime.handle.return_value = resp
        adapter = SupportRuntimeAdapter(runtime)
        session = _make_session()

        adapter.handle_transcript_sync("I want to return my order", session)
        assert session.issue_type == "return_request"


class TestTTSShaping:
    def test_shape_strips_email_signoff(self):
        runtime = _mock_runtime()
        adapter = SupportRuntimeAdapter(runtime)

        text = "Sure, I can help. Best regards, the team."
        shaped = adapter._shape_for_tts(text)
        assert "Best regards" not in shaped
        assert "Sure" in shaped

    def test_shape_trims_to_two_sentences(self):
        runtime = _mock_runtime()
        adapter = SupportRuntimeAdapter(runtime)

        text = "Sentence one. Sentence two. Sentence three. Sentence four."
        shaped = adapter._shape_for_tts(text)
        # Should keep at most 2 sentences
        sentences = [s for s in shaped.split(". ") if s.strip()]
        assert len(sentences) <= 2

    def test_shape_empty_stays_empty(self):
        adapter = SupportRuntimeAdapter(MagicMock())
        assert adapter._shape_for_tts("") == ""
        assert adapter._shape_for_tts(None) == ""


class TestEnsureResponseText:
    def test_uses_response_field_when_present(self):
        adapter = SupportRuntimeAdapter(MagicMock())
        result = RuntimeResponse(response="Hello from runtime")
        text = adapter._ensure_response_text(result, "hello")
        assert text == "Hello from runtime"

    def test_falls_back_to_identity_challenge(self):
        adapter = SupportRuntimeAdapter(MagicMock())
        result = RuntimeResponse(response="")
        result.raw = {"identity_challenge": {"message": "Please verify your order."}}
        text = adapter._ensure_response_text(result, "test")
        assert "verify" in text.lower()

    def test_falls_back_to_generic_when_empty(self):
        adapter = SupportRuntimeAdapter(MagicMock())
        result = RuntimeResponse(response="")
        result.raw = {}
        result.error = None
        result.identity_blocked = False
        result.needs_identity = False
        text = adapter._ensure_response_text(result, "test")
        assert len(text) > 0  # some fallback always returned
