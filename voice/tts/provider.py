"""
voice/tts/provider.py — TTS provider factory.

Currently supports: openai (TTS-1 via OpenAI API)
Future: elevenlabs, sarvam, cartesia

The factory returns a Pipecat TTS service instance. Swap the provider by
setting VOICE_TTS_PROVIDER in your .env file. The pipeline does not need
to change when you switch providers.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from voice.config import VoiceConfig


def get_tts_service(config: "VoiceConfig"):
    """
    Factory: return the configured Pipecat TTS service.

    Args:
        config: VoiceConfig instance.

    Returns:
        A Pipecat TTS service (e.g. OpenAITTSService).

    Raises:
        ValueError: If the provider is not supported.
        RuntimeError: If required credentials are missing.
    """
    provider = (config.tts_provider or "openai").lower().strip()
    logger.info(f"[TTS] Initializing provider={provider!r} voice={config.openai_tts_voice!r}")

    if provider == "openai":
        return _make_openai_tts(config)

    raise ValueError(
        f"Unsupported TTS provider: {provider!r}. "
        "Supported: 'openai'. Set VOICE_TTS_PROVIDER in .env."
    )


def _make_openai_tts(config: "VoiceConfig"):
    """OpenAI TTS-1 — low latency, natural voice, multiple voice options."""
    from pipecat.services.openai.tts import OpenAITTSService

    if not config.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for openai TTS provider.")

    valid_voices = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
    voice = config.openai_tts_voice
    if voice not in valid_voices:
        logger.warning(
            f"[TTS] Unknown voice {voice!r}, falling back to 'alloy'. "
            f"Valid: {valid_voices}"
        )
        voice = "alloy"

    try:
        service = OpenAITTSService(
            api_key=config.openai_api_key,
            voice=voice,
        )
    except TypeError:
        service = OpenAITTSService(api_key=config.openai_api_key)

    logger.info(f"[TTS] OpenAITTSService ready (voice={voice!r})")
    return service
