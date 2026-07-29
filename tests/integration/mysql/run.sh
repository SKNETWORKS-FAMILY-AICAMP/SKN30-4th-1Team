#!/usr/bin/env bash
# 백엔드 전체 게이트 — 비통합 pytest + 실제 MySQL 통합 pytest.
#
# MySQL 전용이 아니다. 비통합 pytest 를 먼저 돌린 뒤 컨테이너를 띄운다.
# 이 파일이 유일한 기준이며, scripts/run-backend-tests.sh 는 호환 래퍼일 뿐이다.
#
#   ./tests/integration/mysql/run.sh            전체 실행
#   ./tests/integration/mysql/run.sh --check    preflight 만 (Docker 미기동)
#
# preflight 는 compose 가 참조하는 bind mount 를 `docker compose config` 로
# 정규화해 읽는다. 경로 목록을 여기에 적지 않는다 — 복제하면 compose 만 깨진
# 경우를 놓친다.
#
# 시스템 전제: git, uv, docker(+compose plugin), awk, realpath, python3 >= 3.6.
# 이 python3 는 JSON 파싱 전용이며 pyproject.toml 의 requires-python(>=3.11,
# uv 가 관리하는 프로젝트 런타임)과는 별개 인터프리터다.
set -euo pipefail

# ── 인자 (F-10) ──────────────────────────────────────────────────────────────
# 인자 없음 또는 정확히 --check 하나만. 오타를 무시한 채 고비용 실행을 시작하지
# 않는다.
usage() {
    echo "usage: run.sh [--check]" >&2
    echo "  (인자 없음)  전체 게이트 실행" >&2
    echo "  --check      preflight 만. Docker 를 기동하지 않는다" >&2
}
CHECK_ONLY=0
case $# in
    0) ;;
    1) if [ "$1" = "--check" ]; then
           CHECK_ONLY=1
       else
           echo "[harness] 알 수 없는 인자: $1" >&2; usage; exit 2
       fi ;;
    *) echo "[harness] 인자가 너무 많다: $*" >&2; usage; exit 2 ;;
esac

# ── 저장소 루트 ───────────────────────────────────────────────────────────────
# git rev-parse 는 호출자의 CWD 를 따르므로 쓰지 않는다. /tmp 에서 부르면 /tmp 가 된다.
_src="${BASH_SOURCE[0]}"
if [ -L "$_src" ]; then
    echo "[harness] 심볼릭 링크 호출은 지원하지 않는다: $_src" >&2
    exit 2
fi
ROOT="$(cd -P "$(dirname "$_src")/../../.." && pwd)" || {
    echo "[harness] 저장소 루트를 확인하지 못했다" >&2
    exit 2
}
[ -d "$ROOT/backend/db" ] || {
    echo "[harness] 저장소 루트가 아니다: $ROOT" >&2
    exit 2
}

CANONICAL_COMPOSE="$ROOT/tests/integration/mysql/compose.yml"

# ── compose override (F-1) ───────────────────────────────────────────────────
# 음성 fixture 를 가리키는 용도이며 --check 에서만 허용한다. 전체 실행에서
# 허용하면 로그에 기록된 입력과 실제 실행 입력이 달라질 수 있다.
if [ -n "${HARNESS_COMPOSE_FILE:-}" ]; then
    if [ "$CHECK_ONLY" -ne 1 ]; then
        echo "[harness] HARNESS_COMPOSE_FILE 은 --check 에서만 쓸 수 있다." >&2
        echo "[harness] 전체 실행은 canonical compose 만 사용한다: $CANONICAL_COMPOSE" >&2
        exit 2
    fi
    COMPOSE_FILE="$HARNESS_COMPOSE_FILE"
else
    COMPOSE_FILE="$CANONICAL_COMPOSE"
fi

MIGRATION="$ROOT/backend/db/migrate_v9.sql"
PROJECT_NAME="paim-mysql-integration-$$"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/paim-uv-cache}"


