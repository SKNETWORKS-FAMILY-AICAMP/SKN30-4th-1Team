"""deploy/preflight.sh 회귀 테스트.

preflight가 막는 것은 "기동과 /health는 통과하는데 실제 기능에서 터지는" 설정
조합이다. Compose 보간(${VAR:?})으로는 표현할 수 없는 조건부 규칙이라 별도
스크립트로 두었고, 그 규칙을 여기서 고정한다.

Docker 없이 돈다 — 스크립트가 env 파일을 직접 파싱하기 때문이다.
"""
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PREFLIGHT = _ROOT / "deploy" / "preflight.sh"

_ALWAYS_REQUIRED = {
    "DB_USER": "root",
    "DB_PASSWORD": "pw",
    "DB_NAME": "paiM",
    "PAIM_JWT_SECRET": "x" * 48,
    "SESSION_MEMORY_KEY": "base64key",
    "OPENAI_API_KEY": "sk-test",
    "DB_HOST": "db",
    "DB_PORT": "3306",
    "PAIM_AUTH_MODE": "jwt",
    "RATE_LIMIT_SIGNUP": "5/minute",
    "RATE_LIMIT_LOGIN": "5/minute",
    "RATE_LIMIT_UPLOAD": "20/minute",
    "RATE_LIMIT_QUERY": "30/minute",
    "RATE_LIMIT_CHAT": "30/minute",
    "PAIM_PROXY_SUBNET": "172.30.12.0/24",
    "PAIM_CADDY_PROXY_IP": "172.30.12.10",
    "PAIM_BACKEND_PROXY_IP": "172.30.12.20",
    "FORWARDED_ALLOW_IPS": "172.30.12.10/32",
    "CORS_ORIGINS": "https://paim.example.org",
}


def _write_env(tmp_path: Path, **overrides: str) -> Path:
    values = dict(_ALWAYS_REQUIRED)
    values.update(overrides)
    path = tmp_path / "env"
    path.write_text(
        "".join(f"{k}={v}\n" for k, v in values.items() if v is not None),
        encoding="utf-8",
    )
    return path


def _run(env_file: Path, mode: str = "local") -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(_PREFLIGHT), "--env-file", str(env_file), "--mode", mode],
        capture_output=True, text=True, cwd=_ROOT,
    )


# ── 항상 필수 ────────────────────────────────────────────────────────────────

def test_minimal_config_passes(tmp_path: Path):
    assert _run(_write_env(tmp_path)).returncode == 0


def test_production_desktop_cors_origins_pass(tmp_path: Path):
    env = _write_env(
        tmp_path,
        CORS_ORIGINS="tauri://localhost,http://tauri.localhost",
    )
    assert _run(env).returncode == 0


@pytest.mark.parametrize(
    "origin",
    [
        "tauri://LOCALHOST",
        "tauri://localhost:1420",
        "tauri://other-host",
        "http://example.test\\path",
        "http://example.test?",
        "http://example.test#",
        "http://example.test:",
        "http://exam ple.test",
    ],
)
def test_cors_preflight_rejects_noncanonical_or_forbidden_origins(tmp_path: Path, origin: str):
    result = _run(_write_env(tmp_path, CORS_ORIGINS=origin))
    assert result.returncode == 1
    assert "CORS_ORIGINS" in result.stderr


def test_deploy_template_uses_actual_production_desktop_origins():
    template = (_ROOT / "deploy" / ".env.deploy.example").read_text(encoding="utf-8")
    assert "CORS_ORIGINS=tauri://localhost,http://tauri.localhost" in template
    assert "127.0.0.1:1420" not in template
    assert "localhost:1420" not in template


@pytest.mark.parametrize("missing", sorted(_ALWAYS_REQUIRED))
def test_each_required_value_is_enforced(tmp_path: Path, missing: str):
    result = _run(_write_env(tmp_path, **{missing: None}))
    assert result.returncode == 1
    assert missing in result.stderr


def test_openai_key_required_even_for_other_providers(tmp_path: Path):
    """backend/db/chroma.py가 LLM_PROVIDER와 무관하게 임베딩용으로 요구한다.
    lazy 검사라 누락돼도 기동·/health를 통과한 뒤 적재·검색에서 터진다."""
    env = _write_env(
        tmp_path, OPENAI_API_KEY=None, LLM_PROVIDER="claude", ANTHROPIC_API_KEY="k"
    )
    result = _run(env)
    assert result.returncode == 1
    assert "OPENAI_API_KEY" in result.stderr


