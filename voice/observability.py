"""
voice/observability.py — Terminal Observability Layer for Realtime Voice.

Provides visual terminal logging for:
  - Voice turn lifecycle (T0..T5)
  - VAD state transitions
  - STT transcripts & latency
  - RequestContext validation (channel="voice", auth, tenant, session)
  - LangGraph node execution & memory trace
  - TTS synthesis & TTFA breakdown
  - Interruption / barge-in alerts
  - Session writebacks & Cross-channel handoffs
"""
from __future__ import annotations

import sys
import time
from typing import Any, Dict, Optional

# ANSI Color codes for terminal formatting
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


class VoiceObserver:
    """Terminal observability logger for Voice pipeline."""

    @staticmethod
    def log_turn_start(turn_num: int, call_id: str, session_id: Optional[str], channel: str = "voice"):
        cid = call_id[:8] if call_id else "unknown"
        sid = session_id[:8] if session_id else "new_session"
        print(f"\n{CYAN}{BOLD}╔══════════════════════════════════════════════════════════════════════════════╗{RESET}")
        print(f"{CYAN}{BOLD}║ 🎙️  VOICE TURN #{turn_num:<3} [Call: {cid} | Session: {sid} | Channel: {channel}]     ║{RESET}")
        print(f"{CYAN}{BOLD}╚══════════════════════════════════════════════════════════════════════════════╝{RESET}")

    @staticmethod
    def log_vad(event: str, details: str = ""):
        if "start" in event.lower():
            print(f"  {YELLOW}🎤 [VAD] User started speaking...{RESET} {DIM}{details}{RESET}")
        else:
            print(f"  {YELLOW}⏹️  [VAD] User stopped speaking (T0){RESET} {DIM}{details}{RESET}")

    @staticmethod
    def log_stt(transcript: str, latency_ms: Optional[float] = None):
        lat = f" ({latency_ms:.0f}ms)" if latency_ms is not None else ""
        print(f"  {GREEN}{BOLD}📝 [STT] Whisper Transcribed:{RESET} \"{transcript}\"{lat}")

    @staticmethod
    def log_context(ctx: Any):
        auth = getattr(ctx, "auth", None)
        auth_level = getattr(auth, "auth_level", "anonymous") if auth else "anonymous"
        cid = getattr(ctx, "customer_id", "")
        tid = getattr(ctx, "tenant_id", "")
        sid = (getattr(ctx, "session_id", "") or "none")[:8]
        case_id = (getattr(ctx, "case_id", "") or "none")[:8]
        channel = getattr(ctx, "channel", "voice")

        print(f"  {BLUE}📦 [CONTEXT]{RESET} channel='{channel}' tenant='{tid}' customer='{cid}' session='{sid}' case='{case_id}' auth='{auth_level}'")

    @staticmethod
    def log_runtime_start():
        print(f"  {MAGENTA}🧠 [RUNTIME] Entering SupportRuntime -> LangGraph Brain...{RESET}")

    @staticmethod
    def log_runtime_reply(reply: str, latency_ms: Optional[float] = None, intent: Optional[str] = None):
        lat = f" ({latency_ms:.0f}ms)" if latency_ms is not None else ""
        int_str = f" [intent: {intent}]" if intent else ""
        print(f"  {GREEN}{BOLD}🤖 [REPLY]{RESET}{int_str}: \"{reply}\"{lat}")

    @staticmethod
    def log_tts_start(voice: str = "alloy"):
        print(f"  {CYAN}🔊 [TTS] Synthesizing speech via OpenAI TTS (voice: '{voice}')...{RESET}")

    @staticmethod
    def log_audio_out(duration_ms: Optional[float] = None):
        dur = f" ({duration_ms:.0f}ms)" if duration_ms is not None else ""
        print(f"  {GREEN}🎧 [AUDIO OUT] Streaming audio chunks to browser speaker{dur}{RESET}")

    @staticmethod
    def log_ttfa(ttfa_ms: Optional[float], stt_ms: Optional[float] = None, runtime_ms: Optional[float] = None, tts_ms: Optional[float] = None):
        print(f"  {DIM}┌────────────────────────────────────────────────────────────────────────────┐{RESET}")
        print(f"  {DIM}│{RESET} {BOLD}📊 LATENCY / TTFA BREAKDOWN:{RESET}{DIM}                                         │{RESET}")
        if stt_ms is not None:
            print(f"  {DIM}│{RESET}  • VAD -> STT:        {stt_ms:>7.1f} ms                                       {DIM}│{RESET}")
        if runtime_ms is not None:
            print(f"  {DIM}│{RESET}  • SupportRuntime:    {runtime_ms:>7.1f} ms                                       {DIM}│{RESET}")
        if tts_ms is not None:
            print(f"  {DIM}│{RESET}  • TTS Generation:    {tts_ms:>7.1f} ms                                       {DIM}│{RESET}")
        if ttfa_ms is not None:
            status = f"{GREEN}PASS (<2000ms){RESET}" if ttfa_ms <= 2000 else f"{YELLOW}MEASURED{RESET}"
            print(f"  {DIM}│{RESET}  {BOLD}• Time to First Audio (TTFA): {ttfa_ms:>7.1f} ms{RESET} [{status}]              {DIM}│{RESET}")
        print(f"  {DIM}└────────────────────────────────────────────────────────────────────────────┘{RESET}")

    @staticmethod
    def log_interruption(turn_was: str, count: int):
        print(f"\n  {RED}{BOLD}⚡ [INTERRUPTION DETECTED]{RESET} {YELLOW}User barged in while bot was {turn_was}! Canceling turn and stopping audio playback. (Total interruptions: {count}){RESET}\n")

    @staticmethod
    def log_writeback(session: Any):
        auth = getattr(session, "auth_level", "anonymous")
        verified = getattr(session, "verified", False)
        order = getattr(session, "pending_order_id", None)
        orders = getattr(session, "verified_order_ids", [])
        needs_id = getattr(session, "needs_identity", False)
        print(f"  {BLUE}💾 [SESSION STATE]{RESET} auth='{auth}' verified={verified} pending_order='{order}' verified_orders={orders} needs_identity={needs_id}")

    @staticmethod
    def log_handoff(from_channel: str, to_channel: str, session_id: str, case_id: Optional[str]):
        print(f"\n  {GREEN}{BOLD}🔄 [CHANNEL HANDOFF]{RESET} Handoff {from_channel.upper()} ➔ {to_channel.upper()} | Session: {session_id} | Case: {case_id or 'none'}")


obs = VoiceObserver()
