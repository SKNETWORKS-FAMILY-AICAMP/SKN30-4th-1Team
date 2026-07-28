import asyncio
import concurrent.futures
import io
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from backend.api import health as health_api
from backend.config import RuntimeConfigError, cors_origins, log_level, quota_limits
from backend.db import mysql as mysql_db
from backend.logging_config import JsonFormatter
from backend.main import app
from backend import main as main_module, startup as startup_module


@app.get("/_phase-b-crash", include_in_schema=False)
async def _phase_b_crash():
    raise RuntimeError("PRIVATE-UPLOAD-QUESTION-TOKEN-PASSWORD")


@app.get("/_phase-b-handled", include_in_schema=False)
def _phase_b_handled():
    raise HTTPException(status_code=418, detail="handled")


@app.get("/_phase-b-validate/{value}", include_in_schema=False)
def _phase_b_validate(value: int):
    return {"value": value}


@app.get("/_phase-b-heartbeat", include_in_schema=False)
async def _phase_b_heartbeat():
    return {"status": "ok"}


client = TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("launch_order", ["docker", "paim-server"])
def test_uvicorn_launch_orders_keep_all_access_logging_safe(launch_order):
    probe = f"""
import copy
import asyncio
import json
import logging
import logging.config
from unittest.mock import patch

from uvicorn.config import LOGGING_CONFIG

launch_order = {launch_order!r}
if launch_order == "docker":
    logging.config.dictConfig(copy.deepcopy(LOGGING_CONFIG))
    from backend import main
else:
    from backend import main
    with patch("uvicorn.run") as run:
        main.serve()
    assert run.call_args.kwargs["log_config"] is None
    assert run.call_args.kwargs["access_log"] is False

async def request_probe():
    sent = []
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {{"type": "http.request", "body": b"", "more_body": False}}
        return {{"type": "http.disconnect"}}

    async def send(message):
        sent.append(message)

    await main.app(
        {{
            "type": "http",
            "asgi": {{"version": "3.0"}},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/PRIVATE-PATH-SENTINEL",
            "raw_path": b"/PRIVATE-PATH-SENTINEL",
            "query_string": b"code=PRIVATE-QUERY-SENTINEL",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
        }},
        receive,
        send,
    )
    start = next(message for message in sent if message["type"] == "http.response.start")
    assert start["status"] == 401
    assert any(name.lower() == b"x-request-id" for name, _value in start["headers"])

asyncio.run(request_probe())
logging.getLogger("uvicorn.access").info(
    '%s - "%s %s HTTP/%s" %d',
    "127.0.0.1:1",
    "GET",
    "/callback?code=PRIVATE-QUERY-SENTINEL",
    "1.1",
    401,
)
logging.getLogger("uvicorn.error").error("uvicorn_probe_error")
"""
    env = os.environ.copy()
    env.update(
        {
            "PAIM_AUTH_MODE": "jwt",
            "LOG_LEVEL": "INFO",
            "CORS_ORIGINS": "http://127.0.0.1:7420",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    combined = result.stdout + result.stderr
    assert "PRIVATE-PATH-SENTINEL" not in combined
    assert "PRIVATE-QUERY-SENTINEL" not in combined
    records = [json.loads(line) for line in result.stdout.splitlines()]
    access_records = [row for row in records if row["event"] == "request_completed"]
    error_records = [row for row in records if row["event"] == "uvicorn_probe_error"]
    assert len(access_records) == 1
    assert access_records[0]["route"] == "unrouted"
    assert access_records[0]["request_id"]
    assert len(error_records) == 1
    assert "uvicorn_probe_error" not in result.stderr


def test_readiness_timeouts_are_not_applied_to_general_connections():
    connection = object()
    with patch.object(mysql_db.pymysql, "connect", return_value=connection) as connect:
        assert mysql_db.get_connection() is connection
        general_kwargs = connect.call_args.kwargs
        assert "connect_timeout" not in general_kwargs
        assert "read_timeout" not in general_kwargs
        assert "write_timeout" not in general_kwargs

        assert mysql_db.get_readiness_connection() is connection
        readiness_kwargs = connect.call_args.kwargs
        assert readiness_kwargs["connect_timeout"] == 2
        assert readiness_kwargs["read_timeout"] == 2
        assert readiness_kwargs["write_timeout"] == 2


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LOG_LEVEL", "verbose"),
        ("PROJECT_STORAGE_QUOTA_BYTES", "0"),
        ("USER_STORAGE_QUOTA_BYTES", "-1"),
        ("PROJECT_FILE_COUNT_QUOTA", "1.5"),
    ],
)
def test_phase_b_config_rejects_invalid_values(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeConfigError):
        log_level() if name == "LOG_LEVEL" else quota_limits()


