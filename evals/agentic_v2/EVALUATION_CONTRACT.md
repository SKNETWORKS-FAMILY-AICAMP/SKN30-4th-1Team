# Agentic Q&A v2 평가 계약

## 목적

이 평가는 Agentic Q&A 변경 전후의 답변 품질, Tool 사용, 지연 시간을 같은 입력과
동결된 검색 상태에서 비교한다. 기존 160문항 평가와 `backend/test/golden/run_eval.py`의
내부 검색 재구성은 사용하지 않는다.

## 실행 경계

- `run`은 `POST /api/v1/projects/{project_id}/query`와 같은 요청 모델을
  `execute_project_query(project_id, body)` 서비스 경계에 전달한다. HTTP endpoint의
  access check와 rate limiter를 흉내 내거나 decorator를 unwrap하지 않는다.
- 외부 응답 계약(`answer`, `plan`, `sources`, `route`, `debug`)을 변경하지 않는다.
- MySQL과 Chroma는 한 번 만든 동결 snapshot을 baseline과 candidate가 함께 사용한다.
- LLM 모델, judge, temperature, 동시성, 재시도 설정을 한 비교 안에서 고정한다.
- 저장소에는 반복 측정용 `dev` 질문과 골든만 둔다.
- `final` 질문과 골든은 구현자에게 공개하지 않고 저장소 밖의 접근 통제된 위치에
  잠근다. 최종 후보와 구현이 동결된 뒤 독립 평가 담당자가 한 번만 실행한다.
- `final run`에는 저장소 밖의 `--questions`만, `final score`에는 같은
  `--questions`와 별도 `--golden`을 모두 명시해야 한다. 공개 dev 파일이나 저장소
  내부 파일로 final을 실행하거나 채점할 수 없다. 두 경로가 같은 파일, symlink 또는
  hard link를 가리키면 score를 거부한다.
- `run`은 골든을 인자로 받거나 읽지 않고 문항별 계약 통과 여부도 출력하지 않는다.
  질문, 실제 요청 입력, 실제 응답을 각각 SHA-256으로 봉인한다. `score`가 질문과
  골든을 처음 함께 읽고 봉인을 재검증한 뒤 결정론 계약과 RAGAS를 계산한다.
- 질문, 원시 record, 골든의 `id`는 각각 비어 있지 않은 고유 문자열이어야 한다.
  중복 ID를 dict의 마지막 항목으로 덮어쓰지 않고 실행·봉인 검증·채점 전에 거부한다.

## 역할 기반 Tool 계약

골든셋은 함수명 대신 역할을 기록한다. 함수명을 바꾸더라도 아래 매핑 한 곳만 갱신한다.

| capability | 현재 Tool |
|---|---|
| `hybrid_search` | `search_hybrid_vector_rag` |
| `structured_state` | `query_sql_state`의 `operation=list/count` |
| `overview` | `query_sql_state`의 `operation=overview` |

`attachment_evidence`는 Tool이 아니라 현재 요청에만 존재하는 입력 근거다.
역할 충족 여부는 Tool 이름만이 아니라 위 operation predicate까지 함께 비교한다.

## 문항별 검증

- `required_capabilities`: 반드시 사용해야 하는 Tool 역할
- `allowed_capabilities`: 사용해도 되는 Tool 역할. 이 밖의 호출은 실패
- `max_tool_rounds`: 허용 라운드 상한. 첨부가 있어도 첫 프로젝트 Tool 확인은
  생략하지 않으므로 실행 문항은 최소 1회 조회를 허용해야 함
- `expected_arguments`: capability 이름 아래에 명시된 키만 정확히 비교하는 Tool 인자
  계약. 둘 이상의 capability를 허용할 때 평면 인자 객체를 임의 역할에 결합하지 않는다.
- `expected_history_mode`: trace의 실제 history 판별값
- `must_abstain`: 원문에 답이 없어 근거 부족을 밝혀야 하는지 여부
- `required_evidence_kinds`: 답변이 프로젝트 검색 또는 첨부 중 무엇을 근거로 해야 하는지

