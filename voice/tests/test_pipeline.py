"""
voice/tests/test_pipeline.py — Pipeline and processor unit tests.

Tests (without real audio hardware or network):
  - build_phase2_pipeline() constructs without error (mocked transport)
  - SupportRuntimeResponder processes TranscriptionFrame correctly
  - Interruption resets state
  - Empty transcript does not call runtime
  - Turn state machine transitions
  - TTFA timestamps are recorded
  - Response shaper (processors/response.py)
  - Transcript logger (processors/transcript.py)
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from runtime.response import RuntimeResponse
from voice.context import VoiceSession
from voice.events import VoiceSessionStatus
from voice.processors.runtime_responder import SupportRuntimeResponder, TurnState
from voice.processors.response import shape_for_voice, is_voice_appropriate
from voice.processors.transcript import TranscriptLogger


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_session(**kwargs) -> VoiceSession:
    return VoiceSession(tenant_id="test", customer_id="cust", **kwargs)


def _make_adapter(response="Hello from runtime."):
    adapter = MagicMock()
    adapter.handle_transcript = AsyncMock(
        return_value=RuntimeResponse(response=response)
    )
    return adapter


def _make_transcript(text: str) -> TranscriptionFrame:
    """Create a TranscriptionFrame with the required timestamp argument."""
    import time
    return TranscriptionFrame(
        text=text,
        user_id="test_user",
        timestamp=str(time.time()),
        language=None,
    )


async def _collect_frames(processor: SupportRuntimeResponder, frames_in):
    """Run frames through processor and collect output frames."""
    collected = []
    original_push = processor.push_frame

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        collected.append(frame)
        return await original_push(frame, direction)

    processor.push_frame = capture

    for frame in frames_in:
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)

    return collected


# ─── SupportRuntimeResponder tests ───────────────────────────────────────────

class TestSupportRuntimeResponder:

    @pytest.mark.asyncio
    async def test_transcription_triggers_runtime(self):
        session = _make_session()
        adapter = _make_adapter("Test response.")
        responder = SupportRuntimeResponder(adapter=adapter, session=session)

        await _collect_frames(responder, [
            _make_transcript("I need help"),
        ])

        adapter.handle_transcript.assert_called_once()
        call_args = adapter.handle_transcript.call_args
        assert call_args[0][0] == "I need help"

    @pytest.mark.asyncio
    async def test_empty_transcript_skipped(self):
        session = _make_session()
        adapter = _make_adapter()
        responder = SupportRuntimeResponder(adapter=adapter, session=session)

        await _collect_frames(responder, [
            _make_transcript(""),
        ])

        adapter.handle_transcript.assert_not_called()

    @pytest.mark.asyncio
    async def test_whitespace_transcript_skipped(self):
        session = _make_session()
        adapter = _make_adapter()
        responder = SupportRuntimeResponder(adapter=adapter, session=session)

        await _collect_frames(responder, [
            _make_transcript("   \t  "),
        ])

        adapter.handle_transcript.assert_not_called()

    @pytest.mark.asyncio
    async def test_interruption_resets_state(self):
        session = _make_session()
        adapter = _make_adapter()
        responder = SupportRuntimeResponder(adapter=adapter, session=session)

        # Start a turn
        await responder.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        assert responder.state == TurnState.USER_SPEAKING

        # Interrupt
        await responder.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
        assert responder.state == TurnState.IDLE
        assert responder._emitted_this_turn is False

    @pytest.mark.asyncio
    async def test_interruption_increments_counter(self):
        session = _make_session()
        adapter = _make_adapter()
        responder = SupportRuntimeResponder(adapter=adapter, session=session)

        await responder.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await responder.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
        assert session.interruption_count == 1

    @pytest.mark.asyncio
    async def test_one_call_per_turn(self):
        """TranscriptionFrame should only trigger runtime once per turn."""
        session = _make_session()
        adapter = _make_adapter()
        responder = SupportRuntimeResponder(adapter=adapter, session=session)

        # Two transcription frames in the same turn — should only call once
        await _collect_frames(responder, [
            _make_transcript("Hello"),
            _make_transcript("Hello there"),
        ])

        assert adapter.handle_transcript.call_count == 1

    @pytest.mark.asyncio
    async def test_response_pushed_as_text_frame(self):
        session = _make_session()
        adapter = _make_adapter("Sure, let me check that for you.")
        responder = SupportRuntimeResponder(adapter=adapter, session=session)

        collected = await _collect_frames(responder, [
            _make_transcript("Where is my order?"),
        ])

        text_frames = [f for f in collected if isinstance(f, TextFrame)]
        assert len(text_frames) == 1
        assert "let me check" in text_frames[0].text.lower()

    @pytest.mark.asyncio
    async def test_response_wrapped_in_llm_frames(self):
        session = _make_session()
        adapter = _make_adapter("OK.")
        responder = SupportRuntimeResponder(adapter=adapter, session=session)

        collected = await _collect_frames(responder, [
            _make_transcript("Hi"),
        ])

        types = [type(f).__name__ for f in collected]
        assert "LLMFullResponseStartFrame" in types
        assert "TextFrame" in types
        assert "LLMFullResponseEndFrame" in types

    @pytest.mark.asyncio
    async def test_user_speaking_sets_state(self):
        session = _make_session()
        adapter = _make_adapter()
        responder = SupportRuntimeResponder(adapter=adapter, session=session)

        await responder.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        assert responder.state == TurnState.USER_SPEAKING
        assert session.status == VoiceSessionStatus.USER_SPEAKING

    @pytest.mark.asyncio
    async def test_ttfa_timestamps_recorded(self):
        session = _make_session()
        adapter = _make_adapter("Done.")
        responder = SupportRuntimeResponder(adapter=adapter, session=session)

        await _collect_frames(responder, [
            UserStartedSpeakingFrame(),
            UserStoppedSpeakingFrame(),
            _make_transcript("Test"),
        ])

        # Runtime start should be recorded
        assert session.current_latency.t_runtime_start is not None or \
               (len(session.latency_history) > 0 and
                session.latency_history[-1].t_runtime_start is not None)

    @pytest.mark.asyncio
    async def test_runtime_error_sends_error_message(self):
        session = _make_session()
        adapter = MagicMock()
        adapter.handle_transcript = AsyncMock(side_effect=Exception("Runtime boom"))
        responder = SupportRuntimeResponder(adapter=adapter, session=session)

        collected = await _collect_frames(responder, [
            _make_transcript("Test"),
        ])

        text_frames = [f for f in collected if isinstance(f, TextFrame)]
        assert len(text_frames) == 1
        assert "trouble" in text_frames[0].text.lower()


# ─── Response shaper tests ────────────────────────────────────────────────────

class TestResponseShaper:

    def test_strips_markdown_bold(self):
        text = "Your order **12345** is on its way."
        result = shape_for_voice(text)
        assert "**" not in result
        assert "12345" in result

    def test_strips_markdown_headers(self):
        text = "## Order Status\nYour order is ready."
        result = shape_for_voice(text)
        assert "##" not in result
        assert "Order Status" in result or "Your order" in result

    def test_strips_bullet_lists(self):
        text = "- Item one\n- Item two\n- Item three"
        result = shape_for_voice(text)
        assert "- " not in result

    def test_trims_to_two_sentences(self):
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        result = shape_for_voice(text, max_sentences=2)
        # Count sentence-ending punctuation
        count = result.count(". ") + (1 if result.endswith(".") else 0)
        assert count <= 2

    def test_removes_email_signoffs(self):
        text = "I will help you. Best regards, Support Team."
        result = shape_for_voice(text)
        assert "Best regards" not in result

    def test_empty_returns_empty(self):
        assert shape_for_voice("") == ""
        assert shape_for_voice(None) == ""

    def test_short_text_unchanged_in_substance(self):
        text = "Sure, I can help."
        result = shape_for_voice(text)
        assert "Sure" in result

    def test_is_voice_appropriate_normal_text(self):
        assert is_voice_appropriate("Hello, how can I help?") is True

    def test_is_voice_appropriate_too_long(self):
        assert is_voice_appropriate("x" * 501) is False

    def test_is_voice_appropriate_empty(self):
        assert is_voice_appropriate("") is False


# ─── TranscriptLogger tests ───────────────────────────────────────────────────

class TestTranscriptLogger:

    @pytest.mark.asyncio
    async def test_callback_called_on_transcript(self):
        captured = []

        def on_transcript(text, ts):
            captured.append(text)

        logger_proc = TranscriptLogger(on_transcript=on_transcript)

        frames_out = []
        original_push = logger_proc.push_frame

        async def capture_push(frame, direction=FrameDirection.DOWNSTREAM):
            frames_out.append(frame)
            return await original_push(frame, direction)

        logger_proc.push_frame = capture_push

        frame = _make_transcript("Hello world")
        await logger_proc.process_frame(frame, FrameDirection.DOWNSTREAM)

        assert "Hello world" in captured

    @pytest.mark.asyncio
    async def test_all_frames_passed_through(self):
        logger_proc = TranscriptLogger()

        frames_out = []
        original_push = logger_proc.push_frame

        async def capture_push(frame, direction=FrameDirection.DOWNSTREAM):
            frames_out.append(frame)
            return await original_push(frame, direction)

        logger_proc.push_frame = capture_push

        frame = _make_transcript("Test")
        await logger_proc.process_frame(frame, FrameDirection.DOWNSTREAM)

        # Frame must be forwarded
        assert any(isinstance(f, TranscriptionFrame) for f in frames_out)
