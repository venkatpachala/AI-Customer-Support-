# Phase 2 — Realtime Voice Foundation

Real-time voice interface to `SupportRuntime` via **Pipecat 1.7.0** + **SmallWebRTC**.

```
Browser → Microphone → WebRTC → Pipecat Pipeline → SupportRuntimeAdapter → SupportRuntime → LangGraph
                                (VAD + STT + TTS)
```

## Architecture

```
BROWSER
  │ microphone / speaker
  │ WebRTC (native browser API)
  ▼
voice/server.py (FastAPI port 7860)
  │ SmallWebRTCRequestHandler — one pipeline per connection
  ▼
Pipecat Pipeline (per call):
  transport.input()
    → [AudioDebugProcessor]  ← optional (VOICE_DEBUG_AUDIO=true)
    → OpenAISTTService       ← Whisper via OpenAI
    → SupportRuntimeResponder
        │ InterruptionFrame → barge-in handled
        │ TranscriptionFrame → SupportRuntime.handle()
        │ → VoiceSession tracked (TTFA, auth, order_id)
    → OpenAITTSService       ← OpenAI TTS-1
  transport.output()
  ▼
SupportRuntimeAdapter (voice/adapter.py)
  │ Greeting short-circuit (no runtime call for hi/hello/etc)
  │ Builds RequestContext with channel="voice"
  │ Session writeback (auth_level, order_id, case_id, needs_identity)
  ▼
SupportRuntime (runtime/support_runtime.py)
  ▼
LangGraph → Supervisor → Planner → Executor → Verifier → QA
```

## Quick Start

### 1. Start the voice server

```powershell
# In your D2C project root
.\.venv\Scripts\python.exe -m voice.server
```

Server starts at: `http://localhost:7860`

### 2. Open the browser client

Open `http://localhost:7860` in Chrome/Edge (Firefox also works).

Or open `frontend/voice.html` directly.

### 3. Configure context (optional)

In the browser UI, set:
- **Tenant**: your tenant ID (default: `zepto`)
- **Customer**: customer ID (default: `voice_demo_user`)
- **Session**: paste a chat session ID for cross-channel test (optional)
- **Language**: `en` (default)

### 4. Click "🎙️ Start Voice"

- Browser requests microphone permission
- WebRTC connection established
- Status shows: `LISTENING`
- Speak — see `USER SPEAKING` → `PROCESSING` → `BOT SPEAKING`
- Interrupt the bot mid-sentence — it stops immediately

## Configuration

Add to `.env`:

```env
# Voice server
VOICE_HOST=localhost
VOICE_PORT=7860

# STT provider: openai (default) | deepgram | sarvam
VOICE_STT_PROVIDER=openai
VOICE_STT_LANGUAGE=en

# TTS provider: openai (default) | elevenlabs | sarvam
VOICE_TTS_PROVIDER=openai
VOICE_TTS_VOICE=alloy        # alloy | echo | fable | onyx | nova | shimmer

# VAD
VOICE_VAD_SILENCE_MS=800     # ms of silence before turn ends
VOICE_ALLOW_INTERRUPTIONS=true
VOICE_IDLE_TIMEOUT=300       # seconds

# Debug
VOICE_DEBUG_AUDIO=false      # set true to log every audio frame

# Latency targets (ms) — used in assertions
VOICE_TARGET_STT_MS=500
VOICE_TARGET_RUNTIME_MS=800
VOICE_TARGET_TTS_MS=500
VOICE_TARGET_TTFA_MS=2000
```

## File Structure

```
voice/
├── __init__.py              — Module exports
├── server.py                — FastAPI WebRTC server (main entry point)
├── bot.py                   — Pipecat CLI runner (alternative entry point)
├── pipeline.py              — build_phase2_pipeline() + build_pipeline_task()
├── adapter.py               — SupportRuntimeAdapter: Pipecat ↔ SupportRuntime
├── context.py               — VoiceSession + LatencyRecord (TTFA tracking)
├── config.py                — VoiceConfig (env-driven)
├── events.py                — VoiceSessionStatus + VoiceEvent lifecycle events
│
├── stt/
│   └── provider.py          — STT factory: get_stt_service(config)
│
├── tts/
│   └── provider.py          — TTS factory: get_tts_service(config)
│
├── processors/
│   ├── runtime_responder.py — Core: TranscriptionFrame → SupportRuntime → TTS
│   ├── transcript.py        — TranscriptLogger: logs STT output with timestamps
│   ├── response.py          — shape_for_voice(): strips markdown, trims to 2 sentences
│   └── audio_debug.py       — AudioDebugProcessor: logs mic audio frames
│
└── tests/
    ├── test_voice_session.py  — LatencyRecord, auth ladder, lifecycle
    ├── test_adapter.py        — SupportRuntimeAdapter (greeting, context, writeback)
    ├── test_pipeline.py       — SupportRuntimeResponder, response shaper, logger
    └── test_end_to_end.py     — Full scenarios: greeting, return, multi-turn, cross-channel
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Browser voice client (voice.html) |
| `GET` | `/voice/health` | Server health + config |
| `GET` | `/voice/metrics` | Per-session TTFA + latency metrics |
| `POST` | `/voice/offer` | WebRTC SDP negotiation |
| `POST` | `/voice/ice` | ICE candidate trickle |

### Context injection

Pass tenant/customer context via query params on `/voice/offer`:
```
POST /voice/offer?tenant_id=zepto&customer_id=cust_123&session_id=sess_abc
```

## TTFA Latency Architecture

Voice latency is measured across 5 timestamps per turn:

| Timestamp | Label | Target |
|-----------|-------|--------|
| T0 | User stops speaking (VAD) | — |
| T1 | STT final transcript | < 500ms from T0 |
| T2 | SupportRuntime starts | < 800ms from T1 |
| T3 | RuntimeResponse received | — |
| T4 | First audio played (TTFA) | < 2000ms from T0 |

Check TTFA at: `GET /voice/metrics`

## Running Tests

```powershell
# All voice tests (85 tests, no hardware needed)
.\.venv\Scripts\python.exe -m pytest voice/tests/ -v

# Individual suites
.\.venv\Scripts\python.exe -m pytest voice/tests/test_voice_session.py -v
.\.venv\Scripts\python.exe -m pytest voice/tests/test_adapter.py -v
.\.venv\Scripts\python.exe -m pytest voice/tests/test_pipeline.py -v
.\.venv\Scripts\python.exe -m pytest voice/tests/test_end_to_end.py -v
```

## Phase 2 Acceptance Tests

| Test | Status |
|------|--------|
| Browser connects, mic works | ✅ Manual |
| STT produces final transcript | ✅ Automated |
| Silence doesn't trigger requests | ✅ Automated |
| Turn boundaries work | ✅ Automated |
| Transcript reaches SupportRuntime with `channel=voice` | ✅ Automated |
| Correct tenant_id / customer_id / session_id | ✅ Automated |
| Response from LangGraph (not a new LLM) | ✅ Automated |
| AI can be interrupted (TTS stops) | ✅ Automated |
| Memory persists across voice turns | ✅ Automated |
| Chat→Voice session handoff | ✅ Automated |

## Adding a New STT/TTS Provider

1. Edit `voice/stt/provider.py` or `voice/tts/provider.py`
2. Add your provider case to `get_stt_service()` / `get_tts_service()`
3. Set `VOICE_STT_PROVIDER=your_provider` in `.env`
4. No pipeline changes required