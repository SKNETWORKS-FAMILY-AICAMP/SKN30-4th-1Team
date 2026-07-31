# 백엔드 변경 총정리 — main 대비 develop/hyseo

- 작성: 2026-07-15, 갱신: 2026-07-16 / 범위: `main(eee53bf)` → `develop/hyseo(81e4bd6)`
- 규모: **18커밋, 51파일**, 테스트 203 → **262**
- 워크플로: `.agent-workflow` 기반 TASK-001~003(검증자 PASS + 최종 승인 완료),
  TASK-005(PR #49 백엔드 통합 — 리뷰 0건 + 실기동 스모크 통과)

## 한눈에 보기

main 이후의 백엔드 작업은 크게 **두 덩어리**다:

1. **다중 사용자 + 보안 fail-closed** (TASK-001) — 로그인/권한/데이터 격리
2. **supersede(결정 번복) 수명주기** (TASK-002·003) — "번복된 결정이 RAG 답과
   통계를 오염시키는" 문제(로드맵 #2)의 계층 1·2

## 커밋 타임라인

| 커밋 | 태스크 | 내용 |
|---|---|---|
| `6501f12` | TASK-001 | 다중 사용자+보안 백엔드 본체 랜딩 (28파일, +3209) |
| `e618021` `2692bff` | TASK-001 | Codex 리뷰 2라운드 결함 보완 |
| `9c8426d` `f34a0ad` | TASK-002 | supersede 계층1: migrate_v7 + 조회 필터 (+회귀 테스트) |
| `3d0638c` | TASK-003 | supersede 계층2 본체: LLM 판별 + 제안 생성 |
| `bd8c815`~`8d40248` (8개) | TASK-003 | 리뷰 round 2~9 해결 — 아래 "계층2 보강" 참조 |
| `95b2044` | 문서 | 이 문서 + 프론트 핸드오버 2편 |
| `81e4bd6` | TASK-005 | PR #49 백엔드 통합: `ensure_runtime_schema` 시작 시 보증 |

## 영역별 변경

### A. 인증·다중 사용자 (TASK-001)

- **`backend/api/auth.py`(수정)** — 자체 JWT(HS256) + bcrypt 해시,
  `auth_middleware`(contextvar로 사용자 전파), **fail-closed**
  `require_project_access(project_id, min_role)` + `get_project_role`.
  jwt 모드에서 시크릿 미설정/약함이면 기동 자체를 중단.
- **`backend/api/auth_routes.py`(신규)** — `POST /signup`, `POST /login`, `GET /me`.
- **`backend/api/member.py`(신규)** — 프로젝트 멤버 CRUD
  (`GET/POST /projects/{id}/members`, `PATCH/DELETE /{member_user_id}`) — 역할 관리.
- **`backend/db/migrate_v6.sql`(신규)** — `password_hash`, `chat_sessions.user_id`
  (세션 소유자 격리), `memory_suggestions.resolved_by`(감사 추적), `last_seen_at`.
- 기존 라우터들(project/upload/chat 등)에 접근 제어 적용, 세션 격리.

### B. supersede 계층1 — 스키마 + 조회 필터 (TASK-002)

- **`backend/db/migrate_v7.sql`(신규)** — `memory.superseded_by/superseded_at`.
  번복돼도 row를 지우지 않고 표시만 한다(이력 보존).
- **`backend/retriever/mysql_search.py`(수정)** — 구조화 조회의 단일 초크포인트
  `search()`가 기본적으로 superseded row 제외, `include_superseded=True` 옵트인.
  메모리 패널 목록(`GET /projects/{id}/memory`)이 이 함수를 쓰므로 자동 적용.

### C. supersede 계층2 — 판별 + 제안 (TASK-003 본체)

- **`backend/reconciler/supersede.py`(신규)** — 판별기. ChromaDB 유사 후보 조회
  (`find_similar_memories`) → 살아있는 decision만 LLM 입력 → high/medium 매칭만
  `memory_suggestions`에 pending INSERT (중복 방지, 자기참조/미지 id/날짜 역전 스킵).
- **`backend/pipeline/ingestor.py`(수정)** — 적재 말미 best-effort 훅: 신규 decision이
  있으면 판별 실행. 행 date에 업로드 폼 날짜 폴백 저장(시간순서 검증 재료).
- **`backend/api/suggestion.py`(수정)** — accept를 kind별로 일반화.
  supersede accept = 대상 decision에 `superseded_by` 설정(트랜잭션 내 재검증:
  존재·decision·미번복 + `FOR UPDATE` 행 잠금). `kind` 쿼리 파라미터
  (기본 `complete_action` — 구 데스크톱 보호). 해소 UPDATE는 pending 조건부.

### D. supersede 수명주기 보강 (TASK-003 리뷰 round 3~9)

리뷰가 잡은 것은 대부분 "숨김 상태의 소비자 동기화" — 한 줄씩:

- **포인터 수명주기**: `migrate_v8.sql`(신규) self-FK `ON DELETE SET NULL` —
  신 결정 삭제 시 구 결정 자동 복귀. 삭제 경로 6곳 앱 코드는 무수정(DB가 소유).
- **`active_memory` 뷰**(schema.sql·migrate_v8) — `superseded_by IS NULL` 필터의
  중앙화. 요약 재생성(`project_memory.py`)·조망 집계(`query_intent.py`)·델타(`delta.py`)가
  이 뷰를 읽는다. 잔여 raw `FROM memory` 조회는 전수 조사로 의도적임을 확인.
- **벡터 수렴**(`memory_vector.py`) — 백필은 살아있는 row만 색인, 시작 시 cleanup이
  superseded 벡터 제거, PATCH는 superseded row면 upsert 대신 삭제.
- **시작 시퀀스**(`startup.py`·`main.py`) — `ensure_schema_v8()`: 기존 DB 볼륨에도
  FK·뷰를 idempotent 자동 적용(수동 마이그레이션 불필요). lifespan 최선두 실행.
- **제안 무효화** (`memory.py` update_memory) — 의미 필드(content 등) 수정 시 관련
  pending supersede 제안 자동 reject(양쪽), 번복 관계를 깨는 category 변경은 409.
- **경합 차단** — 해소 UPDATE `status='pending'` 조건부(+rowcount 409), 상호 승인
  순환은 `FOR UPDATE`로 차단, 데드락(1213)은 409로 변환.
- **델타 정합**(`delta.py`) — `pending_suggestions`는 complete_action만(배너=인박스),
  전체는 신규 `pending_suggestions_by_kind`, 집계·브리핑은 active_memory.

### E. 런타임 스키마 보증 (TASK-005 — PR #49 백엔드 통합)

- **`backend/startup.py`** — `ensure_runtime_schema()`(PR #49 유래):
  `memory_sources`·`project_memory` 테이블과 `documents.progress_done/
  progress_total` 컬럼을 시작 시 idempotent 보증. **기존 mysql_data 볼륨
  사용자는 기동만 하면 자동 보정** — 수동 마이그레이션 불필요.
- **`backend/main.py`** — lifespan에서 `ensure_runtime_schema()` →
  `ensure_schema_v8()` 순 실행(기반 테이블·컬럼 → FK·뷰).
- #49 원본과의 차이: 예외 전파 대신 **best-effort**(실패해도 기동 유지) —
  브랜치의 startup 보증 정책과 일관.
- **효과: PR #49와의 백엔드 충돌 소멸** — #49 작성자는 `backend/main.py`,
  `backend/startup.py`, `tests/test_startup_recovery.py` 3개 파일을 PR에서
  제외하면 desktop 전용 PR이 된다(조율 완료).
- 검증: 단위 3건(mock) + 실 MySQL 스모크(구버전 스키마에서 생성 경로·컬럼
  위치·멱등 재실행·전체 lifespan 기동·/health 200 확인).

### F. 인프라·설정

- **`docker-compose.yml`** — migrate_v6~v8 initdb.d 마운트 추가.
- **`.env.example`·`.gitignore(.example)`·`pyproject.toml`·`uv.lock`** — 인증
  관련 설정·의존성 소폭.

### G. 테스트 (+59개, 신규 파일 8)

- 신규: `test_auth_jwt`, `test_mysql_search_supersede`, `test_supersede`,
  `test_supersede_e2e`(accept→계층1 필터 end-to-end), `test_memory_vector_similar`,
  `test_ingest_supersede_hook`, `conftest.py`.
- 보강: suggestions/delta/frontend_contract/query_intent/lifecycle/startup —
  라운드별 회귀 테스트(가드·경합·뷰 사용·마이그레이션 순서 등).

## API 계약 변화 (프론트 관점)

프론트 핸드오버 문서 2편으로 분리 — **인증이 supersede보다 우선순위 높음**
(데스크톱에 로그인 연동이 없어 jwt 모드 전환 시 전면 401):

- `docs/HANDOVER_AUTH_FRONTEND.md` — 로그인/토큰/역할/멤버 관리/세션 격리,
  프론트 작업 체크리스트, jwt 전환 시점 협의 사항.
- `docs/HANDOVER_SUPERSEDE_FRONTEND.md` — `kind` 파라미터, 새 400/409 8종,
  델타 신규 필드, PATCH의 제안 자동 reject, supersede 카드 UI 작업.

## 알려진 한계·이월

- **L-001**: 승인된 supersede 관계의 의미 필드 수정 보호 — 후속 태스크
  (un-supersede API 또는 결정 버저닝 필요).
- **G-004**: A→B→C 체인 중간 삭제 시 A·C 동시 노출 — 설계상 수용(복귀 우선).
- supersede 계층 **3(검색 RRF/주석)·4(골든 평가)** 미착수 — 다음 작업.
- 상세 근거·라운드별 이력: `.agent-workflow/tasks/TASK-00N/`(git 미추적, 로컬).

## 다음 단계

1. push → **main 병합**(PR) + 프론트에 핸드오버 문서 공유
2. #49 작성자의 백엔드 3파일 제외 확인 → #49는 desktop 전용으로 병합
3. 계층3(TASK-004, plan v6 승인 대기): 검색이 superseded 정보를 활용
   (이력 체인 + 주석 + recency RRF)
4. 계층4: 골든 평가로 회귀 감지
