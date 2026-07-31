# PaiM 배포 운영 가이드

단일 VM(AWS EC2 t3.small) + Docker Compose + Caddy(HTTPS 종단) 구성이다.

모든 명령은 **`deploy/stack.sh`를 거친다.** raw `docker compose`를 쓰면 환경변수
preflight 검사가 통째로 건너뛰어지고, `-p`/`-f` 옵션 누락으로 엉뚱한 스택을
조작하게 된다.

```bash
deploy/stack.sh <prod|rehearsal|restore> <compose args...>
```

| 프로필 | project | env 파일 | 포트 | 용도 |
|---|---|---|---|---|
| `prod` | `paim-prod` | `.env` | 80/443 | 실서버 |
| `rehearsal` | `paim-rehearsal` | `deploy/.env.rehearsal` | 8080/8443 | 로컬 검증 |
| `restore` | `paim-restore` | `deploy/.env.restore` | 8081/8444 | 복구 리허설 |

각 프로필은 Caddy↔backend 전용 proxy subnet을 고정한다. Caddy만 edge
네트워크와 호스트 포트에 연결되고, DB는 backend와 data network만 공유한다.

| 프로필 | proxy subnet | Caddy | backend | 신뢰 프록시 |
|---|---|---|---|---|
| `prod` | `172.30.12.0/24` | `.10` | `.20` | `172.30.12.10/32` |
| `rehearsal` | `172.30.13.0/24` | `.10` | `.20` | `172.30.13.10/32` |
| `restore` | `172.30.14.0/24` | `.10` | `.20` | `172.30.14.10/32` |

`up`, `create`, `run`은 Docker network와 호스트 route의 CIDR 중첩을
fail-closed로 검사한다. 현재 project가 이미 만든 동일 network만 재사용하며,
`down`, `logs`, `exec`, `ps`, `stop`, `start`, `restart` 같은 관리 명령은 기존
스택을 복구·진단할 수 있도록 충돌 검사로 막지 않는다.

---

## ⛔ production rollout 선행 조건 (배포 완료 게이트)

**아래가 전부 충족되기 전에는 외부에 공개하지 않는다.** 컨테이너가 뜨고
`/health`가 200이라는 것은 "코드 산출물이 준비됐다"는 뜻이지 "공개해도 된다"는
뜻이 아니다.

| 조건 | 확인 방법 |
|---|---|
| 외부 네트워크에서 `https://<도메인>/health` 200 | 사내망 밖에서 `curl` |
| `http://<도메인>/health` → HTTPS 리다이렉트 | `curl -I` 로 301/308 확인 |
| 인증서 hostname·만료일 정상, 갱신 가능 상태 | `openssl s_client -connect <도메인>:443` |
| **디스크 여유 임계치 알람 실제 구성 + 수신 확인** | CloudWatch 알람 생성 후 테스트 알림 수신 |
| **TASK-012A PASS** — rate limit, proxy trust, 파일 검증, fail-fast, GitHub 오류 계약 | 해당 태스크 validator PASS |
| **TASK-012B PASS** — 심층 readiness, CORS 운영값, 사용자·프로젝트별 저장량 quota | 해당 태스크 validator PASS |
| **TASK-013 PASS** — 동일 파일명 재업로드 원자 교체 | 해당 태스크 validator PASS |
| **GitHub App 완전 설정 + 인증 상태 preview/connect/sync 확인** | 아래 "GitHub App" 절 참조 |
| **내용이 다른 이전 이미지로 실제 롤백 실증** | 서버에서 이전 git sha 태그로 되돌려 health·데이터 정상 확인 (로컬 리허설은 동일 이미지 alias라 전환 경로까지만 검증) |
| 데스크톱 base URL·CORS Origin 통합 검증 | 데스크톱 담당자와 함께 |

태스크를 나눈 것은 작업 단위를 쪼갠 것이지, **안전하지 않은 중간 상태를 공개해도
된다는 뜻이 아니다.**