def test_phase_b_config_defaults(monkeypatch):
    for name in (
        "LOG_LEVEL",
        "PROJECT_STORAGE_QUOTA_BYTES",
        "USER_STORAGE_QUOTA_BYTES",
        "PROJECT_FILE_COUNT_QUOTA",
        "CORS_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAIM_AUTH_MODE", "dev")
    assert log_level() == "INFO"
    assert quota_limits() == (209_715_200, 524_288_000, 500)
    assert cors_origins() == ["http://127.0.0.1:7420"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("HTTP://EXAMPLE.COM:80", "http://example.com"),
        ("HTTPS://EXAMPLE.COM:443", "https://example.com"),
        ("http://EXAMPLE.COM:8080", "http://example.com:8080"),
        ("http://[2001:0DB8::1]:8080", "http://[2001:db8::1]:8080"),
        ("tauri://localhost", "tauri://localhost"),
        ("https://BÜCHER.EXAMPLE", "https://xn--bcher-kva.example"),
        ("https://faß.de", "https://xn--fa-hia.de"),
        ("http://127.1", "http://127.0.0.1"),
        ("http://2130706433", "http://127.0.0.1"),
        ("http://[::ffff:192.0.2.1]", "http://[::ffff:c000:201]"),
    ],
)
def test_non_dev_cors_parser_returns_browser_canonical_origin(monkeypatch, value, expected):
    monkeypatch.setenv("PAIM_AUTH_MODE", "jwt")
    monkeypatch.setenv("CORS_ORIGINS", value)
    assert cors_origins() == [expected]


@pytest.mark.parametrize(
    ("configured", "browser_origin"),
    [
        ("HTTP://EXAMPLE.COM:80", "http://example.com"),
        ("https://faß.de", "https://xn--fa-hia.de"),
        ("http://127.1", "http://127.0.0.1"),
        ("http://2130706433", "http://127.0.0.1"),
        ("http://[::ffff:192.0.2.1]", "http://[::ffff:c000:201]"),
        ("tauri://localhost", "tauri://localhost"),
        ("http://tauri.localhost", "http://tauri.localhost"),
    ],
)
def test_canonical_cors_origin_matches_browser_request(monkeypatch, configured, browser_origin):
    monkeypatch.setenv("PAIM_AUTH_MODE", "jwt")
    monkeypatch.setenv("CORS_ORIGINS", configured)
    sent = []

    async def ok(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    cors_app = CORSMiddleware(
        ok,
        allow_origins=cors_origins(),
        allow_credentials=False,
    )
    asyncio.run(
        cors_app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/",
                "raw_path": b"/",
                "query_string": b"",
                "root_path": "",
                "headers": [(b"origin", browser_origin.encode("ascii"))],
                "client": ("127.0.0.1", 1),
                "server": ("testserver", 80),
            },
            receive,
            send,
        )
    )
    start = next(message for message in sent if message["type"] == "http.response.start")
    headers = dict(start["headers"])
    assert start["status"] == 200
    assert headers[b"access-control-allow-origin"] == browser_origin.encode("ascii")


