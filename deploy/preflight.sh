#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 배포 전 환경변수 조합 검사.
#
# Compose 보간(${VAR:?})은 해당 변수 자신의 존재만 검사한다. LLM_PROVIDER 값에
# 따라 다른 변수를 요구하거나 "둘 중 하나" 같은 조건을 강제할 문법이 없다.
# 그 조건부 검사를 여기서 한다.
#
# 지정된 env 파일을 직접 파싱한다 — 셸 환경을 보지 않는다. Compose의 .env는
# 보간 입력일 뿐 셸 subprocess로 export되지 않으므로, 셸 환경을 검사하면
# Compose가 실제로 쓸 값과 다른 것을 검사하게 된다.
#
# 비밀값은 어떤 경우에도 출력하지 않는다. 변수 이름만 보고한다.
#
# Usage: preflight.sh --env-file <path> [--mode local|rollout]

ENV_FILE=""
MODE="local"
GET_KEY=""   # --get KEY: 문법 검증을 통과한 뒤 KEY의 Compose 해석값만 출력(런북 공용)
PROFILE=""
PROJECT=""
CHECK_NETWORK=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="${2:-}"; shift 2 ;;
    --mode)     MODE="${2:-}";     shift 2 ;;
    --get)      GET_KEY="${2:-}";  shift 2 ;;
    --profile)  PROFILE="${2:-}";  shift 2 ;;
    --project)  PROJECT="${2:-}";  shift 2 ;;
    --check-network) CHECK_NETWORK=1; shift ;;
    *) echo "[preflight] FAIL: unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$ENV_FILE" ]] || { echo "[preflight] FAIL: --env-file is required" >&2; exit 2; }
[[ -f "$ENV_FILE" ]] || { echo "[preflight] FAIL: env file not found: $ENV_FILE" >&2; exit 2; }

case "$MODE" in
  local|rollout) ;;
  *) echo "[preflight] FAIL: --mode must be 'local' or 'rollout'" >&2; exit 2 ;;
esac

ERRORS=()
WARNINGS=()

