"""
voice/processors/runtime_responder.py — Core Pipecat frame processor.

Connects the STT output to SupportRuntime and feeds the response to TTS.

Frame flow:
  UserStartedSpeakingFrame   → reset state, mark turn start
  TranscriptionFrame (text)  → PRIMARY trigger → call SupportRuntime
  UserStoppedSpeakingFrame   → fallback trigger if text already arrived
  InterruptionFrame          → cancel current turn, reset state
  LLMMessagesAppendFrame     → typed playground support

TTFA is tracked via VoiceSession.mark_* calls.

Interruption / barge-in: Pipecat sends InterruptionFrame when VAD detects
user speech while the bot is speaking. We reset state so the new user
turn is captured cleanly.
"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Optional

from loguru import logger

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
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Optional frames — import-guarded for version compatibility
try:
    from pipecat.frames.frames import LLMMessagesAppendFrame
except ImportError:
    LLMMessagesAppendFrame = None

try:
    from pipecat.frames.frames import (
        VADUserStartedSpeakingFrame,
        VADUserStoppedSpeakingFrame,
    )
except ImportError:
    VADUserStartedSpeakingFrame = None
    VADUserStoppedSpeakingFrame = None

try:
    from pipecat.frames.frames import BotSpeakingFrame
except ImportError:
    BotSpeakingFrame = None


class TurnState(str, Enum):
    IDLE = "idle"
    USER_SPEAKING = "user_speaking"
    PROCESSING = "processing"
    RESPONDING = "responding"


class SupportRuntimeResponder(FrameProcessor):
    """
    Connects Pipecat STT output → SupportRuntime → TTS input.

    Rules:
    - TranscriptionFrame is the primary trigger (OpenAI STT delivers text here)
    - UserStoppedSpeakingFrame is a secondary trigger (catches cases where
      transcript arrives before or after the stop signal)
    - InterruptionFrame resets all state — barge-in handled cleanly
    - One runtime call per turn (emitted_this_turn guard prevents duplicates)
    - Empty/whitespace transcripts are silently dropped
    """

    def __init__(self, adapter, session, **kwargs):
        super().__init__(**kwargs)
        self.adapter = adapter
        self.session = session
        self.state = TurnState.IDLE
        self._latest_text: str = ""
        self._emitted_this_turn: bool = False
        self._turn_start_ts: Optional[float] = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # ─── Interruption / barge-in ────────────────────────────────────────
        if isinstance(frame, InterruptionFrame):
            if self.state != TurnState.IDLE:
                self.session.interruption_count += 1
                logger.info(
                    f"[responder] INTERRUPTION — was={self.state} "
                    f"total_interruptions={self.session.interruption_count}"
                )
            self._reset_turn()
            await self.push_frame(frame, direction)
            return

        # ─── User started speaking ───────────────────────────────────────────
        if isinstance(frame, UserStartedSpeakingFrame) or (
            VADUserStartedSpeakingFrame
            and isinstance(frame, VADUserStartedSpeakingFrame)
        ):
            self.state = TurnState.USER_SPEAKING
            self._emitted_this_turn = False
            self._latest_text = ""
            self._turn_start_ts = time.time()
            self.session.begin_turn()
            logger.debug("[responder] USER_SPEAKING")
            await self.push_frame(frame, direction)
            return

        # ─── STT result: PRIMARY trigger ────────────────────────────────────
        if isinstance(frame, TranscriptionFrame):
            text = (getattr(frame, "text", None) or "").strip()
            logger.info(
                f"[STT] text={text!r} state={self.state} "
                f"emitted={self._emitted_this_turn}"
            )
            if not text:
                return  # never forward empty transcripts

            # Mark STT final timestamp (T1)
            self.session.mark_stt_final()
            self._latest_text = text

            if not self._emitted_this_turn and self.state != TurnState.PROCESSING:
                await self._run_turn(text, direction)
            return

        # ─── User stopped speaking: secondary trigger ────────────────────────
        if isinstance(frame, UserStoppedSpeakingFrame) or (
            VADUserStoppedSpeakingFrame
            and isinstance(frame, VADUserStoppedSpeakingFrame)
        ):
            # Mark turn-end timestamp (T0)
            self.session.mark_turn_ended()
            logger.debug(f"[responder] USER_STOPPED text_buffered={self._latest_text!r}")
            await self.push_frame(frame, direction)

            text = self._latest_text.strip()
            if text and not self._emitted_this_turn and self.state != TurnState.PROCESSING:
                await self._run_turn(text, direction)
            return

        # ─── Typed input from playground (optional) ──────────────────────────
        if LLMMessagesAppendFrame and isinstance(frame, LLMMessagesAppendFrame):
            text = self._extract_append_text(frame)
            logger.info(f"[TYPED] text={text!r}")
            if text and not self._emitted_this_turn and self.state != TurnState.PROCESSING:
                self.session.mark_stt_final()
                await self._run_turn(text, direction)
            return

        # ─── Pass everything else through ────────────────────────────────────
        await self.push_frame(frame, direction)

    # ── Private helpers ──────────────────────────────────────────────────────

    def _reset_turn(self) -> None:
        self.state = TurnState.IDLE
        self._emitted_this_turn = False
        self._latest_text = ""
        self._turn_start_ts = None

    def _extract_append_text(self, frame) -> str:
        messages = getattr(frame, "messages", None) or []
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict):
                return (last.get("content") or "").strip()
            return str(getattr(last, "content", last) or "").strip()
        for attr in ("message", "text", "content"):
            v = getattr(frame, attr, None)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def _extract_reply(self, result) -> str:
        text = (getattr(result, "response", None) or "").strip()
        return text

    async def _run_turn(self, text: str, direction: FrameDirection) -> None:
        self.state = TurnState.PROCESSING
        self._emitted_this_turn = True
        logger.info(f"[turn] PROCESSING → runtime text={text!r}")

        # Mark runtime start (T2)
        self.session.mark_runtime_start()

        try:
            handle = getattr(self.adapter, "handle_transcript", None)
            if asyncio.iscoroutinefunction(handle):
                result = await handle(text, self.session)
            elif handle is not None:
                result = await asyncio.to_thread(handle, text, self.session)
            else:
                result = await asyncio.to_thread(
                    self.adapter.handle_transcript_sync, text, self.session
                )

            # Mark runtime done (T3)
            self.session.mark_runtime_done()

            reply = self._extract_reply(result)
            if not reply:
                reply = "Sorry, I could not generate a reply. Please try again."

            logger.info(f"[turn] RESPONDING reply={reply[:80]!r}")

            # Mark TTS start (T4)
            self.session.mark_tts_start()
            self.state = TurnState.RESPONDING

            await self.push_frame(LLMFullResponseStartFrame(), direction)
            await self.push_frame(TextFrame(text=reply), direction)
            await self.push_frame(LLMFullResponseEndFrame(), direction)

            self.session.complete_turn()

            ttfa = self.session.latency_history[-1].ttfa_ms if self.session.latency_history else None
            logger.info(
                f"[turn] DONE ttfa={ttfa:.0f}ms" if ttfa else "[turn] DONE ttfa=unknown"
            )

        except Exception as exc:
            logger.exception(f"[turn] runtime error: {exc}")
            self.session.mark_runtime_done()
            err_msg = "Sorry, I'm having trouble right now. Please try again."
            await self.push_frame(LLMFullResponseStartFrame(), direction)
            await self.push_frame(TextFrame(text=err_msg), direction)
            await self.push_frame(LLMFullResponseEndFrame(), direction)

        finally:
            self.state = TurnState.IDLE
            self._latest_text = ""