@pytest.mark.parametrize(
    "value",
    [
        "https://faß.de,https://xn--fa-hia.de",
        "http://127.1,http://127.0.0.1",
        "http://2130706433,http://127.0.0.1",
        "http://[::ffff:192.0.2.1],http://[::ffff:c000:201]",
    ],
)
def test_non_dev_cors_parser_rejects_browser_equivalent_duplicates(monkeypatch, value):
    monkeypatch.setenv("PAIM_AUTH_MODE", "jwt")
    monkeypatch.setenv("CORS_ORIGINS", value)
    with pytest.raises(RuntimeConfigError):
        cors_origins()


@pytest.mark.parametrize(
    "value",
    [
        "",
        "*",
        "http://user:pw@example.test",
        "http://example.test/path",
        "http://example.test?q=1",
        "http://example.test#x",
        "http://example.test\\path",
        "http://example.test?",
        "http://example.test#",
        "http://example.test:",
        "http://exam\tple.test",
        "http://exam\x1fple.test",
        "example.test",
        "http://example.test,http://example.test",
        "http://example.test,http://EXAMPLE.TEST:80",
        "http://example.test,",
        "ftp://example.test",
        "http://example.test:bad",
        "tauri://LOCALHOST",
        "tauri://localhost:1420",
        "tauri://other-host",
    ],
)
def test_non_dev_cors_parser_is_fail_closed(monkeypatch, value):
    monkeypatch.setenv("PAIM_AUTH_MODE", "jwt")
    monkeypatch.setenv("CORS_ORIGINS", value)
    with pytest.raises(RuntimeConfigError):
        cors_origins()


def test_forbidden_raw_cors_syntax_prevents_app_module_creation():
    env = os.environ.copy()
    env.update(
        {
            "PAIM_AUTH_MODE": "jwt",
            "CORS_ORIGINS": "http://example.test?",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", "import backend.main"],
        cwd=Path(__file__).parents[1],
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "RuntimeConfigError" in result.stderr


@pytest.mark.parametrize(
    ("origin", "sentinel", "forbidden_cause_text"),
    [
        (
            "http://PRIVATE-HOST-SENTINEL_%",
            "PRIVATE-HOST-SENTINEL",
            "input_value",
        ),
        (
            "http://example.test:PRIVATE-PORT-SENTINEL",
            "PRIVATE-PORT-SENTINEL",
            "Port could not be cast",
        ),
    ],
)
def test_cors_parser_failure_traceback_hides_input(
    origin, sentinel, forbidden_cause_text
):
    env = os.environ.copy()
    env.update({"PAIM_AUTH_MODE": "jwt", "CORS_ORIGINS": origin})
    result = subprocess.run(
        [sys.executable, "-c", "import backend.main"],
        cwd=Path(__file__).parents[1],
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "RuntimeConfigError" in result.stderr
    assert sentinel not in output
    assert forbidden_cause_text not in output


def test_runtime_config_error_suppresses_parser_context(monkeypatch):
    monkeypatch.setenv("PAIM_AUTH_MODE", "jwt")
    monkeypatch.setenv("CORS_ORIGINS", "http://PRIVATE-HOST-SENTINEL_%")
    with pytest.raises(RuntimeConfigError) as exc_info:
        cors_origins()
    assert exc_info.value.__suppress_context__ is True
    assert "PRIVATE-HOST-SENTINEL" not in str(exc_info.value)


def test_request_ids_error_shapes_cors_and_sensitive_log_redaction():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logging.getLogger().addHandler(handler)
    try:
        external = str(uuid.uuid4())
        response = client.get(
            "/_phase-b-crash",
            headers={"Origin": "http://127.0.0.1:7420", "X-Request-ID": external},
        )
    finally:
        logging.getLogger().removeHandler(handler)
    assert response.status_code == 500
    request_id = response.headers["X-Request-ID"]
    assert request_id != external
    assert response.json() == {
        "detail": "내부 서버 오류가 발생했습니다.",
        "request_id": request_id,
        "code": "INTERNAL_ERROR",
    }
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:7420"
    assert "X-Request-ID" in response.headers["access-control-expose-headers"]
    assert "PRIVATE-UPLOAD-QUESTION-TOKEN-PASSWORD" not in stream.getvalue()
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert any(row["event"] == "request_completed" and row["request_id"] == request_id for row in records)


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("/", 200),
        ("/does-not-exist", 404),
        ("/_phase-b-validate/nope", 422),
        ("/_phase-b-handled", 418),
    ],
)
def test_request_id_is_on_success_and_handled_errors(path, status):
    response = client.get(path)
    assert response.status_code == status
    uuid.UUID(response.headers["X-Request-ID"])
    if status >= 400:
        assert response.json()["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/auth/login", {"email": "user@example.test", "password": {"secret": "SENSITIVE-PASSWORD"}}),
        ("/api/v1/projects/1/query", {"question": {"secret": "SENSITIVE-QUESTION"}}),
    ],
)
def test_validation_errors_do_not_reflect_original_input(path, body):
    response = client.post(path, json=body)
    assert response.status_code == 422
    serialized = response.text
    assert "SENSITIVE-PASSWORD" not in serialized
    assert "SENSITIVE-QUESTION" not in serialized
    for item in response.json()["detail"]:
        assert set(item) == {"type", "loc", "msg"}


