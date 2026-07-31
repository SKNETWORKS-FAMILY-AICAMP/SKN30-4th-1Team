# Agentic 프롬프트 전환 후 레거시·자유도 감사

- 대상 브랜치: `feat/이동욱-프롬프트_수정`
- 기준 커밋: `34083dc7b5ca2302f78da190742ebe191a71d9b8`
- 적용 상태: 위 기준 커밋에 본 PR 정리 변경 적용
- 감사일: 2026-07-31
- 범위: 실제 HTTP 진입점, Agentic graph, Tool schema와 실행, 검색기, 세션 호환 경로, 평가 근거

## 결론

정본 API인 `/api/v1/projects/{id}/query`는 **Agentic 단일 답변 생성 경로**다.
`qa_engine.SYSTEM_QA`와 새 Agentic 프롬프트가 다시 합쳐지는 문제는 없다.

다만 다음은 정리가 필요하다.

1. deprecated 세션 API에서 사용자 입력이 `SystemMessage`로 승격된다.
2. Agent가 Tool 실패 후 올바르게 재시도해도 최종 수집기가 전체 요청을 실패시킨다.
3. Agent가 만든 동의어 검색어는 신규 근거를 입장시키지 못해 검색 자유도가 제한된다.
4. 구 답변 생성 체인과 no-op 환경변수 등 운영 미사용 코드는 이번 변경에서
   현재 트리에서 제거했다.
5. `routing_v2`는 위 경로들을 검증하지 않으므로 성능 동일·과적합 부재를 입증하지 못한다.

## 이번 변경 적용 결과

`archive/legacy_qa_v1/`은 비교·시연용 보존본이므로 수정하지 않았다. 그 밖의
정리 범위에는 다음을 적용했다.

| 항목 | 적용 결과 |
|---|---|
| 일반 `/query` history | 백엔드 최근 10개·데스크톱 최근 20개 제한을 제거하고 `gpt-4.1-mini` tokenizer 기준 4,000토큰 예산으로 일원화했다. 최신 메시지를 우선 보존하고 경계 메시지는 오래된 앞부분만 생략한다. |
| 구 QA 답변 프롬프트·체인 | 현재 트리에서 제거했다. 비교·시연은 `archive/legacy_qa_v1/`의 고정 커밋만 사용한다. |
| 내부 multi-query LLM fallback | 현재 검색기에서 제거했다. Agentic Tool이 전달한 검색어만 사용하고 direct 평가 호출은 원 질문 하나를 쓴다. |
| 구 수동 평가 runner | 현 엔진과 맞지 않고 deprecated된 `backend/test/rag_eval.py`, `rag_eval_langsmith.py`를 제거했다. |
| 현재 golden 평가 생성 | 구 프롬프트 대신 `ORCHESTRATOR_SYSTEM_PROMPT` 단독 adapter를 사용한다. |
| `PAIM_QUERY_ROUTING_MODE` | 읽기·경고·예시 설정·tracked 평가 runner 설정을 제거했다. |
| 첨부 호환 wrapper | 테스트를 실제 evidence/render 함수로 이관하고 `_prepare_attachment_context()`를 제거했다. |
| route 중복 대입 | API 계층의 중복 덮어쓰기를 제거했다. 응답 필드는 Agentic 결과가 계속 제공한다. |
| 세션·안전 정책 | 사용자 요청에 따라 `ContextBuilder`, rolling summary, Tool 재시도 fail-closed, 검색 admission gate, SQL 0건 치환은 변경하지 않았다. |

구조 회귀 검사는 production `qa_engine`에 `SYSTEM_QA`, `_get_chain()`,
`_generate_multi_queries()` 등이 다시 생기지 않는지 확인하고, backend 운영 모듈이
`evals`를 import하지 않는지도 확인한다.

## 실제 런타임 경로

| 구성 | 판정 | 근거 |
|---|---|---|
| `/api/v1/projects/{id}/query` | Agentic 단일 생성 | `backend/api/query.py:261-301` |
| `ORCHESTRATOR_SYSTEM_PROMPT` | 독립 프롬프트 | `backend/agentic_graph.py:36-113` |
| `qa_engine._build_context()` | 현재 운영 검색 핵심 | `backend/retriever/qa_tools.py:224-237` |
| 구 `SYSTEM_QA/_get_chain()` | 현재 트리에서 제거 | 비교본은 `archive/legacy_qa_v1/`의 고정 커밋으로만 실행 |
| `/sessions/{id}/query` | deprecated지만 mount된 실제 경로 | `backend/chat/router.py:392-402`, `backend/main.py:222` |
| `ContextBuilder` | deprecated 세션 경로에서 실제 실행 | `backend/chat/router.py:318-338` |

## 삭제 안전성 분류

“운영에서 낡아 보임”과 “지금 삭제해도 동작·성능이 같음”은 다르다.

| 후보 | 분류 | 이유 |
|---|---|---|
| `PAIM_QUERY_ROUTING_MODE` 읽기·경고와 `agentic` 설정 | 제거 완료 | 어떤 분기도 선택하지 않던 no-op이었다. |
| `OUTPUT_RESERVE`, 사용하지 않는 `last_summary_id` 바인딩 | 이번 변경 제외 | 세션 경로는 사용자 요청에 따라 별도 작업으로 남겼다. |
| `_prepare_attachment_context()` | 제거 완료 | 테스트를 실제 evidence/render 함수로 이관했다. |
| `SYSTEM_QA`, `_prompt`, `_chain`, `_get_chain()` | 제거 완료 | 비교·시연은 archive가 materialize하는 고정 Legacy 커밋이 담당한다. |
| `_generate_multi_queries()` fallback | 제거 완료 | Agentic Tool은 계속 명시적 `query_variants`를 전달하고 direct 호출은 원 질문만 쓴다. |
| 세션 router와 `ContextBuilder` | 사용 로그·호환 종료 후 제거 가능 | 현재 데스크톱은 쓰지 않지만 API 문서가 구형 클라이언트 호환 계약으로 명시하며 endpoint가 실제 mount돼 있다. |
| `plan: []` | 지금 제거 불가 | 저장소 내부 소비자는 없지만 공개 응답의 무모델 필드라 외부 소비 여부를 확인할 수 없다. |
| `route`, `sources`, `debug.router_stage` | 제거 금지 | `route`와 `sources`는 현재 frontend가 소비하고, debug 필드는 평가 계약이 사용한다. |
| `_build_context()`, 첫 Tool 강제, 라운드·중복 guard | 제거 금지 | 현재 Agentic 검색·안전 계약의 실제 실행 코드다. |
| 검색 admission gate, 오류 후 fail-closed, SQL 0건 치환 | A/B 후 변경 | dead code가 아니라 답변 결과를 바꾸는 정책이다. 삭제하면 좋아질 가능성도 있지만 안전성·정확도 회귀 가능성도 있어 “무손실 제거”로 분류할 수 없다. |

이번 변경은 위 표에서 운영 영향이 없거나 호출부를 함께 이관할 수 있는 항목만 처리했다.
동작 정책과 세션 경로는 그대로 남겼다.

## 발견 사항

### P1 — 세션 API에서 사용자 입력이 System 권한으로 승격된다

세션 요청은 클라이언트가 `rag_context`를 직접 보낼 수 있다.

- 입력 필드: `backend/chat/router.py:37-40`
- 클라이언트 문자열을 RAG 청크로 포장: `backend/chat/router.py:273-276`
- `ContextBuilder`가 서버 검색 결과라는 라벨과 `system` 역할을 부여:
  `backend/chat/context_builder.py:131-137`
- 어댑터와 Agentic 입력기가 이 역할을 보존:
  `backend/chat/router.py:84-119`, `backend/agentic_graph.py:377-389`

직접 probe 결과 메시지 순서는 아래와 같았다.

1. `SystemMessage`: Agentic 오케스트레이터 규칙
2. `SystemMessage`: 과거 대화 요약
3. `SystemMessage`: 클라이언트 `rag_context`
4. `HumanMessage`: 현재 질문

즉 비신뢰 사용자 문자열이 프로젝트 검색 결과처럼 보이고 system 우선순위를 얻는다.
과거 메시지도 실제 요약이 아니라 `role: text`를 이어 붙인 문자열인데
`SystemMessage`로 다시 들어간다(`backend/chat/router.py:359-377`).

이 경로는 deprecated지만 앱에 mount되어 있어 호출 가능하다. 선택지는 둘 중 하나다.

- 사용자가 없다면 세션 query endpoint와 `ContextBuilder`를 퇴역시킨다.
- 유지해야 한다면 `rag_context`와 rolling summary를 명시적인 비신뢰
  `HumanMessage` 블록으로 내리고 서버가 만든 근거와 구분한다.

### P1 — 성공적인 Tool 재시도도 최종적으로 503이 된다

ToolNode 오류 안내는 Agent에게 다른 도구로 재시도하라고 한다
(`backend/agentic_graph.py:285-290`).

하지만 최종 수집기는 과거 호출 중 하나라도 아래 상태가 있으면 이후 성공과 무관하게
`RuntimeError`를 발생시킨다.

- `error`
- `invalid_query`
- context 없는 `ok`

근거: `backend/agentic_graph.py:540-567`.

hybrid 검색이 한 번 `empty`였던 경우에도 이후 검색 또는 SQL이 정상 근거를 찾으면
오히려 전체 요청을 실패시킨다(`backend/agentic_graph.py:517-539,568-569`).
테스트도 이 동작을 계약으로 고정한다
(`tests/test_agentic_qa.py:509-555,627-660,769-803`).

이 안전장치는 복합 질문의 일부가 확인되지 않았는데 전체가 확인된 것처럼 답하는 일을
막는다. 그러나 현재 구현은 “질문 facet별 실패”와 “같은 facet의 성공적 재시도”를
구분하지 않는다. 동일 Tool·동일 인자 재시도도 중복 호출로 막힌다
(`backend/agentic_graph.py:188-208`).

권장 방향은 실패 이력을 전역 boolean으로 보지 않고, 요청 facet 또는 canonical Tool
호출별로 추적하는 것이다. 같은 범위의 정상 재시도가 성공했다면 복구를 허용하고,
끝까지 실패한 facet만 답변에서 미확인으로 표시해야 한다.

### P2 — Agent가 만든 동의어 검색어가 신규 근거를 찾지 못한다

Agent는 `query`와 `alternate_queries`를 생성한다. 하지만 근거가 검색 후보로 들어오려면
사용자 질문 또는 첫 서버 질문과 canonical token이 하나 이상 겹쳐야 한다.

- 입장 토큰 결정: `backend/retriever/qa_engine.py:237-251`
- MySQL 사전 필터: `backend/retriever/qa_engine.py:807-811`
- Chroma 사전 필터: `backend/retriever/qa_engine.py:895-900`
- Agent 검색어 전달: `backend/retriever/qa_tools.py:221-237`

따라서 `배포 일정`을 Agent가 `릴리스 날짜`로 잘 바꿔도 저장 근거가 원 질문과
표면 토큰을 공유하지 않으면 검색 전에 탈락할 수 있다. Agent 검색어는 이미 입장한
후보의 순위만 바꿀 수 있다.

이 코드는 모델이 멋대로 넓힌 검색어로 무관한 근거를 가져오는 일을 막는 안전장치다.
바로 제거하면 안 된다. 숨겨진 프로젝트에서 아래 두 지표를 함께 비교해야 한다.

- scope 위반·오인용률
- 동의어·간접 표현 context recall

### P2 — 확정적인 SQL 0건 답변도 일반적인 “확인되지 않음”으로 치환된다