---

## 1. EC2 준비

### 인스턴스

- **t3.small (2GB RAM)** 이상. t3.micro(1GB)는 이미지 빌드 중 OOM이 난다.
- 보안그룹 인바운드: **22(SSH), 80, 443만** 허용. MySQL 3306은 절대 열지 않는다
  (운영 compose가 포트를 공개하지 않으므로 열어도 닿지 않지만, 실수 방지).
- 스토리지 30GB 이상.

### 스왑 2GB (필수, 빌드 전에)

2GB RAM에서 `chromadb`·`langchain`·`kiwipiepy` 설치는 빠듯하다. 빌드 시점에
이미 스왑이 있어야 한다.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab   # 재부팅 후에도 유지
free -h
```

### Docker + 부팅 자동 시작

```bash
sudo systemctl enable docker     # 서버 재부팅 후 자동 실행 (WBS 완료 조건)
sudo systemctl is-enabled docker # → enabled
```

컨테이너는 전부 `restart: unless-stopped`이므로, Docker 데몬이 부팅과 함께
뜨면 스택도 함께 복구된다.

### 비용 가드 (크레딧 방식 계정)

크레딧이 소진되면 자동으로 과금이 시작된다. **AWS Budgets에 $20 알림을 걸어둔다.**

---

## 2. 도메인 (DuckDNS)

HTTPS에는 공인 도메인이 필요하다. Let's Encrypt가 도메인 소유를 확인해야 하므로
IP 주소만으로는 인증서를 받을 수 없다.

1. https://www.duckdns.org 에서 서브도메인 생성 (예: `paim.duckdns.org`)
2. EC2 퍼블릭 IP를 등록
3. `.env`에 `PAIM_DOMAIN=paim.duckdns.org`

나중에 실도메인을 사면 이 한 줄만 바꾸면 된다.

> **도메인 표기 계약:** `PAIM_DOMAIN`은 **ASCII hostname**만 지원한다
> (`[A-Za-z0-9.-]`). 한글·유니코드 IDN을 쓰려면 **punycode(`xn--…`)로 변환한 ASCII**를
> 넣는다. 런북의 배포·롤백 확인은 이 문자셋을 벗어난 값을 조용히 고치지 않고 즉시
> 멈춘다.

---

## 3. 배포

```bash
cp deploy/.env.deploy.example .env
# 필수값 채우기 — 아래 "환경변수" 절 참조
vi .env

# 이미지에 불변 태그를 부여한다. 롤백하려면 되돌릴 대상이 있어야 한다.
TAG="paim-backend:$(git rev-parse --short HEAD)"
docker build -t "$TAG" .
echo "PAIM_IMAGE=$TAG" >> .env

deploy/stack.sh prod up -d
deploy/stack.sh prod ps

# 도메인은 .env에서 읽는다. 셸에 export하는 것을 전제하지 않는다 —
# stack.sh가 호스트 셸 값을 의도적으로 차단하기 때문이다.
# export 접두·따옴표·인라인 주석을 preflight와 동일하게 처리한다.
# 도메인은 preflight의 --get으로 읽는다 — Compose가 Caddy에 넘기는 값과 **동일한
# 파서**를 써서 "런북이 검사한 값 = Caddy가 받는 값"을 보장한다(손 파싱 금지).
DOMAIN=$(deploy/preflight.sh --get PAIM_DOMAIN --env-file .env)
# hostname 형식이 아니면(빈 값, 따옴표 안 공백/#, 보간 잔여 등) 조용히 정규화하지
# 말고 여기서 멈춘다. Caddy가 받는 값 그대로를 검증한다.
case "$DOMAIN" in
  ""|*[!A-Za-z0-9.-]*) echo "PAIM_DOMAIN 미설정 또는 hostname 형식 아님: [$DOMAIN] — .env 확인"; exit 1 ;;
