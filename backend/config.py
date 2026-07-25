"""운영 시작 전에 닫힌 상태로 검증하는 런타임 설정 계약."""

import base64
import binascii
import ipaddress
import os
import re


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


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return (
        lowered in {"change_me", "changeme", "secret", "password"}
        or lowered.startswith(("your-", "your_", "sk-placeholder"))
        or "replace-with" in lowered
    )


def _fail(keys: list[str], reason: str) -> None:
    joined = ", ".join(sorted(keys))
    raise RuntimeConfigError(f"런타임 설정 오류: {joined} — {reason}")


def validate_runtime_config() -> None:
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