# ── provider 조건부 ──────────────────────────────────────────────────────────

def test_claude_requires_anthropic_key(tmp_path: Path):
    result = _run(_write_env(tmp_path, LLM_PROVIDER="claude"))
    assert result.returncode == 1
    assert "ANTHROPIC_API_KEY" in result.stderr


def test_claude_passes_with_its_key(tmp_path: Path):
    assert _run(_write_env(tmp_path, LLM_PROVIDER="claude", ANTHROPIC_API_KEY="k")).returncode == 0


def test_unused_provider_keys_are_not_required(tmp_path: Path):
    """openai 배포가 쓰지도 않는 Anthropic·Google 자격증명을 요구하면 안 된다."""
    assert _run(_write_env(tmp_path, LLM_PROVIDER="openai")).returncode == 0


def test_unknown_provider_fails(tmp_path: Path):
    result = _run(_write_env(tmp_path, LLM_PROVIDER="gemini-pro"))
    assert result.returncode == 1
    assert "LLM_PROVIDER" in result.stderr


@pytest.mark.parametrize(
    ("provider", "extra"),
    [("google", {"GOOGLE_API_KEY": "g"}), ("local", {"LOCAL_LLM_URL": "http://x"})],
)
def test_extraction_incapable_providers_are_rejected_for_rollout(
    tmp_path: Path, provider: str, extra: dict
):
    """google은 google_client.py가 tool_schema에서 NotImplementedError를,
    local은 llm/factory.py가 지원 분기 부재로 ValueError를 던진다.
    환경변수가 완비돼도 문서·저장소 적재가 실패하므로 운영에 올리면 안 된다."""
    env = _write_env(tmp_path, LLM_PROVIDER=provider, PAIM_DOMAIN="paim.example.org", **extra)
    result = _run(env, mode="rollout")
    assert result.returncode == 1
    assert provider in result.stderr


@pytest.mark.parametrize(
    ("provider", "extra"),
    [("google", {"GOOGLE_API_KEY": "g"}), ("local", {"LOCAL_LLM_URL": "http://x"})],
)
def test_extraction_incapable_providers_only_warn_locally(
    tmp_path: Path, provider: str, extra: dict
):
    result = _run(_write_env(tmp_path, LLM_PROVIDER=provider, **extra))
    assert result.returncode == 0
    assert "WARN" in result.stderr


# ── 도메인 모드 계약 ─────────────────────────────────────────────────────────

def test_rollout_requires_domain(tmp_path: Path):
    """미설정이면 Caddy가 :80 폴백으로 떠서 인증서를 발급하지 않는다.
    WBS: HTTP만 제공되는 상태는 배포 완료로 인정하지 않음."""
    result = _run(_write_env(tmp_path), mode="rollout")
    assert result.returncode == 1
    assert "PAIM_DOMAIN" in result.stderr


def test_local_mode_allows_missing_domain(tmp_path: Path):
    result = _run(_write_env(tmp_path))
    assert result.returncode == 0
    assert "PAIM_DOMAIN" in result.stderr  # 경고는 남는다


def test_rollout_passes_with_domain(tmp_path: Path):
    assert _run(_write_env(tmp_path, PAIM_DOMAIN="paim.example.org"), mode="rollout").returncode == 0


# ── GitHub App 설정군 ────────────────────────────────────────────────────────

def test_github_unset_is_allowed_with_warning(tmp_path: Path):
    result = _run(_write_env(tmp_path))
    assert result.returncode == 0
    assert "GitHub App" in result.stderr


@pytest.mark.parametrize(
    ("partial", "expected"),
    [
        ({"GITHUB_APP_SLUG": "s"}, "GITHUB_APP_ID"),
        ({"GITHUB_APP_ID": "1"}, "GITHUB_APP_INSTALL_URL"),
        ({"GITHUB_APP_ID": "1", "GITHUB_APP_SLUG": "s"}, "GITHUB_APP_PRIVATE_KEY"),
    ],
)
def test_partial_github_config_is_rejected(tmp_path: Path, partial: dict, expected: str):
    """부분 설정이 가장 위험하다 — router.py의 세 검사가 전부 lazy 503이라
    기동·/health를 통과한 뒤 사용 시점에 실패한다."""
    result = _run(_write_env(tmp_path, **partial))
    assert result.returncode == 1
    assert expected in result.stderr


