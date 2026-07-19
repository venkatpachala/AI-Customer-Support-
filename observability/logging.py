import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional
import uuid

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
    extra = {
        "extra_data": {
            "event": event,
            "request_id": request_id,
            "node": node,
            **(data or {})
        }
    }

    if level == "error":
        logger.error(event, extra=extra)
    elif level == "warning":
        logger.warning(event, extra=extra)
    else:
        logger.info(event, extra=extra)