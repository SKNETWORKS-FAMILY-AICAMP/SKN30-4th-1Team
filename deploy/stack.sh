#!/usr/bin/env bash
set -euo pipefail

# PaiM 스택 실행 wrapper. preflight → docker compose 를 원자적으로 묶는다.
#
# 왜 필요한가:
#   1. preflight를 별도로 두면 raw `docker compose up`으로 우회된다. 여기서만
#      compose를 호출하고 문서의 모든 절차가 이 스크립트를 쓰게 해서 막는다.
#   2. Compose의 .env / --env-file은 보간 입력일 뿐 셸로 export되지 않는다.
#      프로필마다 env 파일을 한 곳에서 정하고 그 파일을 preflight에 직접 넘겨야
#      "검사한 값"과 "컨테이너가 쓰는 값"이 갈라지지 않는다.
#   3. -p / -f 는 후속 명령에 승계되지 않는다. down/up을 옵션 없이 실행하면
#      개발 스택을 조작하게 되므로 프로필이 항상 전체 조합을 붙인다.
#
# Usage: deploy/stack.sh <prod|rehearsal|restore> <compose args...>
#   deploy/stack.sh prod up -d
#   deploy/stack.sh rehearsal down
#   deploy/stack.sh restore exec db mysql -uroot -p"$PW" paiM

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROFILE="${1:-}"
shift || true

[[ -n "$PROFILE" ]] || {
  echo "Usage: deploy/stack.sh <prod|rehearsal|restore> <compose args...>" >&2
  exit 2
}

# 프로필별로 project 이름·compose 파일·env 파일·모드를 완결적으로 정한다.
# source(rehearsal)와 restore가 서로 다른 project여야 빈 볼륨 복구를 검증할 수
# 있으므로 단일 공통 prefix로는 표현할 수 없다.
case "$PROFILE" in
  prod)
    PROJECT="paim-prod"
    COMPOSE_FILES=(-f docker-compose.prod.yml)
    ENV_FILE=".env"
    MODE="rollout"
    ;;
  rehearsal)
    PROJECT="paim-rehearsal"
    COMPOSE_FILES=(-f docker-compose.prod.yml -f deploy/compose.rehearsal.yml)
    ENV_FILE="deploy/.env.rehearsal"
    MODE="local"
    ;;
  restore)
    PROJECT="paim-restore"
    COMPOSE_FILES=(-f docker-compose.prod.yml -f deploy/compose.restore.yml)
    ENV_FILE="deploy/.env.restore"
    MODE="local"
    ;;
  *)
    echo "[stack] FAIL: unknown profile '$PROFILE' (prod | rehearsal | restore)" >&2
    exit 2
    ;;
esac

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[stack] FAIL: env file not found for profile '$PROFILE': $ENV_FILE" >&2
  echo "[stack] deploy/.env.deploy.example 를 복사해 만들 것 (비밀값은 저장소에 커밋하지 않는다)" >&2
  exit 2
fi

# 전역 옵션 위치를 통째로 막는다.
#
# Compose 문법상 전역 옵션(-p, -f, --env-file …)은 **subcommand 앞에만** 올 수
# 있고, 뒤에 오면 Compose 자신이 거부한다. 따라서 "첫 non-dash 토큰 = subcommand"
# 이고, 그 앞의 모든 dash 토큰은 전역 옵션이다. 이름을 열거해 걸러내는 대신 위치로
# 막는다 — 열거 방식은 `-ppaim-prod`처럼 값이 붙은 축약형을 놓쳤고, Compose는
# 뒤에 온 -p가 이기므로 그대로 운영 project를 조작할 수 있었다.
#
# 이 방식은 subcommand 뒤의 옵션은 건드리지 않으므로 `logs -f`(follow)나
# `up -d` 같은 정상 사용은 그대로 통과한다.
for arg in "$@"; do
  case "$arg" in
    --) break ;;          # 이후는 전부 subcommand 인자
    -*)
      echo "[stack] FAIL: '$arg' — subcommand 앞의 전역 옵션은 허용하지 않는다." >&2
      echo "[stack] project·compose 파일·env 파일은 프로필('$PROFILE')이 결정한다." >&2
      echo "[stack] 사용법: deploy/stack.sh $PROFILE <subcommand> [options...]" >&2
      exit 2
      ;;
    *) break ;;           # subcommand 도달 — 이후 인자는 검사하지 않는다
  esac
done

# preflight가 실패하면 docker compose를 호출하지 않는다. set -e가 여기서 끊는다.
SUBCOMMAND="${1:-}"
NETWORK_GATE=()
case "$SUBCOMMAND" in
  up|create|run) NETWORK_GATE=(--check-network) ;;
esac
"$ROOT/deploy/preflight.sh" \
  --env-file "$ENV_FILE" \
  --mode "$MODE" \
  --profile "$PROFILE" \
  --project "$PROJECT" \
  "${NETWORK_GATE[@]}"

# 보간에서 호스트 셸 값이 --env-file보다 우선한다. 셸에 DB_PASSWORD나
# PAIM_HTTP_PORT가 export되어 있으면 preflight는 프로필 파일을 PASS로 판정했는데
# Compose는 다른 값으로 렌더링한다 — 잘못된 자격증명으로 기동하거나 리허설이
# 운영 포트를 점유하는 경로다.
#
# 두 집합의 합집합을 셸 환경에서 지운다.
#   1. 프로필 파일에 정의된 키
#   2. compose 파일이 보간하는 ${VAR} 이름 — 프로필 파일에 없는 변수도 호스트
#      값이 쓰이기 때문이다. 예: PAIM_HTTP_PORT를 프로필 파일에 안 적었는데
#      셸에 있으면 리허설이 그 포트로 뜬다.
# 값을 읽지 않고 키 이름만 뽑으므로 비밀값이 노출되지 않는다.
UNSET_KEYS=()
while IFS= read -r key; do
  [[ -n "$key" ]] && UNSET_KEYS+=("$key")
done < <(
  {
    sed -nE 's/^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=.*$/\2/p' "$ENV_FILE"
    for file in "${COMPOSE_FILES[@]}"; do
      [[ "$file" == -f ]] && continue
      grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*' "$file" | sed 's/^\${//'
    done
  } | sort -u
)

# --env-file은 보간용이다. 컨테이너 환경은 각 프로필의 compose override가
# 서비스 env_file을 !override로 교체해 결정한다.
exec env ${UNSET_KEYS[@]+"${UNSET_KEYS[@]/#/--unset=}"} \
  docker compose \
  -p "$PROJECT" \
  "${COMPOSE_FILES[@]}" \
  --env-file "$ENV_FILE" \
  "$@"
