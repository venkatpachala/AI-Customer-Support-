"""
Phase 2 — Realtime Voice Foundation.

Connects browser microphone → Pipecat (VAD + STT + TTS) → SupportRuntime → LangGraph.
Same customer session, case, and memory as the Chat channel.

Quick start:
  python -m voice.server          # start voice server on localhost:7860
  open frontend/voice.html        # browser client

Architecture:
  Browser → SmallWebRTC → Pipecat Pipeline → SupportRuntimeAdapter → SupportRuntime
"""

from voice.context import VoiceSession
from voice.adapter import SupportRuntimeAdapter
from voice.events import VoiceSessionStatus, VoiceEvent, VoiceEventType

__all__ = [
    "VoiceSession",
    "SupportRuntimeAdapter",
    "VoiceSessionStatus",
    "VoiceEvent",
    "VoiceEventType",
]