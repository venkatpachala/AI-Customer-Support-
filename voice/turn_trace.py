"""
voice/turn_trace.py — Per-turn structured observability trace (Phase 3).

A VoiceTurnTrace is created at the start of each user turn and populated as
the turn progresses through STT → Supervisor → Tool → QA → TTS.

It is appended to VoiceSession.latency_history as the authoritative record
of what happened each turn, and emitted as JSON to the terminal/log.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VoiceTurnTrace:
    """
    One complete user → assistant turn trace.

    Timestamps:
      t0  = VAD end / user turn ended
      t1  = STT final transcript
      t2  = SupportRuntime start (after thinking phrase if any)
      t3  = SupportRuntime done (RuntimeResponse received)
      t4  = TTS first text frame pushed
      t5  = first audio frame out
    """
    call_id: str = ""
    session_id: Optional[str] = None
    turn_number: int = 0

    # ── Classification ───────────────────────────────────────────────────────
    user_utterance: str = ""
    intent: Optional[str] = None
    intent_type: Optional[str] = None
    is_continuation: bool = False

    # ── Tool execution ───────────────────────────────────────────────────────
    tool_name: Optional[str] = None
    tool_input: Dict[str, Any] = field(default_factory=dict)
    tool_result: Optional[Dict[str, Any]] = None
    tool_success: bool = False
    tool_latency_ms: float = 0.0

    # ── RAG ──────────────────────────────────────────────────────────────────
    rag_used: bool = False
    rag_docs_retrieved: int = 0
    rag_latency_ms: float = 0.0

    # ── Identity ─────────────────────────────────────────────────────────────
    identity_required: bool = False
    identity_result: Optional[str] = None  # "passed" | "challenged" | "failed"

    # ── Response ─────────────────────────────────────────────────────────────
    response_text: str = ""
    thinking_phrase: Optional[str] = None  # spoken while waiting for tool

    # ── Latency breakdown (ms) ───────────────────────────────────────────────
    stt_latency_ms: Optional[float] = None
    supervisor_latency_ms: Optional[float] = None
    runtime_latency_ms: Optional[float] = None
    tts_latency_ms: Optional[float] = None
    ttfa_ms: Optional[float] = None           # Time To First Audio

    # ── Raw timestamps (epoch seconds) ──────────────────────────────────────
    t0_vad_end: Optional[float] = None
    t1_stt_final: Optional[float] = None
    t2_runtime_start: Optional[float] = None
    t3_runtime_done: Optional[float] = None
    t4_tts_start: Optional[float] = None
    t5_first_audio: Optional[float] = None

    # ── Status ───────────────────────────────────────────────────────────────
    escalated: bool = False
    blocked: bool = False
    error: Optional[str] = None

    def mark_runtime_done(self) -> None:
        self.t3_runtime_done = time.time()
        if self.t2_runtime_start:
            self.runtime_latency_ms = (self.t3_runtime_done - self.t2_runtime_start) * 1000

    def compute_ttfa(self) -> None:
        if self.t0_vad_end and self.t5_first_audio:
            self.ttfa_ms = (self.t5_first_audio - self.t0_vad_end) * 1000
        elif self.t2_runtime_start and self.t3_runtime_done:
            # Fallback: use runtime latency as proxy
            self.ttfa_ms = self.runtime_latency_ms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "session_id": self.session_id,
            "turn": self.turn_number,
            "utterance": self.user_utterance[:120],
            "intent": self.intent,
            "intent_type": self.intent_type,
            "is_continuation": self.is_continuation,
            "thinking_phrase": self.thinking_phrase,
            "rag_used": self.rag_used,
            "rag_docs": self.rag_docs_retrieved,
            "identity_required": self.identity_required,
            "identity_result": self.identity_result,
            "tool": self.tool_name,
            "tool_success": self.tool_success,
            "response_preview": self.response_text[:120],
            "latency": {
                "stt_ms": round(self.stt_latency_ms or 0, 1),
                "supervisor_ms": round(self.supervisor_latency_ms or 0, 1),
                "runtime_ms": round(self.runtime_latency_ms or 0, 1),
                "rag_ms": round(self.rag_latency_ms or 0, 1),
                "tool_ms": round(self.tool_latency_ms or 0, 1),
                "tts_ms": round(self.tts_latency_ms or 0, 1),
                "ttfa_ms": round(self.ttfa_ms or 0, 1),
            },
            "escalated": self.escalated,
            "blocked": self.blocked,
            "error": self.error,
        }

    def log_to_terminal(self) -> None:
        """Emit a compact per-turn summary to terminal."""
        import json
        from loguru import logger
        d = self.to_dict()
        l = d["latency"]
        tool_str = f" → {self.tool_name} ({l['tool_ms']}ms)" if self.tool_name else ""
        logger.info(
            f"\n{'─'*60}\n"
            f"  Turn {self.turn_number} | intent={self.intent} ({self.intent_type})"
            f"{' [continuation]' if self.is_continuation else ''}\n"
            f"  User: \"{self.user_utterance[:80]}\"\n"
            f"  {'Thinking: \"' + self.thinking_phrase + '\"' + chr(10) + '  ' if self.thinking_phrase else ''}"
            f"RAG={'yes ('+str(self.rag_docs_retrieved)+' docs)' if self.rag_used else 'no'}"
            f"{tool_str}\n"
            f"  Reply: \"{self.response_text[:100]}\"\n"
            f"  Latency → STT:{l['stt_ms']}ms | Runtime:{l['runtime_ms']}ms | "
            f"TTS:{l['tts_ms']}ms | TTFA:{l['ttfa_ms']}ms\n"
            f"{'─'*60}"
        )
