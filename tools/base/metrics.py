import time
from typing import Optional

try:
    from observability.metrics import TOOL_COUNT, NODE_LATENCY
except Exception:
    TOOL_COUNT = None
    NODE_LATENCY = None


def record_tool_result(tool_name: str, status: str, latency_ms: float):
    if TOOL_COUNT is not None:
        try:
            TOOL_COUNT.labels(tool_name=tool_name, status=status).inc()
        except Exception:
            pass

    # Optional: reuse histogram if desired
    if NODE_LATENCY is not None:
        try:
            NODE_LATENCY.labels(node=f"tool:{tool_name}").observe(latency_ms / 1000.0)
        except Exception:
            pass


class Timer:
    def __init__(self):
        self.start = time.time()

    def ms(self) -> float:
        return round((time.time() - self.start) * 1000.0, 2)