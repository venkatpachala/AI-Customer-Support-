"""
voice/config.py — Structured voice configuration.

All values are read from environment variables with safe defaults.
Provider selection is done here so pipeline.py stays provider-agnostic.
"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)


class VoiceConfig:
    # ─── Server ───────────────────────────────────────────────────────────────
    host: str = os.getenv("VOICE_HOST", "localhost")
    port: int = int(os.getenv("VOICE_PORT", "7860"))

    # ─── OpenAI (STT + TTS) ───────────────────────────────────────────────────
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("VOICE_LLM_MODEL", "gpt-4o-mini")

    # ─── STT ──────────────────────────────────────────────────────────────────
    # VOICE_STT_PROVIDER: "openai" | "deepgram" | "sarvam"
    stt_provider: str = os.getenv("VOICE_STT_PROVIDER", "openai")
    stt_language: str = os.getenv("VOICE_STT_LANGUAGE", "en")

    # ─── TTS ──────────────────────────────────────────────────────────────────
    # VOICE_TTS_PROVIDER: "openai" | "elevenlabs" | "sarvam"
    tts_provider: str = os.getenv("VOICE_TTS_PROVIDER", "openai")
    openai_tts_voice: str = os.getenv("VOICE_TTS_VOICE", "alloy")
    # alloy | echo | fable | onyx | nova | shimmer

    # ─── VAD ──────────────────────────────────────────────────────────────────
    # Silence threshold (ms) before end-of-turn is detected
    vad_silence_ms: int = int(os.getenv("VOICE_VAD_SILENCE_MS", "800"))

    # ─── Pipeline ─────────────────────────────────────────────────────────────
    allow_interruptions: bool = os.getenv("VOICE_ALLOW_INTERRUPTIONS", "true").lower() == "true"
    idle_timeout_secs: int = int(os.getenv("VOICE_IDLE_TIMEOUT", "300"))
    enable_debug_audio: bool = os.getenv("VOICE_DEBUG_AUDIO", "false").lower() == "true"

    # ─── Latency targets (ms) — used in test assertions ───────────────────────
    target_stt_latency_ms: float = float(os.getenv("VOICE_TARGET_STT_MS", "500"))
    target_runtime_latency_ms: float = float(os.getenv("VOICE_TARGET_RUNTIME_MS", "800"))
    target_tts_latency_ms: float = float(os.getenv("VOICE_TARGET_TTS_MS", "500"))
    target_ttfa_ms: float = float(os.getenv("VOICE_TARGET_TTFA_MS", "2000"))

    # ─── System prompt (TTS shaping) ─────────────────────────────────────────
    voice_system_note: str = (
        "Keep replies short (1-2 sentences max). "
        "No markdown, no bullets, no emojis. "
        "Speak naturally as if on a phone call."
    )

    def validate(self) -> None:
        if not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required. Set it in your .env file."
            )

    def __repr__(self) -> str:  # safe — no secrets
        return (
            f"VoiceConfig(host={self.host}, port={self.port}, "
            f"stt={self.stt_provider}, tts={self.tts_provider}, "
            f"tts_voice={self.openai_tts_voice}, vad_silence_ms={self.vad_silence_ms})"
        )


voice_config = VoiceConfig()