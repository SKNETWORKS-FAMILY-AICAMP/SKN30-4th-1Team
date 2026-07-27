"""check-scope.sh의 비밀 파일 검출 회귀 테스트.

두 가지를 고정한다.

1. 루트 `.env` 예외는 **미추적 상태에서만** 적용된다. 스테이징·커밋되면 여전히 잡혀야
   한다 — 그게 이 검사가 실제로 막는 유출 경로다. 주소가 정확히 `^\\.env$`라서
   `.env.local`·`backend/.env`는 계속 걸린다.
2. 필터가 빈 입력에서 죽지 않는다. `grep -v`는 선택한 줄이 없으면 exit 1이고
   `set -o pipefail` 아래에서 스크립트를 진단 없이 종료시킨다. 변경 0건인 clean
   checkout이 정확히 그 상태였다.

실패 케이스는 종료 코드만 보지 않고 **출력의 파일명과 진단 문자열까지** 확인한다.
그러지 않으면 파이프라인 조기 종료(exit 1, 출력 없음)를 검출 성공으로 오인한다.
"""
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "check-scope.sh"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """스크립트와 config만 담은 최소 git 저장소. baseline 커밋까지 만들어 반환한다."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".agent-workflow").mkdir()
    (tmp_path / "scripts" / "check-scope.sh").write_bytes(_SCRIPT.read_bytes())
    (tmp_path / "scripts" / "check-scope.sh").chmod(0o755)
    (tmp_path / ".agent-workflow" / "config.sh").write_bytes(
        (_REPO_ROOT / ".agent-workflow" / "config.sh").read_bytes()
    )
    _git(tmp_path, "init", "-q", ".")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "baseline")
    return tmp_path


def _run(repo: Path, baseline: str = "HEAD") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["./scripts/check-scope.sh", baseline],
        cwd=repo, capture_output=True, text=True,
    )


# ── 통과해야 하는 경우 ────────────────────────────────────────────────────────

def test_clean_checkout_passes(repo: Path):
    """변경 0건. 이전 구현은 여기서 진단 없이 exit 1로 죽었다."""
    result = _run(repo)
    assert result.returncode == 0, result.stderr


def test_untracked_root_env_passes(repo: Path):
    """README.md·start-paim.bat이 요구하는 로컬 실행 계약 파일."""
    (repo / ".env").write_text("SECRET=value\n")
    result = _run(repo)
    assert result.returncode == 0, result.stderr


def test_untracked_root_env_with_other_files_passes(repo: Path):
    (repo / ".env").write_text("SECRET=value\n")
    (repo / "notes.md").write_text("hello\n")
    result = _run(repo)
    assert result.returncode == 0, result.stderr


def test_env_example_passes(repo: Path):
    (repo / ".env.example").write_text("SECRET=placeholder\n")
    result = _run(repo)
    assert result.returncode == 0, result.stderr


# ── 검출해야 하는 경우 ────────────────────────────────────────────────────────

def _assert_detected(result: subprocess.CompletedProcess, filename: str) -> None:
    """exit 1이면서 해당 파일을 secret-like로 진단했는지 확인.

    종료 코드만 보면 파이프라인 조기 종료를 검출로 오인한다.
    """
    assert result.returncode == 1
    assert "secret-like" in result.stderr
    assert filename in result.stderr


def test_staged_root_env_is_detected(repo: Path):
    """면제는 미추적 소스에만 적용된다. 스테이징되면 git diff --cached가 잡는다."""
    (repo / ".env").write_text("SECRET=value\n")
    _git(repo, "add", "-f", ".env")
    _assert_detected(_run(repo), ".env")


def test_committed_root_env_is_detected(repo: Path):
    """baseline 이후 커밋된 .env는 git diff가 잡는다."""
    (repo / ".env").write_text("SECRET=value\n")
    _git(repo, "add", "-f", ".env")
    _git(repo, "commit", "-qm", "leak")
    _assert_detected(_run(repo, "HEAD~1"), ".env")


@pytest.mark.parametrize(
    "path",
    [".env.local", ".env.prod", "backend/.env", "server.pem", "id_rsa.key"],
)
def test_other_secret_files_are_detected(repo: Path, path: str):
    """면제 주소가 정확히 ^\\.env$ 이므로 나머지는 전부 걸린다."""
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("secret\n")
    _assert_detected(_run(repo), path)


@pytest.mark.parametrize("path", [".env.local", "server.pem"])
def test_other_secret_files_detected_when_staged(repo: Path, path: str):
    target = repo / path
    target.write_text("secret\n")
    _git(repo, "add", "-f", path)
    _assert_detected(_run(repo), path)
