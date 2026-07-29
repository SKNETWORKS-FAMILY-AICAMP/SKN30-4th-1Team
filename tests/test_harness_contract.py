"""통합 테스트 하네스의 경로·인자·신호 계약 회귀.

`tests/integration/mysql/run.sh` 는 compose·마이그레이션 파일을 직접 읽는다.
그 경로가 옮겨지면 하네스가 깨지는데, 하네스를 돌려봐야만 알 수 있으면 늦다.
여기서는 Docker 를 기동하지 않는 `--check` 만 호출해 계약을 고정한다.

**경로 목록을 이 파일에 다시 적지 않는다.** 러너가 단일 출처이고 테스트는
그것을 호출만 한다. 러너도 목록을 하드코딩하지 않고 `docker compose config`
로 읽으므로, compose 만 깨진 경우도 검출된다.

각 테스트는 안정적인 **행위 ID**(`HC-*`)를 marker 로 단다. 수용 기준은 함수
이름이 아니라 이 집합을 계약으로 삼는다 — 함수 이름을 바꿔도 계약이 유지된다.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "integration" / "mysql" / "run.sh"
RUNNER_REL = Path("tests/integration/mysql/run.sh")
FIXTURES = ROOT / "tests" / "integration" / "mysql" / "fixtures"

#: AC 가 계약으로 삼는 필수 행위. 함수 이름과 독립이다.
REQUIRED_BEHAVIORS = {
    "HC-TRACKED",         # 러너가 추적되고 실행 가능하다
    "HC-PREFLIGHT-OK",    # 현재 트리에서 preflight 통과
    "HC-UTC-MARKERS",     # START/END 표지에 UTC 시각
    "HC-EXTERNAL-CWD",    # 저장소 밖 CWD 에서 호출 가능
    "HC-SPACE-PATH",      # 공백 포함 경로
    "HC-SYMLINK-CALL",    # 심볼릭 링크 호출 거부
    "HC-MISSING-BIND",    # compose 가 없는 경로를 참조
    "HC-ESCAPE-BIND",     # bind 가 저장소 밖을 가리킴
    "HC-UNTRACKED-BIND",  # bind 가 추적되지 않는 파일
    "HC-BAD-ARGS",        # 알 수 없는 인자·과다 인자
    "HC-OVERRIDE-GUARD",  # override 는 --check 전용
    "HC-ADDOPTS-GUARD",   # 상속된 PYTEST_ADDOPTS 를 비운다
}

#: 쓰기 없이 판정 가능한 케이스. read-only 검증자가 그대로 재실행할 수 있다.
READONLY_FIXTURES = {
    "compose-missing-migration.yml": "없는 경로",
    "compose-escapes-repo.yml": "저장소 밖을 가리킨다",
}


def _run(args, cwd=None, env_extra=None, runner=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [str(runner or RUNNER), *args],
        cwd=str(cwd or ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.fixture
def sandbox(tmp_path):
    """러너와 최소 구조를 담은 임시 Git 저장소.

    fixture 만 복사하면 compose 가 저장소 밖이 되어 '미추적' 이 아니라
    '저장소 밖' 으로 실패한다. 러너의 `ROOT` 가 임시 저장소가 되도록 구조를
    통째로 옮겨야 의도한 사유가 나온다.
    """
    repo = tmp_path / "repo"
    (repo / "backend" / "db").mkdir(parents=True)
    (repo / "tests" / "integration" / "mysql").mkdir(parents=True)

    for rel in [
        "tests/integration/mysql/run.sh",
        "tests/integration/mysql/compose.yml",
        "tests/integration/mysql/schema_v8.sql",
        "backend/db/schema.sql",
        "backend/db/migrate_v9.sql",
    ]:
        shutil.copy2(ROOT / rel, repo / rel)
    (repo / RUNNER_REL).chmod(0o755)

    git = ["git", "-C", str(repo)]
    subprocess.run([*git, "init", "-q", "."], check=True, capture_output=True)
    subprocess.run([*git, "config", "user.email", "t@example.com"], check=True)
    subprocess.run([*git, "config", "user.name", "t"], check=True)
    subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [*git, "commit", "-qm", "init"], check=True, capture_output=True,
        env={**os.environ, "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"},
    )
    return repo


def _check_in(repo, compose=None):
    return _run(
        ["--check"],
        cwd=repo,
        runner=repo / RUNNER_REL,
        env_extra={"HARNESS_COMPOSE_FILE": str(compose)} if compose else None,
    )


# ── 러너가 저장소 자산으로 존재한다 ─────────────────────────────────────────


@pytest.mark.behavior("HC-TRACKED")
def test_runner_is_really_staged_and_executable():
    """`git add -N` 만 된 상태를 추적으로 인정하면 안 된다.

    intent-to-add 는 index entry 가 empty blob 이라 `ls-files` 는 통과하지만
    실제 내용은 커밋 대상이 아니다. fresh checkout 보장의 증거가 되지 못한다.
    """
    assert RUNNER.is_file()
    assert os.access(RUNNER, os.X_OK), f"실행 권한이 없다: {RUNNER}"

    in_head = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"HEAD:{RUNNER_REL}"],
        capture_output=True,
    ).returncode == 0
    if in_head:
        return
    staged = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--cached", "--diff-filter=A",
         "--name-only", "--", str(RUNNER_REL)],
        capture_output=True, text=True,
    ).stdout
    assert str(RUNNER_REL) in staged, (
        "러너가 HEAD 에도 없고 실제 staged addition 도 아니다. "
        "`git add -N` 만 된 상태는 추적으로 인정하지 않는다."
    )


# ── preflight 기본 동작 ──────────────────────────────────────────────────────


@pytest.mark.behavior("HC-PREFLIGHT-OK")
def test_preflight_passes_on_current_tree():
    result = _run(["--check"])
    assert result.returncode == 0, (
        f"현재 트리에서 preflight 실패.\n{result.stdout}\n{result.stderr}"
    )
    assert "PASS preflight" in result.stdout


@pytest.mark.behavior("HC-UTC-MARKERS")
def test_preflight_reports_utc_markers():
    out = _run(["--check"]).stdout
    assert "START preflight at " in out
    assert "END rc=0 at " in out
    assert out.rstrip().endswith("Z"), f"UTC 표기가 아니다: {out[-40:]!r}"


@pytest.mark.behavior("HC-EXTERNAL-CWD")
def test_preflight_runs_from_unrelated_cwd(tmp_path):
    """`git rev-parse --show-toplevel` 은 호출자 CWD 를 따른다.

    러너가 그것에 의존하면 `/tmp` 에서 호출 시 루트를 `/tmp` 로 잡는다.
    """
    result = _run(["--check"], cwd=tmp_path)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


@pytest.mark.behavior("HC-SPACE-PATH")
def test_preflight_runs_from_path_with_spaces(tmp_path):
    workdir = tmp_path / "dir with spaces"
    workdir.mkdir()
    assert _run(["--check"], cwd=workdir).returncode == 0


@pytest.mark.behavior("HC-SYMLINK-CALL")
def test_symlink_invocation_is_rejected(tmp_path):
    """링크 경로로 루트를 잡으면 엉뚱한 디렉터리를 저장소로 오인한다."""
    link = tmp_path / "run-link.sh"
    link.symlink_to(RUNNER)
    result = subprocess.run([str(link), "--check"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 2
    assert "심볼릭 링크" in result.stderr


# ── 인자·override 가드 ──────────────────────────────────────────────────────


@pytest.mark.behavior("HC-BAD-ARGS")
@pytest.mark.parametrize("args", [["--help"], ["--Check"], ["--check", "extra"], ["a", "b"]])
def test_bad_arguments_exit_2_before_docker(args):
    """오타를 무시한 채 고비용 Docker 실행을 시작하면 안 된다."""
    result = _run(args)
    assert result.returncode == 2, f"{args} → {result.returncode}"
    assert "START compose-up" not in result.stdout


@pytest.mark.behavior("HC-OVERRIDE-GUARD")
def test_compose_override_rejected_outside_check(tmp_path):
    """테스트 전용 우회로가 운영 경로를 바꾸면 로그와 실제 입력이 달라진다."""
    result = _run([], env_extra={"HARNESS_COMPOSE_FILE": str(tmp_path / "x.yml")})
    assert result.returncode == 2
    assert "--check 에서만" in result.stderr
    assert "START compose-up" not in result.stdout


@pytest.mark.behavior("HC-OVERRIDE-GUARD")
def test_runner_marker_records_actual_compose():
    """로그만 보고 어떤 compose 를 썼는지 알 수 있어야 한다."""
    out = _run(["--check"]).stdout
    assert "RUNNER=tests/integration/mysql/run.sh" in out
    assert "COMPOSE=" in out


# ── compose 계약 — 고정 fixture (쓰기 불필요) ────────────────────────────────
#
# read-only 검증자가 그대로 재실행할 수 있어야 한다. Git 상태 조작이 필요한
# 케이스는 아래 sandbox 절이 담당한다.


@pytest.mark.behavior("HC-MISSING-BIND")
@pytest.mark.behavior("HC-ESCAPE-BIND")
@pytest.mark.parametrize("fixture,expected", sorted(READONLY_FIXTURES.items()))
def test_fixed_fixtures_fail_for_their_own_reason(fixture, expected):
    """각 fixture 가 **의도한 사유 하나로만** 실패해야 한다.

    사유가 섞이면 검출 대상이 아니라 다른 결함을 보고 있는 것이다.
    """
    path = FIXTURES / fixture
    assert path.is_file(), f"고정 fixture 가 없다: {path}"
    result = _run(["--check"], env_extra={"HARNESS_COMPOSE_FILE": str(path)})
    assert result.returncode != 0, f"{fixture} 를 통과시켰다"
    assert expected in result.stderr, (
        f"{fixture} 가 다른 이유로 실패했다. 기대={expected!r}\n{result.stderr}"
    )


@pytest.mark.behavior("HC-ADDOPTS-GUARD")
@pytest.mark.parametrize(
    "inherited",
    [
        "--collect-only",
        "--ignore=tests",
        "--deselect=tests/test_harness_contract.py::test_runner_is_really_staged_and_executable",
    ],
)
def test_inherited_pytest_addopts_is_neutralized(sandbox, tmp_path, inherited):
    """상속 옵션은 테스트를 미실행·제외하고도 exit 0 으로 끝낼 수 있다.

    8단계와 `END rc=0` 을 모두 갖춘 로그가 만들어져 게이트를 통과한 것처럼
    보인다. fake Docker 로 전체 경로를 통과시키고 두 fake uv 호출 모두에서
    상속 값이 실제로 사라졌는지 관찰한다. `--check`만 실행하면 pytest 경로를
    전혀 지나지 않아 이 회귀를 증명하지 못한다.
    """
    shim_dir = tmp_path / "shim-bin"
    shim_dir.mkdir()
    uv_spy = tmp_path / "uv-calls.log"

    fake_uv = shim_dir / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
{
    printf 'PYTEST_ADDOPTS=%s' "${PYTEST_ADDOPTS-<unset>}"
    printf '\tARG=%q' "$@"
    printf '\n'
} >> "$HARNESS_UV_SPY"
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    fake_docker = shim_dir / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case " $* " in
    *" compose version "*)
        echo 'Docker Compose version v2.test'
        ;;
    *" config --format json "*)
        python3 - <<'PY'
import json
import os

repo = os.environ["HARNESS_SPY_REPO"]
sources = [
    os.path.join(repo, "backend/db/schema.sql"),
    os.path.join(repo, "backend/db/migrate_v9.sql"),
    os.path.join(repo, "tests/integration/mysql/schema_v8.sql"),
]
print(json.dumps({
    "services": {
        "db": {
            "volumes": [
                {"type": "bind", "source": source} for source in sources
            ]
        }
    }
}))
PY
        ;;
    *" port v8_db 3306 "*)
        echo '127.0.0.1:33061'
        ;;
    *" port db 3306 "*)
        echo '127.0.0.1:33060'
        ;;
    *" exec -T db "*)
        cat >/dev/null
        ;;
    *)
        ;;
esac
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    result = _run(
        [],
        cwd=sandbox,
        runner=sandbox / RUNNER_REL,
        env_extra={
            "HARNESS_SPY_REPO": str(sandbox),
            "HARNESS_UV_SPY": str(uv_spy),
            "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}",
            "PYTEST_ADDOPTS": inherited,
        },
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert f"무시함: PYTEST_ADDOPTS={inherited}" in result.stdout, result.stdout

    calls = uv_spy.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 2, f"두 pytest 경로를 모두 관찰하지 못했다: {calls!r}"
    assert all(call.startswith("PYTEST_ADDOPTS=<unset>") for call in calls), calls
    assert "ARG=--ignore=tests/integration/mysql" in calls[0], calls
    assert "ARG=tests/integration/mysql" in calls[1], calls


# ── compose 계약 — 임시 Git 저장소에서 ───────────────────────────────────────
#
# Git index 를 조작해야 재현되는 케이스. 쓰기가 필요하므로 read-only 검증자는
# 이 테스트들을 재실행할 수 없다. 위 고정 fixture 가 그 공백을 메운다.


@pytest.mark.behavior("HC-PREFLIGHT-OK")
def test_sandbox_baseline_passes(sandbox):
    """음성 케이스가 의도한 사유로 실패함을 보이려면 기준선이 통과해야 한다."""
    result = _check_in(sandbox)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


@pytest.mark.behavior("HC-MISSING-BIND")
def test_missing_bind_source_is_detected(sandbox):
    compose = sandbox / "tests/integration/mysql/compose.yml"
    compose.write_text(
        compose.read_text().replace("migrate_v9.sql", "migrate_vNOPE.sql"),
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(sandbox), "add", "-A"], check=True, capture_output=True)
    result = _check_in(sandbox)
    assert result.returncode != 0
    assert "없는 경로" in result.stderr, result.stderr


@pytest.mark.behavior("HC-ESCAPE-BIND")
def test_bind_escaping_repo_is_detected(sandbox):
    """마지막 요소가 심볼릭 링크면 저장소 밖으로 탈출할 수 있다."""
    target = sandbox / "backend/db/schema.sql"
    target.unlink()
    target.symlink_to("/etc/hostname")
    subprocess.run(["git", "-C", str(sandbox), "add", "-A"], check=True, capture_output=True)
    result = _check_in(sandbox)
    assert result.returncode != 0
    assert "저장소 밖" in result.stderr, result.stderr


@pytest.mark.behavior("HC-UNTRACKED-BIND")
def test_untracked_bind_source_is_detected(sandbox):
    """존재하지만 추적되지 않는 파일은 fresh checkout 에 없다.

    참조 경로 자체를 검사하지 않으면, 미추적 심볼릭 링크가 추적된 파일을
    가리킬 때 통과한다.
    """
    real = sandbox / "backend/db/real_schema.sql"
    (sandbox / "backend/db/schema.sql").rename(real)
    subprocess.run(["git", "-C", str(sandbox), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(sandbox), "commit", "-qm", "move"], check=True, capture_output=True,
        env={**os.environ, "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"},
    )
    (sandbox / "backend/db/schema.sql").symlink_to("real_schema.sql")  # 미추적
    result = _check_in(sandbox)
    assert result.returncode != 0
    assert "추적되지 않는다" in result.stderr, result.stderr


# ── 메타 계약 — 행위 ID 집합 ────────────────────────────────────────────────


def _declared_behaviors():
    """이 모듈의 테스트들이 선언한 행위 ID 를 모은다."""
    found = set()
    for obj in list(globals().values()):
        for mark in getattr(obj, "pytestmark", []):
            if mark.name == "behavior":
                found.update(mark.args)
    return found


def test_required_behaviors_are_all_covered():
    """필수 행위 ID 가 하나도 빠지지 않았는지 검사한다.

    함수 이름이 아니라 행위 ID 를 계약으로 삼으므로 이름을 바꿔도 계약이
    유지된다. 반대로 행위를 지우거나 marker 를 떼면 여기서 걸린다.
    """
    missing = REQUIRED_BEHAVIORS - _declared_behaviors()
    assert not missing, f"검증되지 않은 필수 행위: {sorted(missing)}"


def test_no_undeclared_behavior_ids():
    """오타난 행위 ID 가 조용히 추가되지 않도록 한다."""
    extra = _declared_behaviors() - REQUIRED_BEHAVIORS
    assert not extra, f"REQUIRED_BEHAVIORS 에 없는 ID: {sorted(extra)}"


# ── State fingerprint golden vector (R-003) ─────────────────────────────────

FINGERPRINT_REFERENCE = ROOT / "tests" / "state_fingerprint.py"
FINGERPRINT_EXCLUDED_LOG = "artifacts/delegated-run.log"

# 아래 fixture의 byte stream을 독립 oracle로 계산한 값이다. 의도적인 명세 변경
# 없이는 갱신하지 않는다.
FINGERPRINT_GOLDEN_DIGEST = (
    "753828fbbf4de93fe95b3c6235aaf51f1dd02729c3cbd614057f163eb5ac337d"
)


def _fingerprint_git(repo: Path, *args: str, env=None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    ).stdout


def _make_fingerprint_vector(repo: Path) -> None:
    repo.mkdir()
    _fingerprint_git(repo, "init", "-q", "--initial-branch=main")
    _fingerprint_git(repo, "config", "user.name", "Fingerprint Fixture")
    _fingerprint_git(repo, "config", "user.email", "fingerprint@example.invalid")
    _fingerprint_git(repo, "config", "commit.gpgsign", "false")
    _fingerprint_git(repo, "config", "core.filemode", "true")

    tracked = repo / "tracked.txt"
    tracked.write_bytes(b"baseline\n")
    tracked.chmod(0o644)
    _fingerprint_git(repo, "add", "--", "tracked.txt")
    commit_env = {
        **os.environ,
        "LC_ALL": "C",
        "TZ": "UTC",
        "GIT_AUTHOR_NAME": "Fingerprint Fixture",
        "GIT_AUTHOR_EMAIL": "fingerprint@example.invalid",
        "GIT_AUTHOR_DATE": "2000-01-02T03:04:05+0000",
        "GIT_COMMITTER_NAME": "Fingerprint Fixture",
        "GIT_COMMITTER_EMAIL": "fingerprint@example.invalid",
        "GIT_COMMITTER_DATE": "2000-01-02T03:04:05+0000",
    }
    _fingerprint_git(repo, "commit", "-qm", "baseline", env=commit_env)

    # diff payload가 index와 worktree 양쪽 변경을 모두 포함해야 한다.
    tracked.write_bytes(b"unstaged change\n")
    (repo / "staged.txt").write_bytes(b"staged change\n")
    _fingerprint_git(repo, "add", "--", "staged.txt")

    # raw-path 정렬, mode, link payload의 경계가 드러나는 untracked 항목들이다.
    (repo / "space name.txt").write_bytes(b"space\x00payload\n")
    (repo / "space name.txt").chmod(0o751)
    (repo / "line\nbreak.bin").write_bytes(b"newline path")
    (repo / "line\nbreak.bin").chmod(0o640)
    (repo / "link to space").symlink_to("space name.txt")

    excluded = repo / FINGERPRINT_EXCLUDED_LOG
    excluded.parent.mkdir()
    excluded.write_bytes(b"this log must not affect the digest\n")


def _fingerprint_frame(kind: bytes, path: bytes, payload: bytes) -> bytes:
    """문서 명세만 보고 작성한 독립 직렬화 oracle."""
    fields = [
        kind,
        str(len(path)).encode(),
        path,
        str(len(payload)).encode(),
        payload,
    ]
    return b"\n".join(fields) + b"\n"


def _fingerprint_oracle(repo: Path) -> str:
    env = {**os.environ, "LC_ALL": "C"}
    head_output = _fingerprint_git(
        repo, "rev-parse", "--verify", "HEAD", env=env
    )
    assert head_output.endswith(b"\n") and not head_output.endswith(b"\n\n")
    head = head_output[:-1]

    diff = _fingerprint_git(
        repo,
        "-c",
        "core.quotePath=true",
        "diff",
        "--binary",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--diff-algorithm=myers",
        "--no-indent-heuristic",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "HEAD",
        "--",
        env=env,
    )
    assert b"tracked.txt" in diff and b"staged.txt" in diff
    assert diff.endswith(b"\n")

    raw_paths = _fingerprint_git(
        repo,
        "ls-files",
        "-z",
        "--others",
        "--exclude-standard",
        "--",
        env=env,
    ).split(b"\0")
    assert raw_paths.pop() == b""
    excluded = os.fsencode(FINGERPRINT_EXCLUDED_LOG)

    entries = []
    root = os.fsencode(repo)
    for path in sorted(candidate for candidate in raw_paths if candidate != excluded):
        absolute = os.path.join(root, path)
        metadata = os.lstat(absolute)
        if stat.S_ISLNK(metadata.st_mode):
            target = os.readlink(absolute)
            assert isinstance(target, bytes)
            entries.append(_fingerprint_frame(b"link", path, target))
        else:
            assert stat.S_ISREG(metadata.st_mode)
            mode = f"{stat.S_IMODE(metadata.st_mode):04o}".encode()
            content = Path(os.fsdecode(absolute)).read_bytes()
            payload = mode + b" " + hashlib.sha256(content).hexdigest().encode()
            entries.append(_fingerprint_frame(b"file", path, payload))

    stream = (
        _fingerprint_frame(b"head", b"", head)
        + _fingerprint_frame(b"diff", b"", diff)
        + b"".join(entries)
    )
    return hashlib.sha256(stream).hexdigest()


def _reference_fingerprint(repo: Path) -> str:
    result = subprocess.run(
        [
            os.fspath(FINGERPRINT_REFERENCE),
            "--repo",
            os.fspath(repo),
            "--exclude-path",
            FINGERPRINT_EXCLUDED_LOG,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_fingerprint_golden_vector_matches_reference_and_independent_oracle(tmp_path):
    repo = tmp_path / "fingerprint-vector"
    _make_fingerprint_vector(repo)

    reference = _reference_fingerprint(repo)
    oracle = _fingerprint_oracle(repo)
    assert reference == oracle == FINGERPRINT_GOLDEN_DIGEST


def test_fingerprint_exact_exclusion_removes_log_bytes_only(tmp_path):
    repo = tmp_path / "fingerprint-vector"
    _make_fingerprint_vector(repo)
    before = _reference_fingerprint(repo)

    (repo / FINGERPRINT_EXCLUDED_LOG).write_bytes(b"different delegated output\n")
    assert _reference_fingerprint(repo) == before

    # glob/prefix 규칙이 아니라 정확한 path 하나만 제외한다.
    sibling = repo / f"{FINGERPRINT_EXCLUDED_LOG}.extra"
    sibling.write_bytes(b"must be fingerprinted\n")
    assert _reference_fingerprint(repo) != before
