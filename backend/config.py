"""운영 시작 전에 닫힌 상태로 검증하는 런타임 설정 계약."""

import base64
import binascii
import ipaddress
import os
import re
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AnyUrl, TypeAdapter, UrlConstraints, ValidationError


class RuntimeConfigError(RuntimeError):
    pass


_REQUIRED = (
    "PAIM_AUTH_MODE",
    "PAIM_JWT_SECRET",
    "OPENAI_API_KEY",
    "SESSION_MEMORY_KEY",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "RATE_LIMIT_SIGNUP",
    "RATE_LIMIT_LOGIN",
    "RATE_LIMIT_UPLOAD",
    "RATE_LIMIT_QUERY",
    "RATE_LIMIT_CHAT",
    "FORWARDED_ALLOW_IPS",
)
_RATE_LIMITS = {
    "RATE_LIMIT_SIGNUP": "5/minute",
    "RATE_LIMIT_LOGIN": "5/minute",
    "RATE_LIMIT_UPLOAD": "20/minute",
    "RATE_LIMIT_QUERY": "30/minute",
    "RATE_LIMIT_CHAT": "30/minute",
}
_TRUSTED_PROXY_IPS = {
    "172.30.12.10/32",
    "172.30.13.10/32",
    "172.30.14.10/32",
}
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
PROJECT_STORAGE_QUOTA_BYTES = 209_715_200
USER_STORAGE_QUOTA_BYTES = 524_288_000
PROJECT_FILE_COUNT_QUOTA = 500
_HTTP_ORIGIN_ADAPTER = TypeAdapter(
    Annotated[
        AnyUrl,
        UrlConstraints(
            allowed_schemes=["http", "https"],
            host_required=True,
            preserve_empty_path=True,
        ),
    ]
)


def positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    if not re.fullmatch(r"[1-9][0-9]*", raw):
        _fail([name], "양의 정수여야 합니다")
    return int(raw)


def log_level() -> str:
    value = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    if value not in LOG_LEVELS:
        _fail(["LOG_LEVEL"], "DEBUG|INFO|WARNING|ERROR|CRITICAL 중 하나여야 합니다")
    return value


def quota_limits() -> tuple[int, int, int]:
    return (
        positive_int_env("PROJECT_STORAGE_QUOTA_BYTES", PROJECT_STORAGE_QUOTA_BYTES),
        positive_int_env("USER_STORAGE_QUOTA_BYTES", USER_STORAGE_QUOTA_BYTES),
        positive_int_env("PROJECT_FILE_COUNT_QUOTA", PROJECT_FILE_COUNT_QUOTA),
    )


def _canonical_http_origin(origin: str) -> str:
    try:
        parsed = _HTTP_ORIGIN_ADAPTER.validate_python(origin)
    except ValidationError:
        _fail(["CORS_ORIGINS"], "유효한 HTTP 또는 HTTPS origin이어야 합니다")
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path is not None
        or parsed.query is not None
        or parsed.fragment is not None
    ):
        _fail(["CORS_ORIGINS"], "scheme/host/port만 있는 origin이어야 합니다")
    return str(parsed)


def _has_forbidden_raw_origin_syntax(origin: str) -> bool:
    return bool(re.search(r"[\x00-\x20\x7f]", origin)) or any(
        marker in origin for marker in ("\\", "?", "#")
    )


