from typing import Any

from fastapi.responses import JSONResponse

from ..request_context import get_request_id


def error_response(status_code: int, detail: Any, *, code: str | None = None) -> JSONResponse:
    content: dict[str, Any] = {"detail": detail, "request_id": get_request_id()}
    if code is not None:
        content["code"] = code
    return JSONResponse(status_code=status_code, content=content)
