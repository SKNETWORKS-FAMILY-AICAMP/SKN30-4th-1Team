import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend import rate_limit
from backend.chat.router import get_db
from backend.main import app


_client = TestClient(app, raise_server_exceptions=False)


def _request(path: str, peer: str = "203.0.113.5", forwarded: str | None = None):
    headers = []
    if forwarded:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": headers,
            "client": (peer, 1234),
            "app": SimpleNamespace(state=SimpleNamespace(limiter=rate_limit.limiter)),
        }
    )


def test_public_limit_uses_peer_ip_not_spoofed_forwarded_header():
    rate_limit.limiter.reset()

    @rate_limit.limiter.limit("5/minute")
    def login(request: Request):
        return {"ok": True}

    for i in range(5):
        assert login(_request("/login", forwarded=f"198.51.100.{i}"))["ok"]
    with pytest.raises(RateLimitExceeded):
        login(_request("/login", forwarded="198.51.100.99"))


def test_authenticated_limit_is_separate_per_user(monkeypatch):
    rate_limit.limiter.reset()
    current = {"id": 1}
    monkeypatch.setattr(rate_limit, "get_current_user_id", lambda: current["id"])

    @rate_limit.limiter.limit("30/minute", key_func=rate_limit.authenticated_user_key)
    def query(request: Request):
        return {"ok": True}

    for _ in range(30):
        assert query(_request("/query"))["ok"]
    with pytest.raises(RateLimitExceeded):
        query(_request("/query"))
    current["id"] = 2
    assert query(_request("/query"))["ok"]


@pytest.mark.asyncio
async def test_rate_limit_handler_returns_stable_code():
    rate_limit.limiter.reset()

    @rate_limit.limiter.limit("1/minute")
    def endpoint(request: Request):
        return {"ok": True}

    endpoint(_request("/limited"))
    with pytest.raises(RateLimitExceeded) as exc_info:
        endpoint(_request("/limited"))
    response = await rate_limit.rate_limit_exceeded_handler(
        _request("/limited"), exc_info.value
    )
    assert response.status_code == 429
    assert json.loads(response.body)["code"] == "RATE_LIMIT_EXCEEDED"


def _conn(row=None):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    cursor.fetchall.return_value = []
    cursor.lastrowid = 1
    return conn


def _assert_http_boundary(send, limit: int):
    for _ in range(limit - 1):
        assert send().status_code < 400
    assert send().status_code < 400  # N
    exceeded = send()  # N+1
    assert exceeded.status_code == 429
    assert exceeded.json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert exceeded.json()["request_id"] == exceeded.headers["X-Request-ID"]


def test_signup_actual_endpoint_enforces_configured_boundary():
    user = {"id": 1, "email": "rate@test.local", "name": "Rate"}
    with patch("backend.api.auth_routes.get_connection", return_value=_conn(user)), patch(
        "backend.api.auth_routes.hash_password", return_value="hash"
    ), patch("backend.api.auth_routes._token_response", return_value={"ok": True}):
        _assert_http_boundary(
            lambda: _client.post(
                "/api/v1/auth/signup",
                json={"email": "rate@test.local", "password": "password1", "name": "Rate"},
            ),
            5,
        )


def test_login_actual_endpoint_enforces_configured_boundary_and_peer_ip_key():
    user = {"id": 1, "email": "rate@test.local", "name": "Rate", "password_hash": "hash"}
    first = TestClient(app, raise_server_exceptions=False, client=("203.0.113.10", 50000))
    second = TestClient(app, raise_server_exceptions=False, client=("203.0.113.11", 50000))
    with patch("backend.api.auth_routes.get_connection", return_value=_conn(user)), patch(
        "backend.api.auth_routes.verify_password", return_value=True
    ), patch("backend.api.auth_routes._token_response", return_value={"ok": True}):
        send = lambda: first.post(
            "/api/v1/auth/login",
            headers={"X-Forwarded-For": "198.51.100.99"},
            json={"email": "rate@test.local", "password": "password1"},
        )
        _assert_http_boundary(send, 5)
        assert second.post(
            "/api/v1/auth/login",
            json={"email": "rate@test.local", "password": "password1"},
        ).status_code == 200


def test_upload_actual_endpoint_enforces_configured_boundary():
    with patch("backend.rate_limit.get_current_user_id", return_value=11), patch(
        "backend.api.upload.require_project_access"
    ), patch("backend.api.upload.require_upload_user", return_value=11), patch(
        "backend.api.upload.reserve_document",
        return_value={"reservation_id": "r", "temp_path": "/tmp/r.tmp", "target_path": "/tmp/r.txt"},
    ), patch("backend.api.upload.write_reserved_file"), patch(
        "backend.api.upload.finalize_document",
        return_value={"doc_id": 1, "old_doc_ids": [], "file_path": "/tmp/r.txt", "processing_token": "t"},
    ), patch("backend.api.upload._process_upload"):
        _assert_http_boundary(
            lambda: _client.post(
                "/api/v1/projects/1/documents",
                files={"file": ("rate.txt", b"valid text", "text/plain")},
            ),
            20,
        )


def test_query_actual_endpoint_enforces_boundary_and_user_key_isolation():
    current = {"id": 21}
    with patch(
        "backend.rate_limit.get_current_user_id", side_effect=lambda: current["id"]
    ), patch("backend.api.query.require_project_access"), patch(
        "backend.api.query.get_connection", return_value=_conn({"id": 1})
    ), patch("backend.api.query.run_agentic_qa", return_value={"answer": "ok"}):
        send = lambda: _client.post(
            "/api/v1/projects/1/query", json={"question": "rate test"}
        )
        _assert_http_boundary(send, 30)
        current["id"] = 22
        assert send().status_code == 200


def test_chat_actual_endpoint_enforces_configured_boundary():
    app.dependency_overrides[get_db] = lambda: _conn({"id": 1})
    try:
        with patch("backend.rate_limit.get_current_user_id", return_value=31), patch(
            "backend.chat.router.handle_session_query", return_value={"answer": "ok"}
        ):
            _assert_http_boundary(
                lambda: _client.post(
                    "/api/v1/projects/1/sessions/session-1/query",
                    json={"current_question": "rate test"},
                ),
                30,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)


def _proxy_client(peer: str) -> TestClient:
    captured = FastAPI()

    @captured.get("/")
    def show_client(request: Request):
        return {"client": request.client.host}

    proxied = ProxyHeadersMiddleware(captured, trusted_hosts=["172.30.13.10/32"])
    return TestClient(proxied, client=(peer, 50000))


def test_uvicorn_proxy_boundary_trusts_only_caddy_and_ignores_leading_chain():
    trusted = _proxy_client("172.30.13.10")
    assert trusted.get("/", headers={"X-Forwarded-For": "198.51.100.7"}).json() == {
        "client": "198.51.100.7"
    }
    # Uvicorn은 오른쪽부터 가장 가까운 비신뢰 주소를 고르므로 공격자가 앞에 붙인
    # 값을 client로 쓰지 않는다. Caddy는 실제 배포에서 이 단일 hop을 만든다.
    assert trusted.get(
        "/", headers={"X-Forwarded-For": "203.0.113.66, 198.51.100.7"}
    ).json() == {"client": "198.51.100.7"}

    direct = _proxy_client("192.0.2.40")
    assert direct.get("/", headers={"X-Forwarded-For": "198.51.100.99"}).json() == {
        "client": "192.0.2.40"
    }
