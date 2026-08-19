from __future__ import annotations

from loguru import logger

from pipecat.frames.frames import Frame, InputAudioRawFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

try:
    from pipecat.frames.frames import InterimTranscriptionFrame
except ImportError:
    InterimTranscriptionFrame = None

try:
    from pipecat.frames.frames import (
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
    )
except ImportError:
    UserStartedSpeakingFrame = None
    UserStoppedSpeakingFrame = None


class STTProbe(FrameProcessor):
    """Log every frame type; highlight transcripts. Use before and after STT."""

    def __init__(self, label: str, **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self._audio_n = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        name = type(frame).__name__

        if isinstance(frame, InputAudioRawFrame):
            self._audio_n += 1
            if self._audio_n == 1 or self._audio_n % 50 == 0:
                audio = getattr(frame, "audio", b"") or b""
                logger.warning(
                    f"[{self.label}] InputAudioRawFrame n={self._audio_n} bytes={len(audio)}"
                )
        elif UserStartedSpeakingFrame and isinstance(frame, UserStartedSpeakingFrame):
            logger.warning(f"[{self.label}] USER STARTED")
        elif UserStoppedSpeakingFrame and isinstance(frame, UserStoppedSpeakingFrame):
            logger.warning(f"[{self.label}] USER STOPPED")
        elif InterimTranscriptionFrame and isinstance(frame, InterimTranscriptionFrame):
            logger.warning(f"[{self.label}] INTERIM: {getattr(frame, 'text', None)!r}")
        elif isinstance(frame, TranscriptionFrame):
            logger.warning(f"[{self.label}] FINAL TRANSCRIPT: {getattr(frame, 'text', None)!r}")
        else:
            # keep noise low: skip pure StartFrame spam if any
            if name not in ("StartFrame", "MetricsFrame"):
                logger.warning(f"[{self.label}] {name}")

        await self.push_frame(frame, direction)