`query_sql_state(count)`는 정확히 0건이면 `empty` 상태를 반환한다
(`backend/retriever/qa_tools.py:483-502`).
수집기는 이를 실질 근거로 인정하지 않고 모델이 작성한 `0건` 답변을
`프로젝트 기록에서 확인되지 않습니다.`로 교체한다
(`backend/agentic_graph.py:494-514,523-524,575-579`).

전체 운영 DB의 부재로 확대하지 않는 것은 맞지만, 질문 범위가 명확한 구조화 집계라면
`현재 프로젝트의 활성 risk 기록은 0건입니다`처럼 도구 범위를 붙여 정확히 답할 수 있다.
현재 동작은 안전성보다 정보 손실이 크다.

### P2 — 세션 rolling summary는 최신 내용을 버리고 중복 예산 계산을 한다

세션은 오래된 메시지를 요약하지 않고 기존 summary 뒤에 계속 붙인다
(`backend/chat/router.py:367-377`).
`ContextBuilder`는 2,000토큰을 넘으면 항상 문자열 앞부분만 남긴다
(`backend/chat/context_builder.py:49-61`).

probe에서는 2,115토큰 summary가 2,000토큰으로 잘렸고 문자열 끝의
`최신핵심결론`이 사라졌다. DB 문자열과 복호화·토큰화 작업은 계속 커지지만 모델은
오래된 앞부분만 반복해서 보게 된다.

또한 현재 질문을 recent message에 넣고 별도 질문 토큰으로 한 번 더 계산한다
(`backend/chat/router.py:270-291`). `ContextBuilder`가 다시 질문을 고정 예산과
recent message로 계산한 뒤, 어댑터가 중복 질문을 제거한다
(`backend/chat/context_builder.py:30-44,92-104,139-140`,
`backend/chat/router.py:94-119`).

`OUTPUT_RESERVE`와 `last_summary_id`도 현재 계산에 쓰이지 않는다
(`backend/chat/router.py:257,281-283`).

### P2 — 일반 history의 고정 10개 제한 — 해결

Agentic 일반 경로는 retrieval 모듈의 `MAX_HISTORY=10`을 직접 참조한다.

- 상수: `backend/retriever/qa_engine.py:35`
- 사용: `backend/agentic_graph.py:391-398`
- 요청 문자열 크기 제한 없음: `backend/api/query.py:36-39`

짧은 메시지 11개에서는 필요한 첫 메시지가 잘리고, 매우 긴 메시지 10개는 그대로
전달되던 문제였다. 이번 변경에서 Agentic 소유의 4,000토큰 예산으로 옮겼다.
짧은 메시지는 10개를 넘어도 예산 안에서 모두 보존하고, 매우 긴 경계 메시지는
오래된 앞부분을 생략하고 최신 끝부분을 남긴다. 데스크톱의 별도 20개 선행 절단도
제거해 백엔드 토큰 예산을 단일 기준으로 삼았다. 세션용 `prepared_context`는 변경하지
않았다. 사용자가 붙여 넣은 `<|endoftext|>` 같은 모델 특수 토큰 표기도 일반 텍스트로
계산해 입력 오류를 내지 않는다.

### P3 — 운영에 쓰이지 않는 레거시와 no-op 설정 — 해결

다음 코드는 정본 Agentic 요청에서 실행되지 않는다.

- `qa_engine.SYSTEM_QA`
- `_prompt`, `_chain`, `_get_chain()`
- `_generate_multi_queries()`의 LLM 경로

삭제 전 `_get_chain()` 호출부는 deprecated 수동 평가 runner 둘과
`backend/test/golden/run_eval.py`뿐이었다.
운영 Tool은 항상 `query_variants`를 넘기므로 내부 multi-query LLM 생성도 타지 않는다
(`backend/retriever/qa_tools.py:224-237`,
`backend/retriever/qa_engine.py:788-795`).

이 코드는 온라인 지연을 만들지는 않았지만 실제 Agentic 평가와 구 평가를 혼동시켰다.
이번 변경에서 현재 트리에서는 제거했다. Legacy 재현은
`archive/legacy_qa_v1/`이 고정 커밋을 별도 worktree로 materialize해 담당한다.

