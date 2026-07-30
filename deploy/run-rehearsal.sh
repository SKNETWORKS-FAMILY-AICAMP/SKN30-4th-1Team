#!/usr/bin/env bash
# 로컬 리허설을 재현 가능하게 실행하고 각 단계의 명령·종료코드·대조값을 남긴다.
#
# 수동 요약이 아니라 이 스크립트의 출력 자체가 검증 증거다. 비밀값은 argv에
# 싣지 않으며(컨테이너 안에서 MYSQL_PWD로 읽는다), env 파일은 placeholder를 쓴다.
#
# 사용: OPENAI_API_KEY=sk-... deploy/run-rehearsal.sh   (임베딩까지 검증하려면)
#       deploy/run-rehearsal.sh                          (placeholder — 파일 수준까지)
#
# 전제: docker, 리포지토리 루트에서 실행.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TAG="paim-backend:rehearsal-$(date +%s)"
BK="$(mktemp -d)"
FAIL=0

step() { echo; echo "### $*"; }
run()  { echo "\$ $*"; "$@"; local rc=$?; echo "[exit=$rc]"; [[ $rc -ne 0 ]] && FAIL=1; return $rc; }

cleanup() {
  step "정리"
  deploy/stack.sh rehearsal down -v  >/dev/null 2>&1 && echo "rehearsal 볼륨 제거"
  deploy/stack.sh restore   down -v  >/dev/null 2>&1 && echo "restore 볼륨 제거"
  rm -f deploy/.env.rehearsal deploy/.env.restore
  docker rmi "$TAG" "${TAG}-prev" >/dev/null 2>&1 && echo "이미지 제거"
  rm -rf "$BK"

  # 개발 스택 무결성은 리허설 컨테이너를 모두 내린 지금 비교한다.
  step "개발 스택 무결성 (정리 후)"
  local dev_after; dev_after="$(docker ps -q | sort)"
  if [[ "${DEV_BEFORE_GLOBAL:-$DEV_BEFORE}" == "$dev_after" ]]; then
    echo "[exit=0] 개발 컨테이너 불변"
  else
    echo "[exit=1] 개발 컨테이너 변화 — 검토 필요"; FAIL=1
  fi
  local env_after; env_after="$( [[ -f .env ]] && sha256sum .env | cut -c1-16 || echo none)"
  if [[ "$ENV_SHA_BEFORE" == "$env_after" ]]; then
    echo "[exit=0] 루트 .env 불변 ($env_after)"
  else
    echo "[exit=1] 루트 .env 변경됨"; FAIL=1
  fi

  echo; echo "════════════════════════════════"
  [[ $FAIL -eq 0 ]] && echo "REHEARSAL PASS (전체)" || echo "REHEARSAL FAIL (전체)"
  exit $FAIL
}
trap cleanup EXIT

# ── 프로필 env (placeholder 비밀값) ──────────────────────────────────────────
cat > deploy/.env.rehearsal <<EOF
DB_USER=root
DB_PASSWORD=rehearsal_pw
DB_NAME=paiM
DB_HOST=db
DB_PORT=3306
PAIM_AUTH_MODE=jwt
PAIM_JWT_SECRET=rehearsal-secret-0123456789012345678901234567890123456789
SESSION_MEMORY_KEY=aGVsbG93b3JsZGhlbGxvd29ybGRoZWxsb3dvcmxkMTI=
OPENAI_API_KEY=${OPENAI_API_KEY:-sk-rehearsal-placeholder}
RATE_LIMIT_SIGNUP=5/minute
RATE_LIMIT_LOGIN=5/minute
RATE_LIMIT_UPLOAD=20/minute
RATE_LIMIT_QUERY=30/minute
RATE_LIMIT_CHAT=30/minute
CORS_ORIGINS=http://127.0.0.1:7420
PAIM_PROXY_SUBNET=172.30.13.0/24
PAIM_CADDY_PROXY_IP=172.30.13.10
PAIM_BACKEND_PROXY_IP=172.30.13.20
FORWARDED_ALLOW_IPS=172.30.13.10/32
LLM_PROVIDER=openai
OPENAI_MODEL=gpt-4.1-mini
PAIM_HTTP_PORT=8080
PAIM_HTTPS_PORT=8443
PAIM_IMAGE=$TAG
EOF

