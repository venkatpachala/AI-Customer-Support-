"""
voice/server.py — Phase 2 Voice HTTP Server (SmallWebRTC + FastAPI).

Endpoints:
  POST /voice/offer      — WebRTC SDP negotiation (creates bot pipeline per connection)
  POST /voice/ice        — ICE candidate trickle
  GET  /voice/health     — Server health check
  GET  /voice/metrics    — Per-session TTFA and latency metrics
  GET  /                 — Serve browser voice client (frontend/voice.html)

Architecture:
  Browser → WebRTC → SmallWebRTCTransport → Pipecat Pipeline → SupportRuntime

Each WebRTC connection gets:
  - Its own VoiceSession (with call_id, session_id from query params)
  - Its own pipeline instance (VAD → STT → SupportRuntimeResponder → TTS)
  - Its own PipelineTask running in a background asyncio task

Context injection:
  Tenant/customer context is passed via query params on /voice/offer:
    ?tenant_id=zepto&customer_id=cust_123&session_id=sess_abc

Usage:
  python -m voice.server           # runs on localhost:7860
  VOICE_PORT=8001 python -m voice.server
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel

load_dotenv(override=True)

# Register tools before importing graph
from tools.bootstrap import register_default_tools
register_default_tools()

# Core imports
from config.loaders import load_tenant_config
from interactions.service import InteractionService
from memory.service import MemoryService
from observability.logging import log_event, new_request_id
from orchestration.graph import compiled_graph
from runtime.support_runtime import SupportRuntime

# Voice imports
from voice.adapter import SupportRuntimeAdapter
from voice.config import voice_config
from voice.context import VoiceSession
from voice.pipeline import build_pipeline_task, build_transport_params

# Pipecat SmallWebRTC
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.smallwebrtc.request_handler import (
    IceCandidate,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport


# ─── Session Registry ────────────────────────────────────────────────────────

_active_sessions: dict[str, VoiceSession] = {}


# ─── Runtime Singleton ───────────────────────────────────────────────────────

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


# ─── WebRTC Handler ─────────────────────────────────────────────────────────

_webrtc_handler = SmallWebRTCRequestHandler()


# ─── App lifecycle ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    voice_config.validate()
    logger.info(f"[server] Voice server starting — {voice_config}")
    yield
    logger.info("[server] Voice server shutting down")
    await _webrtc_handler.close()


app = FastAPI(
    title="D2C Voice Server (Phase 2)",
    description="Realtime voice interface to SupportRuntime via Pipecat + SmallWebRTC",
    lifespan=lifespan,
)

# Serve browser client
_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
_VOICE_HTML = _FRONTEND_DIR / "voice.html"


# ─── Request / Response models ───────────────────────────────────────────────

class OfferRequest(BaseModel):
    """WebRTC SDP offer from browser client."""
    sdp: str
    type: str
    pc_id: Optional[str] = None
    restart_pc: Optional[bool] = None
    # Context fields (also accepted as query params)
    tenant_id: Optional[str] = None
    customer_id: Optional[str] = None
    session_id: Optional[str] = None
    language: Optional[str] = None


class IceCandidateRequest(BaseModel):
    pc_id: str
    candidates: list[dict]


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def serve_voice_ui():
    """Serve the browser voice client."""
    if _VOICE_HTML.exists():
        return FileResponse(str(_VOICE_HTML))
    return JSONResponse(
        {"error": "voice.html not found", "path": str(_VOICE_HTML)},
        status_code=404,
    )


@app.get("/voice/health")
async def health():
    """Health check — confirms server is running and config is valid."""
    return {
        "status": "ok",
        "version": "phase2",
        "stt": voice_config.stt_provider,
        "tts": voice_config.tts_provider,
        "active_calls": len(_active_sessions),
    }


@app.get("/voice/metrics")
async def metrics():
    """Per-session TTFA and latency metrics."""
    return {
        "active_calls": len(_active_sessions),
        "sessions": [s.metrics_summary() for s in _active_sessions.values()],
    }


@app.post("/voice/offer")
async def voice_offer(
    body: OfferRequest,
    tenant_id: str = Query("zepto"),
    customer_id: str = Query("voice_demo_user"),
    session_id: Optional[str] = Query(None),
    language: str = Query("en"),
):
    """
    WebRTC SDP offer endpoint.

    Creates a new bot pipeline for each new peer connection.
    Context (tenant_id, customer_id, session_id) is injected via query params
    or request body. Query params take precedence over body fields.
    """
    # Resolve context — query params win over body
    resolved_tenant = tenant_id or body.tenant_id or "zepto"
    resolved_customer = customer_id or body.customer_id or "voice_demo_user"
    resolved_session = session_id or body.session_id or None
    resolved_language = language or body.language or "en"

    logger.info(
        f"[offer] tenant={resolved_tenant!r} customer={resolved_customer!r} "
        f"session={resolved_session!r} lang={resolved_language!r}"
    )

    request = SmallWebRTCRequest(
        sdp=body.sdp,
        type=body.type,
        pc_id=body.pc_id,
        restart_pc=body.restart_pc,
    )

    async def on_webrtc_connection(webrtc_connection):
        """Callback invoked for each new WebRTC peer connection."""
        # Build VoiceSession for this call
        session = VoiceSession(
            tenant_id=resolved_tenant,
            customer_id=resolved_customer,
            session_id=resolved_session,
            language=resolved_language,
        )
        _active_sessions[session.call_id] = session

        logger.info(
            f"[call] New call call_id={session.call_id[:8]} "
            f"tenant={resolved_tenant!r} customer={resolved_customer!r}"
        )

        # Build transport from WebRTC connection
        transport_params = build_transport_params(voice_config)
        transport = SmallWebRTCTransport(
            params=transport_params,
            webrtc_connection=webrtc_connection,
        )

        # Build runtime + adapter
        runtime = _build_runtime()
        adapter = SupportRuntimeAdapter(runtime)

        # Build pipeline task
        task = build_pipeline_task(transport, adapter, session)

        # Run pipeline in background task
        async def _run():
            runner = PipelineRunner(handle_sigint=False)
            try:
                await runner.run(task)
            except Exception as exc:
                logger.exception(f"[call] pipeline error call_id={session.call_id[:8]}: {exc}")
            finally:
                _active_sessions.pop(session.call_id, None)
                logger.info(f"[call] Ended call_id={session.call_id[:8]}")

        asyncio.create_task(_run())

    try:
        answer = await _webrtc_handler.handle_web_request(request, on_webrtc_connection)
        return JSONResponse(answer)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"[offer] Error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/voice/ice")
async def voice_ice(body: IceCandidateRequest):
    """ICE candidate trickle endpoint."""
    from pipecat.transports.smallwebrtc.request_handler import (
        IceCandidate,
        SmallWebRTCPatchRequest,
    )

    candidates = [
        IceCandidate(
            candidate=c.get("candidate", ""),
            sdp_mid=c.get("sdpMid", "0"),
            sdp_mline_index=int(c.get("sdpMLineIndex", 0)),
        )
        for c in body.candidates
    ]

    patch = SmallWebRTCPatchRequest(pc_id=body.pc_id, candidates=candidates)
    try:
        await _webrtc_handler.handle_patch_request(patch)
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"[ice] Error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = voice_config.host
    port = voice_config.port

    logger.info(f"Starting voice server on {host}:{port}")
    uvicorn.run(
        "voice.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