def test_complete_github_config_passes(tmp_path: Path):
    env = _write_env(
        tmp_path,
        GITHUB_APP_SLUG="paim",
        GITHUB_APP_ID="123456",
        GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----",
    )
    assert _run(env).returncode == 0


def test_private_key_path_rejected_for_rollout(tmp_path: Path):
    """github/router.py가 이 경로를 컨테이너 내부에서 그대로 open()한다.
    호스트 경로를 넣으면 파일이 없어 실패한다."""
    env = _write_env(
        tmp_path,
        PAIM_DOMAIN="paim.example.org",
        GITHUB_APP_SLUG="paim",
        GITHUB_APP_ID="123456",
        GITHUB_APP_PRIVATE_KEY_PATH="/home/user/paim.pem",
    )
    result = _run(env, mode="rollout")
    assert result.returncode == 1
    assert "GITHUB_APP_PRIVATE_KEY_PATH" in result.stderr


# ── 비밀값 비노출 ────────────────────────────────────────────────────────────

def test_secret_values_never_appear_in_output(tmp_path: Path):
    """진단은 변수 이름만 보고해야 한다. 값이 새면 로그·CI 출력에 남는다."""
    sentinel = "SENTINEL-e3b0c44298fc1c14"
    env = _write_env(tmp_path, DB_PASSWORD=sentinel, PAIM_JWT_SECRET=sentinel, ANTHROPIC_API_KEY=None)
    result = _run(env, mode="rollout")
    assert sentinel not in result.stdout
    assert sentinel not in result.stderr


# ── dotenv 파싱 경계 조건 ────────────────────────────────────────────────────
#
# Compose의 dotenv 규칙과 어긋나면 "preflight는 통과했는데 컨테이너는 다른 값을
# 쓴다"가 되어 검사 자체가 무의미해진다. 아래 두 케이스는 실제로 오판했던 것이다.

def _write_raw(tmp_path: Path, extra: str) -> Path:
    path = tmp_path / "env"
    path.write_text(
        "".join(f"{k}={v}\n" for k, v in _ALWAYS_REQUIRED.items()) + extra,
        encoding="utf-8",
    )
    return path


def test_quoted_value_with_inline_comment(tmp_path: Path):
    """Compose는 claude로 읽는다. 순진한 파서는 주석까지 값으로 삼아 rollout을 막았다."""
    env = _write_raw(tmp_path, 'LLM_PROVIDER="claude" # 주석\nANTHROPIC_API_KEY=key\n')
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "provider=claude" in result.stderr


def test_empty_quoted_value_with_inline_comment_is_empty(tmp_path: Path):
    """Compose는 빈 값으로 읽는다. 순진한 파서는 `"" # ...`를 non-empty로 보아
    자격증명 없이 통과시켰고, 컨테이너는 첫 LLM 호출에서 실패했다."""
    env = _write_raw(tmp_path, 'LLM_PROVIDER=claude\nANTHROPIC_API_KEY="" # 의도적 빈 값\n')
    result = _run(env)
    assert result.returncode == 1
    assert "ANTHROPIC_API_KEY" in result.stderr


def test_single_quoted_value(tmp_path: Path):
    env = _write_raw(tmp_path, "LLM_PROVIDER='claude'\nANTHROPIC_API_KEY='key'\n")
    assert _run(env).returncode == 0


def test_unquoted_inline_comment_is_stripped(tmp_path: Path):
    env = _write_raw(tmp_path, "LLM_PROVIDER=claude # 주석\nANTHROPIC_API_KEY=key\n")
    result = _run(env)
    assert result.returncode == 0
    assert "provider=claude" in result.stderr


def test_export_prefix_is_accepted(tmp_path: Path):
    env = _write_raw(tmp_path, "export LLM_PROVIDER=claude\nexport ANTHROPIC_API_KEY=key\n")
    assert _run(env).returncode == 0


def test_duplicate_key_last_wins(tmp_path: Path):
    """Compose·dotenv 관례. 마지막 정의가 이긴다."""
    env = _write_raw(tmp_path, "LLM_PROVIDER=google\nLLM_PROVIDER=claude\nANTHROPIC_API_KEY=key\n")
    result = _run(env)
    assert result.returncode == 0
    assert "provider=claude" in result.stderr


