"""요청 제한 정책의 단일 진입점."""

import os

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from .api.auth import get_current_user_id


RATE_LIMIT_SIGNUP = os.getenv("RATE_LIMIT_SIGNUP", "5/minute")
RATE_LIMIT_LOGIN = os.getenv("RATE_LIMIT_LOGIN", "5/minute")
RATE_LIMIT_UPLOAD = os.getenv("RATE_LIMIT_UPLOAD", "20/minute")
RATE_LIMIT_QUERY = os.getenv("RATE_LIMIT_QUERY", "30/minute")
RATE_LIMIT_CHAT = os.getenv("RATE_LIMIT_CHAT", "30/minute")


def client_ip_key(request: Request) -> str:
    """Uvicorn이 검증한 직전 peer 주소만 사용한다."""
    return request.client.host if request.client else "unknown-client"


def authenticated_user_key(request: Request) -> str:
    user_id = get_current_user_id()
    return f"user:{user_id}" if user_id is not None else "user:dev-anonymous"


limiter = Limiter(key_func=client_ip_key)


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    response = JSONResponse(
        status_code=429,
        content={"detail": "요청 한도를 초과했습니다.", "code": "RATE_LIMIT_EXCEEDED"},
    )
    return response