동일한 Tool 이름과 서버 기본값을 채운 뒤 정규화한 인자를 반복 호출하면 실패한다.
canonicalization은 `backend.agentic_graph.QA_TOOLS`를 lazy import하고 각 Tool의
`tool_call_schema.model_validate(...).model_dump(...)`를 사용한다. evaluator에
기본값을 복사하지 않으며 request-level history 범위나 구조화 schema 밖 자연어 조건을
Tool 인자로 가정하지 않는다. 실제 검색어는 원 질문을 포함해 최대 4개이고, 빈 문자열과
정규화 후 중복이 없어야 한다.

`sources`는 basename으로 줄이지 않고 경로 구분자만 정규화한 전체 ID로 골든 범위와
정확히 비교한다. 근거를 요구하는 문항은 비어 있지 않은 실제 source가 모든 필수
source와 일치해야 한다. 프로젝트 근거는
`debug.evidence.project.has_substantive_evidence=true`, 양의
`model_context_count`, 비어 있지 않은 `source_ids`, 실제 `debug.model_contexts`가
함께 있어야 한다. 공개 응답의 `sources`가 스스로 프로젝트 근거를 증명할 수 없으며,
서버가 성공한 Tool artifact에서 별도로 모은 `source_ids`만 프로젝트 출처로 인정한다.
첨부 근거는 debug의 canonical
`source_location`이 요청 첨부의
`attachment:<request-local-name>` source와 일치하고
`extraction_status=ok`일 때만 인정한다. `empty`/`error`/`failed`는 근거가 아니다.
프로젝트와 첨부 source 집합은 각각 검증한 뒤 합치며 한 종류의 성공이 다른 종류의
누락 source를 대신할 수 없다.

답변 의미는 `run`에서 검사하지 않는다. `score`가 골든을 읽은 뒤 RAGAS와 같은
`--judge`에게 각 required/forbidden fact, exact count, required item, abstention
target을 전달하고 `affirmed`/`denied`/`absent`/`uncertain` 중 하나만 받는다.
count의 대체·상충 수치, item의 명시적 제외, 뒤집힌 기권처럼 언어별 substring으로
안전하게 판정할 수 없는 경우를 이 단계에서 의미적으로 분류한다. 결정론 계약 검사는
답변 문자열을 다시 읽지 않고 verdict 객체의 정확한 키·타입·target 순서·enum과
target별 허용 verdict만 비교한다. verdict에 자유 형식 rationale을 허용하지 않는다.

## 지표 적용 범위

- `context_precision`, `context_recall`: 프로젝트 검색 컨텍스트가 있는 문항만 RAGAS 평가
- `faithfulness`, `answer_correctness`, `response_relevancy`: 참조 답변이 있는 생성 문항만 RAGAS 평가
- 구조화 count/list, Tool 선택·인자, history, 검색어 상한, 첨부의 첫 프로젝트 Tool
  조회, 기권은
  결정론 검사로 평가
- 전체 문항에서 latency, Tool 라운드, Tool 호출 수, LLM 호출 수와 비용 대용치인
  입력·출력 token 수를 직접 집계

## 합격 기준

결정론 항목은 모두 통과해야 한다.

- HTTP 성공률 100%
- 필수 Tool 역할·명시 인자·history 판별 100%
- 중복 Tool 호출 0건, Tool 라운드 5회 초과 0건
- 첨부 문항의 첫 프로젝트 Tool 확인 누락 0건
- 기권 문항에서 근거 없는 사실 주장 0건
- `sources`가 골든 근거 출처 범위를 벗어난 문항 0건

