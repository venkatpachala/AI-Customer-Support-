"""
Phase 1 voice bot — standalone Pipecat hello path.

Run:
  python -m voice.bot

Then open the runner UI (typically http://localhost:7860/client),
allow mic, and talk.

Does NOT call SupportRuntime / LangGraph.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.transports.base_transport import TransportParams

from voice.pipeline import build_phase1_pipeline


async def run_bot(transport, runner_args: RunnerArguments):
    logger.info("Phase 1 voice bot starting (no SupportRuntime)")
    pipeline, _, _ = build_phase1_pipeline(transport)

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
        ),
    )
    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)
    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    transport_params = {
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    }
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()