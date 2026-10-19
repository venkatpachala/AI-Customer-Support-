"""Model telemetry without retaining prompts or completions."""
import os
import time
from threading import Lock
from contextvars import ContextVar
from dataclasses import dataclass, field
from langchain_core.callbacks import BaseCallbackHandler
from prometheus_client import Counter, Histogram

TOKENS = Counter("d2c_model_tokens_total", "Reported provider tokens", ["model", "direction"])
CALLS = Counter("d2c_model_calls_total", "Provider model calls", ["model", "status"])
LATENCY = Histogram("d2c_model_latency_seconds", "Provider latency", ["model"], buckets=[.2,.5,1,2,5,10,20,40])
COST = Counter("d2c_model_estimated_cost_usd", "Estimated cost using operator-configured token prices", ["model"])
_usage = ContextVar("model_usage", default=None)


@dataclass
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    lock: Lock = field(default_factory=Lock)

    def snapshot(self):
        with self.lock:
            return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                    "calls": self.calls, "tokens_reported": bool(self.input_tokens or self.output_tokens)}


def begin_usage():
    usage = UsageTotals()
    return usage, _usage.set(usage)


def end_usage(token):
    _usage.reset(token)


class ModelMetrics(BaseCallbackHandler):
    def __init__(self, model):
        self.model, self.starts, self.lock = model, {}, Lock()

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        with self.lock:
            self.starts[run_id] = time.monotonic()

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.on_llm_start(serialized, None, run_id=run_id)

    def _finish(self, run_id, status):
        with self.lock:
            start = self.starts.pop(run_id, None)
        if start is not None:
            LATENCY.labels(self.model).observe(time.monotonic() - start)
        CALLS.labels(self.model, status).inc()

    def on_llm_end(self, response, *, run_id, **kwargs):
        self._finish(run_id, "success")
        usage = (response.llm_output or {}).get("token_usage", {})
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))
        totals = _usage.get()
        if totals:
            with totals.lock:
                totals.input_tokens += input_tokens
                totals.output_tokens += output_tokens
                totals.calls += 1
        TOKENS.labels(self.model, "input").inc(input_tokens)
        TOKENS.labels(self.model, "output").inc(output_tokens)
        if os.getenv("MODEL_INPUT_USD_PER_MILLION") and os.getenv("MODEL_OUTPUT_USD_PER_MILLION"):
            cost = (input_tokens * float(os.environ["MODEL_INPUT_USD_PER_MILLION"]) +
                    output_tokens * float(os.environ["MODEL_OUTPUT_USD_PER_MILLION"])) / 1_000_000
            COST.labels(self.model).inc(max(0.0, cost))

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._finish(run_id, "error")