def test_default_cors_rejects_old_and_arbitrary_origins():
    for origin in ("http://localhost:7420", "http://127.0.0.1:1420", "https://evil.test"):
        response = client.get("/", headers={"Origin": origin})
        assert "access-control-allow-origin" not in response.headers


def test_auth_middleware_401_has_request_id_and_cors(monkeypatch):
    monkeypatch.setenv("PAIM_AUTH_MODE", "jwt")
    response = client.get(
        "/api/v1/projects",
        headers={"Origin": "http://127.0.0.1:7420"},
    )
    assert response.status_code == 401
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:7420"


@pytest.mark.parametrize("failed_name", ["mysql", "schema", "chroma", "upload"])
def test_readiness_component_failure_matrix(failed_name):
    probes = {name: (lambda: None) for name in health_api._PROBES}

    def fail():
        raise RuntimeError("private-path-secret")

    probes[failed_name] = fail
    with patch.object(health_api, "_PROBES", probes):
        health_api._pending.clear()
        response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["components"][failed_name]["status"] == "failed"
    assert "private-path-secret" not in response.text


def test_readiness_timeout_is_single_flight():
    calls = {"mysql": 0}
    release = threading.Event()

    def slow():
        calls["mysql"] += 1
        release.wait(timeout=2)

    probes = {name: (lambda: None) for name in health_api._PROBES}
    probes["mysql"] = slow
    try:
        with patch.object(health_api, "_PROBES", probes), patch.object(
            health_api, "_COMPONENT_TIMEOUT", 0.01
        ):
            health_api._pending.clear()
            first = client.get("/health/ready")
            second = client.get("/health/ready")
    finally:
        release.set()
        health_api._pending["mysql"].result(timeout=2)
    assert first.json()["components"]["mysql"]["status"] == "timeout"
    assert second.json()["components"]["mysql"]["status"] == "timeout"
    assert calls["mysql"] == 1


@pytest.mark.parametrize("blocked_name", ["mysql", "schema", "chroma", "upload"])
def test_readiness_component_timeout_matrix(blocked_name):
    release = threading.Event()
    probes = {name: (lambda: None) for name in health_api._PROBES}
    probes[blocked_name] = lambda: release.wait(timeout=2)
    try:
        with patch.object(health_api, "_PROBES", probes), patch.object(
            health_api, "_COMPONENT_TIMEOUT", 0.01
        ):
            health_api._pending.clear()
            response = client.get("/health/ready")
    finally:
        release.set()
        health_api._pending[blocked_name].result(timeout=2)
    assert response.status_code == 503
    components = response.json()["components"]
    assert components[blocked_name]["status"] == "timeout"
    assert all(
        item["status"] == "ok"
        for name, item in components.items()
        if name != blocked_name
    )