# /health는 static이라 DB 준비를 반영하지 않는다(심층 health는 TASK-012). 실제
# DB 연결이 되는 신호는 signup 성공이다 — depends_on: service_healthy도
# mysqladmin ping(내부 소켓)이 TCP 리슨보다 먼저 통과해 몇 초 갭이 있다.
signup() {
  local email="$1"
  for _ in $(seq 1 20); do
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8080/api/v1/auth/signup \
      -H 'Content-Type: application/json' -d "{\"email\":\"$email\",\"password\":\"pw12345678\",\"name\":\"R\"}")"
    [[ "$code" == 201 || "$code" == 409 ]] && { echo "$code"; return 0; }
    sleep 2
  done
  echo "timeout"; return 1
}

# 개발 스택의 "리허설 이전" 컨테이너 집합. 리허설이 띄우는 것은 제외해야
# 무결성 비교가 정확하다.
DEV_BEFORE="$(docker ps -q | sort)"
ENV_SHA_BEFORE="$( [[ -f .env ]] && sha256sum .env | cut -c1-16 || echo none)"
echo "dev 컨테이너(전): $(echo "$DEV_BEFORE" | grep -c . )개"

step "이미지 빌드"
run docker build -q -t "$TAG" . >/dev/null

step "스택 기동"
run deploy/stack.sh rehearsal up -d
echo "health 대기..."; for _ in $(seq 1 20); do
  [[ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/health)" == 200 ]] && break; sleep 3
done
run test "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/health)" = 200

step "격리 확인 — 루트 .env 전용 키가 새지 않는가 (C-001)"
# 값이 아니라 **키 이름만** 담는다. 새면 이 진단 자체가 비밀값을 로그에 남긴다
# (run()이 $* 전체를 출력하므로). grep -oE + `=` 제거로 이름만 추출한다.
# GITHUB_APP_ 는 접두라 `[A-Z0-9_]*`를 붙여 실제 키 이름 전체를 매칭한다.
LEAK="$(docker exec paim-rehearsal-backend-1 env \
  | grep -oE '^(ANTHROPIC_API_KEY|GITHUB_APP_[A-Z0-9_]*|CHROMA_COLLECTION_NAME|EMBED_MODEL)=' \
  | tr -d '=' | sort -u | tr '\n' ' ' || true)"
run test -z "$LEAK"

step "런타임 계약 — 비루트·워커1·jwt"
run test "$(docker exec paim-rehearsal-backend-1 id -un)" = paim
run test "$(docker exec paim-rehearsal-backend-1 printenv WEB_CONCURRENCY)" = 1
run test "$(docker exec paim-rehearsal-backend-1 printenv PAIM_AUTH_MODE)" = jwt

step "표본 생성 — MySQL row + 업로드(checksum)"
run test "$(signup rehearsal@test.local)" = 201
run docker exec paim-rehearsal-backend-1 sh -c 'echo sample-bytes > /app/data/uploads/s.txt'
UP_SHA="$(docker exec paim-rehearsal-backend-1 sha256sum /app/data/uploads/s.txt | cut -c1-64)"
# 쓰기·checksum이 실패해 빈 문자열이 되면 뒤의 UP_SHA==UP_SHA2 가 거짓 성공한다.
# 비어 있지 않음을 먼저 강제한다.
run test -n "$UP_SHA"
echo "업로드 checksum: $UP_SHA"
# chroma는 placeholder(무 OpenAI 키) 경로에서 벡터가 안 쌓여 정상적으로 비어 있다.
# "비어있지 않음"을 요구하면 정상 실행이 실패한다(CR4-003). 대신 chroma 볼륨에
# sentinel을 심어 백업→복원 왕복 자체를 검증한다 — 벡터 유무와 무관하게 동작한다.
run docker exec paim-rehearsal-backend-1 sh -c 'echo chroma-rt-sentinel > /app/.chroma/.rehearsal_sentinel'

step "영속성 — down/up 재생성 후 대조 (restart 아님, -v 금지)"
run deploy/stack.sh rehearsal down
run deploy/stack.sh rehearsal up -d
until [ "$(docker inspect -f '{{.State.Health.Status}}' paim-rehearsal-db-1 2>/dev/null)" = healthy ]; do sleep 2; done
ROW="$(deploy/stack.sh rehearsal exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -B -e "SELECT email FROM users WHERE email=\"rehearsal@test.local\"" "$MYSQL_DATABASE"' 2>/dev/null)"
run test "$ROW" = rehearsal@test.local
UP_SHA2="$(docker exec paim-rehearsal-backend-1 sha256sum /app/data/uploads/s.txt | cut -c1-64)"
run test -n "$UP_SHA2"                 # 빈 값끼리 같다고 통과하는 것을 막는다
run test "$UP_SHA" = "$UP_SHA2"

step "백업 (정지 → dump → 볼륨 → 체크섬)"
run deploy/stack.sh rehearsal stop backend
# mysqldump가 SQL 일부를 쓴 뒤 non-zero로 죽어도 파일은 남아 test -s를 통과한다.
# dump 명령 자체를 run()으로 감싸 종료코드를 FAIL에 반영하고, 완료 marker까지
# 검증한다(CR4-002).
# restore project도 공식 이미지의 init SQL로 빈 볼륨에 스키마를 먼저 만든다.
# --add-drop-table을 명시하지 않으면 클라이언트 기본 설정에 따라 dump가 CREATE만
# 담을 수 있고, 복원 시 "Table already exists"로 중단된다.
run sh -c "deploy/stack.sh rehearsal exec -T db sh -c 'MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" mysqldump -uroot --single-transaction --add-drop-table \"\$MYSQL_DATABASE\"' > '$BK/mysql.sql'"
run test -s "$BK/mysql.sql"
run sh -c "tail -1 '$BK/mysql.sql' | grep -q 'Dump completed'"
echo "dump: $(wc -c < "$BK/mysql.sql") bytes / $(tail -1 "$BK/mysql.sql" | cut -c1-30)"
# tar 생성 실패를 삼키면 이후 sha256sum -c가 없는 파일을 두고 통과할 수 있다.
# run()으로 감싸 각 볼륨 아카이브 실패를 FAIL에 반영한다.
for vol in chroma_data upload_data; do
  run docker run --rm -v "paim-rehearsal_$vol:/src:ro" -v "$BK:/out" alpine tar czf "/out/$vol.tar.gz" -C /src .
done
run sh -c "cd '$BK' && sha256sum ./* > SHA256SUMS"
run deploy/stack.sh rehearsal start backend

step "복구 — 빈 project(restore)로"
cp deploy/.env.rehearsal deploy/.env.restore
sed -i '
  s/^PAIM_HTTP_PORT=.*/PAIM_HTTP_PORT=8081/
  s/^PAIM_HTTPS_PORT=.*/PAIM_HTTPS_PORT=8444/
  s#^PAIM_PROXY_SUBNET=.*#PAIM_PROXY_SUBNET=172.30.14.0/24#
  s/^PAIM_CADDY_PROXY_IP=.*/PAIM_CADDY_PROXY_IP=172.30.14.10/
  s/^PAIM_BACKEND_PROXY_IP=.*/PAIM_BACKEND_PROXY_IP=172.30.14.20/
  s#^FORWARDED_ALLOW_IPS=.*#FORWARDED_ALLOW_IPS=172.30.14.10/32#
' deploy/.env.restore
run deploy/stack.sh restore up -d db
echo "restore DB 초기화 대기..."; until [ "$(docker inspect -f '{{.State.Health.Status}}' paim-restore-db-1 2>/dev/null)" = healthy ]; do sleep 3; done
run sh -c "cd '$BK' && sha256sum -c SHA256SUMS >/dev/null"
run sh -c "deploy/stack.sh restore exec -T db sh -c 'MYSQL_PWD=\"\$MYSQL_ROOT_PASSWORD\" mysql -uroot \"\$MYSQL_DATABASE\"' < '$BK/mysql.sql'"
# 볼륨 복원 실패도 삼키지 않는다.
for vol in chroma_data upload_data; do
  run docker run --rm -v "paim-restore_$vol:/dst" -v "$BK:/in:ro" alpine sh -c "rm -rf /dst/* && tar xzf /in/$vol.tar.gz -C /dst"
done
RROW="$(deploy/stack.sh restore exec -T db sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -B -e "SELECT email FROM users WHERE email=\"rehearsal@test.local\"" "$MYSQL_DATABASE"' 2>/dev/null)"
run test "$RROW" = rehearsal@test.local
run deploy/stack.sh restore up -d
# 업로드는 checksum 일치로, chroma는 sentinel 왕복으로 복원 성공을 확인한다.
# (복원 tar 해제가 조용히 실패하면 sentinel이 없어 grep이 실패한다. 빈 chroma도
# sentinel은 남으므로 placeholder 경로에서 오탐 없이 동작한다 — CR4-003.)
run sh -c "docker run --rm -v paim-restore_upload_data:/d:ro alpine sha256sum /d/s.txt | cut -c1-64 | grep -qx '$UP_SHA'"
run sh -c "docker run --rm -v paim-restore_chroma_data:/d:ro alpine cat /d/.rehearsal_sentinel | grep -qx chroma-rt-sentinel"

step "롤백 smoke — PAIM_IMAGE 전환 경로 + health 재확인"
# 한계(정직하게): 로컬 리허설에는 내용이 다른 '이전 빌드'가 없다. 현재 이미지를
# 별도 태그로 alias하므로 image ID(digest)는 두 태그가 같다 — digest 비교로는
# 전환을 증명할 수 없다(CR4-004). 그래서 여기서 검증하는 것은 **PAIM_IMAGE 치환이
# 반영돼 Compose가 지정 태그를 선택했는가**(Config.Image 이름)와 그 컨테이너가
# 실제로 살아 있는가(health)뿐이다. 내용이 다른 이미지의 롤백 실증은 실서버에서만
# 가능하며 README rollout 게이트 항목으로 남긴다.
run docker tag "$TAG" "${TAG}-prev"
run sh -c "sed -i 's|^PAIM_IMAGE=.*|PAIM_IMAGE=${TAG}-prev|' deploy/.env.rehearsal"
run grep -qx "PAIM_IMAGE=${TAG}-prev" deploy/.env.rehearsal   # 치환이 실제로 적용됐는지
run deploy/stack.sh rehearsal up -d backend
# Compose가 선택한 이미지 태그 이름을 확인한다 — 치환이 무시돼 이전 current
# 태그로 그냥 떠 있으면 여기서 잡힌다.
SEL="$(docker inspect -f '{{.Config.Image}}' paim-rehearsal-backend-1)"
run test "$SEL" = "${TAG}-prev"
# 이름만 맞고 컨테이너가 직후 죽어도 통과하지 않도록 health 200을 재확인한다.
for _ in $(seq 1 20); do
  [[ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/health)" == 200 ]] && break; sleep 3
done
run test "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/health)" = 200
echo "기동 이미지 태그: $SEL"

# 개발 스택 무결성은 리허설·복구 스택을 내린 뒤(cleanup 후) 비교한다. 여기서
# 재면 리허설 컨테이너가 잡혀 항상 다르게 나온다. cleanup()이 EXIT에서 돌므로
# 그 안에서 최종 비교한다.
DEV_BEFORE_GLOBAL="$DEV_BEFORE"

echo; echo "════════════════════════════════"
if [[ $FAIL -eq 0 ]]; then echo "REHEARSAL 본 단계 PASS (개발 스택 무결성은 정리 후 확인)"; else echo "REHEARSAL FAIL"; fi