esac
curl -I "https://$DOMAIN/health"
```

`deploy/stack.sh`가 compose를 호출하기 전에 preflight를 돌린다. 필수 환경변수가
빠져 있으면 컨테이너가 뜨기 전에 멈춘다.

### 디스크 preflight

배포·백업 전에 확인한다. 30GB를 MySQL·Chroma·업로드·이미지·빌드 캐시가 나눠 쓴다.

```bash
df -h /
docker system df
docker image prune -f          # 사용하지 않는 이미지 정리 (태그 보존분 주의)
```

업로드에는 프로젝트 200MB, 사용자 500MB, 프로젝트당 파일 500개의 기본 quota가
적용됩니다(`backend/config.py`). 처리 중 예약량과 정리 실패도 영속 테이블로 추적하지만,
기간 기반 자동 보존 정책은 없으므로 디스크 사용량과 pending cleanup은 계속 점검해야 합니다.

---

## 4. 환경변수

전체 목록과 설명은 `deploy/.env.deploy.example` 참조. 요약하면:

### 항상 필수

`PAIM_AUTH_MODE` `PAIM_JWT_SECRET` `SESSION_MEMORY_KEY`, `LLM_PROVIDER`
`OPENAI_API_KEY` `OPENAI_MODEL`,
`DB_HOST` `DB_PORT` `DB_USER` `DB_PASSWORD` `DB_NAME`, 다섯 `RATE_LIMIT_*`,
`FORWARDED_ALLOW_IPS`, `PAIM_PROXY_SUBNET`, `PAIM_CADDY_PROXY_IP`,
`PAIM_BACKEND_PROXY_IP`가 필수다.

`SESSION_MEMORY_KEY`와 `OPENAI_API_KEY`의 누락·placeholder 값도 preflight와
non-dev 앱 시작에서 거부된다. 단, `OPENAI_API_KEY` 자체가 실제로 유효한지는
외부 API를 호출해야 확인할 수 있다. 이 키는 Agentic Q&A와 벡터 임베딩 모두에
사용한다.

non-dev 시작 시 앱도 같은 계약을 DB/schema 작업보다 먼저 검증한다. DB 포트,
32바이트 Base64 세션 키, placeholder, 승인된 요청 제한값과 Caddy `/32`가 맞지
않으면 비밀값을 출력하지 않고 기동을 중단한다.

### Agentic Q&A MVP 모델

운영은 **공식 OpenAI API + `gpt-4.1-mini`**로 고정한다.

| 설정 | 운영값 |
|---|---|
| `LLM_PROVIDER` | `openai` |
| `OPENAI_MODEL` | `gpt-4.1-mini` |
| `OPENAI_BASE_URL`, `OPENAI_API_BASE` | 미설정 또는 `https://api.openai.com/v1` |

일반 LLM factory에 Claude·Google·local 분기가 남아 있어도 #18 Agentic Q&A의
운영 지원 범위는 아니다. preflight, 앱 startup, `/health/ready`가 잘못된 조합을
첫 사용자 요청 전에 거부한다.

### GitHub App

**부분 설정이 가장 위험하다.** 세 검사가 전부 lazy 503이라 기동과 `/health`를
통과한 뒤 사용 시점에 실패한다. preflight가 all-or-nothing으로 강제한다.

- 설치 URL: `GITHUB_APP_INSTALL_URL` 또는 `GITHUB_APP_SLUG`
- 토큰: `GITHUB_APP_ID` + `GITHUB_APP_PRIVATE_KEY`

`GITHUB_APP_PRIVATE_KEY_PATH`는 **운영에서 쓰지 않는다.** 백엔드가 이 경로를
컨테이너 내부에서 그대로 `open()`하므로 호스트 경로를 넣으면 파일이 없어 실패한다.

**콜백 URL을 배포 도메인으로 갱신해야 한다.** GitHub 콘솔의 App 설정에서
`https://<도메인>/github/app/callback`으로 맞춘다. 코드가 아니라 외부 콘솔
작업이며, DuckDNS → 실도메인 전환 시 다시 갱신해야 한다.