def test_readiness_overall_timeout_is_bounded():
    release = threading.Event()
    probes = {name: (lambda: release.wait(timeout=2)) for name in health_api._PROBES}
    try:
        with patch.object(health_api, "_PROBES", probes), patch.object(
            health_api, "_COMPONENT_TIMEOUT", 1
        ), patch.object(health_api, "_OVERALL_TIMEOUT", 0.01):
            health_api._pending.clear()
            started = time.monotonic()
            response = client.get("/health/ready")
            elapsed = time.monotonic() - started
    finally:
        release.set()
        for future in health_api._pending.values():
            future.result(timeout=2)
    assert elapsed < 0.5
    assert response.status_code == 503
    assert all(
        item["status"] == "timeout"
        for item in response.json()["components"].values()
    )


def test_upload_probe_late_completion_removes_artifact(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    entered = threading.Event()
    release = threading.Event()
    real_fsync = health_api.os.fsync

    def blocking_fsync(fd):
        entered.set()
        release.wait(timeout=2)
        return real_fsync(fd)

    probes = {name: (lambda: None) for name in health_api._PROBES}
    probes["upload"] = health_api._upload_probe
    try:
        with patch.object(health_api, "_PROBES", probes), patch.object(
            health_api, "_COMPONENT_TIMEOUT", 0.01
        ), patch.object(health_api.os, "fsync", side_effect=blocking_fsync):
            health_api._pending.clear()
            response = client.get("/health/ready")
            assert entered.wait(timeout=1)
    finally:
        release.set()
        health_api._pending["upload"].result(timeout=2)
    assert response.json()["components"]["upload"]["status"] == "timeout"
    assert list(tmp_path.iterdir()) == []


def test_mysql_probe_late_completion_closes_connection():
    entered = threading.Event()
    release = threading.Event()

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _sql):
            entered.set()
            release.wait(timeout=2)

        def fetchone(self):
            return {"1": 1}

    class Connection:
        closed = False

        def cursor(self):
            return Cursor()

        def close(self):
            self.closed = True

    connection = Connection()
    probes = {name: (lambda: None) for name in health_api._PROBES}
    probes["mysql"] = health_api._mysql_probe
    try:
        with patch.object(health_api, "_PROBES", probes), patch.object(
            health_api, "_COMPONENT_TIMEOUT", 0.01
        ), patch.object(health_api, "get_readiness_connection", return_value=connection):
            health_api._pending.clear()
            response = client.get("/health/ready")
            assert entered.wait(timeout=1)
    finally:
        release.set()
        health_api._pending["mysql"].result(timeout=2)
    assert response.json()["components"]["mysql"]["status"] == "timeout"
    assert connection.closed


def test_upload_probe_always_removes_file(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    health_api._upload_probe()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_runtime_recovery_does_not_block_event_loop_or_overlap(monkeypatch):
    monkeypatch.setenv("PAIM_AUTH_MODE", "dev")
    entered = threading.Event()
    release = threading.Event()
    calls = {"quota": 0, "stale": 0}

    def blocking_quota_recovery():
        calls["quota"] += 1
        entered.set()
        release.wait(timeout=5)

    def stale_recovery():
        calls["stale"] += 1

    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="quota-recovery-test"
    )
    task = None
    with patch.object(startup_module, "_WATCHDOG_INTERVAL_SECONDS", 0), patch.object(
        startup_module, "recover_quota_tasks", side_effect=blocking_quota_recovery
    ), patch.object(startup_module, "recover_stale_tasks", side_effect=stale_recovery):
        try:
            task = asyncio.create_task(startup_module.stale_watchdog(executor))
            for _attempt in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            assert entered.is_set()

            sent = []
            delivered = False

            async def receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                return {"type": "http.disconnect"}

            async def send(message):
                sent.append(message)

            await asyncio.wait_for(
                app(
                    {
                        "type": "http",
                        "asgi": {"version": "3.0"},
                        "http_version": "1.1",
                        "method": "GET",
                        "scheme": "http",
                        "path": "/_phase-b-heartbeat",
                        "raw_path": b"/_phase-b-heartbeat",
                        "query_string": b"",
                        "root_path": "",
                        "headers": [],
                        "client": ("127.0.0.1", 1),
                        "server": ("testserver", 80),
                    },
                    receive,
                    send,
                ),
                timeout=0.5,
            )
            start = next(item for item in sent if item["type"] == "http.response.start")
            assert start["status"] == 200
            assert calls == {"quota": 1, "stale": 0}
        finally:
            if task is not None:
                task.cancel()
            release.set()
            if task is not None:
                with pytest.raises(asyncio.CancelledError):
                    await task
            executor.shutdown(wait=True, cancel_futures=True)

    assert calls == {"quota": 1, "stale": 1}
    assert not any(
        thread.name.startswith("quota-recovery-test") for thread in threading.enumerate()
    )


