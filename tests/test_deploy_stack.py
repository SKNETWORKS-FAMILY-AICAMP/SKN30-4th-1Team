"""deploy/stack.sh wrapper 회귀 테스트.

wrapper가 약속하는 것은 세 가지다.

1. preflight가 실패하면 docker compose를 **호출하지 않는다**
2. 프로필이 정한 project·compose 파일·env 파일을 인자로 덮어쓸 수 없다
3. 호스트 셸에 export된 값이 프로필 env 파일을 이기지 못한다

3번이 특히 중요하다. Compose 보간은 호스트 환경을 --env-file보다 우선하므로,
막지 않으면 "preflight는 프로필 파일을 검사해 PASS했는데 컨테이너는 호스트 값으로
뜨는" 상태가 된다 — 잘못된 자격증명으로 기동하거나 리허설이 운영 포트를 점유한다.

docker 바이너리를 PATH 앞단의 가짜로 가려 실제 컨테이너 없이 검증한다.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

_VALID_ENV = """\
DB_USER=root
DB_PASSWORD=pw
DB_NAME=paiM
DB_HOST=db
DB_PORT=3306
PAIM_AUTH_MODE=jwt
PAIM_JWT_SECRET=%s
SESSION_MEMORY_KEY=key
OPENAI_API_KEY=sk-test
RATE_LIMIT_SIGNUP=5/minute
RATE_LIMIT_LOGIN=5/minute
RATE_LIMIT_UPLOAD=20/minute
RATE_LIMIT_QUERY=30/minute
RATE_LIMIT_CHAT=30/minute
PAIM_PROXY_SUBNET=172.30.13.0/24
PAIM_CADDY_PROXY_IP=172.30.13.10
PAIM_BACKEND_PROXY_IP=172.30.13.20
FORWARDED_ALLOW_IPS=172.30.13.10/32
CORS_ORIGINS=http://127.0.0.1:7420
PAIM_HTTP_PORT=8080
PAIM_HTTPS_PORT=8443
""" % ("x" * 48)


@pytest.fixture()
def fake_docker(tmp_path: Path) -> Path:
    """호출 인자를 파일로 기록하는 가짜 docker. 호출 여부까지 확인할 수 있다."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker-args.txt"
    (bin_dir / "docker").write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > {log}\nexit 0\n', encoding="utf-8"
    )
    (bin_dir / "docker").chmod(0o755)
    return log


@pytest.fixture()
def stack_root(tmp_path: Path) -> Path:
    """배포 wrapper가 생성하는 env 파일을 저장소 밖에서 격리한다."""
    root = tmp_path / "stack-root"
    shutil.copytree(_ROOT / "deploy", root / "deploy")
    shutil.copy2(_ROOT / "docker-compose.prod.yml", root / "docker-compose.prod.yml")
    return root


