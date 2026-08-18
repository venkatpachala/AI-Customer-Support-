import os
from dotenv import load_dotenv

load_dotenv(override=True)


class VoiceConfig:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("VOICE_LLM_MODEL", "gpt-4o-mini")
    openai_tts_voice: str = os.getenv("VOICE_TTS_VOICE", "alloy")
    system_prompt: str = (
        "You are a concise voice assistant for a product demo. "
        "Keep replies short (1-2 sentences). No markdown, no bullets, no emojis. "
        "Speak naturally as if on a phone call."
    )

    def validate(self) -> None:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for Phase 1 voice bot")


voice_config = VoiceConfig()