미설정으로 두면 `/github/app/*`가 503이고 비공개 저장소를 쓸 수 없다. 공개
저장소는 비인증 호출로 동작하지만 **GitHub REST 한도가 IP당 60회/시간**이라
팀 사용량에는 부족하다 — 그래서 rollout 게이트에 포함되어 있다.

> 백엔드 컨테이너를 재시작하면 **진행 중인 설치 세션(TTL 30분)이 유실된다.**
> 세션이 인메모리라 그렇다. 재배포 타이밍에 설치 중이던 사용자는 처음부터
> 다시 해야 한다.

---

## 5. 백업

**순서가 중요하다.** `mysqldump`와 볼륨 tar를 임의 시점에 각각 뜨면 MySQL과
Chroma의 시점이 어긋나 복구 후 검색 누락·고아 벡터가 생긴다.

비밀번호를 호스트 셸에 export하지 않는다. DB 컨테이너에는 이미
`MYSQL_ROOT_PASSWORD`가 들어 있으므로 **컨테이너 안에서** `MYSQL_PWD`로 넘긴다.
`-p<password>` 형태는 호스트와 컨테이너의 process listing에 비밀번호를 남긴다.

```bash
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=~/paim-backup/$STAMP
mkdir -p "$BACKUP"

# 1. 쓰기 중단
deploy/stack.sh prod stop backend

# 2. MySQL — 단일 일관 시점.
#    셸이 아니라 컨테이너 안에서 환경변수를 읽으므로 argv에 비밀번호가 없다.
deploy/stack.sh prod exec -T db sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --add-drop-table "$MYSQL_DATABASE"' \
  > "$BACKUP/mysql.sql"

# 3. 볼륨 아카이브
for vol in chroma_data upload_data; do
  docker run --rm -v "paim-prod_$vol:/src:ro" -v "$BACKUP:/out" \
    alpine tar czf "/out/$vol.tar.gz" -C /src .
done

# 4. 체크섬
(cd "$BACKUP" && sha256sum ./* > SHA256SUMS)

# 5. 재기동
deploy/stack.sh prod start backend
```

덤프 파일이 비어 있지 않은지 확인한다. `mysqldump`가 실패해도 리다이렉션은
성공하므로 빈 파일이 남을 수 있다.

```bash
test -s "$BACKUP/mysql.sql" && tail -1 "$BACKUP/mysql.sql"   # "Dump completed" 확인
```

### ⚠ 비밀값 백업 — 데이터만으로는 복구되지 않는다

`SESSION_MEMORY_KEY`를 잃으면 **DB를 복구해도 기존 채팅 기록을 영구히 복호화할
수 없다.** 암호화 구현이 환경변수의 단일 키만 쓰고 다른 키 버전이나 복구 경로가
없기 때문이다.

- `SESSION_MEMORY_KEY`, `PAIM_JWT_SECRET`, `DB_PASSWORD`를 **데이터 아카이브와
  분리된 비밀 저장소**(팀 비밀번호 관리자, AWS SSM Parameter Store 등)에 보관한다
- 위 백업 tar에 `.env`를 넣지 않는다 — 아카이브 하나가 유출되면 데이터와 키가
  동시에 털린다
- 새 서버로 복구할 때 **반드시 기존 키를 재사용**한다
- 키를 로그·테스트 출력·저장소에 남기지 않는다

---

## 6. 복구

빈 대상에 복구가 실제로 되는지 확인하려면 원본과 **다른 project**를 써야 한다.

이 절은 **새 셸에서 단독으로 실행 가능**해야 한다. 장애 대응 중에 앞 절의 변수가
남아 있을 거라고 가정하지 않는다.

