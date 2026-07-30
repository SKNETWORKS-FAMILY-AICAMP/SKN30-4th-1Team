# PaiM 평가 로드맵

> 작성: 2026-07-22
>
> 범위: 검색·응답·라우팅 품질을 측정하고 개선 우선순위를 관리한다. 배포·인증·인프라 계획은 [PRODUCTION_ROADMAP.md](PRODUCTION_ROADMAP.md)에서 관리한다.

## 목적과 운영 원칙

- 현재의 60문항 골든셋은 **semantic RAG 및 supersede 이력 검색** 전용 트랙이다.
- `filter_lookup`, `overview`, `브리핑`은 검색을 중심으로 답하지 않으므로 RAGAS와 섞지 않고 별도 결정론·체크리스트 트랙으로 평가한다.
- 수치가 좋아 보여도 실제 supersede/비-supersede 판정이 틀리면 완료가 아니다. 답변 원문과 판정 근거를 함께 보존한다.
- 평가 데이터·기준 라벨 변경과 서비스 코드 변경은 별도 태스크에서 검토한다. 이 문서는 우선순위와 완료 기준만 기록한다.

## 현재 기준선

| 항목 | 현재 관측 | 의미 |
|---|---:|---|
| E0 검색 recall | 0.981 | 하이브리드 검색은 근거 누락을 대체로 막음 |
| E1 변경 질문 recall | 0.900 → 1.000 | supersede 적용 후 변경 근거 누락 감소 |
| E2-e2e 이력 감지 | 0 / 5 | end-to-end 이력 기능의 핵심 병목 |
| E2-oracle 변경 질문 recall | 1.000 | 강제 history mode의 검색 체인은 동작 |
| E2 비번복 대조군 faithfulness | Modu .592 / CS-Bot .607 | 번복 서사 과장 가능성 확인 필요 |
| citation grounding | 0.962~1.000 | 실제 근거 파일명 인용은 대체로 안정 |

세부 수치와 유형별 차트는 [EVAL_INSIGHTS_REPORT.md](../../evaluation/golden-v1/EVAL_INSIGHTS_REPORT.md) 및 [EVAL_INSIGHTS_REPORT.html](../../evaluation/golden-v1/EVAL_INSIGHTS_REPORT.html)을 당시 정본으로 참조한다.

## 우선순위 로드맵

| 순서 | 작업 | 목적 | 완료 판단 | 선행 조건 |
|---:|---|---|---|---|
| 1 | history intent 감지 recall 개선 | 실제 이력 질문을 E2 history 경로로 보냄 | 기존 실제 supersede 5문항의 E2-e2e 감지 결과와 오탐 목록을 기록하고, 목표 기준을 합의 | 현재 routing audit 결과 |
| 2 | 5/5 이력 평가셋 확장 | 변경 이해와 과잉 변경 서사를 균형 평가 | 실제 supersede 5개 + 비-supersede 5개, 각각 골든 답·기대 상태·근거 문서 확정 | 기존 5개 변경 질문·4개 음성 대조군 검수 |
| 3 | E2-oracle 생성·정합성 평가 | 감지 실패와 체인/답변 품질을 분리 | E2-e2e와 oracle 모두에 답변 원문·생성 3지표·`supersede_correctness`·판정 근거를 저장 | 1, 2 |
| 4 | filter_lookup 결정론 평가 | ‘정답 보장’ SQL 조회 경로 검증 | 라우팅·필터 추출·SQL 결과·응답 필수/금지 요소를 문항별로 모두 판정 | 순방향 질문 초안 6개 확정 |
| 5 | overview·브리핑 평가 | 요약 경로의 최신성·누락·안전성 검증 | 필수/금지 요소 체크리스트와 supersede 전·후 비교 통과 | 2, 3의 최신/구 결정 기준 |
| 6 | 검색·생성 개선 반복 | SQL 노이즈와 답변 직접성 개선 | precision/recall 및 relevancy의 개선이 회귀 없이 재현 | 1~5에서 원인·측정 기준 확정 |

## 1. History intent 감지 개선

### 목표

이력 질문을 `semantic + history_mode=True`로 라우팅하고, 비번복 질문에는 history mode를 불필요하게 켜지 않는다.

### 측정

| 지표 | 정의 |
|---|---|
| history recall | 실제 supersede 질문 중 `history_mode=True` 비율 |
| history precision | history mode가 켜진 질문 중 실제 supersede 질문 비율 |
| 라우팅 정확도 | 기대 semantic/overview/filter_lookup 경로와 실제 경로 일치율 |
| 오탐 목록 | 비-supersede·일반 질문에서 history mode가 켜진 문항과 원인 |

