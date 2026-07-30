# PR #28 코드 단독 전수검사 보고서

- 기준 브랜치: `origin/main`
- 검사 브랜치: `codex/review-pr28-on-main`
- 검사 기준: `origin/main...HEAD`의 추적 코드와 그 호출 경로
- 검사일: 2026-07-30
- 결론: **현재 상태로는 병합 보류**

## 1. 검사 원칙

이번 검사는 구현 코드만 보고 다시 수행했다.

- 질문셋, 골든셋, 정답 fixture, 기존 리뷰 문서는 열거나 실행하지 않았다.
- `backend/test/golden/`, 평가 JSON, 기존 리뷰 문서 및 작업 중 생긴 untracked 평가 파일·디렉터리는 검사 입력에서 제외했다.
- 재현은 코드에서 독립적으로 만든 `Alpha`, `Beta`, 임의 파일명과 임의 문장만 사용했다.
- 성능, 호출 비용, 지연 시간 개선은 이번 판정에서 제외했다.
- `critical`이라는 제품·평가 스키마는 검사한 구현 코드에 없다. 이 문서의 우선순위 표시는 리뷰 정렬용일 뿐 새 스키마를 제안하지 않는다.

검사 범위는 다음과 같다.

- 운영 경로: `backend/agentic_graph.py`, `backend/api/query.py`
- 검색 경로: `backend/retriever/history_intent.py`, `qa_engine.py`, `qa_tools.py`, `mysql_search.py`
- 평가 경로: `evals/agentic_v2/pipeline.py`
- PR에서 추가·수정한 관련 테스트 코드

## 2. 요약

코드만 보아도 제거 또는 재설계가 필요한 과적합·하드코딩 경로가 확인됐다.

1. 평가 `run`이 실행 전에 골든을 직접 읽고 같은 프로세스에서 문항별 정오 피드백을 낸다.
2. 이력 판정은 고정 문구 목록, 정규식, 8·12·16자 창에 의존한다.
3. 자연어 범위와 상태 판정에 고정 한국어 화이트리스트가 사용된다.
4. 정답 검사는 숫자·문구가 “포함됐는지”만 검사하여 명시적으로 틀린 답도 통과한다.
5. 골든 유출 방지 테스트 자체가 골든 파일, 고정 길이 조각, 알려진 해시에 결합돼 있다.
6. 시스템 프롬프트에 특정 SDK/OAuth 역할 사례가 직접 들어가 있다.

또한 성능과 무관한 확정 오류를 운영 경로 17건, 평가 경로 7건으로 분류했다. 최우선 수정 대상은 혼합 Tool 호출 유실, 근거 없는 답변 허용, 첨부 검증 우회, 구조화 필터 오적용, 평가기의 오합격이다.

## 3. 과적합·하드코딩·정규식 전수검사

### OH-01 — 실행기와 채점기가 분리되지 않음

- 위치: `evals/agentic_v2/pipeline.py:324-335`, `409-415`, `695-710`
- 현재 상황: `run_questions()`가 질문 파일과 골든 파일을 함께 읽고, 각 응답 직후 `score_contract()`를 실행해 문항별 통과 여부를 출력한다. `run` 명령 자체에 `--golden` 인자가 있다.
- 발생 오류: 실행 코드를 반복할 때마다 정답 기반 피드백을 즉시 얻을 수 있다. 최종 평가도 코드 수정과 피드백 반복에 노출되므로 블라인드 평가가 아니다.
- 수정 방향: `run`은 질문과 원시 응답만 다루고 골든을 전혀 받지 않게 한다. 원시 결과를 불변 파일로 확정한 뒤, 별도 권한·별도 프로세스의 `score`만 잠긴 골든을 읽게 한다.
- 판정: **최우선 제거 대상**

### OH-02 — “외부 경로”를 “잠긴 최종셋”으로 간주

- 위치: `evals/agentic_v2/pipeline.py:43-80`
- 현재 상황: 저장소 바깥 경로인지 여부만 확인한다.
- 발생 오류: 외부 경로의 파일도 구현자가 읽고 수정하고 반복 실행할 수 있다. 해시 고정, 접근 기록, 실행 횟수 제한, 결과 봉인 중 어느 것도 없다.
- 수정 방향: 평가 입력 해시와 실행 산출물 해시를 기록하고, 읽기 권한을 실행기와 채점기로 분리하며, 최종셋 실행은 1회성 ledger로 통제한다. 문항별 정오 피드백은 최종 실행에서 반환하지 않는다.
- 판정: **최우선 제거 대상**

