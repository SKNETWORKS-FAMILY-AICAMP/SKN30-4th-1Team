# supersede(결정 번복) 기능 — 프론트엔드 핸드오버

- 작성: 2026-07-15, 백엔드 TASK-002·TASK-003 완료 기준 (브랜치 `develop/hyseo`, 검증 PASS)
- 대상 독자: 데스크톱(desktop/) 작업자
- ⚠️ 선행 문서: [HANDOVER_AUTH_FRONTEND.md](HANDOVER_AUTH_FRONTEND.md) — 로그인/토큰 연동이 이 문서의
  작업보다 우선순위가 높다(jwt 모드 전환 시 앱 전체가 401).
- 요지: **백엔드는 끝났고 기존 데스크톱은 수정 없이도 깨지지 않는다.**
  다만 supersede 제안 UI를 붙여야 기능이 사용자에게 보인다. API 형태에 대한
  변경 요청은 지금이 가장 싸다 — 계층3 작업과 병렬로 반영 가능.

## 1. 개념 요약

- 새 문서 적재 시 신규 **decision**이 기존 decision을 번복하는지 LLM이 판별해
  `kind='supersede'`인 **pending 제안**을 만든다 (자동 적용 없음, 사람이 승인).
- 승인(accept)하면 구 결정에 `superseded_by`(신 결정 id)가 설정되고, 이후
  **기본 조회에서 숨겨진다** (RAG 검색·메모리 패널 목록·통계·델타 모두).
- 신 결정이 삭제되면 DB의 FK가 포인터를 자동 해제해 구 결정이 **자동 복귀**한다.

## 2. 지금 데스크톱이 어떻게 동작하나 (수정 전)

- `GET /suggestions` 기본 응답이 `complete_action`으로 한정돼 있어서
  (구 클라이언트 보호) **기존 화면은 그대로 동작하고 크래시 없음**.
- 대신 supersede 제안은 화면에 **전혀 안 보인다** — 아래 UI 작업이 필요한 이유.
- 승인이 일어나면(예: 다른 도구로) 메모리 패널 목록에서 구 결정이 자동으로
  빠진다 — 목록 엔드포인트가 필터를 내장하므로 프론트 처리 불필요.

## 3. 필요한 UI 작업

### 3-1. supersede 제안 카드

```
GET /api/v1/projects/{id}/suggestions?kind=supersede   (supersede만)
GET /api/v1/projects/{id}/suggestions?kind=all         (전체 kind)
```

- `kind` 파라미터: `complete_action`(기본) | `supersede` | `all`. 미지 값은 400.
- supersede 항목의 evidence는 PR형과 **다르다** — `title`/`number` 없음:

```json
{
  "id": 8, "memory_id": 10, "kind": "supersede",
  "evidence": {"type": "supersede", "superseding_memory_id": 42},
  "rationale": "새 결정이 기존 배포 방침을 대체합니다.",
  "confidence": "high", "status": "pending", ...
}
```

- 카드에 양쪽 결정 내용을 보여주려면 `memory_id`(구)·`superseding_memory_id`(신)의
  content가 필요 — 현재는 메모리 목록 응답에서 id로 찾아야 한다.
  **목록 응답에 양쪽 content를 인라인해 주는 게 편하면 요청해 달라(§6).**

### 3-2. accept / reject

기존과 동일한 엔드포인트: `POST .../suggestions/{sid}/accept | /reject`

- supersede accept의 효과는 "action 완료"가 아니라 **구 결정 숨김**이다.
- 성공 후: 제안 목록 + 메모리 목록 재조회 권장.

### 3-3. 델타 배너

- `pending_suggestions`는 이제 **complete_action만** 센다(배너 수 = 인박스 수 일치).
- 새 필드 `pending_suggestions_by_kind` 예: `{"complete_action": 2, "supersede": 1}`
  — supersede 배지/카운트는 이 필드로 표시.
- supersede만 pending인 구간의 델타 브리핑은 "변화 없음"을 반환한다(레거시 의미 유지).

### 3-4. 메모리 수정(PATCH)과의 상호작용

- 의미 필드(category/content/topic/reason/date)를 수정하면 그 항목과 관련된
  **pending supersede 제안이 자동 reject**된다 → 수정 후 제안 목록 재조회 필요.
- 새 409 두 종(아래 표) 토스트/안내 처리 필요.

## 4. 새 에러 응답 정리

| 엔드포인트 | 코드 | detail | 의미 |
|---|---|---|---|
| GET /suggestions | 400 | Invalid suggestion kind | kind 파라미터 오타 |
| POST accept (supersede) | 409 | Superseding decision no longer exists or is not a live decision | 신 결정이 삭제됐거나 decision이 아니거나 이미 번복됨 |
| POST accept (supersede) | 409 | Decision already superseded by another decision | 대상이 이미 다른 결정으로 번복됨 |
| POST accept/reject | 400 | Suggestion already resolved | 이미 해소된 제안 재요청(순차) |
| POST accept/reject | 409 | Suggestion already resolved | 동시 요청 경합에서 패배 |
| POST accept/reject | 409 | Concurrent suggestion resolution conflict | 동시 경합 데드락 — 재시도하면 명확한 응답으로 수렴 |
| PATCH /memory/{mid} | 409 | Cannot change category: this decision supersedes another decision | 다른 결정을 번복 중인 decision의 category 변경 불가 |
| PATCH /memory/{mid} | 409 | Cannot change category: this decision is superseded by another decision | 번복된 decision의 category 변경 불가 |

## 5. 캐시/동기화 규칙 (요약)

- accept 성공 → 제안 목록 + 메모리 목록 재조회.
- 메모리 의미 필드 PATCH 성공 → 제안 목록 재조회(자동 reject 가능성).
- 409 수신 → 로컬 상태가 낡은 것 — 해당 목록 재조회 후 UI 갱신.

## 6. 백엔드에 요청 가능한 것 (지금이 변경 적기)

- 제안 응답에 양쪽 결정 content 인라인(카드 렌더링 편의).
- 이력 보기: 숨겨진 결정 조회(`include_superseded`)는 내부에만 있고 API 미노출 —
  "번복 이력 보기" UI가 필요하면 파라미터 노출 요청.
- un-supersede(승인 취소) API는 현재 없음 — 후속 태스크 후보(L-001과 함께).
- 계층3(검색 개선)은 **완료·병합**됐다(이력 질문 체인·컨텍스트 주석·recency
  RRF). supersede 관련 응답 필드 계약은 위 §3·§4가 확정본이다.

## 7. 참고 문서

- 상세 계약 변화 이력: `.agent-workflow/tasks/TASK-003/implementation-report.md`
  (라운드별 "프론트엔드 영향" 섹션) — 로컬 전용(git 미추적)이라 필요하면 요청.
- 과거 supersede 설계 배경: [PRODUCTION_ROADMAP.md](../../archive/planning/2026-07/PRODUCTION_ROADMAP.md) #2.