```bash
# 1. 복구할 백업을 명시적으로 고른다. 없으면 여기서 멈춘다.
BACKUP=${BACKUP:-$(ls -1d ~/paim-backup/*/ 2>/dev/null | tail -1)}
test -n "$BACKUP" -a -s "$BACKUP/mysql.sql" || { echo "복구할 백업이 없다: $BACKUP"; exit 1; }
echo "복구 대상: $BACKUP"

# 2. 운영 .env를 복사하고 포트를 옮긴다.
#    grep -q로 확인 후 없으면 append 한다 — 템플릿에는 포트 줄이 주석 처리되어
#    있어서 sed 치환만 하면 아무것도 바뀌지 않고 restore가 80/443으로 떠서
#    운영 스택과 충돌한다.
#    PAIM_DOMAIN은 남겨둬도 된다 — restore 프로필이 Caddy를 :80으로 고정한다.
cp .env deploy/.env.restore
# 마지막 줄에 개행이 없으면 append가 기존 값에 달라붙어 포트가 정의되지 않고
# restore가 80/443으로 떠서 운영 스택과 충돌한다. 먼저 파일 끝 개행을 보장한다
# (마지막 바이트가 개행이 아니면 한 줄 추가 — 이미 개행이면 아무것도 안 한다).
[ -s deploy/.env.restore ] && [ -n "$(tail -c1 deploy/.env.restore)" ] && echo >> deploy/.env.restore
for kv in PAIM_HTTP_PORT=8081 PAIM_HTTPS_PORT=8444; do
  key=${kv%%=*}
  if grep -qE "^[[:space:]]*${key}=" deploy/.env.restore; then
    sed -i "s|^[[:space:]]*${key}=.*|${kv}|" deploy/.env.restore
  else
    echo "$kv" >> deploy/.env.restore
  fi
done
grep -E '^PAIM_HTTP(S)?_PORT=' deploy/.env.restore   # 8081 / 8444 확인

deploy/stack.sh restore up -d db

# ⚠ DB가 healthy가 될 때까지 기다린다. 빈 볼륨에서는 MySQL 초기화(스키마·마이그
#   레이션 8개 적용)에 수십 초가 걸리고, 그 전에 복원하면 조용히 실패한다.
until [ "$(docker inspect -f '{{.State.Health.Status}}' paim-restore-db-1)" = healthy ]; do
  sleep 3; echo "  DB 초기화 대기..."
done

# 체크섬 검증 후 복원
(cd "$BACKUP" && sha256sum -c SHA256SUMS)

deploy/stack.sh restore exec -T db sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE"' < "$BACKUP/mysql.sql"

for vol in chroma_data upload_data; do
  docker run --rm -v "paim-restore_$vol:/dst" -v "$BACKUP:/in:ro" \
    alpine sh -c "rm -rf /dst/* && tar xzf /in/$vol.tar.gz -C /dst"
done

deploy/stack.sh restore up -d
curl http://localhost:8081/health
```

복구 성공 판정은 `/health` 200이 아니라 **데이터 대조**다 — 프로젝트·문서 row가
살아 있는지, 업로드 파일 checksum이 같은지, 검색 결과가 같은지, 그리고
**기존 채팅이 평문으로 복호화되는지** 확인한다.

---

## 7. 롤백

이 절도 새 셸에서 단독 실행 가능하다.

