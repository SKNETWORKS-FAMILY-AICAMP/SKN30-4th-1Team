import base64
import hashlib
import hmac
import json
import logging
import os
import time
from contextvars import ContextVar
from typing import Optional

import bcrypt
from fastapi import HTTPException
from starlette.requests import Request
from .errors import error_response
from ..db.mysql import get_connection

logger = logging.getLogger(__name__)

_ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}

# 요청 처리 중 인증된 사용자 ID. auth_middleware가 JWT 검증 후 설정한다.
_current_user_id: ContextVar[Optional[int]] = ContextVar("paim_current_user_id", default=None)

_DEFAULT_TOKEN_TTL_HOURS = 12


def _auth_mode() -> str:
    """인증 모드. 기본 'jwt'(fail-closed). 'dev'는 명시적 옵트인 —
    DEV_USER_ID 기반 단일 사용자 개발/테스트 전용이며 토큰 검증을 생략한다."""
    return os.getenv("PAIM_AUTH_MODE", "jwt").strip().lower()


# ── 비밀번호 해시 ─────────────────────────────────────────────────────────────

# bcrypt는 72바이트 초과 입력에서 ValueError를 던진다(멀티바이트는 24자 정도로도 초과).
# 조용한 절단이나 500 대신 명시적 400으로 처리한다.
_MAX_PASSWORD_BYTES = 72


def hash_password(plain: str) -> str:
    if len(plain.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=400,
            detail="비밀번호가 너무 깁니다. (UTF-8 기준 72바이트 이하)",
        )
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


# ── JWT (HS256) — github/router.py의 RS256 구현과 같은 무의존 방식 ───────────

def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


# .env.example 등에 공개된 placeholder를 그대로 쓰면 서명키가 알려진 값이 되어
# 누구나 토큰을 위조할 수 있다. 알려진 기본값/약한 값은 미설정과 동일하게 거부한다.
_PLACEHOLDER_JWT_SECRETS = {
    "your_random_jwt_secret",
    "change_me",
    "changeme",
    "secret",
    "your-secret-key",
    "please_change_me",
}
# HS256의 서명키는 최소 256비트(=32바이트) 이상이어야 한다(RFC 7518 §3.2).
# 문자 수가 아니라 UTF-8 바이트 수로 재므로, `secrets.token_urlsafe(32)` 같은
# 생성 지침으로 만든 키만 통과하고 "a"*16 같은 약한 값은 거부된다.
_MIN_JWT_SECRET_BYTES = 32


class JWTConfigError(RuntimeError):
    """JWT 설정이 유효하지 않을 때 서버 기동을 중단시키는 예외."""