### OH-03 — 이력 의도를 정규식 문구 패치로 판정

- 위치: `backend/retriever/history_intent.py:13-83`
- 현재 상황: 9개 이력 정규식, 직접 지시 정규식, 순서·상태 정규식, 3개 제거 정규식과 `{0,8}`, `{0,12}`, `{0,16}` 길이 창을 사용한다. 주석도 특정 회차와 `R-005`~`R-008` 실패에 맞춘 패치임을 드러낸다.
- 발생 오류:
  - 일반 문장이 이력 질문으로 오인되어 무관한 과거 질문과 supersede 체인이 섞인다.
  - 표현이 조금 달라지면 실제 후속 질문을 놓친다.
  - `\w*` 제거가 정상 주제어 전체를 지워 프로젝트 전역 이력으로 넓힌다.
- 코드 단독 재현:
  - `마지막 보고서에서 도입한 API를 보여줘` → 이력·지시 질문으로 오인
  - `배포 일정이 결정된 이유는?` → 조사의 `이`를 지시어 `이 결정`으로 오인
  - `출시 이후 API가 변경됐나요?` → 자체 시간 기준이 있는데도 이전 질문을 결합
  - `그 방안은 왜 폐기했어?` → 후속 질문을 놓침
  - `그 뒤에는?`, `그 이후 변경된 내용은?` → 명시적 후속 질문을 놓침
  - `이건우가 왜 바꿨어?` → 이름의 `이건`을 지시어로 오인
  - `변경관리 왜 바뀌었어?` → `변경관리` 주제가 제거됨
- 수정 방향: 정규식으로 최종 판정을 내리지 않는다. 대화 참조 여부, 시간 범위, 주제 토큰을 구조화된 intent 결과로 추출하고, 불확실하면 현재 질문만 검색한 뒤 필요한 경우 보조 이력 검색을 병합한다. 문구별 예외 추가 방식은 중단한다.
- 판정: **과적합 및 확정 오류**

### OH-04 — 자연어 범위를 고정 화이트리스트로 변환

- 위치: `backend/retriever/qa_tools.py:32`, `57-69`
- 현재 상황: `전체`, `모든`, `프로젝트`, `기록`, `항목`, `메모리` 여섯 단어만 전체 범위로 인정한다.
- 발생 오류: 조사, 구두점, 동의어, 복합어가 붙으면 동일한 의미가 `text_query`의 SQL `LIKE` 조건으로 바뀐다. 반대로 화이트리스트에 우연히 포함된 표현은 검색 대상이 사라진다.
- 수정 방향: 자연어를 SQL 필터로 직접 바꾸지 않는다. count/list Tool은 스키마가 제공하는 구조화 필드만 받고, 그 밖의 대상 표현은 원문 검색으로 보낸다.
- 판정: **하드코딩 및 확정 오류**

### OH-05 — 평가 정답을 문자열 포함 여부로 판정

- 위치: `evals/agentic_v2/pipeline.py:40`, `218-237`
- 현재 상황: 네 개의 한국어 기권 문구, 숫자 추출 정규식, 필수 항목 substring 검사로 정답을 판정한다.
- 발생 오류:
  - `7건은 아니고 실제로는 2건`이 기대값 7을 통과한다.
  - `Alpha는 포함되지 않는다`가 필수 항목 Alpha를 통과한다.
  - `근거가 없다는 설명은 틀렸고 담당자는 Beta다`가 기권 답변을 통과한다.
- 수정 방향: 운영 응답과 별도로 구조화 결과를 반환해 `count`, `items`, `abstained`, `claims`, `evidence_ids`를 타입 단위로 검사한다. 자연어만 검사해야 한다면 부정·대조·주장 단위를 파싱하고 상충 숫자가 있으면 실패시킨다.
- 판정: **하드코딩 및 평가 오합격**

### OH-06 — 시스템 프롬프트의 특정 도메인 사례

