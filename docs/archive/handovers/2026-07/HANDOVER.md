# PaiM 인수인계 문서 — 다중 사용자 백엔드 완료 시점 (2026-07-08)

> 대상: 후속 작업을 이어받을 AI 어시스턴트(Sonnet/Opus)와 팀원.
> 전체 로드맵·설계 근거는 `docs/PRODUCTION_ROADMAP.md`, 시스템 구조는 `docs/ARCHITECTURE.md` 참고.
> 일정: 개발 마감 **7/27(월)**, 7/28(화) 오전 마무리·오후 발표. **7/23(목) 기능 동결** 권장.

---

## 1. 현재 상태 요약

로드맵 #7(보안 fail-closed)과 #8(다중 사용자)의 **백엔드 전체가 구현·검증 완료**된 상태다.

- **인증**: 자체 JWT(HS256, 표준 라이브러리 구현 — `backend/github/router.py`의 RS256 선례를 따름) + bcrypt 비밀번호 해시. `POST /api/v1/auth/signup`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`.
- **fail-closed**: 기본 모드(`PAIM_AUTH_MODE=jwt`)에서 토큰 없는 요청은 전부 401. 기존의 "인증 없으면 통과" 동작은 `PAIM_AUTH_MODE=dev`로 **명시적 옵트인**해야만 켜진다(기동 시 경고 로그).
- **contextvar 트릭**: `auth_middleware`가 JWT 검증 후 contextvar에 user_id를 심고, `get_current_user_id()`가 그것을 읽는다. 덕분에 40여 곳의 기존 `require_project_access()` 호출부는 무수정.
- **멤버 관리**: `GET/POST/PATCH/DELETE /api/v1/projects/{id}/members`. 추가/제외/역할변경은 owner 전용, 일반 멤버는 본인 탈퇴만 가능, owner는 탈퇴/제외/역할변경 불가, API로 owner 역할 부여 불가.
- **데이터 격리**: `chat_sessions.user_id` 추가 — 새 세션은 생성자 전용(타인 세션은 404), `user_id IS NULL`인 레거시 세션만 멤버 전원에게 보임. 프로젝트 삭제는 owner 전용으로 상향.
- **감사 추적**: 제안 승인/거절 시 `memory_suggestions.resolved_by`에 user_id 기록.
- **검증**: 단위 테스트 **174개 전부 통과**(신규 29개 포함), 2계정(팀장/팀원) **E2E 27개 시나리오**를 실 MySQL + 실 서버(jwt 모드)에서 확인.

### 마이그레이션 넘버링 주의
원래 로드맵은 supersede=v6, 멀티유저=v7이었으나 **멀티유저가 먼저 랜딩하면서 뒤바뀌었다: 멀티유저=`migrate_v6.sql`(적용됨), supersede=`migrate_v7.sql`(미작성)**. 로드맵 문서는 정정 완료.

---

## 2. 리스크 레지스터

### 🔴 즉시 터질 수 있는 것 (전환 리스크)

| # | 리스크 | 내용 | 완화책 |
|---|---|---|---|
| R1 | **팀원 git pull 직후 API 전체 401** | 기본값이 jwt 모드라, `.env` 갱신 없이 백엔드를 올리면 데스크톱 앱이 전부 401. `PAIM_JWT_SECRET`도 없으면 로그인 자체가 503 | **팀 채널에 공지 필요**: 로그인 UI 나오기 전까지 `.env`에 `PAIM_AUTH_MODE=dev` + `DEV_USER_ID=1`. `.env.example`에 설명 있음 |
| R2 | **레거시 고아 프로젝트** | `project_members` row가 없는 기존 프로젝트는 jwt 모드에서 **아무에게도 보이지 않고 접근 불가**(멤버십 필터). dev 모드용 `backfill_dev_user_membership()`은 jwt 모드에서 동작 안 함 | 실 DB를 jwt 모드로 전환하기 전에 소유자 지정 백필 실행: `INSERT INTO project_members (project_id, user_id, role) SELECT p.id, <owner_id>, 'owner' FROM projects p WHERE NOT EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id = p.id);` |
| R3 | **migrate_v6 미적용 DB** | 기존 DB에 v6를 안 돌리면 signup(`password_hash` 없음)·세션 생성(`user_id` 없음)이 SQL 에러 | `mysql -u root -p paiM < backend/db/migrate_v6.sql` (idempotent, 재실행 안전). docker-compose 신규 볼륨은 자동 |
| R4 | **이 머신의 mysql_data 볼륨 비밀번호 불일치** | 로컬 docker 볼륨이 현재 compose의 `paiM_dev`와 다른 비밀번호로 초기화돼 있어 root 접속 불가 (7/8 확인) | 팀에 실제 비밀번호 확인. E2E 검증은 임시 컨테이너로 수행했고 볼륨은 건드리지 않음 |

### 🟡 설계상 한계 (알고 수용한 것 — 발표 전 재검토 대상)

| # | 리스크 | 내용 | 완화책/시점 |
|---|---|---|---|
| R5 | **토큰 서버측 철회 불가** | 로그아웃/멤버 제외 후에도 발급된 JWT는 TTL(기본 12h)까지 유효. 단, 프로젝트 접근은 매 요청 `project_members`를 조회하므로 **제외 즉시 프로젝트 자원 접근은 차단됨** — 남는 것은 `/auth/me`와 프로젝트 목록 정도 | 데모에는 수용 가능. 공개 서비스 전 짧은 TTL+refresh 또는 Cognito 전환 (로드맵 §8 트레이드오프) |
| R6 | **signup 완전 개방** | 서버 URL만 알면 누구나 가입 → 프로젝트 생성 → **LLM 호출 가능(과금 벡터)**. 로그인/가입에 rate limit·계정 잠금 없음(bcrypt가 브루트포스를 늦출 뿐) | AWS 배포 시 가입 코드(env 기반 invite code) 게이팅 또는 nginx rate limit — 로드맵 §7 2순위와 묶어 처리 |
| R7 | **owner 이관/복수 owner 불가** | owner 계정 분실 시 프로젝트 관리 불능 (DB 직접 수정 외 방법 없음) | 이번 사이클 수용. 필요 시 `PATCH /members`에 이관 로직 추가 (마지막 owner 보호 필수) |
| R8 | **레거시 세션(user_id NULL) 전원 공개** | 마이그레이션 이전 대화가 새로 초대된 멤버에게도 보임 | 팀 판단 필요. 원하면 `UPDATE chat_sessions SET user_id = <owner_id> WHERE user_id IS NULL;`로 owner 귀속 |
| R9 | **제외된 멤버의 세션 잔존** | 멤버 제외 시 그의 chat_sessions는 삭제되지 않음 — 재초대되면 다시 보이고, 그 외에는 아무도 못 봄(데이터만 잔존) | 의도된 동작으로 수용. 정리가 필요하면 제외 시 세션 삭제 옵션 추가 |

### 🟢 기술적 주의점 (후속 작업자가 코드 만질 때)

| # | 주의점 | 내용 |
|---|---|---|
| R10 | **미들웨어 등록 순서 고정** | `backend/main.py`에서 `auth_middleware`는 반드시 CORS `add_middleware`보다 **먼저** 등록돼야 한다(Starlette은 나중 등록이 바깥). 순서가 바뀌면 401 응답에 CORS 헤더가 빠져 브라우저에서 원인 불명 CORS 에러로 보인다. 코드에 주석 있음 |
| R11 | **BackgroundTasks에서는 contextvar가 없다** | 현재 백그라운드 파이프라인(ingest, repo sync)은 auth 함수를 안 쓰는 것 확인(7/8). **앞으로 백그라운드 태스크에서 `get_current_user_id()`를 호출하면 None**이 나온다 — 사용자 귀속이 필요하면 태스크 인자로 user_id를 명시적으로 넘길 것 |
| R12 | **새 공개 엔드포인트는 `_PUBLIC_PATHS` 등록 필수** | GitHub 웹훅 등 외부 서비스가 호출하는 엔드포인트를 추가하면 `backend/api/auth.py`의 `_PUBLIC_PATHS`/`_PUBLIC_PREFIXES`에 넣어야 한다. 안 넣으면 조용히 401. 현재 공개: `/`, `/health`, `/api/v1/auth/signup·login`, `/github/app/callback*`. **`/docs`·`/openapi.json`도 jwt 모드에선 잠김**(의도) — 개발 중엔 dev 모드 사용 |
| R13 | **테스트 suite 기본이 dev 모드** | `tests/conftest.py`가 `PAIM_AUTH_MODE=dev`를 깐다(기존 테스트 호환). **jwt 모드 동작을 테스트할 때는 `tests/test_auth_jwt.py`의 `jwt_mode` fixture처럼 monkeypatch로 명시 설정**할 것. 안 그러면 fail-open 상태를 테스트하게 됨 |
| R14 | **bcrypt 72바이트 절단** | 72바이트 초과 비밀번호는 조용히 잘림(한글 ~24자 이상). 데모에는 무해, 공개 서비스 전 사전 SHA-256 해싱 등 검토 |
| R15 | **`role` 컬럼에 CHECK 제약 없음** | DB에 직접 이상한 role을 넣으면 `_ROLE_RANK.get(role, -1)` → rank -1 → 모든 검사 거부(fail-safe). API는 `_ASSIGNABLE_ROLES`로 검증함 |
| R16 | **의존성 추가됨** | `bcrypt`가 pyproject 명시 의존성으로 추가됨(기존엔 chromadb의 전이 의존성) → 팀원은 `uv sync` 필요 |

### 미변경 기존 리스크 (이번 작업 범위 밖, 로드맵 §1·§7 참조)
- PyMySQL 매 요청 새 커넥션(풀 없음) — 다중 사용자로 요청량 늘면 병목 가능
- 시크릿 전부 평문 `.env` (JWT secret 포함) → 배포 시 SSM Parameter Store
- GitHub App 세션 인메모리 dict — 재시작/멀티워커 유실 → MySQL 테이블화
- 업로드 10MB 제한은 있으나 rate limit 없음

---

## 3. 남은 작업 (우선순위 순)

### ① supersede + recency (#2 — 발표 스토리의 핵심, RAG 2인 몫)
- **설계 전문이 `docs/PRODUCTION_ROADMAP.md` §2에 있다. 반드시 먼저 읽을 것.**
- `backend/db/migrate_v7.sql` 작성: `memory.superseded_by INT NULL` + `superseded_at` (v5/v6의 idempotent 프로시저 패턴 복사)
- 판별 모듈: `backend/reconciler/`의 `_invoke_reconciler_once` 패턴(LLM 배치 판정 → Pydantic 구조 수신, high/medium confidence + 근거 필수) 재사용. high → 자동 링크, medium → `memory_suggestions` 인박스(kind 신설)
- 검색: `WHERE superseded_by IS NULL` 필터 + recency를 세 번째 RRF 리스트로 융합(가중 0.4/0.4/0.2 시작)
- 평가: 타임라인 골든 케이스 5~10개 → RAGAS before/after (기준선: context_precision 0.571, answer_relevancy 0.424). **W2 말까지 측정 완료** 목표
- suggestion 승인 흐름에 `resolved_by`가 이미 있으므로 "팀장이 supersede 제안 승인" 데모가 바로 이어진다

### ② 데스크톱 로그인/멤버 UI (#8 잔여분, 데스크톱 1인 몫)
- `desktop/src/paimApi.ts`: **Authorization 헤더 없음(7/8 확인)** — 토큰 주입 + 401 응답 시 로그인 화면 전환 처리
- 로그인/가입 화면 + 토큰 저장(Tauri secure storage 권장, 최소 localStorage)
- 프로젝트 설정에 멤버 관리 패널 (목록/이메일로 추가/제외 — 백엔드 API 완성돼 있음, 위 §1 참조)
- `App.tsx`가 약 5,800줄 — 작업량 과소평가 금지
- 완성되면 `.env`를 jwt 모드로 전환하고 **2인 동시 사용 E2E 재검증** (아래 §4 절차 재사용)

### ③ AWS 배포 (#1, 인프라 1인 몫)
- 로드맵 §1: 단일 EC2 + RDS + S3 + ALB(TLS) 우선. Fargate는 로컬 의존 3곳(ChromaDB PersistentClient, 업로드 파일, GitHub 인메모리 세션) 외부화 전까지 보류
- 배포 전 필수: R2 백필 실행, `PAIM_JWT_SECRET` 강한 값 생성, R6(가입 게이팅) 처리

### 제외/보류 확정 (재논의 금지 — 사용자와 합의됨)
- #3 멀티모달, #4 에이전트 툴: 이번 사이클 제외, 발표 로드맵 슬라이드로
- #6 Postgres+pgvector 전환: 발표 후 8월 초

---

## 4. 실행·검증 방법

```bash
# 의존성 (bcrypt 추가됨)
uv sync

