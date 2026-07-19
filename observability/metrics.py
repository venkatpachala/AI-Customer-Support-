from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

# ======================
# Counters
# ======================
REQUEST_COUNT = Counter(
    "d2c_requests_total",
    "Total number of chat requests",
    ["tenant_id", "status"]
)

ESCALATION_COUNT = Counter(
    "d2c_escalations_total",
    "Total number of escalated requests",
    ["tenant_id", "reason"]
)

BLOCK_COUNT = Counter(
    "d2c_blocks_total",
    "Total number of blocked requests",
    ["tenant_id"]
)

TOOL_COUNT = Counter(
    "d2c_tool_calls_total",
    "Total tool executions",
    ["tool_name", "status"]
)

RAG_COUNT = Counter(
    "d2c_rag_requests_total",
    "Total RAG retrievals",
    ["tenant_id", "status"]  # hit | miss
)

# ======================
# Histograms
# ======================
REQUEST_LATENCY = Histogram(
    "d2c_request_latency_seconds",
    "Request latency in seconds",
    ["tenant_id"],
    buckets=[0.5, 1, 2, 5, 10, 20, 30, 45, 60, 90]
)

NODE_LATENCY = Histogram(
    "d2c_node_latency_seconds",
    "Latency per node",
    ["node"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 45]
)

# ======================
# Gauges
# ======================
ACTIVE_REQUESTS = Gauge(
    "d2c_active_requests",
    "Number of currently active requests"
)

def metrics_endpoint():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )