# PR #28 Issue #17 정확성 오류 리뷰

- 작성일: 2026-07-30 (KST)
- 비교 기준: `origin/main` (`dd7dda9a62b52d5f11b720ee452edfa838e6e19e`)
- 리뷰 대상: PR #28 (`be5e3bff138008b3395f4d29819abab96ee143c5`)
- 리뷰 브랜치: `codex/review-pr28-on-main`
- 범위: Issue #17의 Tool·구조화 조회·첨부 근거·평가 계약
- 제외: 성능, p95, 비용, 호출 수 최적화, CI 환경
- 과적합 제거 상태: **완료** — 공개된 기존 final 8문항은 영구 폐기
- 판정: **정확성 오류 10건 수정 후 재검증 필요**

## 1. 요약

PR #28은 Tool 이름, 구조화 조회, 첨부 근거, 평가 파이프라인을 추가했지만 질문과 실제 조회 범위가 달라지는 경우를 차단하지 못하고, 일부 Tool 호출 및 첨부 검증을 누락할 수 있다. 또한 평가기가 실제 Tool 결과와 답변의 주장을 대조하지 않아 명백한 오답을 통과시키며, 과적합 제거 뒤에는 모델이 실제로 본 첨부 근거가 평가 context에서 빠지는 문제가 남아 있다.

아래 항목은 성능과 무관하게 사용자 답변의 사실성, 근거 경계 또는 평가 합격 판정을 직접 바꾸는 오류만 정리한 것이다.

| ID | 심각도 | 오류 |
| --- | --- | --- |
| COR-01 | P1 | 질문과 구조화 필터의 의미 불일치가 실행됨 |
| COR-02 | P1 | 중복 호출 하나가 같은 배치의 신규 호출까지 폐기함 |
| COR-03 | P1 | SQL count 0건의 원문 확인이 보장되지 않음 |
| COR-04 | P1 | 첨부 문자 예산 소진 후 파일 검증이 우회됨 |
| COR-05 | P1 | 유효 첨부가 프로젝트 Tool 실패를 가림 |
| COR-06 | P2 | 실패·빈 첨부가 출처가 되고 원문 위치가 유실됨 |
| COR-07 | P1 | 구조화·기권 평가기가 명백한 오답을 통과시킴 |
| COR-08 | P1 | 빈 출처와 무관한 출처가 근거 계약을 통과함 |
| COR-09 | P1 | 모델이 실제로 본 첨부 근거가 평가 context에서 누락됨 |
| COR-10 | P1 | critical count 계약에서 핵심 `text_query`를 검증하지 않음 |

## 2. 정확성 오류

### COR-01. 질문과 구조화 필터의 의미 불일치가 실행됨

#### 현재 상황

`backend/retriever/qa_tools.py:307-317`은 질문에 없는 `owner`와 일부 필터 조합만 거부한다. 질문이 명시한 `category`, 완료 상태, 마감 기간과 Tool 인자를 서로 대조하지 않는다. `category="all"`은 `backend/retriever/qa_tools.py:365`에서 DB의 `category=None`으로 변환된다.

#### 발생하는 오류

다음과 같이 질문과 다른 범위가 정상 조회로 실행된다.

- `김태호가 담당한 결정 목록을 보여줘` + `category="all"` → 결정뿐 아니라 전체 범위 조회
- `완료된 액션은 몇 개인가?` + `completion_status="open"` → 완료가 아닌 미완료 집계
- `7일 안에 마감인 액션 목록` + `due_within_days=30` → 요청 기간보다 넓은 조회

Tool artifact에 `requested_filters`와 `applied_filters`가 남더라도 잘못된 조회를 실행한 뒤이므로 답변의 정확성을 보장하지 못한다.

#### 어떻게 고칠지

1. `current_question`에서 명시적으로 요구한 category·owner·완료 상태·기간 조건을 결정적인 구조로 추출한다.
2. SQL 실행 전에 추출한 조건과 Tool 인자를 대조한다.
3. 명시 조건과 다른 인자는 `status="invalid_query"`로 거부하고 DB를 호출하지 않는다.
4. 동의 표현을 포함한 positive 사례와 category·status·기간 불일치 negative 사례를 각각 회귀 테스트에 추가한다.

### COR-02. 중복 호출 하나가 같은 배치의 신규 호출까지 폐기함

#### 현재 상황

`backend/agentic_graph.py:209-224`는 현재 응답의 Tool 호출 중 하나라도 과거 호출과 같거나 현재 배치 안에서 중복되면 라우트 전체를 `duplicate`로 보낸다. `backend/agentic_graph.py:173-188`의 처리기는 현재 배치의 모든 호출에 `duplicate_call`을 기록한다.

#### 발생하는 오류

첫 라운드에서 검색을 실행한 뒤, 다음 응답이 아래 두 호출을 함께 요청하면 신규 SQL도 실행되지 않는다.

1. 이전과 동일한 `search_hybrid_vector_rag`
2. 처음 요청한 `query_sql_state`

재현 시 SQL 호출 횟수는 0회이고 두 호출 모두 `duplicate_call`로 기록됐다. 필요한 새 근거를 얻지 못해 답변이 누락되거나 근거 부족 오류로 끝난다.

#### 어떻게 고칠지

1. 라우팅 전에 호출별 canonical key를 계산한다.
2. 과거 또는 현재 배치와 중복되는 호출만 `duplicate_call` ToolMessage로 해소한다.
3. 같은 배치의 고유 호출은 ToolNode로 계속 실행한다.
4. `중복 검색 + 신규 SQL`, `동일 배치 내부 중복 + 신규 호출` 조합을 회귀 테스트로 고정한다.

### COR-03. SQL count 0건의 원문 확인이 보장되지 않음

#### 현재 상황

`backend/retriever/qa_tools.py:415-432`는 집계 결과가 0건이어도 항상 `status="ok"`와 `{"count": 0}`을 반환한다. 0건이 실제 부재인지 구조화 추출 누락인지 확인하는 후속 검색은 프롬프트 선택에만 의존하며 런타임 계약으로 강제되지 않는다.

#### 발생하는 오류

구조화 저장소에 아직 추출되지 않았지만 원문에는 존재하는 항목도 `0건`으로 확정할 수 있다. 재현 시 빈 SQL rows가 `status="ok"`, `total_rows=0`으로 반환되고 그 상태만으로 최종 답변을 생성할 수 있었다.

#### 어떻게 고칠지

1. count 0건을 `empty` 또는 별도의 `needs_fallback` 상태로 구분한다.
2. 해당 상태에서는 동일 질문 범위의 `search_hybrid_vector_rag` 확인을 런타임 상태 머신이 요구하도록 한다.
3. 원문에서도 근거가 없을 때만 0건을 확정하고, 검색 실패 시에는 0건이 아니라 확인 불가로 답한다.
4. `구조화 0·원문 존재`, `둘 다 없음`, `원문 검색 실패` 세 경우를 분리해 테스트한다.

### COR-04. 첨부 문자 예산 소진 후 파일 검증이 우회됨

#### 현재 상황

`backend/api/query.py:106-108`은 남은 문자 예산이 없으면 즉시 `continue`한다. 파일 내용 검증인 `validate_document_bytes()`는 그 뒤인 `backend/api/query.py:110-119`에서 호출된다.

#### 발생하는 오류

첫 번째 정상 첨부가 전체 문자 예산을 채우면 두 번째 첨부는 확장자·base64·byte 크기까지만 확인되고 magic, 인코딩, 제어문자 검증을 받지 않는다. 재현에서는 두 파일 중 validator가 한 번만 호출됐으며, 단독 요청이라면 415가 될 손상 파일이 두 번째에 배치되면 요청이 통과했다. 해당 파일의 검증 결과와 provenance도 남지 않는다.

#### 어떻게 고칠지

1. 모든 첨부에 대해 크기와 `validate_document_bytes()` 검증을 먼저 완료한다.
2. 검증이 끝난 파일에만 변환·문자 예산을 적용한다.
3. 예산 때문에 본문을 넣지 못한 정상 파일도 `skipped_budget` 같은 안정적인 상태로 evidence ledger에 남긴다.
4. `정상 대용량 파일 + 손상 파일` 순서와 역순 모두 동일하게 415가 되는 테스트를 추가한다.

### COR-05. 유효 첨부가 프로젝트 Tool 실패를 가림

#### 현재 상황

`backend/agentic_graph.py:341`은 `has_attachment_evidence`만으로 `has_valid_evidence_result=True`를 시작한다. 이 값은 `backend/agentic_graph.py:400-403`의 최종 fail-closed 조건에 사용된다. 호출부도 `backend/agentic_graph.py:453-456`에서 정상 추출 첨부가 하나만 있으면 전체 첨부 근거를 유효하다고 본다.

#### 발생하는 오류

