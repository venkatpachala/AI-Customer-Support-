"""
voice/stt/provider.py — STT provider factory.

Currently supports: openai (Whisper via OpenAI API)
Future: deepgram, sarvam, speechmatics, soniox

The factory returns a Pipecat STT service instance. Swap the provider by
setting VOICE_STT_PROVIDER in your .env file. The pipeline does not need
to change when you switch providers.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from voice.config import VoiceConfig


def get_stt_service(config: "VoiceConfig"):
    """
    Factory: return the configured Pipecat STT service.

    Args:
        config: VoiceConfig instance.

    Returns:
        A Pipecat STT service (e.g. OpenAISTTService).

    Raises:
        ValueError: If the provider is not supported.
        RuntimeError: If required credentials are missing.
    """
    provider = (config.stt_provider or "openai").lower().strip()
    logger.info(f"[STT] Initializing provider={provider!r} language={config.stt_language!r}")

    if provider == "openai":
        return _make_openai_stt(config)

    raise ValueError(
        f"Unsupported STT provider: {provider!r}. "
        "Supported: 'openai'. Set VOICE_STT_PROVIDER in .env."
    )


def _make_openai_stt(config: "VoiceConfig"):
    """Whisper via OpenAI API — low latency, good English, decent multilingual."""
    from pipecat.services.openai.stt import OpenAISTTService

    if not config.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for openai STT provider.")

    # OpenAISTTService constructor varies slightly between pipecat versions.
    # Try with language first, fall back without.
    try:
        service = OpenAISTTService(
            api_key=config.openai_api_key,
            language=config.stt_language,
        )
    except TypeError:
        service = OpenAISTTService(api_key=config.openai_api_key)

    logger.info(f"[STT] OpenAISTTService ready (language={config.stt_language!r})")
    return service