now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[harness] $*"; }

step_start() { say "START $1 at $(now)"; }
step_ok()    { say "PASS $1 rc=0 at $(now)"; }
step_fail()  { say "FAIL $1 rc=$2 at $(now)"; }
# 상속된 PYTEST_ADDOPTS 는 게이트를 무력화할 수 있다.
# `PYTEST_ADDOPTS=--collect-only` 면 테스트를 하나도 실행하지 않고 exit 0 이 되어,
# 8단계와 END rc=0 을 모두 갖춘 로그가 만들어진다. 비운다.
if [ -n "${PYTEST_ADDOPTS:-}" ]; then
    say "무시함: PYTEST_ADDOPTS=${PYTEST_ADDOPTS}"
fi
unset PYTEST_ADDOPTS


# ── preflight ────────────────────────────────────────────────────────────────

# compose 의 bind mount source 를 정규화해 읽는다(F-3).
# `docker compose config` 는 Docker 데몬을 요구하지 않으며 상대 경로를 절대
# 경로로 풀어 준다. 인용 short form, 주석, long form(`type: bind`)을 모두
# 처리하고 named/anonymous volume 은 type 으로 구분된다.
compose_bind_sources() {
    docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null \
        | python3 -c '
import json, sys
try:
    doc = json.load(sys.stdin)
except Exception as exc:
    sys.stderr.write("compose JSON 파싱 실패: %s\n" % exc)
    sys.exit(1)
for svc in (doc.get("services") or {}).values():
    for vol in (svc.get("volumes") or []):
        if vol.get("type") == "bind":
            src = vol.get("source")
            if src:
                print(src)
'
}

