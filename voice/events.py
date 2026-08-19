"""
voice/events.py — Voice session lifecycle event system.

Tracks the full state machine:
  CONNECTING → CONNECTED → LISTENING → USER_SPEAKING → PROCESSING
  → ASSISTANT_SPEAKING → LISTENING → ... → ENDING → ENDED
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class VoiceSessionStatus(str, Enum):
    """Full voice session lifecycle states."""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    LISTENING = "listening"
    USER_SPEAKING = "user_speaking"
    PROCESSING = "processing"
    ASSISTANT_SPEAKING = "assistant_speaking"
    ENDING = "ending"
    ENDED = "ended"
    ERROR = "error"


class VoiceEventType(str, Enum):
    """Typed voice events for observability."""
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    USER_TURN_STARTED = "user_turn_started"
    USER_TURN_ENDED = "user_turn_ended"
    STT_PARTIAL = "stt_partial"
    STT_FINAL = "stt_final"
    RUNTIME_STARTED = "runtime_started"
    RUNTIME_COMPLETED = "runtime_completed"
    TTS_STARTED = "tts_started"
    FIRST_AUDIO_OUT = "first_audio_out"
    INTERRUPTION = "interruption"
    ERROR = "error"


@dataclass
class VoiceEvent:
    """A single voice pipeline event for logging / metrics."""
    event_type: VoiceEventType
    call_id: str
    session_id: Optional[str] = None
    tenant_id: Optional[str] = None
    customer_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event_type.value,
            "call_id": self.call_id,
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "customer_id": self.customer_id,
            "ts": self.timestamp,
            **self.data,
        }