def _jwt_secret() -> bytes:
    secret = os.getenv("PAIM_JWT_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="PAIM_JWT_SECRET is not configured")
    if (
        secret.lower() in _PLACEHOLDER_JWT_SECRETS
        or len(secret.encode("utf-8")) < _MIN_JWT_SECRET_BYTES
    ):
        raise HTTPException(
            status_code=503,
            detail="PAIM_JWT_SECRET must be a strong non-default value "
            "(>= 32 bytes, not a placeholder — e.g. `secrets.token_urlsafe(32)`)",
        )
    return secret.encode("utf-8")


def validate_jwt_config() -> None:
    """jwt 모드에서 기동 시 시크릿 설정을 검증한다.

    설정이 없거나 약하면 JWTConfigError를 던져 기동을 조기 중단시킨다. 이렇게
    하지 않으면 서버와 /health는 정상 기동하는데 로그인은 503, 보호 API는 401로
    실패해 배포 시스템이 정상으로 오판한다. dev 모드는 검증 대상이 아니다."""
    if _auth_mode() == "dev":
        return
    try:
        _jwt_secret()
    except HTTPException as exc:
        raise JWTConfigError(str(exc.detail)) from exc


def create_access_token(user_id: int) -> str:
    try:
        ttl_hours = float(os.getenv("PAIM_JWT_TTL_HOURS", str(_DEFAULT_TOKEN_TTL_HOURS)))
    except ValueError:
        ttl_hours = _DEFAULT_TOKEN_TTL_HOURS

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": str(user_id), "iat": now, "exp": now + int(ttl_hours * 3600)}
    signing_input = (
        f"{_b64url_encode(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url_encode(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    signature = hmac.new(_jwt_secret(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> int:
    """토큰 검증 후 user_id 반환. 실패 시 HTTPException(401).
    알고리즘은 HS256으로 고정 — 헤더의 alg 값은 신뢰하지 않는다."""
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")

    # _jwt_secret()은 설정 오류 시 503을 던진다. try 밖에서 먼저 호출해 그 503이
    # 아래 광범위한 except에 잡혀 토큰 오류(401)로 은폐되지 않게 한다.
    secret = _jwt_secret()
    signing_input = f"{parts[0]}.{parts[1]}"
    try:
        expected = hmac.new(secret, signing_input.encode("ascii"), hashlib.sha256).digest()
        actual = _b64url_decode(parts[2])
    except Exception:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")

    if not hmac.compare_digest(expected, actual):
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")

    try:
        payload = json.loads(_b64url_decode(parts[1]))
        exp = int(payload["exp"])
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")

    if time.time() >= exp:
        raise HTTPException(status_code=401, detail="토큰이 만료되었습니다. 다시 로그인해주세요.")

    return user_id


# ── 인증 미들웨어 ─────────────────────────────────────────────────────────────

# 토큰 없이 접근 가능한 경로. /github/app/callback은 GitHub OAuth 리다이렉트로
# 사용자 브라우저에서 직접 열리므로 Authorization 헤더를 붙일 수 없다.
_PUBLIC_PATHS = {
    "/",
    "/health",
    "/health/ready",
    "/api/v1/auth/signup",
    "/api/v1/auth/login",
}
_PUBLIC_PREFIXES = ("/github/app/callback",)


def _is_public_path(path: str) -> bool:
    return path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES)


class AuthMiddleware:
    """Pure ASGI auth boundary, avoiding BaseHTTPMiddleware exception deadlocks."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or _auth_mode() == "dev":
            return await self.app(scope, receive, send)
        request = Request(scope)
        if request.method == "OPTIONS" or _is_public_path(request.url.path):
            return await self.app(scope, receive, send)
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return await error_response(401, "로그인이 필요합니다.")(scope, receive, send)
        try:
            user_id = decode_access_token(authorization[len("Bearer "):].strip())
        except HTTPException as exc:
            return await error_response(exc.status_code, exc.detail)(scope, receive, send)
        reset_token = _current_user_id.set(user_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_user_id.reset(reset_token)


# ── 현재 사용자 / 권한 검사 ──────────────────────────────────────────────────

def get_current_user_id() -> Optional[int]:
    """현재 요청의 사용자 ID 반환.
    1) auth_middleware가 심은 contextvar (jwt 모드)
    2) dev 모드에서만 DEV_USER_ID 환경변수 fallback
    """
    user_id = _current_user_id.get()
    if user_id is not None:
        return user_id

    if _auth_mode() == "dev":
        raw = os.getenv("DEV_USER_ID", "")
        if raw:
            try:
                parsed = int(raw)
            except ValueError:
                logger.warning("invalid_dev_user_id", extra={"code": "DEV_USER_ID_INVALID"})
            else:
                if parsed > 0:
                    return parsed
                logger.warning("invalid_dev_user_id", extra={"code": "DEV_USER_ID_INVALID"})
    return None


def ensure_dev_user() -> Optional[int]:
    """현재 사용자 ID를 반환하되, dev 모드에서는 users 테이블 row를 보장(upsert).
    jwt 모드에서는 회원가입이 row를 만들므로 조회만 한다."""
    user_id = get_current_user_id()
    if user_id is None or _auth_mode() != "dev":
        return user_id

    email = os.getenv("DEV_USER_EMAIL", "dev@local")
    name = os.getenv("DEV_USER_NAME", "Dev User")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO users (id, email, name) VALUES (%s, %s, %s)",
                    (user_id, email, name),
                )
        conn.commit()
    except Exception:
        logger.warning("DEV user 보장 실패 user_id=%s", user_id, exc_info=True)
    finally:
        conn.close()

    return user_id


def get_project_role(project_id: int, user_id: int) -> Optional[str]:
    """project_members에서 role 조회. 멤버가 아니면 None."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT role FROM project_members WHERE project_id = %s AND user_id = %s",
                (project_id, user_id),
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    return row["role"] if row else None


def require_project_access(project_id: int, min_role: str = "viewer") -> None:
    """프로젝트 접근 권한 검증 (fail-closed).

    - jwt 모드에서 user_id가 없으면 401 (미들웨어가 놓친 경우의 이중 방어).
    - dev 모드에서 DEV_USER_ID 미설정이면 기존 단일 사용자 동작 유지(no-op).
    - user_id가 있으면 project_members role이 min_role 미만일 때 403.
    """
    user_id = get_current_user_id()
    if user_id is None:
        if _auth_mode() == "dev":
            return
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    role = get_project_role(project_id, user_id)
    if role is None:
        raise HTTPException(status_code=403, detail="이 프로젝트에 접근 권한이 없습니다.")

    user_rank = _ROLE_RANK.get(role, -1)
    min_rank = _ROLE_RANK.get(min_role, 0)
    if user_rank < min_rank:
        raise HTTPException(status_code=403, detail=f"최소 '{min_role}' 권한이 필요합니다.")