`첨부의 승인자와 프로젝트 배포일을 비교해줘` 같은 혼합 질문에서 첨부는 정상이고 프로젝트 검색은 예외가 발생해도 전체 요청이 성공한다. 재현에서는 `tool_results=["error"]`인 상태에서 모델이 프로젝트 날짜를 만들어 낸 정상 답변이 반환됐다. 첨부 근거는 프로젝트 영역의 실패를 보완할 수 없는데도 요청 전체의 유효 근거로 취급된다.

#### 어떻게 고칠지

1. 질문이 요구하는 근거 종류를 `attachment`, `project` 등으로 분리한다.
2. 근거 종류별 성공·empty·error 상태를 별도로 추적한다.
3. 혼합 질문에서 필수 프로젝트 Tool이 실패하면 해당 부분은 명시적으로 확인 불가 처리하고, 근거가 있는 첨부 부분만 부분 답변한다.
4. 최종 답변 검증에서 실패한 근거 영역에 대한 구체적 단정을 금지한다.

### COR-06. 실패·빈 첨부가 출처가 되고 원문 위치가 유실됨

#### 현재 상황

`backend/api/query.py:144-150`은 `source_location`에 basename만 기록한다. `backend/api/query.py:163-174`는 `extraction_status`와 관계없이 모든 evidence의 파일명을 공개 `sources`에 포함한다.

#### 발생하는 오류

텍스트 추출에 실패했거나 빈 첨부도 답변 근거 출처처럼 노출된다. 현재 테스트도 `failed` 첨부가 `sources`에 포함되는 동작을 기대한다(`tests/test_query_attachments.py:155-166`). 또한 같은 basename을 가진 여러 첨부를 구별할 수 없고 PDF page, heading, block 등 실제 인용 위치가 사라진다.

#### 어떻게 고칠지

1. 공개 `sources`에는 `extraction_status="ok"`이고 실제 사용된 내용이 있는 첨부만 넣는다.
2. `failed`, `empty`, `skipped` 상태는 디버그용 evidence ledger에만 보존한다.
3. 요청 범위의 고유 attachment ID와 converter가 제공하는 page·heading·block 위치를 `source_location`에 유지한다.
4. 동일 basename, 부분 추출, failed/empty 혼합 사례에서 공개 출처와 내부 provenance를 각각 검증한다.

### COR-07. 구조화·기권 평가기가 명백한 오답을 통과시킴

#### 현재 상황

`evals/agentic_v2/pipeline.py:218-237`은 다음과 같이 문자열 포함만 검사한다.

- count: 답변 속 숫자 목록에 골든 숫자가 하나라도 있는지 확인
- list: 필수 항목 문자열이 답변에 등장하는지 확인
- abstention: 기권 marker와 금지 문장 전체의 정확한 포함 여부 확인

실제 Tool artifact, 적용 필터, 문장의 긍정·부정 관계는 비교하지 않는다.

#### 발생하는 오류

다음 오답이 모두 합격한다.

- Tool count가 12인데 `도구를 2번 확인했습니다. 실제 집계는 12건입니다.`
- 필수 목록을 모두 쓴 뒤 각 항목에 `담당이 아니다`라고 명시
- `확인할 수 없습니다`라고 쓴 뒤 구체 날짜와 금액을 사실로 단정

즉 평가 통과가 실제 답변 정확성을 의미하지 않는 false-green이다.

#### 어떻게 고칠지

1. 구조화 답변은 성공한 Tool artifact의 `operation`, `applied_filters`, count/rows를 정본으로 삼아 최종 주장과 비교한다.
2. count는 답변의 최종 집계 주장 하나를 추출해 정확히 비교하고 주변의 다른 숫자를 허용하지 않는다.
3. list는 항목 존재뿐 아니라 포함·제외·부정의 극성을 검사한다.
4. abstention은 marker 존재 외에 근거 없는 날짜·금액·담당자·상태 단정이 없는지 구조적으로 검사한다.
5. 위 세 반례를 반드시 실패하는 evaluator 단위 테스트로 추가한다.

### COR-08. 빈 출처와 무관한 출처가 근거 계약을 통과함

#### 현재 상황

`evals/agentic_v2/pipeline.py:198-204`의 `source_boundary`는 `actual_sources <= expected_sources`만 확인하므로 빈 집합이 항상 통과한다. `evals/agentic_v2/pipeline.py:206-216`의 프로젝트 근거 판정은 `debug.tool_sources`가 비어 있지 않은지만 확인하며 Tool 성공 상태나 골든 출처와의 관계를 보지 않는다.

