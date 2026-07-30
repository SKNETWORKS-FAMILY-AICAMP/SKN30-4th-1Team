import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.errors import error_response
from .api.health import router as health_router
from .api.auth import AuthMiddleware
from .api.auth_routes import router as auth_router
from .api.member import router as member_router
from .api.project import router as project_router
from .api.documents import router as documents_router
from .api.memory import router as memory_router
from .api.query import router as query_router
from .api.repository import router as repository_router
from .api.suggestion import router as suggestion_router
from .api.delta import router as delta_router
from .api.capabilities import router as capabilities_router
from .chat.router import router as chat_router
from .stt.router import router as stt_router
from .github.router import router as github_router, SessionExpiredException
from .rate_limit import limiter, rate_limit_exceeded_handler
from .config import cors_origins, validate_phase_b_config
from .logging_config import configure_logging
from .request_context import reset_request_id, set_request_id


validate_phase_b_config()
configure_logging()
logger = logging.getLogger(__name__)


class SafeErrorMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        response_started = False

        async def tracked_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception as exc:
            if response_started:
                raise
            logger.error(
                "unhandled_request_error",
                extra={"exception_type": type(exc).__name__},
            )
            response = error_response(500, "내부 서버 오류가 발생했습니다.", code="INTERNAL_ERROR")
            await response(scope, receive, send)


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid.uuid4())
        token = set_request_id(request_id)
        started = time.perf_counter()
        status = 500

        async def send_with_request_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            route = scope.get("route")
            route_name = getattr(route, "path", None) or "unrouted"
            logger.info(
                "request_completed",
                extra={
                    "method": scope.get("method"),
                    "route": route_name,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                },
            )
            reset_request_id(token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from .api.auth import _auth_mode, validate_jwt_config
    from .config import validate_runtime_config
    from .startup import (
        backfill_dev_user_membership,
        cleanup_stale_repository_generations,
        ensure_runtime_schema,
        ensure_schema_v8,
        ensure_schema_v9,
        recover_quota_tasks,
        recover_stale_tasks,
        stale_watchdog,
    )
    from .retriever.memory_vector import backfill_memory_vectors
    from .storage import ensure_upload_root_safe
    if _auth_mode() == "dev":
        logging.getLogger(__name__).warning(
            "PAIM_AUTH_MODE=dev — JWT 검증이 꺼져 있습니다. 로컬 개발 전용이며 배포 환경에서는 사용 금지."
        )
    else:
        # jwt 모드: 시크릿이 없거나 약하면 여기서 기동을 중단시킨다. 그러지 않으면
        # 서버는 뜨지만 로그인 503 / 보호 API 401로 인증 불능 상태가 된다.
        validate_runtime_config()
        validate_jwt_config()
    # 스키마 보증을 다른 DB 작업보다 먼저 실행 — 기존 볼륨에서는 initdb.d가
    # 재실행되지 않으므로 기반 테이블·컬럼(runtime) → v8(FK·active_memory 뷰) 순.
    ensure_upload_root_safe(scan_tree=True)
    ensure_runtime_schema()
    ensure_schema_v8()
    ensure_schema_v9()
    recover_quota_tasks()
    recover_stale_tasks()
    cleanup_stale_repository_generations()
    backfill_dev_user_membership()
    try:
        backfill_memory_vectors()
    except Exception:
        logging.getLogger(__name__).warning("memory vector backfill failed", exc_info=True)
    watchdog_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quota-recovery")
    watchdog_task = asyncio.create_task(stale_watchdog(watchdog_executor))
    try:
        yield
    finally:
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass
        finally:
            # A running synchronous recovery cannot be interrupted safely.
            # Stop accepting queued work and let the single in-flight cycle
            # finish even if collecting the watchdog task itself fails.
            watchdog_executor.shutdown(wait=True, cancel_futures=True)


app = FastAPI(title="PaiM API", version="0.2.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# JWT 인증 미들웨어. CORS보다 먼저 등록해야 CORSMiddleware가 바깥에 위치해
# 401 응답에도 CORS 헤더가 붙는다 (add_middleware는 나중에 등록한 것이 바깥).
app.add_middleware(AuthMiddleware)


app.add_middleware(SafeErrorMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
    expose_headers=["X-Request-ID"],
)


app.add_middleware(RequestContextMiddleware)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return error_response(exc.status_code, exc.detail)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    safe_errors = []
    for item in exc.errors():
        safe_errors.append(
            {
                "type": str(item.get("type", "validation_error")),
                "loc": list(item.get("loc") or ()),
                "msg": str(item.get("msg", "Invalid input")),
            }
        )
    return error_response(422, safe_errors)


@app.exception_handler(SessionExpiredException)
async def session_expired_handler(request: Request, exc: SessionExpiredException):
    return error_response(410, "session expired", code="SESSION_EXPIRED")


app.include_router(auth_router,       prefix="/api/v1")
app.include_router(member_router,     prefix="/api/v1")
app.include_router(project_router,    prefix="/api/v1")
app.include_router(documents_router,  prefix="/api/v1")
app.include_router(memory_router,     prefix="/api/v1")
app.include_router(query_router,      prefix="/api/v1")
app.include_router(repository_router, prefix="/api/v1")
app.include_router(suggestion_router, prefix="/api/v1")
app.include_router(delta_router,      prefix="/api/v1")
app.include_router(capabilities_router, prefix="/api/v1")
app.include_router(chat_router,    prefix="/api/v1")
app.include_router(stt_router,     prefix="/api/v1")
# github_router는 자체 prefix(/github/app)를 사용하므로 /api/v1 붙이지 않음
app.include_router(github_router)
app.include_router(health_router)


@app.get("/")
def root():
    return {"service": "PaiM", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}


def serve():
    import uvicorn
    # 기본값은 로컬 데스크톱 sidecar 전용 — LAN 노출을 막기 위해 127.0.0.1에만
    # 바인딩한다. 컨테이너 배포에서만 PAIM_BIND_HOST=0.0.0.0으로 덮어쓴다(실제
    # 운영 이미지는 이 함수를 거치지 않고 Dockerfile CMD의 uvicorn을 직접 쓴다).
    # reload는 파일 감시용 개발 옵션. 굳힌 sidecar 실행파일에서는 서브프로세스를 못 띄워
    # 오작동하므로, 개발 중에만 PAIM_DEV_RELOAD=1로 켠다.
    uvicorn.run(
        "backend.main:app",
        host=os.getenv("PAIM_BIND_HOST", "127.0.0.1"),
        port=int(os.getenv("PAIM_BIND_PORT", "8000")),
        reload=os.getenv("PAIM_DEV_RELOAD") == "1",
        proxy_headers=False,
        log_config=None,
        access_log=False,
    )