- 위치: `backend/agentic_graph.py:68-69`
- 현재 상황: 앱 SDK 담당과 백엔드 OAuth 지원 담당을 구분하라는 구체 사례가 운영 시스템 프롬프트에 직접 들어 있다.
- 발생 오류: 스키마나 일반 안전 규칙과 무관한 특정 업무 조합이 모델의 답변 선택에 특별한 가중치를 준다.
- 수정 방향: “질문 대상과 보조 작업의 역할 경계를 섞지 않는다”처럼 일반 규칙으로 바꾸고 특정 업무명·역할명은 제거한다.
- 판정: **과적합 의심이 충분한 하드코딩**

### OH-07 — 과적합 방지 테스트가 알려진 데이터에 다시 결합됨

- 위치: `tests/test_agentic_no_golden_overfit.py:15-31`, `65-110`, `142-181`
- 현재 상황: 테스트가 질문·골든 파일을 직접 읽고, 12자 조각과 고정 해시를 블랙리스트로 검사한다. 첫 검사는 운영 파일 네 개만 보며 `backend/api/query.py`도 빠져 있다.
- 발생 오류: 알려진 문구의 변형, 문자열 분할, 누락된 모듈의 복사는 통과한다. 동시에 테스트 자체가 평가 데이터에 계속 의존한다.
- 수정 방향: 이 테스트는 삭제한다. 대신 구조적 규칙을 검사한다. 예: 운영 모듈이 평가 패키지를 import하지 않는지, `run`이 골든 경로를 받지 않는지, 최종 결과가 채점 전 불변 저장되는지 검사한다.
- 판정: **삭제 대상**

### OH-08 — 평가 전용 상태가 운영 검색 코드에 삽입됨

- 위치: `backend/retriever/qa_tools.py:34-54`, `222`, `352`
- 현재 상황: 평가용 `ContextVar`와 수집 함수가 운영 Tool 구현 안에 있다.
- 발생 오류: 현재 답변 결과를 바꾸는 직접 증거는 없지만, 평가기가 운영 구현을 끌어당기며 특정 평가 방식에 맞춘 분기가 추가될 수 있는 결합점이다. 실제로 구조화 Tool과 첨부는 수집에서 빠져 평가도 불완전하다.
- 수정 방향: 운영 ToolMessage의 표준 artifact에 모델이 본 근거를 기록하고, 평가기는 저장된 실행 trace만 소비한다. 함수명과 상태에서 평가 전용 개념을 제거한다.
- 판정: **평가 결합 하드코딩**

### OH-09 — 기존 자연어 category 키워드 사전

- 위치: `backend/retriever/qa_engine.py:155-176`
- 현재 상황: 결정·액션·이슈·리스크를 고정 한국어 substring 사전으로 분류한다.
- 발생 오류: 부정 표현, 동음 substring, 새 표현에서 잘못된 category로 좁히거나 범위를 놓칠 수 있다.
- 수정 방향: 이 분류는 결과 누락을 일으키지 않는 soft hint로만 사용하고, 부정·복수 category·불확실성 시 필터를 적용하지 않는다. 장기적으로 구조화 intent로 대체한다.
- 판정: **기존 하드코딩 위험**. PR #28에서 새로 만든 핵심 결함과는 분리한다.

### 정상 상수로 분류한 항목

다음은 값이 코드에 있더라도 정답 과적합으로 보지 않는다.

- `decision/action/issue/risk`, `open/completed/unknown` 등 DB 스키마 enum
- Tool 이름과 Tool 결과 status enum
- 첨부 파일 크기, 출처 개수, Tool 최대 라운드 같은 안전 상한
- API 호환을 위한 `semantic` route enum

이 값들은 특정 질문의 답을 선택하지 않고 입력·출력 계약과 자원 경계를 정의한다.

## 4. 운영 코드 오류

| ID | 우선 | 위치 | 현재 상황 | 발생 오류 | 수정 방향 |
|---|---|---|---|---|---|
| R-01 | 최상 | `backend/agentic_graph.py:173-188`, `209-224`, `253-270`, `400-403` | 한 batch의 호출 중 하나라도 중복이면 전체 batch를 `duplicate_tools`로 보낸다. | 중복 검색 A와 신규 SQL B가 함께 오면 B도 `duplicate_call`로 표시되고 실행되지 않은 채 강제 종료된다. 첫 라운드에 같은 호출 두 개가 나오면 둘 다 실행되지 않아 유효 근거 0건으로 503까지 이어진다. | 호출을 canonical key별로 분할해 중복 호출에만 가짜 ToolMessage를 만들고 신규 호출은 정상 실행한다. 신규 호출이 하나라도 있으면 duplicate-only 종료 경로를 타지 않는다. |
| R-02 | 높음 | `backend/agentic_graph.py:131-151`; `evals/agentic_v2/pipeline.py:152-164` | 중복 비교가 전달된 JSON 인자의 정확한 shape만 비교한다. | 기본값이 생략된 호출과 같은 기본값을 명시한 호출이 서로 다른 호출로 취급된다. 운영 중복 방지와 평가 검사가 모두 우회된다. | Tool 스키마로 먼저 validate하여 기본값을 채운 뒤 canonicalize한다. Tool별 의미 정규화를 한 함수로 운영·평가가 공유한다. |
| R-03 | 최상 | `backend/retriever/qa_tools.py:415-432`; `backend/agentic_graph.py:379-403` | 구조화 count가 0이어도 `status="ok"`이며, 원문 재검색은 프롬프트 지시뿐이다. | 모델이 원문 Tool을 호출하지 않고 0건 또는 부재를 확정해도 서버가 성공 응답으로 받아들인다. | 0건을 `empty`/`needs_fallback`으로 표시하고, 그래프가 원문 검색 성공 전 부재 단정을 허용하지 않게 상태 전이를 강제한다. |
| R-04 | 최상 | `backend/agentic_graph.py:30-33`, `379-403`; `backend/retriever/qa_tools.py:441-450` | `empty`를 유효 근거 상태로 인정하고 최종 답변의 주장과 근거 관계는 검사하지 않는다. | 빈 검색 뒤 `Alpha는 확실히 활성화됐다` 같은 양의 주장이 그대로 200 응답이 된다. | `empty`는 조회 성공과 증거 존재를 분리해 기록한다. 모든 결과가 비었으면 기권/범위 설명만 허용하는 결정적 final guard를 둔다. |
| R-05 | 최상 | `backend/agentic_graph.py:203-205`, `453-472` | 추출 성공 첨부가 하나라도 있으면 첫 Tool 강제가 풀리고 첨부 전체가 유효 근거로 간주된다. | 질문과 무관한 첨부가 있어도 프로젝트 사실을 Tool 없이 답할 수 있다. | 질문이 요구한 근거 domain과 첨부 관련성을 추적한다. 프로젝트 기록 사실은 관련 프로젝트 Tool 성공 없이는 확정하지 못하게 한다. |
| R-06 | 최상 | `backend/agentic_graph.py:341`, `367-401`, `453-491` | 첨부가 유효 근거 flag를 선점한 뒤 프로젝트 Tool이 `error`여도 요청 전체는 유효하다. | 무관한 첨부 하나가 프로젝트 조회 실패를 가리고 모델의 프로젝트 사실 주장을 성공 처리한다. | 첨부 근거와 프로젝트 근거의 성공 상태를 분리하고 질문별 필수 근거 domain이 성공했는지 검사한다. |
| R-07 | 최상 | `backend/api/query.py:106-114` | 문자 budget이 소진되면 `validate_document_bytes()`보다 먼저 `continue`한다. | 뒤쪽 첨부는 MIME, magic byte, 인코딩, 제어문자 검증을 모두 건너뛴다. 잘못된 PDF도 요청에 수용된다. | 모든 첨부를 먼저 decode·byte limit·content validation하고, 검증 완료 후 별도 pass에서 변환과 문자 budget을 적용한다. |
| R-08 | 높음 | `backend/api/query.py:73-76`, `138-152` | 잘림 결과가 `text[:limit] + marker`다. | 반환 문자열이 설정 limit보다 marker만큼 길고, `used_chars`도 total limit을 초과한다. 이 초과가 R-07을 더 쉽게 만든다. | marker 길이를 budget 안에 예약하거나 marker를 metadata로 분리한다. 최종 렌더 문자열에도 독립 hard limit을 검사한다. |
| R-09 | 높음 | `backend/api/query.py:121-174`; `backend/agentic_graph.py:475-491` | `failed`·`empty` 첨부에도 placeholder를 넣고 모든 파일명을 public source와 debug attachment로 노출한다. | 실제 근거가 없는 파일이 답변 출처처럼 표시되고 평가에서도 첨부 근거로 인정된다. | 실제 비어 있지 않은 `ok` 첨부만 model evidence와 public source에 넣는다. 실패 파일은 별도 diagnostics에만 둔다. |
| R-10 | 보통 | `backend/api/query.py:87-108`, `144-174` | budget 이후 파일은 기록 없이 사라지고, 파일명은 basename만 사용한다. | 사용자는 제출된 첨부가 무시됐는지 알 수 없다. 서로 다른 경로의 같은 basename은 출처가 합쳐져 식별할 수 없다. | 각 첨부에 stable request-local ID와 `used/skipped_budget/failed` 상태를 남기고, source ID와 표시 이름을 분리한다. |
| R-11 | 최상 | `backend/retriever/qa_tools.py:296-317` | owner만 현재 질문의 대소문자 구분 substring으로 확인하고 나머지 필터는 질문 의미와 대조하지 않는다. | `Beta가 아닌 사람`에도 owner=Beta가 통과한다. 모델이 질문에 없던 완료 상태·기한을 임의로 넣어도 적용된다. 반대로 `그 사람의 작업` 같은 정상 후속 질문은 거절된다. | current+bounded history에서 구조화된 scope를 먼저 해석한다. 필터마다 긍정/부정/명시 여부를 검증하고 불일치하면 원문 검색으로 돌린다. |
| R-12 | 최상 | `backend/retriever/qa_tools.py:310-313`, `365-408`; `backend/retriever/mysql_search.py:76-98` | action 전용 상태·마감 필터에 `category="all"`을 허용하고 DB에는 category=None을 전달한다. | `completion_status="unknown"` count에 decision/issue/risk의 unknown 행까지 섞여 action 수가 부풀려진다. | 상태·마감 필터가 있으면 category를 action으로 강제하거나, action 이외 category를 명시적으로 거부한다. |
| R-13 | 높음 | `backend/retriever/qa_tools.py:57-69`, `386-408`; `backend/retriever/mysql_search.py:82-86` | count의 자연어 `text_query`를 content/topic/reason의 literal SQL `LIKE`로 사용한다. | 스키마에 없는 속성의 “정확한 구조화 count”처럼 보이지만 단순 문자열 포함 수다. 표현 차이로 누락되며 정확한 개수 계약을 보장하지 못한다. | 구조화 count는 스키마 필드만 허용한다. 비구조화 대상의 개수는 RAG 검색 결과임을 명시하고 정확 count로 평가하지 않는다. |
| R-14 | 높음 | `backend/retriever/qa_tools.py:390-407`; `backend/retriever/mysql_search.py:87-98` | DB는 `due_within_days`를 365로 clamp하지만 artifact에는 원래 값이 남는다. `overdue`와 미래 due 범위, completed와 overdue 같은 충돌도 허용된다. | 실제 SQL과 `applied_filters`가 달라지고, 모순 조건은 항상 0건을 만들어 잘못된 부재 답변으로 이어진다. | Tool 경계에서 한 번만 canonicalize한 값을 SQL과 trace 모두 사용하고, 모순 조합은 `invalid_query`로 거부한다. |
| R-15 | 높음 | `backend/retriever/qa_tools.py:173-190` | 검증된 `include_history=False` 대신 raw Tool JSON을 다시 읽어 `bool(raw_value)`를 적용한다. | raw 값이 문자열 `"false"`이면 Python에서 True가 되어 명시적 현재 상태 조회가 이력 조회로 뒤집힌다. | 검증된 함수 인자만 사용한다. 최초에 결정된 history mode는 graph state에 저장하고 이후 호출에서 raw JSON을 다시 해석하지 않는다. |
| R-16 | 최상 | `backend/retriever/history_intent.py:13-106`; `backend/retriever/qa_tools.py:167-201` | 정규식 결과가 검색 scope와 이전 질문 결합을 직접 결정한다. | 오탐은 무관한 이전 질문을 붙이고, 미탐은 필요한 supersede 체인을 빼며, trigger strip 과잉은 특정 주제를 프로젝트 전역으로 넓힌다. | OH-03의 구조화 intent 전환을 적용하고, 오탐 시에도 현재 질문 검색 결과가 사라지지 않게 두 검색 범위를 분리한다. |
| R-17 | 높음 | `backend/retriever/qa_engine.py:741-748`, `891-905` | 모델 컨텍스트에는 repo-aware source label을 쓰지만 public `sources`에는 원래 basename만 넣는다. | 서로 다른 저장소의 같은 파일명이 응답에서 충돌하고 사용자가 실제 근거를 식별할 수 없다. | 모델 표시, debug, public response가 동일한 canonical source ID를 사용하게 하고 표시 label은 별도 필드로 둔다. |