# 전체 백엔드 게이트 — 비통합 pytest + 실제 MySQL 통합 (Docker 필요)
./tests/integration/mysql/run.sh

# 경로 계약만 확인 (Docker 미기동)
./tests/integration/mysql/run.sh --check

# 비통합만 (DB 불필요 — 전부 mock)
uv run pytest -q --ignore=tests/integration/mysql

# 로컬 개발 실행 (데스크톱 UI 나오기 전)
# .env: PAIM_AUTH_MODE=dev, DEV_USER_ID=1
docker compose up -d db          # R4 주의: 이 머신은 볼륨 비밀번호 불일치
uv run paim-server

# jwt 모드 실행 (인증 검증용)
# .env: PAIM_AUTH_MODE=jwt, PAIM_JWT_SECRET=<python -c "import secrets;print(secrets.token_urlsafe(48))">
# 기존 DB라면: mysql ... < backend/db/migrate_v6.sql

# jwt 모드 스모크 테스트 (7/8 E2E에서 전부 통과한 시나리오 요약)
curl -s -o /dev/null -w "%{http_code}" localhost:8000/api/v1/projects   # 401 기대
curl -s -X POST localhost:8000/api/v1/auth/signup -H "Content-Type: application/json" \
  -d '{"email":"a@b.co","password":"password123","name":"A"}'           # 201 + access_token
