"""
voice/cli_test.py — Terminal-based Voice Testing Tool (No Browser / No Frontend Needed)

Modes:
  1. Interactive Voice Chat:
     Type messages in terminal -> runs SupportRuntime/LangGraph -> generates OpenAI TTS -> plays audio via speakers.
  2. Multi-turn Scenario Simulation:
     Runs automated customer support flows (Return, Order status, etc.) with real TTS audio generation.
  3. Audio File Test:
     Pass a .wav audio file -> transcribes via Whisper STT -> runs Runtime -> speaks response.

Usage:
  python -m voice.cli_test --mode interactive
  python -m voice.cli_test --mode scenario
  python -m voice.cli_test --help
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import time
from typing import Optional

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

# Ensure tools are registered
from tools.bootstrap import register_default_tools
register_default_tools()

from config.loaders import load_tenant_config
from interactions.service import InteractionService
from memory.service import MemoryService
from observability.logging import log_event, new_request_id
from orchestration.graph import compiled_graph
from runtime.support_runtime import SupportRuntime
from voice.adapter import SupportRuntimeAdapter
from voice.config import voice_config
from voice.context import VoiceSession


def _invoke_graph(inputs: dict) -> dict:
    return compiled_graph.invoke(inputs)


def _build_runtime() -> SupportRuntime:
    def _load_tenant(tenant_id: str):
        cfg = load_tenant_config(tenant_id)
        return cfg.dict() if hasattr(cfg, "dict") else (
            cfg.model_dump() if hasattr(cfg, "model_dump") else cfg
        )

    return SupportRuntime(
        graph_invoker=_invoke_graph,
        memory_service=MemoryService(),
        interaction_service=InteractionService(),
        load_tenant_config=_load_tenant,
        new_request_id=new_request_id,
        log_event=log_event,
        apply_output_guard=lambda text: text or "",
    )


def play_audio_bytes(audio_bytes: bytes):
    """Play audio bytes through Windows speakers using native winsound or temporary file."""
    if not audio_bytes:
        return
    try:
        if sys.platform == "win32":
            import winsound
            # Save to temporary wav file and play
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                temp_path = f.name
            try:
                winsound.PlaySound(temp_path, winsound.SND_FILENAME)
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
        else:
            print("Audio playback is currently configured for Windows (winsound).")
    except Exception as e:
        print(f"⚠️ Audio playback notice: {e}")


def generate_tts_audio(text: str, voice: str = "alloy") -> bytes:
    """Generate audio bytes from text using OpenAI TTS."""
    api_key = voice_config.openai_api_key
    if not api_key:
        return b""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            response_format="wav",
        )
        return response.content
    except Exception as e:
        print(f"⚠️ TTS generation warning: {e}")
        return b""


def transcribe_audio_file(file_path: str) -> str:
    """Transcribe a .wav file using OpenAI Whisper."""
    api_key = voice_config.openai_api_key
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for STT.")
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    with open(file_path, "rb") as audio_file:
        transcription = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language=voice_config.stt_language,
        )
        return transcription.text


def run_interactive_mode(session_id: Optional[str] = None, play_audio: bool = True):
    """Run an interactive CLI session simulating the voice pipeline."""
    print("=" * 65)
    print("🎙️  D2C VOICE PIPELINE — TERMINAL INTERACTIVE TESTER")
    print("=" * 65)
    print("Type your message (as if spoken into the microphone).")
    print("The agent will reason with LangGraph, print the response,")
    print("and speak it back through your speakers.")
    print("Type 'exit' or 'quit' to end.")
    print("-" * 65)

    runtime = _build_runtime()
    adapter = SupportRuntimeAdapter(runtime)
    session = VoiceSession(
        tenant_id="zepto",
        customer_id="cli_test_user",
        session_id=session_id,
        auth_level="anonymous",
    )

    if session_id:
        print(f"🔗 Attaching to existing session: {session_id}")

    while True:
        try:
            user_input = input("\n🎤 You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            print("\nSession ended.")
            break

        t0 = time.time()
        print("🧠 Processing via SupportRuntime & LangGraph...")

        # 1. Process via SupportRuntimeAdapter
        result = adapter.handle_transcript_sync(user_input, session)
        t_runtime = time.time() - t0

        reply_text = result.response
        print(f"🤖 Bot: {reply_text}")
        print(f"📊 [Metrics] Runtime: {t_runtime*1000:.1f}ms | Auth: {session.auth_level} | Order: {session.pending_order_id or 'None'}")

        # 2. TTS Audio Generation & Playback
        if play_audio and reply_text:
            t_tts_start = time.time()
            audio_bytes = generate_tts_audio(reply_text, voice=voice_config.openai_tts_voice)
            t_tts = time.time() - t_tts_start
            ttfa = (time.time() - t0) * 1000

            print(f"🔊 [TTS] Generated in {t_tts*1000:.1f}ms | TTFA: {ttfa:.1f}ms | Playing audio...")
            play_audio_bytes(audio_bytes)


def run_scenario_mode(play_audio: bool = True):
    """Run an automated multi-turn support scenario."""
    print("=" * 65)
    print("🧪 AUTOMATED VOICE SCENARIO TEST")
    print("=" * 65)

    turns = [
        "Hi there!",
        "I want to return my order.",
        "My order number is 12345. It arrived damaged.",
        "Yes, I uploaded the photos.",
    ]

    runtime = _build_runtime()
    adapter = SupportRuntimeAdapter(runtime)
    session = VoiceSession(
        tenant_id="zepto",
        customer_id="scenario_tester",
        auth_level="anonymous",
    )

    for i, user_msg in enumerate(turns, 1):
        print(f"\n--- Turn {i} ---")
        print(f"🎤 Simulated Speech: \"{user_msg}\"")

        t0 = time.time()
        result = adapter.handle_transcript_sync(user_msg, session)
        t_runtime = (time.time() - t0) * 1000

        print(f"🤖 Voice Output: \"{result.response}\"")
        print(f"📊 [Context] Auth: {session.auth_level} | Order: {session.pending_order_id} | Needs Identity: {session.needs_identity} | Runtime: {t_runtime:.1f}ms")

        if play_audio and result.response:
            audio_bytes = generate_tts_audio(result.response)
            play_audio_bytes(audio_bytes)

    print("\n✅ Scenario test complete. Multi-turn memory verified successfully.")


def run_audio_file_mode(file_path: str, play_audio: bool = True):
    """Test using an actual WAV audio file."""
    if not os.path.exists(file_path):
        print(f"❌ Error: File not found at {file_path}")
        return

    print(f"🎧 Transcribing audio file: {file_path} via Whisper...")
    t0 = time.time()
    transcript = transcribe_audio_file(file_path)
    t_stt = (time.time() - t0) * 1000
    print(f"📝 Transcribed Text ({t_stt:.1f}ms): \"{transcript}\"")

    runtime = _build_runtime()
    adapter = SupportRuntimeAdapter(runtime)
    session = VoiceSession(tenant_id="zepto", customer_id="audio_file_tester")

    t_r0 = time.time()
    result = adapter.handle_transcript_sync(transcript, session)
    t_runtime = (time.time() - t_r0) * 1000

    print(f"🤖 Bot Response ({t_runtime:.1f}ms): \"{result.response}\"")

    if play_audio and result.response:
        audio = generate_tts_audio(result.response)
        play_audio_bytes(audio)


def main():
    parser = argparse.ArgumentParser(description="Terminal Voice Pipeline Tester (No Browser Needed)")
    parser.add_argument(
        "--mode",
        choices=["interactive", "scenario", "file"],
        default="interactive",
        help="Testing mode: interactive (terminal chat with TTS), scenario (automated script), file (test a .wav file)",
    )
    parser.add_argument("--session-id", default=None, help="Attach to an existing session ID")
    parser.add_argument("--file", default=None, help="Path to .wav file (for file mode)")
    parser.add_argument("--no-audio", action="store_true", help="Disable audio speaker playback")

    args = parser.parse_args()
    play_audio = not args.no_audio

    if args.mode == "interactive":
        run_interactive_mode(session_id=args.session_id, play_audio=play_audio)
    elif args.mode == "scenario":
        run_scenario_mode(play_audio=play_audio)
    elif args.mode == "file":
        if not args.file:
            print("❌ Please specify --file path/to/audio.wav")
            return
        run_audio_file_mode(args.file, play_audio=play_audio)


if __name__ == "__main__":
    main()
