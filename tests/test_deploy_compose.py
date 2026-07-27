"""배포 구성 회귀 테스트.

YAML을 파싱해 검사하므로 Docker 없이 결정적으로 돈다(verify-backend.sh는
Docker가 없는 환경에서도 통과해야 한다). 실제 기동·영속성 검증은
deploy/README.md의 리허설 절차로 수행하고 결과를 구현 보고서에 기록한다.

여기서 고정하는 것은 "조용히 퇴행하면 배포가 깨지는" 항목들이다.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_ROOT = Path(__file__).resolve().parents[1]


class _ComposeLoader(yaml.SafeLoader):
    """Compose의 병합 제어 태그(`!override`, `!reset`)를 허용하는 로더.

    `safe_load`는 알 수 없는 태그에서 ConstructorError를 던진다. 여기서는 태그를
    무시하고 값만 취한다 — 태그가 붙었는지 자체는 원문 문자열로 검사한다.
    """


_ComposeLoader.add_multi_constructor(
    "!", lambda loader, suffix, node: loader.construct_sequence(node)
    if isinstance(node, yaml.SequenceNode) else loader.construct_object(node)
)


def _load(name: str) -> dict:
    return yaml.load((_ROOT / name).read_text(encoding="utf-8"), Loader=_ComposeLoader)


@pytest.fixture(scope="module")
def prod() -> dict:
    return _load("docker-compose.prod.yml")


@pytest.fixture(scope="module")
def dev() -> dict:
    return _load("docker-compose.yml")


# ── 포트 노출 ────────────────────────────────────────────────────────────────

def test_prod_db_and_backend_have_no_published_ports(prod: dict):
    """WBS "MySQL·Chroma 외부 포트 비공개". 외부 노출은 caddy 하나뿐이어야 한다."""
    for service in ("db", "backend"):
        assert "ports" not in prod["services"][service], (
            f"{service}에 ports가 생겼다 — Caddy를 우회해 직접 노출된다"
        )


def test_prod_caddy_is_the_only_exposed_service(prod: dict):
    exposed = [name for name, svc in prod["services"].items() if svc.get("ports")]
    assert exposed == ["caddy"]


def test_dev_db_binds_loopback_only(dev: dict):
    """개발 compose는 호스트 backend를 위해 포트를 열되 LAN에는 노출하지 않는다.

    README.md Quick Start와 start-paim.bat이 localhost:3306에 의존하므로 완전히
    닫으면 Windows 원클릭 실행이 깨진다.
    """
    ports = dev["services"]["db"]["ports"]
    assert len(ports) == 1
    assert str(ports[0]).startswith("127.0.0.1:"), (
        f"0.0.0.0 바인딩이면 LAN에 MySQL이 노출된다: {ports[0]}"
    )


# ── 영속성 ───────────────────────────────────────────────────────────────────

def test_prod_declares_all_persistent_volumes(prod: dict):
    """재시작·재배포 후 데이터가 남아야 한다. caddy_data는 인증서 재발급 방지."""
    expected = {"mysql_data", "chroma_data", "upload_data", "caddy_data", "caddy_config"}
    assert expected <= set(prod["volumes"])


@pytest.mark.parametrize(
    ("env_key", "mount"),
    [("UPLOAD_DIR", "upload_data"), ("CHROMA_PERSIST_DIR", "chroma_data")],
)
def test_backend_paths_match_their_volume_mounts(prod: dict, env_key: str, mount: str):
    """경로 환경변수와 마운트 지점이 어긋나면 데이터가 볼륨 밖 컨테이너 레이어에
    쌓이고 재배포 시 조용히 사라진다. 배포 구성에서 가장 사고 나기 쉬운 지점."""
    backend = prod["services"]["backend"]
    path = backend["environment"][env_key]
    assert path.startswith("/"), f"{env_key}는 절대경로여야 한다 (작업 디렉터리 의존 제거)"
    mounts = [v.split(":")[1] for v in backend["volumes"]]
    assert path in mounts, f"{env_key}={path} 가 {mount} 마운트 지점과 다르다"


# ── 환경변수 계약 ────────────────────────────────────────────────────────────

def test_backend_pins_db_connection(prod: dict):
    """호스트 .env에 SSH 터널용 DB_PORT=3307 등이 남아 있어도 컨테이너는
    내부 3306으로 붙어야 한다(mysql.py가 이를 클라이언트 포트로 읽는다)."""
    env = prod["services"]["backend"]["environment"]
    assert env["DB_HOST"] == "db"
    assert str(env["DB_PORT"]) == "3306"


def test_backend_pins_jwt_auth_mode(prod: dict):
    """dev 모드는 JWT 검증을 생략한다. 운영에서 그렇게 뜨면 인증이 통째로 무력화된다."""
    assert prod["services"]["backend"]["environment"]["PAIM_AUTH_MODE"] == "jwt"


def test_backend_reads_env_file(prod: dict):
    """Compose의 .env는 YAML 보간용일 뿐 컨테이너 환경으로 자동 주입되지 않는다.
    이 선언이 없으면 PAIM_JWT_SECRET 누락으로 기동 자체가 실패한다."""
    assert prod["services"]["backend"]["env_file"] == [".env"]


def test_caddy_receives_domain(prod: dict):
    """Caddyfile의 {$PAIM_DOMAIN::80}는 Caddy 프로세스 환경을 읽는다. 전달하지
    않으면 도메인을 설정해도 :80 폴백으로 떠서 인증서를 발급하지 않는다."""
    assert "PAIM_DOMAIN" in prod["services"]["caddy"]["environment"]


def test_caddy_domain_falls_back_to_port_80(prod: dict):
    """빈 문자열을 넘기면 Caddy가 기동에 실패한다.

    Caddy의 {$VAR:default}는 변수가 **미설정**일 때만 default를 쓴다.
    `${PAIM_DOMAIN:-}`로 넘기면 "빈 문자열로 설정됨"이 되어 사이트 주소가 비고
    "server block without any key is global configuration" 오류가 난다.
    리허설에서 실제로 재현된 문제다.
    """
    assert prod["services"]["caddy"]["environment"]["PAIM_DOMAIN"] == "${PAIM_DOMAIN:-:80}"


def test_caddyfile_starts_with_global_options_block():
    """Caddyfile의 첫 블록이 `{`로 시작하면 파서가 그것을 전역 옵션으로 읽는다.

    사이트 주소가 `{$PAIM_DOMAIN::80}`이라 이 블록이 없으면 파일 전체가 전역
    옵션으로 해석되어 "unrecognized global option: request_body"로 기동에
    실패한다. 리허설에서 실제로 재현된 문제다.
    """
    lines = [
        line.strip()
        for line in (_ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines[0] == "{", "전역 옵션 블록이 먼저 와야 한다"


@pytest.mark.parametrize(
    "key",
    ["DB_USER", "DB_PASSWORD", "DB_NAME", "PAIM_JWT_SECRET",
     "SESSION_MEMORY_KEY", "OPENAI_API_KEY"],
)
def test_required_env_uses_compose_fail_fast(key: str):
    """`${VAR:?}` 형태여야 누락 시 컨테이너가 뜨기 전에 멈춘다.

    SESSION_MEMORY_KEY와 OPENAI_API_KEY는 lazy 경로라 누락돼도 기동과 /health를
    통과한 뒤 실제 기능에서야 터진다. 그래서 이 단계 검사가 특히 중요하다.
    """
    raw = (_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert f"${{{key}:?" in raw, f"{key}에 fail-fast 보간이 없다"


# ── 단일 워커 ────────────────────────────────────────────────────────────────

def test_backend_pins_single_worker(prod: dict):
    """워커가 2개 이상이면 GitHub App 인메모리 세션과 Chroma 단일 점유가 깨진다.

    uvicorn은 --workers 생략 시 WEB_CONCURRENCY 환경변수를 읽으므로, 옵션을
    빼는 것만으로는 1개가 강제되지 않는다(오히려 외부 env가 결정하게 된다).
    """
    assert str(prod["services"]["backend"]["environment"]["WEB_CONCURRENCY"]) == "1"


def test_backend_healthcheck_uses_readiness_with_safe_timeout(prod: dict):
    health = prod["services"]["backend"]["healthcheck"]
    command = " ".join(health["test"])
    assert "/health/ready" in command
    assert 'b.get("status")=="ready"' in command
    assert str(health["timeout"]).rstrip("s") and int(str(health["timeout"]).rstrip("s")) >= 7


def test_mysql_init_mounts_v9_migration(prod: dict, dev: dict):
    for stack in (prod, dev):
        mounts = stack["services"]["db"]["volumes"]
        assert any("migrate_v9.sql" in mount for mount in mounts)


def test_dockerfile_pins_single_worker():
    dockerfile = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert '"--workers", "1"' in dockerfile


def test_prod_does_not_override_backend_command(prod: dict):
    """command override가 있으면 Dockerfile의 --workers 1 고정이 무력화된다."""
    assert "command" not in prod["services"]["backend"]


# ── MySQL 초기화 완료 ────────────────────────────────────────────────────────

def test_db_health_waits_for_final_mysqld_process(prod: dict):
    """공식 이미지의 init용 임시 mysqld도 ping에는 응답한다.

    backend 의존성과 빈 restore DB 복구가 초기화 SQL과 경합하지 않으려면 최종
    mysqld가 entrypoint를 대체해 PID 1이 된 뒤에만 healthy여야 한다.
    """
    health = prod["services"]["db"]["healthcheck"]["test"]
    assert health[0] == "CMD-SHELL"
    assert "/proc/1/comm" in health[1]
    assert "mysqladmin ping" in health[1]


# ── 재시작·로그 ──────────────────────────────────────────────────────────────

def test_all_services_restart_unless_stopped(prod: dict):
    """WBS "서버 재부팅 후 자동 실행" — Docker 데몬 부팅 시작과 함께 충족한다."""
    for name, svc in prod["services"].items():
        assert svc.get("restart") == "unless-stopped", f"{name}에 재시작 정책이 없다"


def test_all_services_cap_container_logs(prod: dict):
    """컨테이너 로그의 무한 증가만 막는다. 디스크 고갈 전반(볼륨·이미지·캐시)은
    deploy/README.md의 preflight·임계치 절차 담당."""
    for name, svc in prod["services"].items():
        options = svc.get("logging", {}).get("options", {})
        assert options.get("max-size"), f"{name}에 로그 크기 상한이 없다"
        assert options.get("max-file"), f"{name}에 로그 파일 개수 상한이 없다"


# ── 프로필 격리 ──────────────────────────────────────────────────────────────

def test_prod_declares_project_name(prod: dict):
    """지정하지 않으면 디렉터리명이 project가 되어 같은 루트의 개발 compose와
    mysql_data 볼륨을 공유한다 — 리허설이 개발 DB를 오염시킨다."""
    assert prod["name"] == "paim-prod"


@pytest.mark.parametrize(
    ("override", "project", "env_file"),
    [
        ("deploy/compose.rehearsal.yml", "paim-rehearsal", "deploy/.env.rehearsal"),
        ("deploy/compose.restore.yml", "paim-restore", "deploy/.env.restore"),
    ],
)
def test_rehearsal_profiles_are_isolated(override: str, project: str, env_file: str):
    """source(rehearsal)와 restore가 서로 다른 project여야 "빈 볼륨에 복구가
    실제로 되는가"를 검증할 수 있다.

    env_file 경로는 override 파일 위치가 아니라 **프로젝트 디렉터리** 기준으로
    해석된다. `.env.rehearsal`로 쓰면 리포지토리 루트에서 찾다가 실패한다.
    """
    data = _load(override)
    assert data["name"] == project
    assert data["services"]["backend"]["env_file"] == [env_file]


@pytest.mark.parametrize(
    "override", ["deploy/compose.rehearsal.yml", "deploy/compose.restore.yml"]
)
def test_rehearsal_env_file_uses_override_tag(override: str):
    """`!override`가 없으면 Compose는 env_file 시퀀스를 **병합**한다. base의
    `.env`가 남아 리허설 컨테이너가 사용자 루트 .env를 읽고, 재정의하지 않은
    production 자격증명·GitHub 설정이 격리 스택으로 새어 들어간다.

    이 정적 검사만으로는 부족하다 — 실제 합성 결과는
    tests/test_deploy_stack.py::test_root_env_keys_do_not_leak_into_rehearsal이
    `docker compose config`로 확인한다.
    """
    raw = (_ROOT / override).read_text(encoding="utf-8")
    assert "env_file: !override" in raw


@pytest.mark.parametrize(
    "override", ["deploy/compose.rehearsal.yml", "deploy/compose.restore.yml"]
)
def test_rehearsal_profiles_pin_local_http(override: str):
    """운영 .env를 복사해 프로필 파일을 만들면 PAIM_DOMAIN이 딸려온다. 그대로면
    Caddy가 실도메인 TLS 사이트로 떠서 로컬 HTTP 검증이 불가능해진다."""
    data = _load(override)
    assert data["services"]["caddy"]["environment"]["PAIM_DOMAIN"] == ":80"


@pytest.mark.parametrize(
    "override", ["deploy/compose.rehearsal.yml", "deploy/compose.restore.yml"]
)
def test_rehearsal_overrides_do_not_redeclare_ports(override: str):
    """Compose는 ports 시퀀스를 병합(append)한다. override에 8080을 적으면
    80과 8080이 함께 열려 운영 스택과 충돌한다. 포트 이동은 env 파일의
    PAIM_HTTP_PORT·PAIM_HTTPS_PORT로 한다.
    """
    data = _load(override)
    for name, svc in (data.get("services") or {}).items():
        assert "ports" not in svc, f"{override}의 {name}이 ports를 재선언했다"


# ── 비밀 파일 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pattern", [".env", ".env.*", "*.pem", "*.key"])
def test_dockerignore_excludes_secrets(pattern: str):
    """Git ignore는 Docker 빌드 컨텍스트 제외 규칙이 아니다. 루트 .env에는
    실제 API key·DB 비밀번호·JWT secret·세션 키가 들어 있다."""
    lines = (_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert pattern in [line.strip() for line in lines]


def test_dockerignore_keeps_env_example():
    lines = [l.strip() for l in (_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()]
    assert "!.env.example" in lines
