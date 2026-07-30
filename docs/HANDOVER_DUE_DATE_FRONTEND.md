# Action 마감일 자동 적재 — 데스크톱 핸드오버

- 기준 브랜치: `integration/pr18-stabilized-20260729`
- DB 계약: v9 기존 `memory.due_date`, `memory_suggestions` 재사용
- API 정본: [API 명세서](API_명세서.md)

## 백엔드 동작

1. 문서·회의록에서 연도·월·일이 명시된 action 마감은 `memory.due_date`에 자동 저장한다.
2. `7월 28일까지`, `다음 주 금요일까지`처럼 기준일로 계산한 후보는 자동 확정하지 않고
   `kind=set_due_date` pending suggestion으로 만든다.
3. 단일 날짜를 계산할 수 없는 표현은 임의 날짜를 만들지 않는다.
4. 사용자가 `PATCH /memory/{id}`로 마감을 설정·해제하면 기존 마감 후보는 자동 거절된다.

## 데스크톱에서 추가할 항목

기존 suggestion 기본 조회는 구 클라이언트 보호를 위해 계속 `complete_action`만 반환한다.
마감 후보 화면은 다음 중 하나로 조회한다.

```http
GET /api/v1/projects/{project_id}/suggestions?kind=set_due_date
GET /api/v1/projects/{project_id}/suggestions?kind=all
```

마감 후보 카드에는 다음을 표시한다.

- 대상 action 내용
- `evidence.raw_text`: 원문 마감 표현
- `evidence.reference_date`: 상대 표현 계산 기준일
- `evidence.suggested_due_date`: 승인 시 저장될 날짜
- `evidence.source`: 출처

기존 승인·거절 endpoint를 그대로 사용한다.

```http
POST /api/v1/projects/{project_id}/suggestions/{suggestion_id}/accept
POST /api/v1/projects/{project_id}/suggestions/{suggestion_id}/reject
```

승인 전에 사용자가 다른 날짜를 입력하고 싶으면 suggestion accept 대신 기존
`PATCH /api/v1/projects/{project_id}/memory/{memory_id}`에 `due_date`를 보내면 된다.
이 경우 pending 마감 후보는 자동 거절된다.

## 오류 처리

- `400`: 후보 날짜가 유효한 `YYYY-MM-DD`가 아님 또는 이미 해소된 제안
- `404`: 제안 또는 대상 action이 없음
- `409`: 제안 생성 후 사용자가 action 마감일을 다른 값으로 변경했거나 동시 승인 경합

성공 후 action 목록과 suggestion 목록을 다시 조회해 화면 상태를 갱신한다.