# ── DB 계정 계약 ─────────────────────────────────────────────────────────────

def test_non_root_db_user_is_rejected(tmp_path: Path):
    """운영 compose는 MySQL에 MYSQL_ROOT_PASSWORD만 넘긴다 — 다른 계정은 생성되지
    않는다. 그런데 startup의 DB 보증이 오류를 로깅하고 계속 기동해서 /health는
    200이고 DB 기반 API만 조용히 실패한다."""
    result = _run(_write_env(tmp_path, DB_USER="paim_app"))
    assert result.returncode == 1
    assert "DB_USER" in result.stderr


def test_root_db_user_passes(tmp_path: Path):
    assert _run(_write_env(tmp_path, DB_USER="root")).returncode == 0


# ── 위험한 env 문법 거부 ─────────────────────────────────────────────────────
#
# dotenv 문법 전체를 셸로 재구현하려다 두 번 어긋났다. 재구현 대신 해석이 갈릴
# 수 있는 문법을 거부한다 — 아래 두 경우가 "preflight는 통과하는데 컨테이너는
# 다른 값을 쓰는" 실제 우회였다.

def test_interpolation_in_value_is_rejected(tmp_path: Path):
    """`DB_NAME=${HOST_X}`는 Compose가 호스트 셸 값으로 치환한다. preflight가
    검사한 문자열과 컨테이너가 쓰는 값이 달라진다."""
    result = _run(_write_raw(tmp_path, "DB_NAME=${HOST_X}\n"))
    assert result.returncode == 1
    assert "보간" in result.stderr


def test_dollar_password_via_single_quote_is_allowed(tmp_path: Path):
    """`$`가 든 비밀번호는 작은따옴표(완전 리터럴)로 감싸면 통과한다 — 이것이
    계약이 요구하는 유일한 표기다."""
    result = _run(_write_raw(tmp_path, "DB_PASSWORD='pa$word'\n"))
    assert result.returncode == 0, result.stderr


# ── CR3-001: Compose가 허용하는 정상 값을 과잉 거부하지 않는다 ────────────────
#
# 라운드3에서 validate_env_syntax가 작은따옴표 리터럴 $, 인라인 주석 속 $, BOM,
# 값 앞 공백을 Compose와 달리 거부하던 것을 고쳤다. 파서를 env_get과 통일했으므로
# "검사값 = 컨테이너가 쓰는 값"이다. 아래는 파싱 결과를 실제 결정(DB_USER의 root
# 여부)에 연결해 값이 진짜로 그렇게 해석됐는지까지 고정한다.

def test_single_quoted_dollar_is_literal(tmp_path: Path):
    """`DB_PASSWORD='pa$word'`는 Compose에서 리터럴이다 — 작은따옴표는 보간하지
    않는다. 운영 비밀번호에 $가 들어가도 preflight가 막으면 안 된다."""
    result = _run(_write_raw(tmp_path, "DB_PASSWORD='pa$word'\n"))
    assert result.returncode == 0, result.stderr


def test_inline_comment_dollar_is_not_interpolation(tmp_path: Path):
    """따옴표 없는 값의 ` #` 뒤 $는 주석이라 보간이 아니다. Compose는 paiM으로 읽는다."""
    result = _run(_write_raw(tmp_path, "DB_NAME=paiM # 비용 $5\n"))
    assert result.returncode == 0, result.stderr


def test_bom_on_first_line_is_stripped(tmp_path: Path):
    """UTF-8 BOM이 첫 키를 가려 '누락'으로 오판하면 안 된다. Compose는 BOM을 제거한다."""
    path = tmp_path / "env"
    path.write_text(
        "﻿" + "".join(f"{k}={v}\n" for k, v in _ALWAYS_REQUIRED.items()),
        encoding="utf-8",
    )
    assert _run(path).returncode == 0


def test_leading_space_before_quoted_value_parses_to_root(tmp_path: Path):
    """`DB_USER= "root"`는 Compose가 선행 공백을 떼고 root로 읽는다. 파서가 따옴표를
    값에 남기면 `"root"` != root 로 non-root 오판해 막았다 — 통과가 정상."""
    result = _run(_write_raw(tmp_path, 'DB_USER= "root"\n'))
    assert result.returncode == 0, result.stderr


