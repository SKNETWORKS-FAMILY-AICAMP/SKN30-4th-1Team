import json
import logging
import sys
from datetime import datetime, timezone

from .config import log_level
from .request_context import get_request_id


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": get_request_id(),
        }
        for key in (
            "method",
            "route",
            "status",
            "duration_ms",
            "project_id",
            "user_id",
            "code",
            "exception_type",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> None:
    root = logging.getLogger()
    level = getattr(logging, log_level())
    root.setLevel(level)
    json_handler = None
    for handler in root.handlers:
        if getattr(handler, "_paim_json", False):
            json_handler = handler
            break
    if json_handler is None:
        json_handler = logging.StreamHandler(sys.stdout)
        json_handler._paim_json = True  # type: ignore[attr-defined]
        json_handler.setFormatter(JsonFormatter())
        root.addHandler(json_handler)
    json_handler.setLevel(level)

    # Uvicorn configures non-propagating handlers before importing an ASGI app
    # when launched from its CLI. Those handlers bypass the JSON root logger,
    # and the default access formatter includes the raw query string.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
    access_logger.disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
        uvicorn_logger.disabled = False
        uvicorn_logger.setLevel(level)