def _run(root: Path, profile: str, *args: str, env_extra: dict | None = None,
         fake_bin: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if fake_bin is not None:
        env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env.update(env_extra or {})
    return subprocess.run(
        [str(root / "deploy" / "stack.sh"), profile, *args],
        capture_output=True, text=True, cwd=root, env=env,
    )


@pytest.fixture()
def rehearsal_env(stack_root: Path) -> Path:
    """저장소 밖의 격리된 리허설 프로필 env 파일."""
    path = stack_root / "deploy" / ".env.rehearsal"
    path.write_text(_VALID_ENV, encoding="utf-8")
    return path


# ── 프로필 경계 ──────────────────────────────────────────────────────────────

def test_unknown_profile_is_rejected(stack_root: Path):
    result = _run(stack_root, "staging")
    assert result.returncode == 2
    assert "unknown profile" in result.stderr


def test_missing_env_file_is_rejected(stack_root: Path):
    path = stack_root / "deploy" / ".env.restore"
    assert not path.exists(), "테스트 전제: restore 프로필 env 파일이 없어야 한다"
    result = _run(stack_root, "restore", "config")
    assert result.returncode == 2
    assert "env file not found" in result.stderr


@pytest.mark.parametrize(
    "injected",
    [
        # 분리형·long·`=`형
        ["-p", "other"], ["-f", "/tmp/x.yml"], ["--env-file", "/tmp/x"],
        ["--project-name", "other"], ["--project-directory", "/tmp"],
        ["--env-file=/tmp/x"], ["--project-name=other"],
        # 값이 붙은 축약형 — Compose가 유효하게 받으므로 반드시 막아야 한다.
        # 1차 수정은 이 형태를 놓쳐 -ppaim-prod로 운영 project를 조작할 수 있었다.
        ["-ppaim-prod"], ["-fother.yml"],
    ],
)
def test_global_options_before_subcommand_are_rejected(
    stack_root: Path, rehearsal_env: Path, injected: list
):
    """전역 옵션은 subcommand 앞에만 올 수 있다. 이름 열거가 아니라 위치로 막는다."""
    result = _run(stack_root, "rehearsal", *injected, "config")
    assert result.returncode == 2
    assert "전역 옵션" in result.stderr


def test_subcommand_options_are_allowed(
    stack_root: Path, rehearsal_env: Path, fake_docker: Path
):
    """subcommand 뒤의 옵션(logs -f, up -d 등)은 정상 사용이므로 통과해야 한다."""
    result = _run(stack_root, "rehearsal", "logs", "-f", "--tail", "0",
                  fake_bin=fake_docker.parent / "bin")
    assert result.returncode == 0, result.stderr
    args = fake_docker.read_text(encoding="utf-8").split("\n")
    assert "logs" in args and "-f" in args


# ── preflight 게이트 ─────────────────────────────────────────────────────────

def test_compose_not_invoked_when_preflight_fails(
    stack_root: Path, fake_docker: Path
):
    """검사에 걸린 설정으로는 컨테이너가 뜨면 안 된다."""
    path = stack_root / "deploy" / ".env.rehearsal"
    path.write_text("DB_USER=root\n", encoding="utf-8")  # 필수값 대부분 누락
    try:
        result = _run(
            stack_root, "rehearsal", "up", "-d",
            fake_bin=fake_docker.parent / "bin",
        )
        assert result.returncode != 0
        assert not fake_docker.exists(), "preflight 실패인데 docker가 호출됐다"
    finally:
        path.unlink()


def test_compose_invoked_with_profile_options(
    stack_root: Path, rehearsal_env: Path, fake_docker: Path
):
    result = _run(
        stack_root, "rehearsal", "config", fake_bin=fake_docker.parent / "bin"
    )
    assert result.returncode == 0, result.stderr
    args = fake_docker.read_text(encoding="utf-8").split("\n")
    assert "-p" in args and "paim-rehearsal" in args
    assert "docker-compose.prod.yml" in args
    assert "deploy/compose.rehearsal.yml" in args
    assert "deploy/.env.rehearsal" in args


# ── 호스트 셸 오염 차단 ──────────────────────────────────────────────────────

@pytest.mark.skipif(shutil.which("docker") is None, reason="docker 필요")
def test_host_shell_values_do_not_override_profile(
    stack_root: Path, rehearsal_env: Path
):
    """프로필 파일에 있는 키. 호스트 값이 이기면 잘못된 DB로 붙는다."""
    result = _run(
        stack_root, "rehearsal", "config",
        env_extra={"DB_NAME": "HOST_SENTINEL"},
    )
    assert result.returncode == 0, result.stderr
    assert "HOST_SENTINEL" not in result.stdout
    assert "paiM" in result.stdout


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker 필요")
def test_host_shell_values_blocked_even_when_absent_from_env_file(
    stack_root: Path, rehearsal_env: Path
):
    """프로필 파일에 **없는** 변수도 막아야 한다 — compose가 보간하는 이름이면
    호스트 값이 그대로 쓰인다. 리허설이 운영 포트를 점유하는 경로다."""
    rehearsal_env.write_text(
        _VALID_ENV.replace("PAIM_HTTP_PORT=8080\n", ""), encoding="utf-8"
    )
    result = _run(
        stack_root, "rehearsal", "config",
        env_extra={"PAIM_HTTP_PORT": "9999"},
    )
    assert result.returncode == 0, result.stderr
    assert "9999" not in result.stdout


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker 필요")
def test_rehearsal_forces_local_http(stack_root: Path, rehearsal_env: Path):
    """운영 .env를 복사해 프로필 파일을 만들면 PAIM_DOMAIN이 딸려온다. 그대로면
    Caddy가 실도메인 TLS 사이트로 떠서 로컬 HTTP 검증이 불가능해진다.

    TLS 종단을 결정하는 것은 caddy 서비스의 PAIM_DOMAIN이다. backend에도 값이
    전달되지만 사용하지 않으므로 무해하다 — caddy만 검사한다.
    """
    yaml = pytest.importorskip("yaml")
    rehearsal_env.write_text(
        _VALID_ENV + "PAIM_DOMAIN=paim.example.org\n", encoding="utf-8"
    )
    result = _run(stack_root, "rehearsal", "config")
    assert result.returncode == 0, result.stderr
    rendered = yaml.safe_load(result.stdout)
    assert rendered["services"]["caddy"]["environment"]["PAIM_DOMAIN"] == ":80"


# ── 프로필 env 격리 (C-001) ──────────────────────────────────────────────────

@pytest.mark.skipif(shutil.which("docker") is None, reason="docker 필요")
def test_root_env_keys_do_not_leak_into_rehearsal(
    stack_root: Path, rehearsal_env: Path
):
    """env_file은 !override가 없으면 **병합**된다. base의 .env가 남아 리허설
    컨테이너가 사용자 루트 .env를 읽고, 재정의하지 않은 production 자격증명이
    격리 스택으로 새어 들어간다.

    override YAML 하나만 파싱하는 정적 검사로는 이 실패를 볼 수 없다 —
    base와 합성한 최종 렌더링을 봐야 한다.

    루트 .env가 없어도(clean checkout) sentinel을 임시로 심어 검증한다.
    없다고 skip하면 C-001 회귀를 CI에서 놓친다.
    """
    root_env = stack_root / ".env"
    root_env.write_text("ROOT_ONLY_SENTINEL=leaked\n", encoding="utf-8")
    result = _run(stack_root, "rehearsal", "config")
    assert result.returncode == 0, result.stderr
    assert "ROOT_ONLY_SENTINEL" not in result.stdout