def cors_origins() -> list[str]:
    mode = os.getenv("PAIM_AUTH_MODE", "jwt").strip().lower()
    raw = os.getenv("CORS_ORIGINS")
    if raw is None and mode == "dev":
        return ["http://127.0.0.1:7420"]
    if raw is None or not raw.strip():
        _fail(["CORS_ORIGINS"], "non-dev에서는 비어 있을 수 없습니다")
    parts = raw.split(",")
    if any(not item.strip() for item in parts):
        _fail(["CORS_ORIGINS"], "빈 origin 항목은 허용되지 않습니다")
    result: list[str] = []
    for item in parts:
        origin = item.strip()
        if "*" in origin:
            _fail(["CORS_ORIGINS"], "wildcard는 허용되지 않습니다")
        if _has_forbidden_raw_origin_syntax(origin) or origin.endswith(":"):
            _fail(["CORS_ORIGINS"], "origin 원문에 금지된 문법이 있습니다")
        try:
            parsed = urlsplit(origin)
            port = parsed.port
        except ValueError:
            _fail(["CORS_ORIGINS"], "port가 유효해야 합니다")
        if not parsed.hostname or (
            parsed.scheme not in {"http", "https", "tauri"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {""}
            or parsed.query
            or parsed.fragment
        ):
            _fail(["CORS_ORIGINS"], "path/query/fragment/credential 없는 absolute origin이어야 합니다")
        if parsed.scheme == "tauri":
            if origin != "tauri://localhost":
                _fail(["CORS_ORIGINS"], "Tauri origin은 tauri://localhost만 허용됩니다")
            canonical = origin
        else:
            canonical = _canonical_http_origin(origin)
        if canonical in result:
            _fail(["CORS_ORIGINS"], "중복 origin은 허용되지 않습니다")
        result.append(canonical)
    return result


def validate_phase_b_config() -> None:
    log_level()
    quota_limits()
    cors_origins()


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return (
        lowered in {"change_me", "changeme", "secret", "password"}
        or lowered.startswith(("your-", "your_", "sk-placeholder"))
        or "replace-with" in lowered
    )


def _fail(keys: list[str], reason: str) -> None:
    joined = ", ".join(sorted(keys))
    raise RuntimeConfigError(f"런타임 설정 오류: {joined} — {reason}") from None


def validate_runtime_config() -> None:
    validate_phase_b_config()
    values = {key: os.getenv(key, "").strip() for key in _REQUIRED}
    missing = [key for key, value in values.items() if not value]
    if missing:
        _fail(missing, "필수 환경변수가 비어 있습니다")

    placeholders = [key for key, value in values.items() if _is_placeholder(value)]
    if placeholders:
        _fail(placeholders, "placeholder 값은 운영에서 사용할 수 없습니다")

    if values["PAIM_AUTH_MODE"].lower() != "jwt":
        _fail(["PAIM_AUTH_MODE"], "non-dev 실행은 jwt만 허용합니다")

    try:
        port = int(values["DB_PORT"])
    except ValueError:
        _fail(["DB_PORT"], "1~65535 정수여야 합니다")
    if not 1 <= port <= 65535:
        _fail(["DB_PORT"], "1~65535 정수여야 합니다")

    try:
        session_key = base64.b64decode(values["SESSION_MEMORY_KEY"], validate=True)
    except (binascii.Error, ValueError):
        _fail(["SESSION_MEMORY_KEY"], "엄격한 Base64 형식이어야 합니다")
    if len(session_key) != 32:
        _fail(["SESSION_MEMORY_KEY"], "디코딩 결과가 정확히 32바이트여야 합니다")

    bad_rates = [
        key
        for key, expected in _RATE_LIMITS.items()
        if not re.fullmatch(r"[1-9][0-9]*/minute", values[key])
        or values[key] != expected
    ]
    if bad_rates:
        _fail(bad_rates, "승인된 양의 정수/minute 정책과 일치해야 합니다")

    forwarded = values["FORWARDED_ALLOW_IPS"]
    if forwarded == "*" or "," in forwarded:
        _fail(["FORWARDED_ALLOW_IPS"], "단일 승인 프록시 /32만 허용합니다")
    try:
        parsed = ipaddress.ip_network(forwarded, strict=True)
    except ValueError:
        _fail(["FORWARDED_ALLOW_IPS"], "정확한 IP/CIDR 형식이어야 합니다")
    if str(parsed) not in _TRUSTED_PROXY_IPS:
        _fail(["FORWARDED_ALLOW_IPS"], "승인된 프로필의 Caddy /32만 허용합니다")
