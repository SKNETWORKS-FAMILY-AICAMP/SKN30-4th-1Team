# Agentic Q&A v2 평가 계약

## 목적

이 평가는 Agentic Q&A 변경 전후의 답변 품질, Tool 사용, 지연 시간을 같은 입력과
동결된 검색 상태에서 비교한다. 기존 160문항 평가와 `backend/test/golden/run_eval.py`의
내부 검색 재구성은 사용하지 않는다.

## 실행 경계

- 평가는 실제 `POST /api/v1/projects/{project_id}/query` 경로를 호출한다.
- 외부 응답 계약(`answer`, `plan`, `sources`, `route`, `debug`)을 변경하지 않는다.
- MySQL과 Chroma는 한 번 만든 동결 snapshot을 baseline과 candidate가 함께 사용한다.
- LLM 모델, judge, temperature, 동시성, 재시도 설정을 한 비교 안에서 고정한다.
- 개발셋은 반복 측정할 수 있지만 `final` split은 최종 후보에서 한 번만 연다.

## 역할 기반 Tool 계약

골든셋은 함수명 대신 역할을 기록한다. 함수명을 바꾸더라도 아래 매핑 한 곳만 갱신한다.

| capability | 현재 Tool |
|---|---|
| `hybrid_search` | `search_hybrid_vector_rag` |
| `structured_state` | `query_sql_state` |
| `overview` | `query_sql_state`의 `operation=overview` |

`attachment_evidence`는 Tool이 아니라 현재 요청에만 존재하는 입력 근거다.

## 문항별 검증

- `required_capabilities`: 반드시 사용해야 하는 Tool 역할
- `allowed_capabilities`: 사용해도 되는 Tool 역할. 이 밖의 호출은 실패
- `max_tool_rounds`: 허용 라운드 상한. `0`은 첨부만으로 답해야 함을 뜻함
- `expected_arguments`: 명시된 키만 정확히 비교하는 Tool 인자 계약
- `expected_history_mode`: trace의 실제 history 판별값
- `must_abstain`: 원문에 답이 없어 근거 부족을 밝혀야 하는지 여부
- `required_evidence_kinds`: 답변이 프로젝트 검색 또는 첨부 중 무엇을 근거로 해야 하는지

동일한 Tool 이름과 정규화된 인자를 반복 호출하면 실패한다. 실제 검색어는 원 질문을
포함해 최대 4개이고, 빈 문자열과 정규화 후 중복이 없어야 한다.

## 지표 적용 범위

- `context_precision`, `context_recall`: 프로젝트 검색 컨텍스트가 있는 문항만 RAGAS 평가
- `faithfulness`, `answer_correctness`, `response_relevancy`: 참조 답변이 있는 생성 문항만 RAGAS 평가
- 구조화 count/list, Tool 선택·인자, history, 검색어 상한, 첨부 0-Tool, 기권은
  결정론 검사로 평가
- 전체 문항에서 latency, Tool 라운드, Tool 호출 수, LLM 호출 수와 비용 대용치인
  입력·출력 token 수를 직접 집계

## 합격 기준

결정론 항목은 모두 통과해야 한다.

- HTTP 성공률 100%
- 필수 Tool 역할·명시 인자·history 판별 100%
- 중복 Tool 호출 0건, Tool 라운드 5회 초과 0건
- 첨부 전용 문항 Tool 호출 0회
- 기권 문항에서 근거 없는 사실 주장 0건
- `sources`가 골든 근거 출처 범위를 벗어난 문항 0건

RAGAS와 성능은 동일 문항의 baseline 대비 paired 차이로 비교한다.

- 개발셋 평균 `context_precision`은 baseline보다 최소 `0.03` 높아야 한다.
- `context_recall`, `faithfulness`, `answer_correctness`, `response_relevancy`는
  각각 `0.02` 넘게 하락하면 실패한다.
- 잠금 최종셋은 다섯 지표 모두 baseline 이상이어야 한다.
- semantic p95는 baseline 대비 10% 넘게 악화하면 실패한다.
- 평균 Tool 호출 수는 baseline 대비 `0.25`회 넘게 증가하면 실패한다.

평균만 게시하지 않고 문항별 점수, 평균·중앙값, 개선/동률/악화 문항 수를 함께 남긴다.
RAGAS 결과에 `NaN`이 하나라도 있으면 해당 실행은 무효다.

## 골든 작성 분리

- 질문·평가 계약 작성자와 골든 답변 작성자를 분리한다.
- 골든 작성자는 각 문항의 `source_scope`와 inline 첨부만 읽는다.
- 기존 QA 정답 JSON, 과거 평가 출력, 기존 수동 리뷰는 읽지 않는다.
- 골든 항목마다 참조 답변, 필수 사실, 금지 주장, 근거 파일과 근거 문장을 기록한다.
- `answer_correctness`는 골든 항목의 `reference_answer`를 기준으로 계산한다.
- 원문으로 확정할 수 없으면 추측하지 않고 `must_abstain`으로 표시한다.

## 실행 파이프라인

기존 160문항 실행기는 사용하지 않는다. `agentic_v2.pipeline`은 질문 실행을 한 번만
저장하고, 같은 결과를 계약 검사와 RAGAS 채점에 재사용한다. RAGAS 0.4.3의 Windows
의존성 때문에 Python 3.13을 명시한다.

각 코퍼스는 동결 state의 `<state-root>/<corpus>/manifest.json`, `chroma/`와 격리된
MySQL 스키마를 사용해 별도 프로세스로 실행한다.

```powershell
uv run --python 3.13 --group eval python -m evals.agentic_v2.pipeline run `
  --state-root evals/results/agentic_v2/state --corpus modu --split dev `
  --label baseline --output evals/results/agentic_v2/modu-baseline.json

uv run --python 3.13 --group eval python -m evals.agentic_v2.pipeline score `
  --input evals/results/agentic_v2/modu-baseline.json `
  --output evals/results/agentic_v2/modu-baseline-scored.json

uv run --python 3.13 --group eval python -m evals.agentic_v2.pipeline compare `
  --baseline evals/results/agentic_v2/modu-baseline-scored.json `
  --candidate evals/results/agentic_v2/modu-candidate-scored.json `
  --output evals/results/agentic_v2/modu-comparison.json
```

`run`은 실제 query 엔드포인트 함수와 동일한 입력 모델·첨부 변환·Agentic graph를
통과한다. 전체 검색 본문은 공개 API의 `debug`에 추가하지 않고 평가 요청의
`ContextVar`에서만 수집한다. `score` 실패 또는 `NaN`은 결과 파일을 게시하지 않으며,
`compare`는 모든 RAGAS 대상 문항의 채점이 끝나지 않으면 실행을 거부한다.