### 완료 조건

- 5/5 평가셋 확정 후 목표 recall·precision 수치를 사전에 합의한다.
- 변경 전/후 routing audit CSV와 미탐·오탐 차이를 보존한다.
- 감지 규칙의 확장은 실제 supersede 문항만이 아니라 비-supersede 대조군에서 함께 검증한다.

## 2. 5/5 supersede 평가셋

### 구성

| 그룹 | 수 | 반드시 포함할 내용 |
|---|---:|---|
| 실제 supersede | 5 | 구 결정, 신 결정, 최종 상태, 변경 근거 문서 |
| 비-supersede 대조군 | 5 | 유지·재확인·구체화·후속 추가처럼 번복과 구별되는 사례 |

각 문항은 `question`, 골든 답, 기대 상태(`superseded`/`not_superseded`), 구/신 결정 앵커, 근거 파일명, 기대 route/history mode를 가져야 한다.

## 3. E2-e2e / E2-oracle 비교

### 문항별 보존 항목

| 필드 | 설명 |
|---|---|
| `qid`, `question`, `tag`, `mode` | 문항과 E2-e2e/oracle 실행 구분 |
| `history_detected`, `history_rows_added` | 감지 실패와 체인 추가 여부 |
| `response`, `source_labels`, `rendered_context` | 실제 답변과 검색 근거 검토 |
| `faithfulness`, `response_relevancy`, `citation_grounding` | 생성 품질 |
| `supersede_correctness` | 최신·구 결정 및 번복 여부 판단의 정오 |
| `supersede_reason` | 판정 근거 또는 실패 원인 |

### `supersede_correctness` 판정 기준

- 실제 supersede: 구 결정·신 결정·최종 상태를 구분하고 변경 관계를 올바르게 설명한다.
- 비-supersede: 유지·재확인·구체화·후속 추가를 번복으로 단정하지 않는다.
- 최신 상태 질문: 폐기된 결정을 현재 결정처럼 답하지 않는다.
- 근거가 부족하면 추측하지 않고 불확실성을 밝힌다.

## 4. Filter lookup 결정론 평가

### 범위

`filter_lookup`은 RAGAS 대신 기대 결과와 정확히 비교한다. 당시 [nonsearch_track_draft.json](../../../../backend/test/golden/nonsearch_track_draft.json)에 순방향 담당자 조회 6문항 초안이 있다.

### 최소 문항군

- 담당자별 액션 목록
- 담당자 + 미완료 상태
- 완료/미완료 개수
- 기한 초과 및 N일 이내 마감
- 복합 필터
- 결과 없음

### 완료 판단

| 점검 | 통과 기준 |
|---|---|
| 라우팅 | 기대 `filter_lookup` |
| 필터 추출 | owner/category/status/due 조건이 골든 값과 일치 |
| SQL 결과 | 기대 memory ID 집합과 정확히 일치 |
| 답변 | 필수 항목 포함, 금지 항목 미포함 |
| 오류 경계 | 빈 결과를 정확히 표현하고 추출 실패는 semantic으로 안전 폴백 |

## 5. Overview·브리핑 체크리스트 평가

overview와 델타 브리핑은 검색 컨텍스트의 순도보다 요약의 최신성·완결성이 중요하다. supersede 적용 전/후를 각각 측정하고, 다음 체크리스트로 판정한다.

- 최신 결정은 포함한다.
- superseded된 구 결정을 현재 결정처럼 제시하지 않는다.
- 필수 결정·진행·리스크를 빠뜨리지 않는다.
- 문서에 없는 진행 상황을 만들어내지 않는다.
- 요약 길이와 우선순위 규칙을 지킨다.

초기 목표는 overview 4문항과 필수/금지 요소 체크리스트 확정이다.

## 6. 개선 반복의 판단 순서

1. 먼저 라우팅/이력 감지 오류인지 확인한다.
2. 올바른 경로에 들어갔다면 검색·체인 컨텍스트 오류인지 확인한다.
3. 컨텍스트가 충분하면 답변 생성 또는 인용 오류인지 확인한다.
4. 개선은 해당 단계의 회귀 테스트와 전체 평가를 모두 통과해야 채택한다.

SQL 컨텍스트의 재랭킹·상한 축소, 답변 프롬프트의 직접성 개선은 위 분류로 원인이 확인된 뒤 수행한다. precision만 올리고 recall 또는 supersede correctness를 떨어뜨리는 변경은 채택하지 않는다.