추가 잔존물:

- `PAIM_QUERY_ROUTING_MODE`: `legacy`도 무시하고 경고만 남기는 no-op
  (`backend/api/query.py:79-85`)
- `_prepare_attachment_context()`: 운영 호출은 없고 테스트 호환 wrapper
  (`backend/api/query.py:256-258`)
- API가 Agentic 결과의 `route`, `router_stage`를 다시 같은 값으로 덮음
  (`backend/api/query.py:293-297`)
- 응답의 `plan: []`: 소비자가 확인되지 않은 구 응답 계약
  (`backend/agentic_graph.py:627-635`)

앞의 세 잔존물은 이번 변경에서 제거했다. `plan: []`는 외부 응답 호환 가능성이 있어
유지했다.

## 의도된 제약이라 유지할 항목

아래는 자유도를 줄이지만 레거시로 보고 바로 제거할 항목은 아니다.

- 첫 프로젝트 Tool 호출 강제: `backend/agentic_graph.py:252-267`
- Tool 최대 5라운드: `backend/agentic_graph.py:259-262`
- 동일 호출 중복 차단: `backend/agentic_graph.py:188-208`
- `include_history=true`를 번복·대체 이력 질문에만 사용
- attachment를 프로젝트 검색 결과와 별도 근거로 표시

첫 Tool 강제는 attachment-only 질문에도 호출 비용과 장애 의존성을 추가한다.
중복 차단은 transient 오류 후 동일 호출 재시도도 막는다. 따라서 삭제가 아니라
오류 상태를 인지하는 예외 규칙과 별도 평가가 필요하다.

`qa_engine._build_context()`는 이름 때문에 레거시처럼 보이지만 현재
`search_hybrid_vector_rag`의 핵심 검색 구현이다. 제거 대상이 아니다.

## 성능·과적합 판정

### 입증된 것

두 커밋의 실제 문자열을 AST로 추출하고 `gpt-4.1-mini` tokenizer로 재측정했다.

| 커밋 | 문자 | 토큰 |
|---|---:|---:|
| `69d0b4f` | 4,334 | 2,338 |
| `34083dc` | 2,672 | 1,445 |

고정 system 입력은 **893토큰, 38.2% 감소**했다. 이 프롬프트는 각 모델 호출의
메시지에 포함되므로 고정 입력 비용이 줄어드는 구조는 확실하다.

새 프롬프트에 CS-Bot·Modu의 프로젝트명, 인명, 정답 숫자를 직접 하드코딩한 흔적은 없다.

### 입증되지 않은 것

프롬프트 변경 전후의 동일 상태 paired 실행이 없으므로 실제 latency, 총 토큰 비용,
정답 품질이 동일하거나 좋아졌다고 말할 수 없다.

정리 전 현재 브랜치 실행 결과:

- API 40/40
- Tool 계약 40/40
- 엄격 golden: PASS 24 / PARTIAL 14 / FAIL 2
- 현재 DB 상태를 반영한 진단: PASS 26 / PARTIAL 14 / FAIL 0
- 평균 4.22초, p95 9.96초

정리 적용 후 같은 40문항을 다시 실행한 결과:

- API 40/40
- Tool 계약 40/40
- 엄격 golden: PASS 23 / PARTIAL 15 / FAIL 2
- 현재 DB 상태를 반영한 진단: PASS 25 / PARTIAL 15 / FAIL 0
- 평균 4.62초, p95 8.20초

판정 변화는 `V2-SEM-01` 한 건의 PASS→PARTIAL뿐이다. 새 답변도 두 필수 사실을
모두 포함하고 모순이 없지만, judge가 검색 오류·프롬프트 미흡 등 기록에 있는 추가
원인까지 설명해 “핵심 원인에 덜 집중했다”는 이유로 PARTIAL을 부여했다. 이번 변경은
빈 history인 이 데이터셋의 검색·프롬프트·Tool 실행을 바꾸지 않으므로, 이 한 건은
모델·judge 실행 변동으로 보는 것이 타당하다.

