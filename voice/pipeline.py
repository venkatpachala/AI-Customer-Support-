"""
Phase 1 pipeline: transport → STT → LLM → TTS → transport.
No SupportRuntime. No business tools.
"""

from __future__ import annotations

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.transports.base_transport import BaseTransport

from voice.config import voice_config


def build_phase1_pipeline(transport: BaseTransport) -> tuple[Pipeline, object, object]:
    """
    Returns (pipeline, task-ready aggregators info).
    Import STT/LLM/TTS inside to fail clearly if extras missing.
    """
    voice_config.validate()

    # Imports may differ slightly by pipecat version — adjust if needed after first run.
    from pipecat.services.openai.stt import OpenAISTTService
    from pipecat.services.openai.llm import OpenAILLMService
    from pipecat.services.openai.tts import OpenAITTSService

    stt = OpenAISTTService(api_key=voice_config.openai_api_key)
    llm = OpenAILLMService(
        api_key=voice_config.openai_api_key,
        model=voice_config.openai_model,
    )
    tts = OpenAITTSService(
        api_key=voice_config.openai_api_key,
        voice=voice_config.openai_tts_voice,
    )

    messages = [
        {"role": "system", "content": voice_config.system_prompt},
    ]
    context = LLMContext(messages)
    user_agg, assistant_agg = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_agg,
            llm,
            tts,
            transport.output(),
            assistant_agg,
        ]
    )
    return pipeline, user_agg, assistant_agg