#### 발생하는 오류

`sources=[]`이면서 `tool_sources=["not-in-golden.md"]`인 결과도 source boundary와 required project evidence를 동시에 통과할 수 있다. 답변이 요구된 문서를 실제로 사용하지 않았어도 근거 계약 합격으로 기록된다.

#### 어떻게 고칠지

1. 출처가 필수인 문항은 실제 출처가 비어 있지 않아야 한다.
2. 성공한 evidence-bearing Tool의 artifact에서만 프로젝트 출처를 수집한다.
3. 문항 계약에 따라 필요한 출처의 포함 관계와 허용 범위를 함께 검사한다.
4. 공개 `sources`, Tool artifact sources, 평가 contexts가 같은 원천을 가리키는지 교차 검증한다.
5. 빈 출처, 무관한 출처, error Tool 출처를 각각 실패시키는 테스트를 추가한다.

### COR-09. 모델이 실제로 본 첨부 근거가 평가 context에서 누락됨

#### 현재 상황

과적합 제거 작업에서 평가 전용 project memory와 질문 JSON의 원본 첨부 `content_text` 주입은 삭제했다. 현재 `evals/agentic_v2/pipeline.py:366-376`은 검색 Tool이 캡처한 context만 평가 레코드에 넣는다. 반면 모델은 `backend/api/query.py:157-174`에서 렌더링한 첨부 context도 함께 받지만 이 값은 평가 ContextVar에 기록되지 않는다.

#### 발생하는 오류

평가기 context에 모델 미노출 자료가 들어가는 false-green은 제거됐지만, 첨부가 필요한 문항에서는 모델이 실제로 사용한 근거가 평가 context에서 빠진다. 따라서 attachment-and-search 문항의 context recall과 faithfulness가 실제 실행보다 낮거나 불안정하게 계산될 수 있고, 평가 레코드만으로 답변 근거 전체를 재현할 수 없다.

#### 어떻게 고칠지

1. API가 검증·변환·절단한 뒤 모델에 실제 전달한 렌더링 첨부 context를 같은 실행 ContextVar에 기록한다.
2. 질문 fixture의 원본 `content_text`는 다시 사용하지 않는다.
3. Tool context와 첨부 context에 각각 근거 종류와 source ID를 붙여 중복 없이 합친다.
4. `모델에 전달된 첨부 sentinel은 평가 context에도 있고, 잘려서 전달되지 않은 sentinel은 없어야 한다`는 회귀 테스트를 추가한다.
5. 평가 context, 공개 sources, Tool artifact를 동일 실행 trace에서 생성한다.

### COR-10. critical count 계약에서 핵심 `text_query`를 검증하지 않음

#### 현재 상황

`evals/agentic_v2/questions.json:71-87`의 `M-STR-01`은 `현재 기록된 critical 버그는 몇 건이야?`라고 묻지만 `expected_arguments`에는 `operation="count"`와 `category="issue"`만 있고 `text_query`가 없다.

#### 발생하는 오류

critical 범위가 아닌 전체 issue를 집계한 Tool 호출도 인자 계약을 통과한다. 전체 issue 수와 우연히 같은 숫자가 답변에 포함되거나 COR-07의 포함식 점검과 결합되면 잘못된 집계가 최종 합격으로 기록될 수 있다.

#### 어떻게 고칠지

1. 이 문항의 기대 인자에 질문 범위를 보존하는 `text_query="critical 버그"` 또는 동등한 명시적 심각도 필터를 추가한다.
2. evaluator가 `requested_filters`뿐 아니라 실제 `applied_filters`까지 같은 범위인지 확인한다.
3. `category="issue"`만 있는 전체 집계 호출을 명시적인 실패 반례로 추가한다.
4. 향후 구조화 문항은 질문의 대상 집합을 결정하는 모든 필터가 expected contract에 들어갔는지 dataset validation 단계에서 검사한다.

## 3. 수정 후 필수 회귀 시나리오