두 실행 모두 현재 브랜치 한쪽만 측정한 값이다. legacy baseline보다 빠르거나
정확하다는 증거는 아니다.

### `routing_v2`의 일반화 한계

- 두 기존 코퍼스만 사용: CS-Bot 21, Modu 19
- history 문항 0
- attachment 문항 0
- 둘 이상의 필수 capability를 요구하는 문항 0
- 실제 실행 40건 모두 Tool 1라운드
- Tool 오류 후 복구 문항 0
- prompt injection 문항 0
- 프롬프트와 질문·golden이 같은 커밋에 함께 추가됨

따라서 이 데이터셋은 기본 Tool 역할 선택 회귀에는 유용하지만, 과적합 부재,
새 프로젝트 일반화, 다중 Tool 계획, 오류 복구, `include_history`, attachment 안전성을
검증하지 못한다.

golden 자체도 현재 DB와 다음 수치가 달랐다.

- `csbot.risk`: golden 2, 현재 3
- `modu.issue`: golden 18, 현재 19
- `modu.risk`: golden 6, 현재 7

또한 일부 overview 기준은 최신 원문과 시점이 맞지 않는다.

- golden은 re-ranking 도입 여부를 미결로 보지만 6/23 원문은 정식 도입 결정을 기록한다.
- golden은 Modu 알림 지연을 진행 중 과제로 보지만 5/15 원문은 8초에서 1초 이내로
  개선됐다고 기록한다.

현재 결과 확인:

- `evals/routing_v2/CURRENT_BRANCH_REPORT.html`
- `evals/routing_v2/CURRENT_BRANCH_REPORT.md`
- `evals/routing_v2/results/current_scored.json`

## 권장 정리 순서

1. deprecated 세션 query의 실제 사용자를 확인하고, 미사용이면 endpoint와
   `ContextBuilder`를 제거한다.
2. 유지한다면 `rag_context`와 rolling summary의 `SystemMessage` 승격부터 막는다.
3. Tool 결과를 facet별로 추적해 성공한 재시도는 살리고, 미확인 facet만 제한한다.
4. 정확한 SQL count=0을 범위가 붙은 0건 답변으로 허용한다.
5. query admission gate는 hidden 동의어 세트로 안전성/recall A/B 후 조정한다.
6. ~~history의 10개 제한을 Agentic 소유 토큰 예산으로 교체한다.~~ 완료
7. ~~구 `SYSTEM_QA/_get_chain()`과 deprecated runner, no-op 설정을 제거하고
   현재 golden runner를 Agentic 프롬프트로 이관한다.~~ 완료
8. `routing_v2` golden을 동결 DB snapshot에 맞춰 고치고 history·attachment·다중 Tool·
   오류 복구·인젝션 holdout을 별도로 만든다.

## 검증

실행:

```text
.venv/bin/python -m pytest -q \
  tests/test_agentic_qa.py \
  tests/test_agentic_history.py \
  tests/test_semantic_retrieval.py \
  tests/test_qa_citation.py \
  tests/test_qa_supersede_context.py \
  tests/test_query_attachments.py \
  tests/test_document_capabilities.py \
  tests/test_agentic_architecture_boundaries.py \
  tests/test_agentic_eval_v2_dataset.py \
  tests/test_agentic_eval_v2_pipeline.py \
  tests/test_frontend_contract.py \
  tests/test_local_chat_policy.py

209 passed, 8 warnings
```

warning은 `google.generativeai` 패키지 지원 종료 안내이며 이번 Agentic 프롬프트 변경과
직접 관련은 없다.

감사는 코드 호출부, 테스트, 현재 평가 산출물, 직접 메시지·summary probe를 대조했다.
운영 변경은 위 표의 history 예산과 검증된 dead/no-op 제거 범위에 한정했다.
