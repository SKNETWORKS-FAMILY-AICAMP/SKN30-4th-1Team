# 문서 기반 액션 완료·분할 제안 — 프론트엔드 핸드오버

- 작성: 2026-07-27, PR #2 리뷰 대응(F-001·F-011) 반영 기준
- 대상 독자: 데스크톱(desktop/) 작업자 — 박제섭 님
- 선행 문서: `docs/HANDOVER_SUPERSEDE_FRONTEND.md` (제안 인박스 UI의 기존 계약)
- 요지: **데스크톱은 지금 코드 그대로 두어도 안전하다. 크래시는 백엔드에서 막았다.**
  다만 그 대가로 문서 기반 완료·분할 제안이 **사용자에게 전혀 보이지 않는다.**
  UI를 붙여야 기능이 살아난다. API 형태 변경 요청은 지금이 가장 싸다(§7).

---

## 1. 무슨 일이 있었나

`e1c1609`에서 백엔드에 **문서 기반 액션 완료 판정**이 추가됐습니다. 회의록 같은 문서를
업로드하면 LLM이 "이 문서가 기존 열린 액션의 완료를 보고하는지" 판정해 pending 제안을
만듭니다. PR 기반 완료 판정(`complete_action`)과 같은 human-in-the-loop 패턴입니다.

문제는 이 제안이 **기존 `complete_action` kind로 저장됐다**는 점입니다. 그런데 evidence
스키마가 PR 기반과 다릅니다:

| 출처 | evidence |
|---|---|
| PR 기반 (기존) | `{type:"pr", number, title, url, merged_at}` |
| 문서 기반 (신규) | `{type:"document", doc_id, source, date, quote}` — **`title` 없음** |

데스크톱은 `kind === "complete_action"`이면 evidence를 PR형으로 확신하고
`formatSuggestionTitle(suggestion.evidence.title)`을 호출합니다
(`ProjectMemoryPanel.tsx:1535` → `:326`의 `title.trim()`).

**`undefined.trim()` → TypeError.** 확인된 사항:

- 해당 렌더 트리에 **ErrorBoundary가 없어 패널 전체가 중단**됩니다.
- `visibleMemorySuggestions`는 `confidence`로만 거르는데 백엔드가 `confidence='high'`로
  넣어 필터를 통과합니다.
- 문서 상태 폴링 완료 시 메모리 재조회가 자동 발생하므로, **사용자가 제안 인박스를
  열지 않아도 업로드 직후 크래시 경로에 도달**합니다.

여기에 더해, 묶음 액션의 일부만 완료 보고된 경우를 위한 `split_action` kind도 함께
추가됐는데, 데스크톱의 `?status=pending&kind=all` 조회
(`ProjectMemoryPanel.tsx:701`)가 이것까지 받아왔습니다. `kind=all`이
**"내가 아는 것 전부"가 아니라 "앞으로 생길 것까지 전부"**였기 때문입니다.