@pytest.mark.asyncio
async def test_lifespan_collects_watchdog_before_executor_shutdown(monkeypatch):
    monkeypatch.setenv("PAIM_AUTH_MODE", "dev")
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    shutdown_calls = []

    class FakeExecutor:
        def __init__(self, **kwargs):
            assert kwargs == {"max_workers": 1, "thread_name_prefix": "quota-recovery"}

        def shutdown(self, **kwargs):
            assert cancelled.is_set()
            shutdown_calls.append(kwargs)

    async def waiting_watchdog(executor):
        assert isinstance(executor, FakeExecutor)
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    with patch("concurrent.futures.ThreadPoolExecutor", FakeExecutor), patch.object(
        startup_module, "ensure_runtime_schema"
    ), patch.object(startup_module, "ensure_schema_v8"), patch.object(
        startup_module, "ensure_schema_v9"
    ), patch.object(startup_module, "recover_quota_tasks"), patch.object(
        startup_module, "recover_stale_tasks"
    ), patch.object(startup_module, "backfill_dev_user_membership"), patch.object(
        startup_module, "stale_watchdog", side_effect=waiting_watchdog
    ), patch(
        "backend.storage.ensure_upload_root_safe"
    ), patch(
        "backend.retriever.memory_vector.backfill_memory_vectors"
    ):
        async with main_module.lifespan(app):
            await asyncio.wait_for(entered.wait(), timeout=1)

    assert cancelled.is_set()
    assert shutdown_calls == [{"wait": True, "cancel_futures": True}]


def test_json_formatter_survives_exc_info_without_active_exception():
    """활성 예외가 없을 때의 exc_info=True로 포매터가 죽지 않아야 한다.

    logging은 활성 예외가 없으면 exc_info=True를 sys.exc_info()인 (None,None,None)으로
    정규화한다. 이 튜플은 truthy라 그대로 통과시키면 None.__name__에서 AttributeError가
    나고, 포매터가 죽으면 그 로그 라인이 통째로 유실된다. 1차 소비자는 configure_logging이
    root JSON 핸들러로 propagate시키는 uvicorn 등 서드파티 로거다."""
    record = logging.LogRecord(
        "t", logging.WARNING, "x.py", 1, "msg", None, (None, None, None)
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["event"] == "msg"
    assert "exception_type" not in payload


def test_json_formatter_keeps_extra_exception_type_when_exc_info_is_empty():
    """exc_info가 비어 있으면 extra로 넘어온 exception_type을 덮어쓰지 않고 보존한다.

    exception_type은 extra(main.py의 예외 핸들러)와 exc_info 두 경로로 들어오는데,
    exc_info 쪽이 무조건 덮어쓰는 구조였다. 빈 exc_info를 걸러내면서 extra 값이 살아난다."""
    record = logging.LogRecord(
        "t", logging.ERROR, "x.py", 1, "msg", None, (None, None, None)
    )
    record.exception_type = "ValueError"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["exception_type"] == "ValueError"


def test_json_formatter_still_reports_real_exception_type():
    """정상 경로(활성 예외 안의 exc_info)는 그대로 동작해야 한다 — 가드가 과하지 않은지 고정."""
    try:
        raise KeyError("boom")
    except KeyError:
        record = logging.LogRecord(
            "t", logging.ERROR, "x.py", 1, "msg", None, sys.exc_info()
        )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["exception_type"] == "KeyError"
