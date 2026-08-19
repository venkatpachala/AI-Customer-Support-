"""
voice/processors/transcript.py — Transcript logger processor.

Logs every TranscriptionFrame (STT output) with timestamps.
Used for:
  - Debugging STT quality
  - Evaluation: comparing expected vs actual transcripts
  - Latency measurement validation

Place AFTER STT, BEFORE SupportRuntimeResponder for accurate logging.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame, UserStartedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class TranscriptLogger(FrameProcessor):
    """
    Non-intrusive transcript logger.
    Passes all frames through unchanged while logging transcription events.

    Args:
        on_transcript: Optional callback(text: str, ts: float) for test assertions.
    """

    def __init__(self, on_transcript: Optional[Callable[[str, float], None]] = None, **kwargs):
        super().__init__(**kwargs)
        self._on_transcript = on_transcript
        self._turn_start_ts: Optional[float] = None
        self._turn_count = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            self._turn_start_ts = time.time()
            self._turn_count += 1

        elif isinstance(frame, TranscriptionFrame):
            text = (getattr(frame, "text", None) or "").strip()
            ts = time.time()
            elapsed = (ts - self._turn_start_ts) * 1000.0 if self._turn_start_ts else None

            logger.info(
                f"[transcript] turn={self._turn_count} "
                f"text={text!r} "
                f"stt_elapsed={elapsed:.0f}ms" if elapsed else f"[transcript] text={text!r}"
            )

            if self._on_transcript and text:
                try:
                    self._on_transcript(text, ts)
                except Exception:
                    pass

        await self.push_frame(frame, direction)