```bash
docker image ls paim-backend            # 보존된 태그 확인
PREV=paim-backend:<이전-git-sha>

# PAIM_IMAGE 줄이 없을 수도 있으므로 append-safe 하게 설정한다. 마지막 줄에
# 개행이 없으면 append가 기존 값에 달라붙어 PAIM_IMAGE가 인식되지 않고 롤백이
# 실제로 수행되지 않는다. 먼저 파일 끝 개행을 보장한다.
[ -s .env ] && [ -n "$(tail -c1 .env)" ] && echo >> .env
if grep -qE '^[[:space:]]*PAIM_IMAGE=' .env; then
  sed -i "s|^[[:space:]]*PAIM_IMAGE=.*|PAIM_IMAGE=$PREV|" .env
else
  echo "PAIM_IMAGE=$PREV" >> .env
fi

deploy/stack.sh prod up -d backend

# 실제로 그 이미지로 떴는지 확인한다. health 200만으로는 증명되지 않는다.
docker inspect -f '{{.Config.Image}}' paim-prod-backend-1

# 도메인은 .env에서 읽는다 — 앞 절의 셸 변수에 의존하지 않는다.
# export 접두·따옴표·인라인 주석을 preflight와 동일하게 처리한다.
# 도메인은 preflight의 --get으로 읽는다 — Compose가 Caddy에 넘기는 값과 **동일한
# 파서**를 써서 "런북이 검사한 값 = Caddy가 받는 값"을 보장한다(손 파싱 금지).
DOMAIN=$(deploy/preflight.sh --get PAIM_DOMAIN --env-file .env)
# hostname 형식이 아니면(빈 값, 따옴표 안 공백/#, 보간 잔여 등) 조용히 정규화하지
# 말고 여기서 멈춘다. Caddy가 받는 값 그대로를 검증한다.
case "$DOMAIN" in
  ""|*[!A-Za-z0-9.-]*) echo "PAIM_DOMAIN 미설정 또는 hostname 형식 아님: [$DOMAIN] — .env 확인"; exit 1 ;;
esac
curl -I "https://$DOMAIN/health"
```

**이전 태그를 최소 3개 보존한다.** `docker image prune -a`는 태그가 붙어 있어도
참조되지 않으면 지우므로, 롤백 대상까지 날아갈 수 있다.

DB 스키마가 바뀐 배포를 롤백할 때는 이미지만 되돌리면 안 된다 — 마이그레이션
역방향이 없으므로 백업본 복구가 필요하다.

---

## 8. 로컬 리허설

실서버에 올리기 전에 로컬에서 전체 스택을 검증한다.

```bash
cp deploy/.env.deploy.example deploy/.env.rehearsal
# PAIM_HTTP_PORT=8080, PAIM_HTTPS_PORT=8443 설정 (PAIM_DOMAIN은 비워둔다 → HTTP)

# 시작 전: 개발 스택 상태 기록
docker ps -q > /tmp/dev-before.txt

deploy/stack.sh rehearsal up -d --build
curl http://localhost:8080/health

# 세 저장소에 표본 기록 — 프로젝트·문서 생성(MySQL), 파일 업로드(checksum),
# 검색 질의로 벡터 적재 확인, 암호화된 채팅 세션 생성
# ...

# 컨테이너 재생성 (restart로는 볼륨 재부착 경로를 행사하지 않는다)
deploy/stack.sh rehearsal down      # ⚠ -v를 붙이면 볼륨이 삭제된다
deploy/stack.sh rehearsal up -d

# 재기동 후 대조: row ID, 파일 checksum, 검색 결과가 같은가
# 비루트 backend가 두 볼륨에 실제로 쓸 수 있는가

# 종료 후: 개발 스택이 그대로인가
docker ps -q > /tmp/dev-after.txt && diff /tmp/dev-before.txt /tmp/dev-after.txt
```

리허설은 전용 project·env 파일·포트를 쓰므로 개발 스택과 격리된다. 그래도
`down -v`는 절대 쓰지 않는다.

---

## 9. 비상 데모 경로 (RunPod)

AWS 셋업이 발표 전까지 안 끝날 경우의 대비책이다.

RunPod 파드는 `https://<pod-id>-8000.proxy.runpod.net` 형태의 HTTPS 주소가 즉시
붙어서 도메인 확보 절차가 사라진다. 다만 **HTTPS를 RunPod 프록시가 대신
종단하므로 WBS의 "인증서 갱신 가능 상태 확인"을 우리가 증명할 수 없다.**
정식 배포로 인정되지 않으며, 데모를 살리기 위한 최후 수단으로만 쓴다.
