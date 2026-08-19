"""
voice/pipeline.py — Pipecat 1.7.0 production pipeline builder.

Architecture:
  mic → Transport → VADProcessor (Silero) → STT → SupportRuntimeResponder → TTS → speaker

Provider selection is handled by voice/stt/provider.py and voice/tts/provider.py.
"""
from __future__ import annotations

from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.transports.base_transport import BaseTransport, TransportParams

from voice.adapter import SupportRuntimeAdapter
from voice.config import voice_config
from voice.context import VoiceSession
from voice.processors.runtime_responder import SupportRuntimeResponder
from voice.stt.provider import get_stt_service
from voice.tts.provider import get_tts_service


def build_transport_params(config=None) -> TransportParams:
    """Build TransportParams for SmallWebRTC."""
    cfg = config or voice_config
    cfg.validate()

    return TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        audio_out_sample_rate=24000,   # OpenAI TTS outputs 24kHz
        audio_in_sample_rate=16000,    # Whisper/STT expects 16kHz
    )


def build_phase2_pipeline(
    transport: BaseTransport,
    adapter: SupportRuntimeAdapter,
    session: VoiceSession,
    config=None,
) -> Pipeline:
    """
    Build the full Phase 2 voice pipeline.

    Pipeline:
      transport.input()
        → [AudioDebugProcessor]  ← optional, dev-mode only
        → VADProcessor (Silero)
        → STT (Whisper via OpenAI)
        → SupportRuntimeResponder (TranscriptionFrame → SupportRuntime → TextFrame)
        → TTS (OpenAI)
        → transport.output()
    """
    cfg = config or voice_config

    logger.info(
        f"[pipeline] Building Phase 2 pipeline "
        f"call_id={session.call_id} "
        f"stt={cfg.stt_provider!r} tts={cfg.tts_provider!r}"
    )

    # STT and TTS from provider factories
    stt = get_stt_service(cfg)
    tts = get_tts_service(cfg)

    # VAD Analyzer + Processor
    vad_analyzer = SileroVADAnalyzer(
        params=VADParams(
            stop_secs=cfg.vad_silence_ms / 1000.0,
        )
    )
    vad = VADProcessor(vad_analyzer=vad_analyzer)

    # Core responder: TranscriptionFrame → SupportRuntime → TextFrame
    responder = SupportRuntimeResponder(adapter=adapter, session=session)

    # Build processor list
    processors = [transport.input()]

    if cfg.enable_debug_audio:
        from voice.processors.audio_debug import AudioDebugProcessor
        processors.append(AudioDebugProcessor())
        logger.info("[pipeline] AudioDebugProcessor enabled")

    processors.extend([
        vad,
        stt,
        responder,
        tts,
        transport.output(),
    ])

    pipeline = Pipeline(processors)
    logger.info(f"[pipeline] Built: {' → '.join(type(p).__name__ for p in processors)}")
    return pipeline


def build_pipeline_task(
    transport: BaseTransport,
    adapter: SupportRuntimeAdapter,
    session: VoiceSession,
    config=None,
) -> PipelineTask:
    """
    Build a PipelineTask ready to run.
    """
    cfg = config or voice_config
    pipeline = build_phase2_pipeline(transport, adapter, session, cfg)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=float(cfg.idle_timeout_secs),
        name=f"voice-call-{session.call_id[:8]}",
    )

    logger.info(
        f"[pipeline] PipelineTask created: "
        f"idle_timeout={cfg.idle_timeout_secs}s "
        f"call_id={session.call_id[:8]}"
    )
    return task