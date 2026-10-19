import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional
import uuid
import re

_PRIVATE = {"message", "query", "response", "prompt", "content", "text", "message_preview", "contact", "email", "phone", "token", "password", "authorization", "secret", "api_key"}


def redact(value, key: str = ""):
    if key.lower() in _PRIVATE or any(part in key.lower() for part in ("access_token", "secret_key", "password")):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?:sk|pk)_(?:live|test)_[A-Za-z0-9_-]+", "[redacted]", value)
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", value)
        return value[:1000]
    return value

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Add extra fields
        if hasattr(record, "extra_data"):
            log_record.update(record.extra_data)

        return json.dumps(log_record, default=str)

def get_logger(name: str = "d2c_agent"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)

    return logger

logger = get_logger()

def new_request_id() -> str:
    return str(uuid.uuid4())

def log_event(
    event: str,
    request_id: str,
    node: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    level: str = "info"
):
    from controlplane.tenant_context import current_scope

    scope = current_scope()
    payload = redact(dict(data or {}))
    payload.setdefault("tenant_id", scope.tenant_id or None)
    payload.setdefault("case_id", scope.case_id or None)
    extra = {
        "extra_data": {
            "event": event,
            "request_id": request_id or scope.request_id,
            "node": node,
            **payload,
        }
    }

    if level == "error":
        logger.error(event, extra=extra)
    elif level == "warning":
        logger.warning(event, extra=extra)
    else:
        logger.info(event, extra=extra)