## 5. 평가 코드 오류

| ID | 우선 | 위치 | 현재 상황 | 발생 오류 | 수정 방향 |
|---|---|---|---|---|---|
| E-01 | 최상 | `evals/agentic_v2/pipeline.py:350-386`; `backend/api/query.py:191-192`; `backend/rate_limit.py:17`, `26-28` | 평가기가 rate-limit decorator가 붙은 API 함수를 직접 호출하고 모든 요청을 `user:dev-anonymous` key로 보낸다. | 기본 30회/분에서 빠른 31번째 호출이 `RateLimitExceeded`가 되고 일반 예외 500으로 기록된다. retry도 quota를 더 소비한다. | endpoint decorator 밖의 순수 query service를 분리해 평가기가 호출한다. 평가에서 limiter를 우회한다면 범위를 명시적으로 격리하고 원상 복구한다. |
| E-02 | 최상 | `backend/retriever/qa_tools.py:34-54`, `222`, `344-352`, `415-462`; `evals/agentic_v2/pipeline.py:366-407`, `482-505` | hybrid 검색과 overview만 context를 capture한다. 구조화 count/list와 첨부 본문은 빠져 있다. | 구조화·첨부 전용 답변은 실제 근거를 사용했는데도 context가 비어 RAGAS가 중단된다. 혼합 답변은 일부 근거가 누락돼 잘못된 faithfulness가 나온다. | 모델이 본 모든 ToolMessage와 성공 첨부 본문을 실행 순서대로 표준 trace에 저장하고 평가기는 그 trace만 사용한다. |
| E-03 | 최상 | `evals/agentic_v2/pipeline.py:115-117`, `198-215` | source는 basename만 비교하고 `actual_sources <= expected_sources`만 검사한다. attachment는 debug에 파일명만 있으면 근거로 본다. | 실제 source가 빈 집합이어도 통과한다. 다른 경로의 같은 파일, 변환 실패 첨부도 통과한다. | expected/actual canonical source ID를 완전 비교하고 필수 evidence 종류마다 최소 1개의 성공 evidence ID를 요구한다. 실패·empty 첨부는 제외한다. |
| E-04 | 최상 | `evals/agentic_v2/pipeline.py:218-237` | 숫자 존재, substring 존재, 네 개 기권 문구 존재만 검사한다. | 부정문, 정정문, 상충 숫자, 기권 문구 뒤의 근거 없는 주장까지 오합격한다. | OH-05와 같이 구조화된 answer contract를 검사하고, 자연어 검사는 부정·상충·주장 단위까지 확인한다. |
| E-05 | 높음 | `evals/agentic_v2/pipeline.py:28-32`, `125-174` | overview와 structured_state가 모두 Tool 이름 `query_sql_state` 하나로 축약된다. `expected_arguments` 대상은 `next(iter(required_tools))`로 고른다. | overview 요구가 count 호출로도 통과한다. 여러 필수 Tool에서는 hash seed에 따라 다른 Tool에 expected args를 대조해 결과가 비결정적이다. | capability를 `(tool, operation, argument predicate)`로 정의하고 expected arguments를 Tool별로 명시한다. set iteration으로 대상을 고르지 않는다. |
| E-06 | 높음 | `evals/agentic_v2/pipeline.py:583-598`, `609-657` | baseline과 candidate의 metric set 동일성을 확인하지 않고 교집합만 비교한다. 빈 `ragas`에 `all()`을 적용한다. | 두 실행에 공통 metric이 하나도 없어도 `ragas_passed=True`가 된다. | 문항별 metric set의 완전 동일성을 먼저 요구하고, 비교 가능한 metric이 0개면 명시적으로 실패시킨다. |
| E-07 | 보통 | `evals/agentic_v2/pipeline.py:290-302` | inline `content_text`를 확장자와 무관하게 UTF-8 raw bytes로 만든다. | PDF/DOCX 파일명을 사용하면 실제 형식이 아닌 바이트가 되어 첨부 변환 경로를 정상적으로 검증하지 못한다. | text inline 첨부는 text 확장자로 제한한다. binary 형식은 유효한 fixture builder로 실제 최소 문서를 생성하거나 별도 test asset을 사용한다. |

## 6. 독립 재현 결과

아래 결과는 질문·골든 파일을 읽지 않고 fake model, fake DB와 임의 입력으로 직접 실행한 결과다.

| 재현 | 관찰 결과 |
|---|---|
| 이전 search A 후 `[중복 search A, 신규 SQL B]` | SQL B 실행 횟수 0, 두 호출 모두 `duplicate_call` |
| 첫 라운드에 같은 Tool 호출 두 개 | 둘 다 미실행, `no valid evidence` 예외가 API 503으로 변환됨 |
| 구조화 count 0 후 모델이 바로 답변 | 사용 Tool은 SQL 하나뿐이고 원문 검색 실행 횟수 0 |
| 빈 검색 뒤 `Alpha는 확실히 활성화됐다` | `status="empty"`인데 최종 답변이 성공 수용됨 |
| 질문과 무관한 정상 첨부 + 프로젝트 사실 답변 | Tool 0회인데 답변 성공 |
| 정상 첨부 + 프로젝트 Tool error | 첨부 flag가 error를 가리고 답변 성공 |
| 첫 첨부가 문자 한도 소진 + 잘못된 두 번째 PDF | 두 번째 파일 content validation이 호출되지 않음 |
| 질문은 action, Tool category는 decision | `status="ok"`로 필터 적용 |
| `due_within_days=1000` | 실제 SQL은 365일, trace는 1000일 |
| self-contained 시간 표현과 후속 표현 | 이력 오탐·미탐 및 주제 삭제 재현 |
| 명시적으로 틀린 count/list/abstain 답변 | `score_contract(...).passed == True` |
| baseline/candidate metric이 서로 불일치 | 공통 metric 0개인데 `ragas_passed == True` |
| 여러 필수 Tool의 `expected_arguments` | `PYTHONHASHSEED`에 따라 검사 대상 Tool이 달라짐 |

