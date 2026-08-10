from typing import Any, Dict, Optional, Literal
from pydantic import BaseModel, Field


class ToolResponse(BaseModel):
    success: bool
    status: Literal["success", "error", "skipped", "requires_approval"] = "success"
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable: bool = False
    provider: str
    operation: str
    latency_ms: float = 0.0
    attempts: int = 1
    meta: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        *,
        provider: str,
        operation: str,
        data: Dict[str, Any],
        latency_ms: float,
        attempts: int = 1,
        status: str = "success",
        meta: Optional[Dict[str, Any]] = None,
    ) -> "ToolResponse":
        return cls(
            success=True,
            status=status,
            data=data,
            provider=provider,
            operation=operation,
            latency_ms=latency_ms,
            attempts=attempts,
            meta=meta or {},
        )

    @classmethod
    def fail(
        cls,
        *,
        provider: str,
        operation: str,
        error_code: str,
        error_message: str,
        latency_ms: float,
        attempts: int = 1,
        retryable: bool = False,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "ToolResponse":
        return cls(
            success=False,
            status="error",
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            provider=provider,
            operation=operation,
            latency_ms=latency_ms,
            attempts=attempts,
            meta=meta or {},
        )