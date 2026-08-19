"""
voice/context.py — Per-call VoiceSession with lifecycle status and TTFA tracking.

Survives multiple turns within one call.
Written back by SupportRuntimeAdapter after every handle().
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional
import uuid

from voice.events import VoiceSessionStatus


@dataclass
class LatencyRecord:
    """Timestamps for one user-turn → first-audio cycle.

    T0 = user_turn_ended   (VAD signals end of user speech)
    T1 = stt_final         (STT delivers final transcript)
    T2 = runtime_start     (SupportRuntime.handle() called)
    T3 = runtime_done      (RuntimeResponse received)
    T4 = tts_start         (first TextFrame pushed to TTS)
    T5 = first_audio       (first AudioFrame leaves pipeline)

    TTFA = T5 - T0   (Time To First Audio)
    """
    t_user_turn_ended: Optional[float] = None
    t_stt_final: Optional[float] = None
    t_runtime_start: Optional[float] = None
    t_runtime_done: Optional[float] = None
    t_tts_start: Optional[float] = None
    t_first_audio: Optional[float] = None

    @property
    def ttfa_ms(self) -> Optional[float]:
        if self.t_user_turn_ended and self.t_first_audio:
            return (self.t_first_audio - self.t_user_turn_ended) * 1000.0
        return None

    @property
    def stt_latency_ms(self) -> Optional[float]:
        if self.t_user_turn_ended and self.t_stt_final:
            return (self.t_stt_final - self.t_user_turn_ended) * 1000.0
        return None

    @property
    def runtime_latency_ms(self) -> Optional[float]:
        if self.t_runtime_start and self.t_runtime_done:
            return (self.t_runtime_done - self.t_runtime_start) * 1000.0
        return None

    @property
    def tts_latency_ms(self) -> Optional[float]:
        if self.t_tts_start and self.t_first_audio:
            return (self.t_first_audio - self.t_tts_start) * 1000.0
        return None

    def as_dict(self) -> dict:
        return {
            "ttfa_ms": self.ttfa_ms,
            "stt_latency_ms": self.stt_latency_ms,
            "runtime_latency_ms": self.runtime_latency_ms,
            "tts_latency_ms": self.tts_latency_ms,
        }


@dataclass
class VoiceSession:
    """Per-call voice session. Survives turns; written back after every handle()."""

    tenant_id: str = "zepto"
    customer_id: str = "voice_demo_user"
    channel: str = "voice"

    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: Optional[str] = None
    case_id: Optional[str] = None

    # Lifecycle
    status: VoiceSessionStatus = VoiceSessionStatus.CONNECTING
    started_at: float = field(default_factory=time.time)

    # Auth ladder: anonymous → identified → verified
    auth_level: str = "anonymous"
    verified: bool = False
    verified_customer: bool = False
    verified_order_ids: List[str] = field(default_factory=list)

    # Identity in progress (not proof of ownership)
    pending_order_id: Optional[str] = None
    pending_contact: Optional[str] = None
    customer_contact: Optional[str] = None
    needs_identity: bool = False

    # Sticky action for email-only turns
    issue_type: Optional[str] = None

    language: str = "en"

    # Latency tracking — current turn
    current_latency: LatencyRecord = field(default_factory=LatencyRecord)

    # History of all completed turns
    latency_history: List[LatencyRecord] = field(default_factory=list)

    # Interruption count
    interruption_count: int = 0

    # Turn count
    turn_count: int = 0

    def normalize_auth(self) -> None:
        level = (self.auth_level or "anonymous").lower().strip()
        if level == "verified":
            self.verified = True
            self.auth_level = "verified"
        elif level == "identified":
            self.verified = False
            self.auth_level = "identified"
        else:
            self.auth_level = "anonymous"
            self.verified = False
            self.verified_customer = False

    def begin_turn(self) -> None:
        """Called when user starts speaking."""
        self.current_latency = LatencyRecord()
        self.current_latency.t_user_turn_ended = None
        self.status = VoiceSessionStatus.USER_SPEAKING

    def mark_turn_ended(self) -> None:
        """Called when VAD detects end of user speech (T0)."""
        self.current_latency.t_user_turn_ended = time.time()
        self.status = VoiceSessionStatus.LISTENING

    def mark_stt_final(self) -> None:
        """Called when STT delivers final transcript (T1)."""
        self.current_latency.t_stt_final = time.time()

    def mark_runtime_start(self) -> None:
        """Called just before SupportRuntime.handle() (T2)."""
        self.current_latency.t_runtime_start = time.time()
        self.status = VoiceSessionStatus.PROCESSING

    def mark_runtime_done(self) -> None:
        """Called after RuntimeResponse received (T3)."""
        self.current_latency.t_runtime_done = time.time()

    def mark_tts_start(self) -> None:
        """Called when first TextFrame is pushed to TTS (T4)."""
        self.current_latency.t_tts_start = time.time()
        self.status = VoiceSessionStatus.ASSISTANT_SPEAKING

    def mark_first_audio(self) -> None:
        """Called when first audio frame leaves pipeline (T5)."""
        if self.current_latency.t_first_audio is None:
            self.current_latency.t_first_audio = time.time()

    def complete_turn(self) -> None:
        """Finalize current turn — move to history."""
        self.latency_history.append(self.current_latency)
        self.turn_count += 1
        self.status = VoiceSessionStatus.LISTENING

    def avg_ttfa_ms(self) -> Optional[float]:
        vals = [r.ttfa_ms for r in self.latency_history if r.ttfa_ms is not None]
        return sum(vals) / len(vals) if vals else None

    def metrics_summary(self) -> dict:
        return {
            "call_id": self.call_id,
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "customer_id": self.customer_id,
            "status": self.status.value,
            "turn_count": self.turn_count,
            "interruption_count": self.interruption_count,
            "avg_ttfa_ms": self.avg_ttfa_ms(),
            "last_turn": self.current_latency.as_dict() if self.latency_history else None,
            "history": [r.as_dict() for r in self.latency_history[-5:]],
        }