## 7. 수정 순서

1. **평가 격리**: `run`에서 골든과 계약 채점을 제거하고 raw-run → locked-score를 분리한다. `tests/test_agentic_no_golden_overfit.py`의 데이터 블랙리스트 방식은 폐기한다.
2. **근거 불변식**: 프로젝트·첨부 근거 domain을 분리하고, empty/error/0건에 대한 서버 측 final guard를 만든다.
3. **Tool 실행 정확성**: 혼합 duplicate batch를 분할하고, Tool 인자를 schema-default까지 적용한 뒤 canonicalize한다.
4. **첨부 경계**: 모든 파일 선검증, hard character budget, 성공 evidence와 diagnostics 분리, source ID 도입을 함께 수정한다.
5. **구조화 조회**: action 전용 필터, 모순 필터, 질문 scope 대조, trace canonicalization을 Tool 경계에서 처리한다.
6. **이력 판정**: 정규식 문구 추가를 중단하고 구조화 intent + 불확실성 시 dual retrieval로 교체한다.
7. **평가 오합격 제거**: source identity, operation-aware capability, 구조화 답 계약, 동일 metric coverage를 강제한다.

## 8. 병합 판정

성능 개선을 제외해도 현재 브랜치는 병합 조건을 충족하지 않는다.

- OH-01~OH-07은 평가 과적합 방지 목표와 직접 충돌한다.
- R-01, R-03~R-07, R-11~R-12, R-16은 실제 답변의 근거·범위·입력 안전성을 깨뜨린다.
- E-01~E-06은 실패한 구현을 통과시키거나 정상 구현을 실패시키므로 평가 결과를 신뢰할 수 없게 한다.

위 최우선 항목을 수정한 뒤에도 같은 질문·골든을 재사용한 튜닝으로 확인하지 말고, 코드 불변식 테스트와 새 블라인드 입력으로 검증해야 한다.
