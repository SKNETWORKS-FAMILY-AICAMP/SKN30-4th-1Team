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
        # exc_info[0] is not None까지 확인 — logging은 활성 예외가 없을 때 exc_info=True를
        # sys.exc_info()인 (None,None,None)으로 정규화하는데, 이 튜플은 truthy라 그냥
        # 통과시키면 None.__name__에서 포매터가 죽고 그 로그 라인이 통째로 유실된다.
        # (1차 소비자는 propagate 설정된 uvicorn 등 서드파티 로거다.)
        # 값이 없으면 위 루프가 넣은 extra의 exception_type을 그대로 살려 둔다.
        if record.exc_info and record.exc_info[0] is not None:
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
