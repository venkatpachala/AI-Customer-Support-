"""
voice/bot.py — Pipecat runner entry point for voice bot.

This runs via the Pipecat development runner:
  python -m voice.bot [--transport webrtc] [--host localhost] [--port 7860]

The runner auto-wires:
  CLI args → SmallWebRTCRunnerArguments → create_transport()
  → transport + callback → bot(runner_args) → run_bot()

For production use, prefer voice/server.py (full FastAPI integration).
For quick prototyping / Pipecat CLI, use this file.
"""
from __future__ import annotations

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

# Register tools before importing graph
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
from voice.pipeline import build_pipeline_task, build_transport_params

from pipecat.pipeline.runner import PipelineRunner
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import TransportParams


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


async def run_bot(transport, runner_args: RunnerArguments):
    """Run one voice call pipeline."""
    logger.info("[bot] Phase 2 voice pipeline starting")
    voice_config.validate()

    runtime = _build_runtime()
    adapter = SupportRuntimeAdapter(runtime)

    session = VoiceSession(
        tenant_id="zepto",
        customer_id="bot_demo_user",
        auth_level="anonymous",
    )
    logger.info(f"[bot] VoiceSession call_id={session.call_id} customer={session.customer_id}")

    task = build_pipeline_task(transport, adapter, session, voice_config)

    runner = PipelineRunner(handle_sigint=True)
    await runner.run(task)

    logger.info(f"[bot] Call ended. Turns={session.turn_count} avg_ttfa={session.avg_ttfa_ms()}")


async def bot(runner_args: RunnerArguments):
    """
    Pipecat bot entry point — called by the runner for each connection.
    """
    transport_params = {
        "webrtc": lambda: build_transport_params(voice_config),
    }
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main
    main()