RAGAS와 성능은 동일 문항의 baseline 대비 paired 차이로 비교한다.
baseline과 candidate는 완전히 채점된 동일한 비어 있지 않은 문항-지표 coverage를
가져야 하며 일부 지표의 교집합만으로 비교하지 않는다. 전체 비교에는 위 다섯 지표가
모두 한 번 이상 포함되어야 하고, 알 수 없는 지표·중복 지표·비수치·`NaN`은 거부한다.
또한 `questions_sha256`, `golden_sha256`, 동결 manifest, 실행 model·retry 설정,
judge·embedding·worker 설정과 문항별 질문/요청 hash가 동일해야 한다.

- 개발셋 평균 `context_precision`은 baseline보다 최소 `0.03` 높아야 한다.
- `context_recall`, `faithfulness`, `answer_correctness`, `response_relevancy`는
  각각 `0.02` 넘게 하락하면 실패한다.
- 잠금 최종셋은 다섯 지표 모두 baseline 이상이어야 한다.
- semantic p95는 baseline 대비 10% 넘게 악화하면 실패한다.
- 평균 Tool 호출 수는 baseline 대비 `0.25`회 넘게 증가하면 실패한다.

평균만 게시하지 않고 문항별 점수, 평균·중앙값, 개선/동률/악화 문항 수를 함께 남긴다.
RAGAS 결과에 `NaN`이 하나라도 있으면 해당 실행은 무효다.

## 골든 작성 분리와 잠금

- 질문·평가 계약 작성자와 골든 답변 작성자를 분리한다.
- 골든 작성자는 각 문항의 `source_scope`와 inline 첨부만 읽는다.
- 기존 QA 정답 JSON, 과거 평가 출력, 기존 수동 리뷰는 읽지 않는다.
- 골든 항목마다 참조 답변, 필수 사실, 금지 주장, 근거 파일과 근거 문장을 기록한다.
- `answer_correctness`는 골든 항목의 `reference_answer`를 기준으로 계산한다.
- 원문으로 확정할 수 없으면 추측하지 않고 `must_abstain`으로 표시한다.
- 공개 JSON의 자기 선언 필드는 작성자 분리나 독립성을 증명하지 못하므로 사용하지
  않는다. final의 작성자, 접근자, 봉인 시각과 1회 실행 기록은 저장소 밖의 감사
  기록으로 검증한다.
- final 질문·정답·고유 표현·예상 인자는 운영 프롬프트, Tool 설명, 정규식, 단위
  테스트와 회귀 테스트에 복사하지 않는다. final 실행 뒤에도 결과는 구현 튜닝에
  재사용하지 않고 다음 평가는 새 잠금셋으로 교체한다.

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

최종 평가 담당자는 저장소 밖 잠금 경로를 명시한다. 아래 경로는 형식 예시일 뿐이며
실제 잠금 파일 경로나 내용은 저장소와 개발자에게 공개하지 않는다.

```powershell
uv run --python 3.13 --group eval python -m evals.agentic_v2.pipeline run `
  --state-root evals/results/agentic_v2/state --corpus modu --split final `
  --questions X:\locked-eval\questions.json `
  --label candidate --output evals/results/agentic_v2/modu-final.json

uv run --python 3.13 --group eval python -m evals.agentic_v2.pipeline score `
  --input evals/results/agentic_v2/modu-final.json `
  --questions X:\locked-eval\questions.json `
  --golden X:\locked-eval\golden.json `
  --output evals/results/agentic_v2/modu-final-scored.json
```

`run`은 query endpoint와 동일한 입력 모델·텍스트 첨부 변환·Agentic graph를
`execute_project_query`로 통과한다. inline 첨부 builder는 텍스트 형식과
`content_text`만 허용한다. 평가 컨텍스트는 graph가 성공한 첨부와 Tool artifact
본문을 실행 순서대로 한 번 집계한 표준 `debug.model_contexts`만 사용한다. 첨부를
원본 질문에서 다시 더하거나 Tool 응답에서 제외된 프로젝트 메모리를 주입하지 않는다.
`score` 실패 또는 `NaN`은 결과 파일을 게시하지 않으며, `compare`는 모든 RAGAS 대상
문항의 채점이 끝나지 않으면 실행을 거부한다.
