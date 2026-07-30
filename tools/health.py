from typing import Any, Dict
from pydantic import BaseModel, Field

from tools.base.tool import BaseTool
from tools.base.context import ToolContext
from tools.base.rate_limit import TokenBucketRateLimiter


class HealthRequest(BaseModel):
    ping: str = Field(default="ping")


class HealthTool(BaseTool):
    name = "system.health"
    provider = "system"
    timeout_seconds = 2.0
    max_retries = 0
    idempotent = True
    request_model = HealthRequest

    def __init__(self):
        super().__init__(
            rate_limiter=TokenBucketRateLimiter(rate_per_sec=20, burst=40)
        )

    def _run(self, request: Dict[str, Any], context: ToolContext) -> Dict[str, Any]:
        return {
            "pong": request.get("ping", "ping"),
            "tenant_id": context.tenant_id,
            "request_id": context.request_id,
        }