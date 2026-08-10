from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel

from tools.base.auth import AuthStrategy, NoAuth
from tools.base.context import ToolContext
from tools.base.response import ToolResponse
from tools.base.retry import RetryPolicy
from tools.base.rate_limit import TokenBucketRateLimiter
from tools.base.validator import validate_request
from tools.base.metrics import Timer, record_tool_result
from tools.base.exceptions import ToolError, ValidationError
from observability.logging import log_event


class BaseTool(ABC):
    name: str = "base.tool"
    provider: str = "base"
    timeout_seconds: float = 10.0
    max_retries: int = 3
    idempotent: bool = False
    request_model: Optional[Type[BaseModel]] = None

    def __init__(
        self,
        auth: Optional[AuthStrategy] = None,
        rate_limiter: Optional[TokenBucketRateLimiter] = None,
        retry_policy: Optional[RetryPolicy] = None,
    ):
        self.auth = auth or NoAuth()
        self.rate_limiter = rate_limiter
        self.retry_policy = retry_policy or RetryPolicy(max_retries=self.max_retries)

    def execute(self, request: Dict[str, Any], context: ToolContext) -> ToolResponse:
        timer = Timer()
        attempts = 0

        try:
            # 1. Validate
            validated = request
            if self.request_model is not None:
                validated_model = validate_request(self.request_model, request)
                validated = validated_model.dict()

            # 2. Rate limit
            if self.rate_limiter is not None:
                self.rate_limiter.acquire()

            # 3. Auth headers preparation is done inside _run if needed,
            # but auth strategy is available to subclass via self.auth

            def _call():
                nonlocal attempts
                attempts += 1
                return self._run(validated, context)

            # 4. Retry wrapper
            data = self.retry_policy.run(_call)

            latency = timer.ms()
            record_tool_result(self.name, "success", latency)

            log_event(
                "tool_success",
                context.request_id,
                node="tool",
                data={
                    "tool": self.name,
                    "provider": self.provider,
                    "latency_ms": latency,
                    "attempts": attempts,
                    "tenant_id": context.tenant_id,
                },
            )

            # Allow subclass to return ToolResponse directly if needed
            if isinstance(data, ToolResponse):
                data.attempts = attempts
                data.latency_ms = latency
                return data

            return ToolResponse.ok(
                provider=self.provider,
                operation=self.name,
                data=data if isinstance(data, dict) else {"result": data},
                latency_ms=latency,
                attempts=attempts,
            )

        except ToolError as e:
            latency = timer.ms()
            status = "error"
            record_tool_result(self.name, status, latency)
            log_event(
                "tool_error",
                context.request_id,
                node="tool",
                data={
                    "tool": self.name,
                    "provider": self.provider,
                    "error_code": e.code,
                    "error_message": e.message,
                    "retryable": e.retryable,
                    "latency_ms": latency,
                    "attempts": max(attempts, 1),
                    "tenant_id": context.tenant_id,
                },
                level="warning",
            )
            return ToolResponse.fail(
                provider=self.provider,
                operation=self.name,
                error_code=e.code,
                error_message=e.message,
                latency_ms=latency,
                attempts=max(attempts, 1),
                retryable=e.retryable,
            )
        except Exception as e:
            latency = timer.ms()
            record_tool_result(self.name, "error", latency)
            log_event(
                "tool_error",
                context.request_id,
                node="tool",
                data={
                    "tool": self.name,
                    "provider": self.provider,
                    "error_code": "unhandled_error",
                    "error_message": str(e),
                    "latency_ms": latency,
                    "attempts": max(attempts, 1),
                    "tenant_id": context.tenant_id,
                },
                level="error",
            )
            return ToolResponse.fail(
                provider=self.provider,
                operation=self.name,
                error_code="unhandled_error",
                error_message=str(e),
                latency_ms=latency,
                attempts=max(attempts, 1),
                retryable=False,
            )

    @abstractmethod
    def _run(self, request: Dict[str, Any], context: ToolContext) -> Dict[str, Any] | ToolResponse:
        """
        Provider-specific business logic.
        Should raise ToolError subclasses on failure.
        """
        raise NotImplementedError