# ── 단일 dotenv 값 파서 (compose-go와 동일 규칙) ─────────────────────────────
#
# Compose의 dotenv 문법을 셸로 부분 재구현하려다 세 번 어긋났다(인라인 주석,
# 여러 줄 따옴표, 그리고 반대로 정상 값을 과잉 거부). 원인은 검증기와 값 추출기가
# 서로 다른 파서를 써서 갈렸기 때문이다. 이제 **하나의 파서**로 통일한다 —
# validate_env_syntax도 env_get도 이 함수만 쓴다.
#
# compose-go(Compose v2 dotenv) 규칙:
#   - `=` 뒤 선행 공백은 제거된다
#   - 작은따옴표 `'...'` → 리터럴. 보간·이스케이프 없음. 안의 `$`도 리터럴이다
#   - 큰따옴표 `"..."` → 보간·이스케이프 적용. 닫는 따옴표 뒤는 인라인 주석
#   - 따옴표 없음 → ` #`(공백+#)부터 인라인 주석, 양끝 공백 제거, 보간 적용
#   - 첫 줄 앞의 UTF-8 BOM은 제거된다
#
# 보간 정책(중요): 큰따옴표·무따옴표의 `$`는 이스케이프(`\$`, `$$`)와 보간이
# quote 모드마다 다른 순서로 얽혀, 리터럴/보간을 셸에서 정확히 구분하려던 시도가
# 세 번 어긋났다. 그래서 **작은따옴표 밖의 `$`는 전부 거부**한다. `$`가 필요한
# 값(비밀번호 등)은 작은따옴표로 감싸면 되고(완전 리터럴), 그러면 preflight가 검사한
# 값과 컨테이너가 쓰는 값이 절대 갈리지 않는다. 이건 편의 게이트의 의도적 계약이다.
#
# 출력 전역:
#   EV_VALUE          해석된 값
#   EV_INTERP=1       해석 불가한 실제 보간이 값에 있음 → preflight가 거부해야 함
#   EV_UNTERMINATED=1 따옴표가 이 물리적 줄에서 닫히지 않음(여러 줄 값) → 거부
_parse_env_value() {
  local raw="$1"
  EV_VALUE=""; EV_INTERP=0; EV_UNTERMINATED=0
  # `=` 뒤 선행 공백 제거 (Compose 동작)
  raw="${raw#"${raw%%[![:space:]]*}"}"
  case "$raw" in
    '"'*)
      # 큰따옴표: 이스케이프되지 않은 닫는 따옴표까지. `\"`는 종료가 아니다.
      local rest="${raw:1}" out="" ch closed=0
      while [[ -n "$rest" ]]; do
        ch="${rest:0:1}"
        if [[ "$ch" == '\' && -n "${rest:1}" ]]; then
          out+="${rest:0:2}"; rest="${rest:2}"; continue
        fi
        if [[ "$ch" == '"' ]]; then closed=1; break; fi
        out+="$ch"; rest="${rest:1}"
      done
      [[ $closed -eq 1 ]] || { EV_UNTERMINATED=1; return; }
      # 큰따옴표·무따옴표의 $는 quote 모드마다 이스케이프 규칙이 달라(무따옴표는
      # 백슬래시 미처리, 큰따옴표는 \$→$$ 변환 후 보간) 리터럴/보간을 안전하게
      # 구분하려던 시도가 거듭 어긋났다. 그래서 $가 하나라도 있으면 거부하고,
      # $가 필요한 값은 작은따옴표(완전 리터럴)로 쓰게 한다. under-rejection 구멍이
      # 원리적으로 없다.
      [[ "$out" == *'$'* ]] && EV_INTERP=1
      EV_VALUE="$out"
      ;;
    "'"*)
      # 작은따옴표: 리터럴. 닫는 따옴표까지. 보간·이스케이프 없음.
      local body="${raw:1}"
      if [[ "$body" == *"'"* ]]; then
        EV_VALUE="${body%%\'*}"
      else
        EV_UNTERMINATED=1
      fi
      ;;
    *)
      # 따옴표 없음: 공백+# 인라인 주석 제거 후 양끝 공백 제거, 보간 적용.
      local v="$raw"
      case "$v" in
        *' #'*) v="${v%% #*}" ;;
      esac
      v="${v%"${v##*[![:space:]]}"}"
      [[ "$v" == *'$'* ]] && EV_INTERP=1   # $는 작은따옴표 밖에서 금지 (위 참조)
      EV_VALUE="$v"
      ;;
  esac
}

# 첫 줄 앞의 UTF-8 BOM을 제거한다 (lineno==1에서만).
_strip_bom() { printf '%s' "${1#$'\xEF\xBB\xBF'}"; }