# 이후: 로그인 → 프로젝트 생성 → 두 번째 계정 가입 → 멤버 추가(owner) → 세션 격리 확인
```

E2E 전체 시나리오(27개: 401/403/404/409 경계, 세션 격리, 탈퇴 규칙)는 7/8에 임시 MySQL 컨테이너 + 실 서버로 통과 확인했다. 데스크톱 통합 후 같은 시나리오를 UI로 재검증할 것.

---

## 5. 작업 컨벤션 (이 리포지토리에서 지킬 것)

- **파일 삭제 금지** — 삭제가 필요하면 별도 보관 디렉토리로 이동하고 기록을 남긴다 (프로젝트 오너 지시)
- **변경 기록** — 모든 파일 변경은 기록으로 남긴다 (이 문서 §6 형식 참고)
- 마이그레이션은 `backend/db/migrate_v*.sql`의 **idempotent 프로시저 패턴** (information_schema 검사 → ALTER) + `docker-compose.yml` initdb 마운트 추가 + `schema.sql`에도 반영(신규 설치용)
- 테스트는 실 DB 없이 동작해야 한다: `get_connection` patch 또는 `app.dependency_overrides` (일반 `patch("...get_db")`는 `Depends`에 안 먹힌다 — 7/8에 그런 테스트 하나를 교정함)
- 주석·에러 메시지는 한국어, 코드 스타일은 주변 코드를 따른다

---

## 6. 변경 이력 (2026-07-06 ~ 07-08 세션)

| 일자 | 동작 | 대상 | 비고 |
|---|---|---|---|
| 07-06 | 생성 | docs/ARCHITECTURE.md, docs/ARCHITECTURE.html | 시스템 아키텍처 문서 |
| 07-06 | 생성 | docs/PRODUCTION_ROADMAP.md | 실서비스 전환 로드맵 (7개 항목 + §8 + 주차별 계획) |
| 07-08 | 수정 | backend/api/auth.py | JWT + bcrypt + contextvar + auth_middleware + fail-closed + get_project_role |
| 07-08 | 생성 | backend/api/auth_routes.py | signup / login / me |
| 07-08 | 생성 | backend/api/member.py | 멤버 관리 API (owner 규칙 포함) |
| 07-08 | 생성 | backend/db/migrate_v6.sql | password_hash, chat_sessions.user_id, resolved_by, last_seen_at |
| 07-08 | 수정 | backend/db/schema.sql | v6 컬럼 신규 설치 반영 |
| 07-08 | 수정 | backend/main.py | 미들웨어(CORS보다 안쪽)·라우터 등록, dev 모드 경고 |
| 07-08 | 수정 | backend/chat/router.py | 세션 user_id 기록 + 본인/레거시 격리 |
| 07-08 | 수정 | backend/api/project.py | 프로젝트 삭제 member→owner |
| 07-08 | 수정 | backend/api/suggestion.py | resolved_by 기록·노출 |
| 07-08 | 수정 | docker-compose.yml | migrate_v6 마운트 |
| 07-08 | 수정 | pyproject.toml, uv.lock | bcrypt 추가 |
| 07-08 | 수정 | .env.example | PAIM_AUTH_MODE / PAIM_JWT_SECRET / TTL 문서화 |
| 07-08 | 생성 | tests/conftest.py | suite 기본 dev 모드 (R13) |
| 07-08 | 생성 | tests/test_auth_jwt.py | 인증 체계 테스트 29개 |
| 07-08 | 수정 | tests/test_chat_router.py | fake cursor에 user_id 반영 |
| 07-08 | 수정 | tests/test_frontend_contract.py | 무효했던 get_db patch → dependency_overrides |
| 07-08 | 수정 | docs/PRODUCTION_ROADMAP.md | §8 완료 표시, v6/v7 넘버링 정정, W1/W2 갱신 |
| 07-08 | 생성 | docs/HANDOVER.md | 이 문서 |

### 환경변수 레퍼런스 (신규)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PAIM_AUTH_MODE` | `jwt` | `jwt`=fail-closed(토큰 필수) / `dev`=검증 생략(로컬 전용, 기동 경고) |
| `PAIM_JWT_SECRET` | 없음 | jwt 모드 필수. 미설정 시 로그인 503 (기본 시크릿 없음 — 의도) |
| `PAIM_JWT_TTL_HOURS` | `12` | 액세스 토큰 유효 시간 |
| `DEV_USER_ID` | 없음 | dev 모드 전용 가짜 사용자 ID |
