from __future__ import annotations

from loguru import logger

from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

try:
    from pipecat.frames.frames import InterimTranscriptionFrame
except ImportError:
    InterimTranscriptionFrame = None


class STTDebugProcessor(FrameProcessor):
    """Sits AFTER STT: log what STT (and VAD frames through the chain) produce."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._audio_n = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InputAudioRawFrame):
            self._audio_n += 1
            # Throttle: log first + every 50th packet
            if self._audio_n == 1 or self._audio_n % 50 == 0:
                logger.info(
                    f"[STT DEBUG] AUDIO n={self._audio_n} "
                    f"bytes={len(getattr(frame, 'audio', b'') or b'')} "
                    f"rate={getattr(frame, 'sample_rate', None)} "
                    f"ch={getattr(frame, 'num_channels', None)}"
                )

        elif isinstance(frame, UserStartedSpeakingFrame):
            logger.info("[STT DEBUG] USER STARTED SPEAKING")

        elif isinstance(frame, UserStoppedSpeakingFrame):
            logger.info("[STT DEBUG] USER STOPPED SPEAKING")

        elif InterimTranscriptionFrame and isinstance(frame, InterimTranscriptionFrame):
            logger.info(f"[STT DEBUG] INTERIM: {getattr(frame, 'text', None)!r}")

        elif isinstance(frame, TranscriptionFrame):
            logger.info(f"[STT DEBUG] FINAL TRANSCRIPT: {getattr(frame, 'text', None)!r}")

        await self.push_frame(frame, direction)