"""backend.main.serve()의 바인딩 기본값 회귀 테스트.

컨테이너 배포를 위해 host/port를 환경변수화했지만, **기본값은 반드시 로컬 전용**
이어야 한다. serve()는 데스크톱 sidecar 실행 경로(pyproject의 paim-server)라
기본값이 0.0.0.0으로 새면 사용자 PC의 백엔드가 LAN에 노출된다.

운영 이미지는 serve()를 거치지 않고 Dockerfile CMD의 uvicorn을 직접 쓰므로,
이 경로에서 컨테이너 편의를 위해 기본값을 바꿀 이유가 없다.
"""
from unittest.mock import patch

from backend import main


def _captured_run(monkeypatch_env: dict) -> dict:
    with patch.dict("os.environ", monkeypatch_env, clear=False):
        with patch("uvicorn.run") as run:
            main.serve()
    return run.call_args.kwargs


def test_defaults_to_loopback_and_8000():
    kwargs = _captured_run({})
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8000
    assert kwargs["log_config"] is None
    assert kwargs["access_log"] is False


def test_environment_can_override_binding():
    kwargs = _captured_run({"PAIM_BIND_HOST": "0.0.0.0", "PAIM_BIND_PORT": "9000"})
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 9000


def test_port_is_passed_as_int():
    """uvicorn.run은 port에 int를 요구한다. 환경변수는 문자열이므로 변환이 필요."""
    kwargs = _captured_run({"PAIM_BIND_PORT": "8123"})
    assert isinstance(kwargs["port"], int)