| 영역 | 최소 회귀 시나리오 | 기대 결과 |
| --- | --- | --- |
| 구조화 경계 | 결정 질문+all, 완료 질문+open, 7일 질문+30일 | DB 호출 전 `invalid_query` |
| 중복 처리 | 중복 검색+신규 SQL | 중복만 생략하고 SQL 실행 |
| 0건 처리 | SQL 0·원문 존재 / 둘 다 없음 / 검색 장애 | 각각 원문 답변 / 0건 / 확인 불가 |
| 첨부 검증 | 정상 대용량 첨부 뒤 손상 첨부 | 순서와 관계없이 415 |
| 혼합 근거 | 정상 첨부+프로젝트 Tool error | 프로젝트 부분 확인 불가 |
| 첨부 출처 | failed·empty·동일 basename | 공개 출처 제외, 내부 provenance 구분 |
| 답변 평가 | 잘못된 count·부정 list·기권 뒤 단정 | 모두 평가 실패 |
| 출처 평가 | 빈 출처·무관한 출처·error Tool | 모두 평가 실패 |
| 평가 context | 모델에 전달된 첨부 / 잘려서 미전달된 첨부 | 전자는 포함, 후자는 부재 |
| critical count | 전체 issue 집계 | 인자 계약 실패 |

## 4. 과적합 제거 결과와 독립 검증

과적합 제거는 이 브랜치에서 완료했다. 기존 final 8문항과 정답은 이미 PR 커밋 기록에 공개됐으므로 독립성을 복구할 수 없으며 영구 폐기한다. 저장소에는 반복 회귀용 dev 16문항만 남긴다.

### 4.1 완료한 제거 작업

- [x] System prompt와 Tool 설명에서 골든 질문의 정확한 문구와 라우팅 예시를 제거하고 일반 범위 규칙으로 교체했다.
- [x] 공개 history 문구 whitelist를 제거하고 `지시 표현` 또는 `시간 순서 + 변화·결정 의미` 조합으로 일반화했다.
- [x] 공개 문구를 복사한 테스트를 unseen paraphrase positive·negative와 산출물 조작 오탐 사례로 교체했다.
- [x] 평가 요청에서만 project memory를 추가하던 숨은 근거 분기를 제거했다.
- [x] 질문 JSON의 전처리 전 첨부 원문을 평가 context에 직접 넣던 분기를 제거했다.
- [x] 공개 final 질문 8개와 대응 골든 8개를 현재 `questions.json`, `golden.json`에서 삭제했다.
- [x] 검증할 수 없는 `independent_from_question_author: true` 자기 선언을 제거했다.
- [x] final 실행·채점은 저장소 밖의 외부 `--questions`, `--golden`을 명시하지 않으면 거부하도록 했다.

### 4.2 완료한 전수검사

- [x] `backend/`의 프롬프트·Tool 설명·정규식과 공개 질문의 정규화 문자열 조각을 대조했다.
- [x] 골든 참조 답변·필수 사실·근거 문장의 production 직접 포함 여부를 검사했다.
- [x] 기존 final ID, 질문 전문, 고유 정답 문장과 final 전용 테스트 값의 현재 작업 트리 잔존 여부를 검사했다.
- [x] `tests/test_agentic_no_golden_overfit.py`에 질문 문구와 정답 문장의 production 누출 방지 회귀를 추가했다.
- [x] 폐기 final 질문과 전용 fixture 값은 원문 대신 SHA-256 지문으로 다시 등장하지 못하게 검사한다.
- [x] 공개 데이터셋에 `split="final"` 문항이 다시 들어오지 못하도록 회귀를 추가했다.
- [x] 모델이 보지 않은 project memory와 원본 첨부가 평가 context에 들어가지 않는지 검증했다.

### 4.3 저장소 밖에서 필요한 독립 평가

- [ ] 구현 동결 뒤 별도 작성자가 운영 코드에 공개하지 않은 새 sealed holdout을 만든다.
- [ ] 최초 실행 전에 dataset hash, 작성자, 접근자, 봉인 시각과 실행 횟수를 기록한다.
- [ ] 최종 후보에서 한 번만 실행하고, 결과를 구현 튜닝에 재사용하지 않는다.
- [ ] 다음 최종 평가는 기존 문항을 재사용하지 않고 새 잠금셋으로 교체한다.

## 5. 완료 조건

다음 조건을 모두 만족해야 Issue #17의 정확성 수정이 완료된 것으로 본다.

1. COR-01~COR-10의 반례가 수정 전에는 실패하고 수정 후에는 통과하는 회귀 테스트로 고정된다.
2. 실제 모델이 받은 근거와 평가기가 채점한 근거가 byte 또는 안정적인 canonical form 기준으로 동일하다.
3. 실패·empty·부분 근거가 정상 성공 근거로 승격되지 않는다.
4. 질문의 구조화 범위와 실제 DB `applied_filters`가 일치한다.
5. 과적합 제거 전수검사가 통과하고, 새 sealed holdout의 독립 검증 기록이 저장소 밖에 남는다.