결과적으로 split 제안이 supersede 카드로 그려지고("기존 결정을 새 결정으로 대체할 것을
제안합니다"), 승인 버튼 비활성 조건(`kind === "supersede" && !supersedingItem`)에도
걸리지 않아 **활성 상태로 남았습니다.**

## 2. 백엔드가 한 조치 (완료)

**신규 kind 2종을 레거시 응답에서 격리했습니다.**

1. 문서 기반 전체 완료를 `complete_action` → **`complete_action_doc`**로 분리
2. `?kind=all`을 **레거시 kind로 동결** — `complete_action`, `supersede`만 반환
3. 이미 저장된 행은 마이그레이션(`backend/db/migrate_v10.sql`)으로 재분류

**⚠️ `kind=all`의 의미가 바뀌었습니다.** "필터 없음" → "레거시 kind 2종".
현재 데스크톱 코드 기준으로는 **받는 결과가 지금과 동일**하므로(아는 kind가 그 둘뿐)
당장 수정할 필요는 없습니다. 다만 앞으로 `all`은 신규 kind를 **영원히 포함하지
않습니다** — 이번 같은 사고를 구조적으로 막기 위한 동결입니다.

> 마이그레이션이 실행되면 이미 `complete_action`으로 내려갔던 문서 기반 제안의 `kind`가
> 바뀝니다. 데스크톱이 제안 목록을 캐시하고 있다면, 재조회 시 해당 항목이 목록에서
> 사라진 것처럼 보일 수 있습니다(id는 그대로, kind만 변경).

## 3. 지금 데스크톱이 어떻게 동작하나 (수정 전)

- **크래시 없음.** 문서 기반 완료 제안이 레거시 응답에서 빠졌습니다.
- **잘못된 카드 없음.** split 제안도 빠졌습니다.
- **대신 두 기능이 사용자에게 전혀 안 보입니다.** 백엔드는 계속 제안을 쌓지만
  아무도 승인할 수 없습니다.

## 4. 필요한 UI 작업

### 4-1. 조회

kind 하나만 필요하면:

```
GET /api/v1/projects/{id}/suggestions?status=pending&kind=complete_action_doc
GET /api/v1/projects/{id}/suggestions?status=pending&kind=split_action
```

인박스 하나에 여러 kind를 같이 보여줄 거면 `?kinds=`로 한 번에:

```
GET /api/v1/projects/{id}/suggestions?status=pending&kinds=complete_action_doc,split_action
```

콤마 구분 kind 목록입니다. `kind`와 동시에 주면 모호하므로 `400`, 모르는 kind가 섞여도
`400`입니다(오타가 빈 목록으로 위장하지 않도록). `supersede`까지 넣고 싶으면
`kinds=complete_action_doc,split_action,supersede`처럼 원하는 만큼 나열하면 됩니다.

### 4-2. evidence 스키마

**`complete_action_doc` (문서 기반 전체 완료)**

```json
{
  "id": 11, "memory_id": 10, "kind": "complete_action_doc",
  "evidence": {
    "type": "document",
    "doc_id": 5,
    "source": "2026-04-13.md",
    "date": "2026-04-13",
    "quote": "인원 관리 로직 완료",
    "original_content": "인원 관리 로직 구현"
  },
  "rationale": "'2026-04-13.md' 문서가 완료로 보고: 인원 관리 로직 완료",
  "confidence": "high", "status": "pending", ...
}
```

**`split_action` (묶음 액션의 일부만 완료)**

```json
{
  "id": 9, "memory_id": 10, "kind": "split_action",
  "evidence": {
    "type": "document",
    "doc_id": 5,
    "source": "2026-04-13.md",
    "date": "2026-04-13",
    "quote": "인원관리는 완료, 알림은 진행중",
    "done_part": "인원 관리 로직 완료",
    "remaining_part": "알림 로직 구현",
    "original_content": "인원 관리 및 알림 로직 구현"
  },
  "rationale": "'2026-04-13.md' 문서가 일부만 완료로 보고: ... (완료: ... / 남음: ...)",
  "confidence": "high", "status": "pending", ...
}
```

필드 설명:

| 필드 | 의미 | 비고 |
|---|---|---|
| `source` | 근거 문서 파일명 | 카드에 표시하기 좋음 |
| `date` | 문서 날짜 | **빈 문자열일 수 있음** (업로드 폼에서 날짜 미입력) |
| `quote` | 완료를 보고한 문서 원문 발췌 | 사용자가 근거를 확인하는 핵심 정보 |
| `done_part` | 완료된 부분 (split 전용) | 새 액션으로 분리됨 |
| `remaining_part` | 남은 부분 (split 전용) | 원본 액션이 이 내용으로 대체됨 |
| `original_content` | 제안 생성 시점의 액션 내용 | 내부 staleness 검사용, 표시 불필요 |

`confidence`는 두 kind 모두 항상 `"high"`입니다(백엔드 하드코딩) — "추정" 배지 분기는
현재로선 안 걸립니다.

### 4-3. 카드 문구와 승인 효과

**`complete_action_doc`**
- 문구 예: `"'{source}' 문서가 이 액션을 완료로 보고했습니다"` + `quote` 인용
- 승인 시 효과: 대상 액션을 완료 처리. **완료 시점은 `NOW()`가 아니라 문서 날짜**
  (`date`가 있으면 그 값, 없으면 `NOW()`). 과거 회의록을 뒤늦게 올려도 완료일이
  오늘로 잘못 찍히지 않게 하기 위함입니다.
- PR 기반과 달리 링크(`url`)가 없습니다 — "PR 링크" 자리는 비우거나 문서명 표시.

**`split_action`**
- 문구 예: `"'{source}' 문서가 이 액션의 일부만 완료로 보고했습니다"`
- **완료분/잔여분 두 덩이를 모두 보여줘야 합니다.** 승인의 결과가 두 갈래라
  한쪽만 보여주면 사용자가 뭘 승인하는지 알 수 없습니다.
- 승인 시 효과: 원본 액션의 content가 `remaining_part`로 **덮어써지고**(계속 열림),
  `done_part`가 **새 액션 행으로 생성되어 즉시 완료 처리**됩니다.
- 되돌리기 API가 없으므로 승인 확인 UI를 권합니다.

### 4-4. 델타 배너

- `pending_suggestions`(레거시 필드)는 **`complete_action`만** 셉니다. 신규 kind 2종은
  포함되지 않으므로 배너 수 = 레거시 인박스 수가 유지됩니다.
- `pending_suggestions_by_kind`에는 신규 kind가 **포함됩니다**:
  `{"complete_action": 2, "complete_action_doc": 1, "split_action": 1, "supersede": 1}`
  — 신규 카드의 배지/카운트는 이 필드를 쓰세요.

## 5. 새 에러 응답

| 엔드포인트 | 코드 | detail | 의미 |
|---|---|---|---|
| GET /suggestions | 400 | Invalid suggestion kind | kind 오타 |
| GET /suggestions | 400 | Specify either kind or kinds, not both | kind(기본값 아닌 값)와 kinds를 동시 지정 |
| GET /suggestions | 400 | Invalid suggestion kind: {값} | kinds에 모르는 kind가 섞임 |
| POST accept (split_action) | 409 | Action already completed — split no longer applicable, please re-derive | 대상 액션이 이미 완료됨 — 분할 불가 |
| POST accept (양쪽) | 409 | Action content changed since this suggestion was created — stale, please re-derive | 제안 생성 후 액션 내용이 바뀜 |
| POST accept (split_action) | 400 | Split evidence missing done_part/remaining_part | evidence 손상 |
| POST accept | 404 | Target action no longer exists | 대상 액션 삭제됨 |

**409 두 종이 중요합니다.** 같은 액션에 완료 제안과 분할 제안이 **동시에 pending으로
존재할 수 있습니다**(dedup이 `(memory_id, kind, status)` 단위). 하나를 승인하면 다른
하나는 낡은 제안이 되고, 승인 시 409가 납니다.

> 이전에는 이 경우가 **조용히 성공 처리**되어 아무 행도 안 만들어졌는데 승인 이력만
> 남았습니다(리뷰 F-002). 지금은 409로 거부하고 제안은 `pending`으로 유지됩니다.

409 수신 시: 제안 목록 + 메모리 목록을 재조회하고 사용자에게 "상황이 바뀌어 이 제안은
더 이상 적용할 수 없습니다" 정도로 안내해 주세요.

## 6. 별개 리스크 — ErrorBoundary

이번 크래시는 백엔드에서 막았지만, **`renderSuggestionInbox()` 렌더 트리에
ErrorBoundary가 없다는 사실 자체는 그대로입니다.** 예상 못 한 형태의 데이터가 한 건만
와도 패널 전체가 중단됩니다. 백엔드 격리는 이 특정 사고를 막은 것이지 구조적 방어가
아닙니다. 별도 대응을 권합니다.

## 7. 협의가 필요한 것

### 7-1. `?kinds=` 파라미터 — 결정됨, 구현 완료

여러 kind를 한 번에 받고 싶으면 콤마 구분으로:

```
GET /suggestions?status=pending&kinds=complete_action_doc,split_action,supersede
```

- `kind`(기본값 아닌 값)와 동시 지정 시 `400` — 택일 강제, 합집합 같은 암묵적 동작 없음
- 모르는 kind가 섞이면 `400` — 오타가 빈 목록으로 위장하지 않도록
- 반복 파라미터(`?kind=a&kind=b`)가 아니라 콤마 구분 단일 파라미터입니다

`docs/API_명세서.md` §제안(Suggestions)에 확정본 반영했습니다. 이제 데스크톱이 아는
kind를 그대로 나열해 부르면 됩니다 — 새 kind가 나올 때마다 그 이름 하나만 목록에
추가하면 되는 구조입니다.

### 7-2. 응답에 표시용 필드 인라인

`split_action` 카드에 원본 액션 내용을 보여주려면 `memory_id`로 메모리 목록에서 찾아야
합니다. 제안 응답에 대상 액션 content를 인라인하는 게 편하면 요청해 주세요.

## 8. 요약 — 지금 결정해야 할 것

1. **UI 작업 착수 시점** — 그때까지 문서 기반 완료·분할 기능은 사용자에게 안 보임
2. (선택) §7-2 응답 필드 인라인이 필요한지

## 9. 참고

- 백엔드 계약: `docs/API_명세서.md` §제안(Suggestions) — 이번 변경 반영 완료
- 기존 제안 인박스 계약: `docs/HANDOVER_SUPERSEDE_FRONTEND.md`
- 리뷰 원문: `.agent-workflow/tasks/PR-002-TASK-001/`
