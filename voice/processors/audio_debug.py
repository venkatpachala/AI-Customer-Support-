from __future__ import annotations

from loguru import logger

from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Optional: older/newer pipecat may or may not export VAD* frames
try:
    from pipecat.frames.frames import (
        VADUserStartedSpeakingFrame,
        VADUserStoppedSpeakingFrame,
    )
except ImportError:
    VADUserStartedSpeakingFrame = None
    VADUserStoppedSpeakingFrame = None


class AudioDebugProcessor(FrameProcessor):
    """Place BEFORE STT: prove mic audio + VAD/turn frames enter the pipeline."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._audio_n = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InputAudioRawFrame):
            self._audio_n += 1
            if self._audio_n == 1 or self._audio_n % 50 == 0:
                audio = getattr(frame, "audio", b"") or b""
                logger.info(
                    f"[AUDIO DEBUG] InputAudioRawFrame n={self._audio_n} "
                    f"bytes={len(audio)} "
                    f"sample_rate={getattr(frame, 'sample_rate', None)} "
                    f"channels={getattr(frame, 'num_channels', None)}"
                )

        elif VADUserStartedSpeakingFrame and isinstance(frame, VADUserStartedSpeakingFrame):
            logger.info("[AUDIO DEBUG] VAD USER STARTED")

        elif VADUserStoppedSpeakingFrame and isinstance(frame, VADUserStoppedSpeakingFrame):
            logger.info("[AUDIO DEBUG] VAD USER STOPPED")

        elif isinstance(frame, UserStartedSpeakingFrame):
            logger.info("[AUDIO DEBUG] USER STARTED")

        elif isinstance(frame, UserStoppedSpeakingFrame):
            logger.info("[AUDIO DEBUG] USER STOPPED")

        await self.push_frame(frame, direction)