def test_single_quoted_value_is_actually_read(tmp_path: Path):
    """단순 '허용'이 아니라 값이 실제로 파싱되는지 결정에 연결해 확인한다.
    `DB_USER='paim_app'`(작은따옴표 non-root)는 거부돼야 한다 — 통과하면 파서가
    값을 읽지 않고 흘려보낸 것이다."""
    result = _run(_write_raw(tmp_path, "DB_USER='paim_app'\n"))
    assert result.returncode == 1
    assert "DB_USER" in result.stderr


# ── CR5-001: 작은따옴표 밖의 $는 전부 거부하는 계약 (under-rejection 구멍 봉쇄) ──
#
# 큰따옴표·무따옴표의 $는 quote 모드마다 이스케이프/보간 규칙이 달라(무따옴표는
# 백슬래시 미처리, 큰따옴표는 \$→$$ 후 보간) 셸로 리터럴/보간을 안전하게 구분하려던
# 시도가 세 번 어긋났다. 그래서 작은따옴표 밖의 $는 전부 거부하고, $가 필요한 값은
# 작은따옴표(완전 리터럴)로 쓰게 한다. 이 방향엔 under-rejection 구멍이 없다.

@pytest.mark.parametrize(
    "literal_value",
    [
        "DB_PASSWORD='pa$word'",      # 작은따옴표 → 완전 리터럴
        "DB_PASSWORD='pa$$word'",     # 안의 $$도 리터럴 두 글자
        "DB_PASSWORD='price$5'",      # 숫자 뒤 $도 그대로
        "DB_PASSWORD='$HOST_X'",      # 보간처럼 보여도 작은따옴표라 리터럴
    ],
)
def test_single_quoted_dollar_always_allowed(tmp_path: Path, literal_value: str):
    """작은따옴표는 compose-go에서 100% 리터럴이라 어떤 $ 조합도 통과해야 한다."""
    result = _run(_write_raw(tmp_path, literal_value + "\n"))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "rejected_value",
    [
        # 실제 보간 (호스트 변수 주입)
        "DB_PASSWORD=$HOST_X",         # 무따옴표 $VAR
        "DB_NAME=${HOST_X}",           # ${VAR}
        "DB_NAME=$_SECRET",            # $_ 식별자 시작
        'DB_NAME="pre${X}post"',       # 큰따옴표 안 ${...}
        # CR5-001 under-rejection 구멍 — 옛 파서가 통과시키던 것들
        "DB_NAME=\\$HOST_DB",          # 무따옴표 \$VAR (백슬래시 미처리 → 보간)
        'DB_NAME="\\$HOST_DB"',        # 큰따옴표 \\$VAR
        'DB_NAME="\\$$HOST_DB"',       # 큰따옴표 \$$VAR (뒤쪽 실제 보간)
        # 리터럴이지만 계약상 작은따옴표 밖이라 거부(over-rejection, 의도적)
        "DB_PASSWORD=pa$$word",        # 무따옴표 $$ → 작은따옴표로 쓰라
        'DB_PASSWORD="pa$word"',       # 큰따옴표 $ → 작은따옴표로 쓰라
    ],
)
def test_dollar_outside_single_quotes_is_rejected(tmp_path: Path, rejected_value: str):
    """작은따옴표 밖의 $는 실제 보간이든 리터럴이든 전부 거부한다. 특히 옛 파서가
    호스트 변수 주입을 통과시키던 \\$VAR·\\$$VAR 구멍이 막혔는지 고정한다."""
    result = _run(_write_raw(tmp_path, rejected_value + "\n"))
    assert result.returncode == 1
    assert "$" in result.stderr


def test_unterminated_double_quote_is_rejected(tmp_path: Path):
    """Compose는 다음 줄까지 이어 읽지만 preflight는 첫 줄만 본다."""
    result = _run(_write_raw(tmp_path, 'EXTRA="unclosed\nstill going\n'))
    assert result.returncode == 1
    assert "따옴표" in result.stderr


def test_unterminated_single_quote_is_rejected(tmp_path: Path):
    """C-004의 조용한 DB 실패가 여러 줄 값으로 재발하던 경로."""
    result = _run(_write_raw(tmp_path, "EXTRA='unclosed\nstill going\n"))
    assert result.returncode == 1
    assert "따옴표" in result.stderr