# ── env 파일 문법 검증 ───────────────────────────────────────────────────────
#
# 거부 대상은 "preflight가 검사한 값 ≠ 컨테이너가 쓰는 값"을 만드는 두 경우뿐이다:
#   1. 작은따옴표 밖의 `$` — 큰따옴표·무따옴표에서는 보간될 수 있고 이스케이프
#      규칙이 미묘하다. `$`가 필요하면 작은따옴표(완전 리터럴)로 감싼다.
#   2. 한 줄에서 닫히지 않은 따옴표 — Compose는 여러 줄 값으로 이어 읽는데 이
#      스크립트는 줄 단위라 앞부분만 본다.
validate_env_syntax() {
  local lineno=0 line key
  while IFS= read -r line || [[ -n "$line" ]]; do
    lineno=$((lineno + 1))
    [[ $lineno -eq 1 ]] && line="$(_strip_bom "$line")"
    # 주석·빈 줄 건너뛰기
    [[ "$line" =~ ^[[:space:]]*(#.*)?$ ]] && continue
    # 엄격한 `export? KEY=VALUE`만 허용한다. Compose는 `KEY = VALUE`(등호 주변 공백)·
    # `KEY: VALUE`(콜론)·탭 구분자도 읽어 값을 보간하는데, 이 줄들을 건너뛰면(skip)
    # preflight가 못 보는 사이 호스트 값이 주입된다(CR6-001). 건너뛰지 말고 거부한다.
    if [[ ! "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      ERRORS+=("$ENV_FILE:$lineno — 지원하지 않는 줄 형식. 'export? KEY=VALUE'만 허용한다(등호 주변 공백·콜론·탭 구분자 금지). Compose는 이런 줄도 읽어 preflight 검사를 우회할 수 있다")
      continue
    fi
    key="${BASH_REMATCH[2]}"
    _parse_env_value "${BASH_REMATCH[3]}"
    if [[ "$EV_UNTERMINATED" -eq 1 ]]; then
      ERRORS+=("$ENV_FILE:$lineno $key — 따옴표가 같은 줄에서 닫히지 않았다. Compose는 여러 줄 값으로 읽지만 preflight는 줄 단위라 앞부분만 본다. 한 줄로 쓸 것")
    elif [[ "$EV_INTERP" -eq 1 ]]; then
      ERRORS+=("$ENV_FILE:$lineno $key — 값에 \$가 있다(작은따옴표 밖). Compose는 큰따옴표·무따옴표의 \$를 호스트 값으로 보간할 수 있고 이스케이프 규칙이 미묘하다. \$가 든 값은 작은따옴표로 감싸 리터럴로 쓸 것 — 예: KEY='pa\$word'")
    fi
  done < "$ENV_FILE"
}

# 문법 검증은 --get 조회 모드에서도 **반드시 먼저** 돈다. 건너뛰면 지원하지 않는
# 줄(`KEY = VALUE` 등)에 숨은 보간을 못 보고 잘못된 값을 출력한다(결정2 구멍).
validate_env_syntax

# 문법이 어긋난 상태에서는 이후 검사 결과를 신뢰할 수 없다. 즉시 중단한다.
if [[ ${#ERRORS[@]} -gt 0 ]]; then
  echo "[preflight] FAIL: env 파일 문법 (mode=$MODE, env=$ENV_FILE)" >&2
  for err in "${ERRORS[@]}"; do
    echo "  - $err" >&2
  done
  exit 1
fi

# env 파일에서 KEY의 값을 읽는다. 마지막 정의가 이긴다(Compose·dotenv 관례).
# 위 validate_env_syntax와 동일한 `_parse_env_value`를 쓰므로 두 경로가 갈릴 수
# 없다. validate가 먼저 통과했으므로 여기서는 미종결 따옴표가 없다고 가정한다.
env_get() {
  local key="$1" lineno=0 line k found=0 result=""
  while IFS= read -r line || [[ -n "$line" ]]; do
    lineno=$((lineno + 1))
    [[ $lineno -eq 1 ]] && line="$(_strip_bom "$line")"
    [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    k="${BASH_REMATCH[2]}"
    [[ "$k" == "$key" ]] || continue
    _parse_env_value "${BASH_REMATCH[3]}"
    result="$EV_VALUE"; found=1  # 마지막 정의가 이긴다
  done < "$ENV_FILE"
  # 키가 없으면 빈 문자열만 낸다. `$(env_get ...)` 할당이 set -e에서 죽지 않도록
  # 항상 0을 반환한다(미설정은 오류가 아니라 require/조건 검사가 판단할 몫).
  [[ $found -eq 1 ]] && printf '%s' "$result"
  return 0
}

# --get 조회 모드: (위 문법 검증을 통과한 뒤) KEY의 Compose 해석값을 그대로 출력하고
# 끝낸다. 배포·롤백 런북이 도메인을 손으로 파싱하다 네 번 어긋났으므로(CR3-006·
# CR4-005·CR5-002·CR6), 런북도 이 **같은 파서 + 같은 문법 게이트**를 쓰게 해
# "런북이 검사한 값 = Caddy가 받는 값"을 보장한다.
if [[ -n "$GET_KEY" ]]; then
  env_get "$GET_KEY"
  exit 0
fi

# 값이 비어 있지 않은지. placeholder 판별은 앱 설정 검사(TASK-012) 몫이다.
env_has() {
  [[ -n "$(env_get "$1")" ]]
}

require() {
  local key="$1" why="$2"
  env_has "$key" || ERRORS+=("$key 누락 — $why")
}

# ── 항상 필수 ────────────────────────────────────────────────────────────────

require DB_USER            "backend/db/mysql.py DB 접속"
require DB_PASSWORD        "backend/db/mysql.py DB 접속"
require DB_NAME            "backend/db/mysql.py DB 접속"

# 이 구성은 MySQL 컨테이너에 MYSQL_ROOT_PASSWORD만 넘긴다(MYSQL_USER 미사용).
# 따라서 root 외의 계정은 **생성되지 않는다**. 그런데 startup의 DB 보증 함수들이
# 연결 오류를 로깅하고 계속 기동하므로 /health는 200을 반환하고 DB 기반 API만
# 조용히 실패한다. 비루트 계정 분리는 별도 작업이므로 여기서 막는다.
DB_USER_VALUE="$(env_get DB_USER)"
if [[ -n "$DB_USER_VALUE" && "$DB_USER_VALUE" != "root" ]]; then
  ERRORS+=("DB_USER='$DB_USER_VALUE' 는 지원하지 않는다 — 이 구성은 MySQL 컨테이너에 MYSQL_ROOT_PASSWORD만 넘기므로 해당 계정이 생성되지 않는다. root를 쓰거나, 비루트 계정을 쓰려면 MYSQL_USER/MYSQL_PASSWORD 초기화와 권한 부여를 먼저 추가할 것")
fi
require PAIM_JWT_SECRET    "backend/api/auth.py — 누락 시 기동 자체가 중단된다"
# 아래 둘은 lazy 경로. 누락돼도 기동과 /health는 통과하고 실제 기능에서 터진다.
require SESSION_MEMORY_KEY "backend/security/session_crypto.py 채팅 암복호화 (lazy)"
require LLM_PROVIDER       "Agentic Q&A MVP provider 고정"
require OPENAI_API_KEY     "Agentic Q&A·임베딩에 필요 (lazy)"
require OPENAI_MODEL       "Agentic Q&A MVP 모델 고정"
require DB_HOST            "backend/db/mysql.py DB 접속"
require DB_PORT            "backend/db/mysql.py DB 접속"
require PAIM_AUTH_MODE     "운영 JWT 모드 고정"
require RATE_LIMIT_SIGNUP  "signup 요청 제한"
require RATE_LIMIT_LOGIN   "login 요청 제한"
require RATE_LIMIT_UPLOAD  "upload 요청 제한"
require RATE_LIMIT_QUERY   "query 요청 제한"
require RATE_LIMIT_CHAT    "chat 요청 제한"
require PAIM_PROXY_SUBNET  "프로필 proxy subnet"
require PAIM_CADDY_PROXY_IP "프로필 Caddy static IP"
require PAIM_BACKEND_PROXY_IP "프로필 backend static IP"
require FORWARDED_ALLOW_IPS "신뢰할 Caddy /32"
require CORS_ORIGINS        "backend CORS allowlist (non-dev 필수)"

CORS_VALUE="$(env_get CORS_ORIGINS)"
if [[ -n "$CORS_VALUE" ]]; then
  IFS=',' read -r -a CORS_ITEMS <<< "$CORS_VALUE"
  declare -A CORS_SEEN=()
  for origin in "${CORS_ITEMS[@]}"; do
    if [[ -z "$origin" || "$origin" == *'*'* || "$origin" == *'@'* ||
          "$origin" == *\\* || "$origin" =~ [[:space:][:cntrl:]] ||
          "$origin" == *: ||
          ! "$origin" =~ ^(http|https|tauri)://[^/?#]+$ ]]; then
      ERRORS+=("CORS_ORIGINS가 유효한 absolute origin allowlist가 아니다")
      break
    fi
    if [[ "$origin" == tauri://* && "$origin" != "tauri://localhost" ]]; then
      ERRORS+=("CORS_ORIGINS의 Tauri origin은 tauri://localhost만 허용된다")
      break
    fi
    if [[ -n "${CORS_SEEN[$origin]:-}" ]]; then
      ERRORS+=("CORS_ORIGINS에 중복 origin이 있다")
      break
    fi
    CORS_SEEN[$origin]=1
  done
fi

LOG_LEVEL_VALUE="$(env_get LOG_LEVEL)"
if [[ -n "$LOG_LEVEL_VALUE" && ! "$LOG_LEVEL_VALUE" =~ ^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$ ]]; then
  ERRORS+=("LOG_LEVEL은 DEBUG|INFO|WARNING|ERROR|CRITICAL 중 하나여야 한다")
fi
for quota_key in PROJECT_STORAGE_QUOTA_BYTES USER_STORAGE_QUOTA_BYTES PROJECT_FILE_COUNT_QUOTA; do
  quota_value="$(env_get "$quota_key")"
  if [[ -n "$quota_value" && ! "$quota_value" =~ ^[1-9][0-9]*$ ]]; then
    ERRORS+=("$quota_key 는 양의 정수여야 한다")
  fi
done

# ── Agentic Q&A MVP 모델 계약 ───────────────────────────────────────────────
# 일반 LLM factory에는 다른 provider가 남아 있지만, #18의 운영 Q&A는 공식
# OpenAI API + gpt-4.1-mini만 지원한다. 여기서 막지 않으면 첫 Q&A에서 503이 난다.

PROVIDER="$(env_get LLM_PROVIDER)"
[[ "$PROVIDER" == "openai" ]] || ERRORS+=("LLM_PROVIDER는 openai여야 한다 — #18 Agentic Q&A MVP는 다른 provider를 지원하지 않는다")

OPENAI_MODEL_VALUE="$(env_get OPENAI_MODEL)"
[[ "$OPENAI_MODEL_VALUE" == "gpt-4.1-mini" ]] || ERRORS+=("OPENAI_MODEL은 gpt-4.1-mini여야 한다 — #18 Agentic Q&A MVP 모델 계약")

for base_key in OPENAI_BASE_URL OPENAI_API_BASE; do
  base_value="$(env_get "$base_key")"
  if [[ -n "$base_value" ]]; then
    normalized="${base_value%/}"
    normalized="${normalized,,}"
    [[ "$normalized" == "https://api.openai.com/v1" ]] || ERRORS+=("$base_key 는 공식 OpenAI endpoint(https://api.openai.com/v1)만 허용한다")
  fi
done

# ── GitHub App 설정군 (all-or-nothing) ───────────────────────────────────────
#
# backend/github/router.py의 세 검사는 전부 lazy 503이라 기동·/health를 통과한
# 뒤 사용 시점에 실패한다. 부분 설정이 가장 위험하므로 완전 조합을 요구한다.

GH_KEYS=(GITHUB_APP_INSTALL_URL GITHUB_APP_SLUG GITHUB_APP_ID \
         GITHUB_APP_PRIVATE_KEY GITHUB_APP_PRIVATE_KEY_PATH)
GH_ANY=0
for key in "${GH_KEYS[@]}"; do
  if env_has "$key"; then GH_ANY=1; break; fi
done

if [[ "$GH_ANY" -eq 1 ]]; then
  if ! env_has GITHUB_APP_INSTALL_URL && ! env_has GITHUB_APP_SLUG; then
    ERRORS+=("GITHUB_APP_INSTALL_URL 또는 GITHUB_APP_SLUG 필요 — github/router.py 설치 URL 생성")
  fi
  require GITHUB_APP_ID "github/router.py installation token"
  if ! env_has GITHUB_APP_PRIVATE_KEY && ! env_has GITHUB_APP_PRIVATE_KEY_PATH; then
    ERRORS+=("GITHUB_APP_PRIVATE_KEY 또는 GITHUB_APP_PRIVATE_KEY_PATH 필요 — github/router.py App JWT 서명")
  fi
  # 경로 방식은 컨테이너 안에서 그대로 open()된다. 호스트 경로를 넣으면 파일이
  # 없어 실패하므로, 운영에서는 inline 키만 허용한다.
  if [[ "$MODE" == "rollout" ]] && env_has GITHUB_APP_PRIVATE_KEY_PATH; then
    ERRORS+=("GITHUB_APP_PRIVATE_KEY_PATH 는 rollout 불가 — github/router.py가 이 경로를 컨테이너 내부에서 open()한다. inline GITHUB_APP_PRIVATE_KEY를 쓰거나, read-only 마운트와 컨테이너 내부 경로를 함께 정의할 것")
  fi
else
  WARNINGS+=("GitHub App 미설정 — /github/app/* 는 503을 반환하고 비공개 저장소를 쓸 수 없다. 공개 저장소는 비인증 호출로 동작하지만 GitHub REST 한도가 IP당 60회/시간이다")
fi

# ── 모드별 ───────────────────────────────────────────────────────────────────

if [[ "$MODE" == "rollout" ]]; then
  env_has PAIM_DOMAIN || ERRORS+=("PAIM_DOMAIN 누락 — 미설정 시 Caddy가 :80 폴백으로 떠서 인증서를 발급하지 않는다(HTTP-only 상태는 배포 완료로 인정되지 않음)")
else
  env_has PAIM_DOMAIN || WARNINGS+=("PAIM_DOMAIN 미설정 — HTTP(:80)로 기동한다. 로컬 리허설에서는 정상")
fi

# ── 보고 ─────────────────────────────────────────────────────────────────────

for warning in ${WARNINGS+"${WARNINGS[@]}"}; do
  echo "[preflight] WARN: $warning" >&2
done

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  echo "[preflight] FAIL (mode=$MODE, env=$ENV_FILE):" >&2
  for err in "${ERRORS[@]}"; do
    echo "  - $err" >&2
  done
  exit 1
fi

if [[ -n "$PROFILE" || -n "$PROJECT" ]]; then
  [[ -n "$PROFILE" && -n "$PROJECT" ]] || {
    echo "[preflight] FAIL: --profile과 --project는 함께 지정해야 한다" >&2
    exit 2
  }
  NETWORK_ARGS=(
    --profile "$PROFILE"
    --project "$PROJECT"
    --subnet "$(env_get PAIM_PROXY_SUBNET)"
    --caddy-ip "$(env_get PAIM_CADDY_PROXY_IP)"
    --backend-ip "$(env_get PAIM_BACKEND_PROXY_IP)"
  )
  [[ "$CHECK_NETWORK" -eq 1 ]] || NETWORK_ARGS+=(--validate-only)
  "$ROOT/deploy/check-proxy-network.py" "${NETWORK_ARGS[@]}"
  if [[ "$(env_get FORWARDED_ALLOW_IPS)" != "$(env_get PAIM_CADDY_PROXY_IP)/32" ]]; then
    echo "[preflight] FAIL: FORWARDED_ALLOW_IPS는 프로필 Caddy IP 하나의 /32여야 한다" >&2
    exit 1
  fi
fi

# 진단은 stderr로 보낸다. stdout으로 내보내면 wrapper가 `docker compose config`
# 출력에 섞어 파이프라인을 깨뜨린다.
echo "[preflight] PASS (mode=$MODE, provider=$PROVIDER, env=$ENV_FILE)" >&2
