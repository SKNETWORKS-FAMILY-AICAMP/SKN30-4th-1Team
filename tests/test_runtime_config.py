import base64

import pytest

from backend.config import RuntimeConfigError, validate_runtime_config


def _valid_env() -> dict[str, str]:
    return {
        "PAIM_AUTH_MODE": "jwt",
        "PAIM_JWT_SECRET": "j" * 48,
        "LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-live-test",
        "OPENAI_MODEL": "gpt-4.1-mini",
        "SESSION_MEMORY_KEY": base64.b64encode(b"k" * 32).decode(),
        "DB_HOST": "db",
        "DB_PORT": "3306",
        "DB_USER": "root",
        "DB_PASSWORD": "db-password-value",
        "DB_NAME": "paiM",
        "RATE_LIMIT_SIGNUP": "5/minute",
        "RATE_LIMIT_LOGIN": "5/minute",
        "RATE_LIMIT_UPLOAD": "20/minute",
        "RATE_LIMIT_QUERY": "30/minute",
        "RATE_LIMIT_CHAT": "30/minute",
        "FORWARDED_ALLOW_IPS": "172.30.12.10/32",
        "CORS_ORIGINS": "https://paim.example.org",
    }


def test_runtime_config_accepts_approved_production_contract(monkeypatch):
    for key, value in _valid_env().items():
        monkeypatch.setenv(key, value)
    validate_runtime_config()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("DB_PORT", "65536"),
        ("SESSION_MEMORY_KEY", base64.b64encode(b"short").decode()),
        ("RATE_LIMIT_QUERY", "31/minute"),
        ("RATE_LIMIT_CHAT", "0/minute"),
        ("FORWARDED_ALLOW_IPS", "*"),
        ("FORWARDED_ALLOW_IPS", "172.30.12.0/24"),
        ("OPENAI_API_KEY", "replace-with-real-key"),
        ("DB_PASSWORD", "Change_Me"),
    ],
)
def test_runtime_config_rejects_invalid_or_unapproved_values(monkeypatch, key, value):
    for env_key, env_value in _valid_env().items():
        monkeypatch.setenv(env_key, env_value)
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeConfigError) as exc_info:
        validate_runtime_config()
    assert key in str(exc_info.value)
    assert value not in str(exc_info.value)


def test_runtime_config_never_reports_secret_value(monkeypatch):
    values = _valid_env()
    sentinel = "replace-with-SENTINEL-secret-material"
    values["PAIM_JWT_SECRET"] = sentinel
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeConfigError) as exc_info:
        validate_runtime_config()
    assert sentinel not in str(exc_info.value)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("LLM_PROVIDER", "claude"),
        ("OPENAI_MODEL", "gpt-4o-mini"),
        ("OPENAI_BASE_URL", "https://openai-compatible.example/v1"),
        ("OPENAI_API_BASE", "http://localhost:8000/v1"),
    ],
)
def test_runtime_config_rejects_non_mvp_agentic_setup(monkeypatch, key, value):
    for env_key, env_value in _valid_env().items():
        monkeypatch.setenv(env_key, env_value)
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeConfigError) as exc_info:
        validate_runtime_config()
    assert key in str(exc_info.value) or key == "LLM_PROVIDER"