def test_multiline_db_user_does_not_slip_through(tmp_path: Path):
    """`DB_USER='root\\njunk'`는 Compose에서 root가 아니다. 미종결 따옴표로 잡힌다.
    (중복 키라 last-wins로 이 값이 실제 DB_USER가 된다.)"""
    result = _run(_write_raw(tmp_path, "DB_USER='root\njunk'\n"))
    assert result.returncode == 1


# ── CR6-001: 지원하지 않는 줄 형식은 건너뛰지 말고 거부 ───────────────────────
#
# Compose는 `KEY = VALUE`(등호 주변 공백)·`KEY: VALUE`(콜론)·탭 구분자도 읽어 값을
# 보간한다(docker compose v5.3.1로 직접 확인). 정규식이 이런 줄을 skip하면 값 파서가
# $를 다 막아도 그 줄의 보간이 못 보는 사이 주입된다. 그래서 skip이 아니라 reject.

@pytest.mark.parametrize(
    "bad_line",
    [
        "DB_USER = $HOST_DB_USER",     # 등호 앞뒤 공백 + 보간
        "DB_USER : $HOST_DB_USER",     # 콜론 구분자
        "DB_USER\t=\t$HOST_DB_USER",   # 탭 구분자
        "export DB_USER = $HOST_DB",   # export + 등호 공백
        "DB_USER $HOST",               # 구분자 없는 줄
    ],
)
def test_unsupported_line_forms_are_rejected(tmp_path: Path, bad_line: str):
    """건너뛰던(skip) 줄들이 이제 즉시 실패해야 한다 — 중복 정의로 안전한 첫 줄 뒤에
    위험한 줄을 둬도 Docker 호출 전에 막힌다."""
    result = _run(_write_raw(tmp_path, bad_line + "\n"))
    assert result.returncode == 1
    assert "지원하지 않는 줄" in result.stderr


def test_spaced_equals_does_not_slip_via_last_wins(tmp_path: Path):
    """`DB_USER=root` 뒤 `DB_USER = paim_app`을 두면 Compose는 last-wins로 paim_app을
    쓴다. skip하면 preflight가 root만 보고 non-root 검사를 통과시키던 CR6-001."""
    result = _run(_write_raw(tmp_path, "DB_USER = paim_app\n"))
    assert result.returncode == 1


def test_get_mode_validates_before_printing(tmp_path: Path):
    """--get은 문법 검증을 먼저 통과해야 값을 낸다. 지원하지 않는 줄이 있으면 값을
    출력하지 말고 non-zero로 끝나야 한다(런북이 Caddy와 다른 값을 검사하지 않도록)."""
    env = _write_raw(
        tmp_path, "PAIM_DOMAIN=safe.example.org\nPAIM_DOMAIN = $HOST_DOMAIN\n"
    )
    result = subprocess.run(
        [str(_PREFLIGHT), "--get", "PAIM_DOMAIN", "--env-file", str(env)],
        capture_output=True, text=True, cwd=_ROOT,
    )
    assert result.returncode != 0
    assert result.stdout.strip() == ""   # stale 값을 흘리지 않는다


def test_get_mode_returns_resolved_value_on_clean_file(tmp_path: Path):
    """정상 파일에서는 --get이 Compose 해석값을 그대로 낸다(따옴표·인라인 주석 처리)."""
    env = _write_raw(tmp_path, 'PAIM_DOMAIN="paim.example.org" # 배포용\n')
    result = subprocess.run(
        [str(_PREFLIGHT), "--get", "PAIM_DOMAIN", "--env-file", str(env)],
        capture_output=True, text=True, cwd=_ROOT,
    )
    assert result.returncode == 0
    assert result.stdout == "paim.example.org"


# ── 입력 검증 ────────────────────────────────────────────────────────────────

def test_missing_env_file_fails(tmp_path: Path):
    result = subprocess.run(
        [str(_PREFLIGHT), "--env-file", str(tmp_path / "nope"), "--mode", "local"],
        capture_output=True, text=True, cwd=_ROOT,
    )
    assert result.returncode == 2


def test_invalid_mode_fails(tmp_path: Path):
    result = _run(_write_env(tmp_path), mode="production")
    assert result.returncode == 2