preflight() {
    local rc=0

    # 필수 명령 — realpath·python3 도 이 러너의 전제다
    local cmd
    for cmd in git uv docker awk realpath python3; do
        command -v "$cmd" >/dev/null 2>&1 || { echo "  없는 명령: $cmd" >&2; rc=1; }
    done
    docker compose version >/dev/null 2>&1 \
        || { echo "  Docker Compose plugin 없음" >&2; rc=1; }

    bash -n "$_src" || { echo "  러너 구문 오류" >&2; rc=1; }
    [ -x "$_src" ] || { echo "  러너에 실행 권한 없음: $_src" >&2; rc=1; }

    [ -e "$COMPOSE_FILE" ] || { echo "  없는 경로: $COMPOSE_FILE" >&2; return 1; }

    # compose 파싱 실패는 반드시 preflight 실패로 전파한다
    local mounts=() src
    while IFS= read -r src; do
        [ -n "$src" ] && mounts+=("$src")
    done < <(compose_bind_sources)
    if [ ${#mounts[@]} -eq 0 ]; then
        echo "  compose 에서 bind mount 를 읽지 못했다: $COMPOSE_FILE" >&2
        rc=1
    fi

    local p resolved
    for p in "$COMPOSE_FILE" "$MIGRATION" ${mounts[@]+"${mounts[@]}"}; do
        if [ ! -e "$p" ]; then
            echo "  없는 경로: $p" >&2; rc=1; continue
        fi

        # 최종 객체까지 해석한다. 부모만 해석하고 basename 을 다시 붙이면
        # 마지막 요소가 심볼릭 링크일 때 저장소 밖으로 탈출한다(F-2).
        resolved="$(realpath -e -- "$p" 2>/dev/null)" || {
            echo "  경로 해석 실패: $p" >&2; rc=1; continue
        }

        # 경계를 먼저 본다. 추적 검사를 앞에 두면 저장소 밖 절대 경로가
        # "추적되지 않는다" 로 먼저 걸려 원인이 가려진다.
        case "$resolved" in
            "$ROOT"/*) ;;
            *) echo "  저장소 밖을 가리킨다: $p -> $resolved" >&2; rc=1; continue ;;
        esac

        # 참조 경로와 해석된 경로가 모두 추적돼야 한다. 해석된 것만 보면
        # 미추적 심볼릭 링크가 추적된 파일을 가리킬 때 통과한다(F-2).
        git -C "$ROOT" ls-files --error-unmatch -- "$p" >/dev/null 2>&1 \
            || { echo "  추적되지 않는다: $p" >&2; rc=1; continue; }
        git -C "$ROOT" ls-files --error-unmatch -- "$resolved" >/dev/null 2>&1 \
            || { echo "  추적되지 않는다: $resolved" >&2; rc=1; }
    done

    return $rc
}

say "RUNNER=tests/integration/mysql/run.sh ROOT=$ROOT COMPOSE=$COMPOSE_FILE"

if [ "$CHECK_ONLY" -eq 1 ]; then
    step_start preflight
    if preflight; then
        step_ok preflight
        say "END rc=0 at $(now)"
        exit 0
    fi
    step_fail preflight 1
    say "END rc=1 at $(now)"
    exit 1
fi

# ── 정리 ─────────────────────────────────────────────────────────────────────
# 신호와 cleanup 의 역할을 분리한다(F-7). INT/TERM 에서 cleanup 을 직접 부르면
# 그 안의 exit 이 EXIT trap 을 다시 발동시켜 중복 실행되고, 종료 코드가 0 으로
# 바뀌어 신호로 죽은 것이 성공으로 보인다.
_cleaned=0
cleanup() {
    local rc=$?
    [ "$_cleaned" -eq 1 ] && return
    _cleaned=1
    step_start cleanup
    if docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" \
        down --volumes --remove-orphans >/dev/null 2>&1; then
        step_ok cleanup
    else
        step_fail cleanup 1
        [ "$rc" -eq 0 ] && rc=1
    fi
    # END 는 cleanup 이 끝난 뒤에만 나온다 — 정리 실패가 성공으로 보이면 안 된다
    say "END rc=$rc at $(now)"
    exit "$rc"
}
trap 'exit 130' INT
trap 'exit 143' TERM
trap cleanup EXIT

# ── 실행 ─────────────────────────────────────────────────────────────────────
step_start preflight
preflight || { step_fail preflight 1; exit 1; }
step_ok preflight

cd "$ROOT"

# -vv -rs 로 skip 의 node ID 와 사유를 로그에 남긴다(F-4).
# -rs 만으로는 `file.py:827` 형식의 source location 만 나와 node ID 가 없다.
step_start pytest-local
uv run pytest -q -vv -rs --ignore=tests/integration/mysql
step_ok pytest-local

step_start compose-up
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d --wait
step_ok compose-up

# 2회 적용해 멱등성을 확인한다
for i in 1 2; do
    step_start "migration-$i"
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" exec -T db \
        sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root "$MYSQL_DATABASE"' \
        < "$MIGRATION"
    step_ok "migration-$i"
done

step_start port-resolve
DB_PORT_VALUE="$(docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" port db 3306 | awk -F: '{print $NF}')"
V8_DB_PORT_VALUE="$(docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" port v8_db 3306 | awk -F: '{print $NF}')"
if [ -z "$DB_PORT_VALUE" ] || [ -z "$V8_DB_PORT_VALUE" ]; then
    step_fail port-resolve 1
    echo "[harness] published MySQL port not found" >&2
    exit 1
fi
step_ok port-resolve

step_start pytest-mysql
env \
    DB_HOST=127.0.0.1 \
    DB_PORT="$DB_PORT_VALUE" \
    DB_USER=root \
    DB_PASSWORD=paim_test_password \
    DB_NAME=paim_test \
    V8_DB_PORT="$V8_DB_PORT_VALUE" \
    V8_DB_NAME=paim_v8 \
    PAIM_AUTH_MODE=dev \
    uv run pytest -q -vv -rs tests/integration/mysql
step_ok pytest-mysql
