# PR #18 독립 리뷰 보고서

- 작성일: 2026-07-29 (KST)
- 비교 기준: `main` (`9ca7d63e712e17364f4acde1a83abfb386a37a3d`)
- 리뷰 대상: PR #18 (`315f5768945d305c48ab7434da529de9e2ebd739`)
- 안정화 브랜치: `integration/pr18-stabilized-20260729`
- 현재 안정화 기준: `74ace2520da9ab4863def34272f34fe82952ea58` (#14 선택 이식 포함)
- 상태: **High 3건 및 MVP 이력 게이트 수정 완료, live E2E 대기**

> 아래 본문은 최초 독립 리뷰에서 발견한 위험과 근거를 보존한다. 현재 반영 상태는 바로 아래의 `안정화 결과`를 정본으로 본다.

## 0. 안정화 결과

| 최초 위험 | 처리 결과 |
| --- | --- |
| H-01 Tool 장애가 성공 답변으로 위장 | Tool 예외 전파, artifact/status 검증, 유효 근거 없는 최종 답변 거부로 fail-closed 처리 |
| H-02 첨부와 Agentic 근거 규칙 충돌 | 첨부를 저장하지 않는 비신뢰 임시 근거로 분리하고, 첨부·프로젝트 출처 예산을 독립 보존 |
| H-03 provider/model 불명확 | Agentic Q&A를 공식 OpenAI endpoint + `gpt-4.1-mini`로 고정하고 키·모델·endpoint 계약 검증 추가 |
| M-01 후속 이력 질문 미연결 | 결정적 이력 감지 결과와 직전 사용자 주제를 `search_project_evidence`의 실제 검색어에 연결 |
| #14 프롬프트 경계 | 범위·대상 보존, 비신뢰 검색 문맥, 제한된 부재 단정, 허위 citation 방지 규칙을 선택 이식 |

검증 결과는 핵심 회귀 `123 passed, 1 skipped`이다. skip은 실제 OpenAI 키가 필요한 opt-in live smoke이며, 현재 합의에 따라 API 키를 주입하지 않았다. 따라서 코드·mock 계약 검증은 완료됐지만 실제 OpenAI/MySQL/Chroma E2E와 성능 기준선 수집은 아직 남아 있다.

## 1. 요약

PR #18의 구조적 방향은 타당하다. 이 PR은 기존 LangGraph 기반 레거시 검색 경로를 운영 코드에서 제거하고, Tool Calling 방식의 Agentic LangGraph를 프로젝트 Q&A의 단일 실행 경로로 만드는 작업이다. 레거시 구현은 운영 fallback이 아니라 전후 비교를 위한 실행 가능한 기준선으로 `archive/legacy_qa_v1`에 분리한다.

독립 리뷰 결과 Critical 리스크는 발견되지 않았으나, 병합 전에 해결해야 할 High 리스크 3건이 확인되었다.

1. 검색 Tool 장애가 정상 성공으로 처리되어 근거 없는 답변이 반환될 수 있다.
2. 첨부 및 세션 RAG가 Agentic의 근거 사용 규칙과 충돌한다.
3. Tool Calling을 지원하지 않는 provider 또는 모델에서 Q&A 전체가 503으로 실패한다.

OpenAPI 공개 계약, 문서·메모리 라우터 분리, 인증·인가 순서, production import 경계는 보존됐다. 임시 `main + #18` 병합 트리의 비-DB 회귀 테스트 934개와 archive의 legacy/current 테스트가 모두 통과했다. 따라서 #18은 폐기 대상이 아니라, 아래 High 리스크를 수정한 뒤 통합 기준으로 사용할 후보이다.

저장소의 MVP 및 평가 로드맵을 함께 대조하면, 단위 테스트 통과만으로는 #18의 MVP 준비 상태를 판정할 수 없다. 평가 로드맵의 최우선 항목인 이력 질문은 #18 기준으로 다시 검증해야 한다. 7월 22일의 `AGENTIC_TOOL_ROUTING` 및 route-balanced 결과는 #18의 직접 기준선이 아니라, 현재 평가에서 다시 확인할 실패 유형을 고르는 참고 자료로만 사용한다. 이 기준에 따라 M-01은 코드 심각도는 Medium이지만 **MVP 병합 게이트**로 분류한다.

## 2. PR 의도와 리뷰 판정 기준

### 2.1 의도된 변경

- 기존 `backend/graph.py` 중심의 레거시 Q&A 실행 경로 제거
- Tool Calling 기반 `backend/agentic_graph.py`를 프로젝트 Q&A 단일 실행 경로로 사용
- 레거시 라우터, intent classifier, 검색 helper를 운영 코드에서 분리
- 과거 구현을 `archive/legacy_qa_v1`에 고정하여 비교 기준선으로 보존
- 문서 업로드와 Project Memory 책임을 도메인 모듈로 분리

다음 항목은 의도된 변경이므로 결함으로 판정하지 않았다.

- `PAIM_QUERY_ROUTING_MODE=legacy`가 운영 fallback으로 동작하지 않는 것
- 삭제된 레거시 모듈이 production runtime에서 import되지 않는 것
- 레거시 구현이 archive에서만 실행되는 것

### 2.2 리뷰에서 확인한 핵심 질문

- Tool Calling 단일 경로가 기존 공개 API와 DTO 계약을 보존하는가?
- 검색 실패와 근거 부재가 정상 답변으로 오인되지 않는가?
- 첨부, 세션 문맥, 후속 질문이 새 Agentic 경로에서 보존되는가?
- 지원한다고 선언한 provider와 모델이 필수 Tool Calling 계약을 만족하는가?
- 레거시 archive가 의도한 비교 기준을 재현할 수 있는가?

## 3. MVP 로드맵 반영

### 3.1 참고한 정본과 과거 평가

MVP 범위와 현재 평가 원칙은 다음 문서를 정본으로 사용했다.

- [PRODUCTION_ROADMAP.md](PRODUCTION_ROADMAP.md)
- [EVALUATION_ROADMAP.md](EVALUATION_ROADMAP.md)
- [HANDOVER.md](HANDOVER.md)

다음 7월 22일 평가 문서는 #18의 성능 근거나 직접 회귀 기준선으로 사용하지 않았다. 당시의 실험용 Agentic 경로·프롬프트·tool contract에서 발견된 질문 유형과 실패 모드만 참고했다.

- [AGENTIC_TOOL_ROUTING_SYSTEM_EVAL_20260722.md](AGENTIC_TOOL_ROUTING_SYSTEM_EVAL_20260722.md)
- [AGENTIC_ROUTE_BALANCED_EVAL_20260722.md](AGENTIC_ROUTE_BALANCED_EVAL_20260722.md)
- [PAIM_USER_REALISTIC_160_EVAL_20260722.md](PAIM_USER_REALISTIC_160_EVAL_20260722.md)

### 3.2 로드맵 해석

Production Roadmap의 이번 사이클 핵심은 AWS 배포, 인증·공유, supersede이며 멀티모달과 “결정 리서처” 형태의 신규 에이전트 기능은 후속으로 분리돼 있다. PR #18의 Agentic Q&A는 로드맵 §4의 웹 검색 기반 결정 리서처와 동일한 신규 기능은 아니며, 기존 프로젝트 Q&A의 내부 실행 경로를 Tool Calling으로 교체하는 작업이다.

따라서 #18 자체를 무조건 MVP 밖으로 볼 필요는 없다. 다만 MVP 안정화 단계에서 큰 내부 경로 교체를 수용하려면 다음 조건이 필요하다.

- 기존 supersede·최신 결정·프로젝트 격리 동작을 회귀시키지 않는다.
- 근거 부족과 검색 장애를 정상 답변으로 위장하지 않는다.
- 이력 질문, 구조화 목록·개수, overview를 #18 contract에 맞는 평가로 다시 검증한다.
- MVP provider 범위를 명확히 고정하고 그 범위만 필수 검증한다.
- 신규 기능 확장보다 기존 공개 Q&A 계약과 데모 시나리오 보존을 우선한다.

### 3.3 평가 로드맵과 과거 실패 유형

#### 평가 로드맵

평가 로드맵의 1순위는 history intent 감지 recall 개선이다. 기준선은 E2 end-to-end 이력 감지 `0/5`, oracle 검색 체인은 `1.000`으로 기록돼 있다. 즉 검색 체인 자체보다 실제 질문을 올바른 이력 문맥으로 연결하는 것이 이미 알려진 핵심 병목이다.

로드맵은 다음도 완료 조건으로 요구한다.

- 실제 supersede와 비-supersede 대조군을 함께 평가한다.
- 최신 상태 질문에서 폐기된 결정을 현재 결정처럼 답하지 않는다.
- 근거가 부족하면 추측하지 않고 불확실성을 밝힌다.
- 구조화 조회는 라우팅, 필터, SQL 결과, 필수/금지 답변 요소를 각각 판정한다.
- overview는 최신 결정, 필수 진행·리스크, stale 결정 배제를 확인한다.
- 개선은 대상 회귀 테스트와 전체 평가를 모두 통과해야 채택한다.

#### 과거 Agentic route-balanced 40문항—#18 직접 기준선 아님

아래 수치는 7월 22일 당시 구조에서 생성된 역사적 결과다. #18은 7월 29일에 Agentic을 운영 단일 경로로 바꾸고 첨부·세션 문맥 전달을 추가했다. 기존 평가 runner도 #18에서 제거되는 `PAIM_QUERY_ROUTING_MODE=agentic` 실험 설정을 남겨 두고 있다. 따라서 데이터셋·기대 tool·판정 로직을 #18 contract에 맞게 점검하지 않고는 수치를 전후 비교에 쓰면 안 된다.

| 지표 | 기존 결과 |
| --- | ---: |
| API 성공 | 40/40 |
| 도구 선택 | 37/40 (92.5%) |
| 도구 인자 | 35/40 (87.5%) |
| 엄격 PASS | 33/40 (82.5%) |
| Mixed-tool 도구 선택 | 6/8 (75.0%) |
| Overview 엄격 판정 | PASS 5 / PARTIAL 2 / FAIL 1 |

#### 과거 실제 사용자형 160문항—#18 직접 기준선 아님

| 지표 | 기존 결과 |
| --- | ---: |
| API 성공 | 160/160 (100.0%) |
| 엄격 PASS | 103/160 (64.4%) |
| 기대 도구 정확 일치 | 137/160 (85.6%) |
| 구조화 인자 전체 일치 | 37/50 (74.0%) |
| 전체 목록 완전성 | 15/30 (50.0%) |
| Overview 엄격 PASS | 0/20 (0%) |

이 결과는 #18의 현재 정확도를 설명하지 않는다. 다만 overview 최신성, 전체 목록 상한, owner·상태 인자, 시점 합성, mixed-tool 질문을 #18용 평가에 포함해야 할 이유는 보여 준다. 과거 절대 점수나 저하 수치를 #18의 병합 판정에 직접 적용하지 않는다.

초기 Agentic 평가에서 발견된 `category` 누락 P0는 #18이 상속한 현재 `query_structured_memory` contract에서 category를 필수 enum으로 제한하고 있다. 다만 이 제약은 #18에서 새로 추가된 것이 아니며, 독립적으로 #18의 실제 답변 품질이 개선됐음을 증명하지도 않는다.

### 3.4 MVP 기준 재분류

| 리스크 | 코드 심각도 | MVP 처리 |
| --- | --- | --- |
| H-01 검색 실패 성공 위장 | High | **병합 차단** — 근거 신뢰성과 fail-closed 원칙 위반 |
| H-02 첨부·세션 RAG 근거 충돌 | High | 첨부 또는 세션 RAG가 MVP에 포함되면 **병합 차단** |
| H-03 provider Tool capability | High | MVP provider를 1~2개로 고정해 검증하면 범위 축소 가능. 전체 provider matrix는 후속 가능 |
| M-01 후속 이력 질문 단절 | Medium | **MVP 병합 게이트** — 평가 로드맵 1순위 및 데모의 변경 이력 질문과 직접 연결 |
| M-02 `rag_context` SystemMessage | Medium | 서버 세션 API가 MVP에서 사용되면 수정. #13 local-only 전환 후 미사용이면 후속 가능 |
| M-03 출처 누락 | Medium | 첨부가 MVP이면 수정. 첨부 제외 시 후속 가능하나 citation 회귀는 별도 확인 |
| M-04 실제 비교 재현 부족 | Medium | 런타임 병합 차단은 아님. 발표에서 전후 개선 수치를 주장하려면 평가 artifact 게이트 |
| M-05 shallow clone archive 실패 | Medium | 로컬 full clone 비교만 요구하면 후속 가능. CI 재현이 요구되면 수정 |

### 3.5 MVP 권장 게이트

최소 안전 범위는 다음과 같다.

1. H-01을 수정한다.
2. 실제 MVP에서 사용할 provider/model을 고정하고 Tool Calling을 검증한다.
3. M-01을 runtime에 연결하고 supersede 5문항 + 비-supersede 5문항을 재실행한다.
4. MVP에 첨부·세션 RAG를 포함할지 결정한 뒤 H-02, M-02, M-03의 차단 여부를 확정한다.
5. 기존 route-balanced 문항을 재사용하려면 먼저 데이터셋·기대 tool·runner를 #18 contract에 맞게 적합성 검토한 뒤 현재 기준선을 새로 생성한다.
6. 전체 재평가가 어렵다면 MVP 시나리오와 overview·mixed-tool·전체 목록 질문을 #18 구조에 맞게 선별해 우선 검증한다.

평가 목표 수치는 코드 변경 전에 팀이 합의해야 한다. #18과 호환되는 현재 기준선을 먼저 만들고 이후 수정은 그 기준선보다 퇴행하지 않아야 한다. API 성공률만으로 품질 통과를 선언해서는 안 된다.

## 4. 리뷰 방법

세 개의 독립 리뷰를 병렬로 수행했다.

1. 백엔드 정확성·아키텍처·API 호환성 리뷰
2. 보안·데이터 정합성·오류 처리 리뷰
3. 테스트 신뢰성·provider 호환성·archive 재현성 리뷰

공유 작업 트리는 수정하지 않았으며, `/tmp`의 임시 clone에서 `main + #18` 병합 결과를 만들어 동적 검증을 수행했다.

## 5. 심각도 기준

| 등급 | 기준 |
| --- | --- |
| Critical | 데이터 손실, 권한 우회, 즉각적인 전체 서비스 침해 가능성 |
| High | 사용자에게 근거 없는 답을 정상으로 제공하거나 핵심 Q&A 기능 전체를 중단시킬 가능성 |
| Medium | 특정 기능·질문·환경에서 품질, 신뢰 경계, 출처 추적 또는 재현성이 깨질 가능성 |
| Low | 직접적인 기능 장애는 아니지만 운영 추적성과 문서 정확도를 낮추는 문제 |

## 6. High 리스크

### H-01. 검색 장애가 정상 답변으로 위장됨

**위치**

- `backend/agentic_graph.py:148-150`
- `backend/agentic_graph.py:230-266`

**의미**

`ToolNode(QA_TOOLS, handle_tool_errors=True)`가 DB 또는 Chroma 검색 예외를 외부로 전달하지 않고 `ToolMessage` 문자열로 변환한다. 이후 결과 수집 코드는 구조화 artifact가 없는 Tool 메시지의 상태를 기본값 `ok`로 기록한다. 성공한 근거 Tool 결과가 하나도 없어도 모델의 최종 답변 문자열만 존재하면 정상 결과로 반환한다.

```text
사용자 질문
→ 검색 Tool 호출
→ DB 또는 Chroma 장애
→ 예외가 Tool 메시지로 변환됨
→ Tool 상태가 기본값 ok로 기록됨
→ 모델이 근거 없이 답변
→ HTTP 성공 응답
```

**재현 결과**

`search_project_evidence` 내부에서 `RuntimeError("DB unavailable")`를 발생시키고 모델이 후속 답변을 생성하도록 했다.

- `sources=[]`
- Tool 결과 상태 `ok`
- 답변 문자열 정상 반환
- 검색 실패를 나타내는 API 오류 없음

**영향**

사용자는 검색 시스템 장애가 있었다는 사실을 알 수 없고, 근거 없는 답변을 정상적인 프로젝트 정보로 신뢰할 수 있다. 명시적인 503보다 탐지하기 어려운 silent integrity failure이므로 High로 분류했다.

**권장 수정**

- Tool 예외를 `status="error"` artifact로 표준화한다.
- 최소 한 번의 성공한 evidence-bearing Tool 결과를 최종 답변의 전제조건으로 둔다.
- 모든 검색이 실패하면 명시적인 실패 상태 또는 HTTP 503을 반환한다.
- 일부 Tool만 실패한 경우의 partial-success 정책을 정의한다.
- DB, Chroma, Tool limit 오류 회귀 테스트를 추가한다.

**승인 조건**

- 검색 Tool 전체 실패 시 HTTP 성공 답변이 생성되지 않는다.
- `sources=[]`와 Tool error만 존재하는 상태를 정상 근거 답변으로 반환하지 않는다.

### H-02. 첨부·세션 RAG와 Agentic 근거 규칙의 충돌

**위치**

- `backend/agentic_graph.py:28-30`
- `backend/agentic_graph.py:114-117`
- `backend/agentic_graph.py:206-208`
- `backend/chat/router.py:305-325`

**의미**

Agentic 프롬프트는 답변 전에 프로젝트 검색 Tool을 반드시 호출하고 Tool이 반환한 근거만 사용하도록 요구한다. 그러나 임시 첨부는 일반 `HumanMessage`, 세션 RAG는 `prepared_context` 메시지로 전달되며 `ToolMessage` 또는 Tool artifact가 아니다.

기존 `SYSTEM_QA`의 “첨부 자료를 우선 참고” 규칙과 새 오케스트레이터의 “Tool 결과만 사용” 규칙이 같은 시스템 프롬프트 안에서 충돌한다.

**실패 시나리오**

```text
프로젝트 DB: Bluefin 정보 없음
첨부 note.txt: "이번 릴리즈 이름은 Bluefin"
질문: 이번 릴리즈 이름은?
```

- 지시를 엄격히 따르면 첨부의 `Bluefin`을 사용할 수 없다.
- 첨부를 사용하면 “Tool 결과만 사용” 규칙을 위반한다.
- 프로젝트 DB에 없는 질문에도 무관한 프로젝트 Tool 호출이 강제된다.

현재 fake-model 테스트는 Tool 결과에 `Bluefin`이 없는데도 모델이 이를 답하도록 작성되어 이 모순을 가린다.

**영향**

첨부 및 세션 RAG에만 있는 사실을 답하지 못하거나, 모델마다 서로 다른 방식으로 지시 충돌을 해석할 수 있다. 근거 사용 규칙의 핵심 계약이 비결정적으로 바뀌므로 High로 분류했다.

**권장 수정**

다음 중 하나를 선택한다.

1. 첨부·세션 RAG를 ephemeral evidence Tool 또는 구조화된 `ToolMessage`로 제공한다.
2. 프롬프트를 “검색 Tool 결과와 서버가 검증한 첨부·세션 자료만 사용”으로 수정하고, 임시 근거만으로 충분한 요청에서는 프로젝트 Tool 강제를 조건화한다.

추가로 실제 Tool Calling 모델 또는 grounding 규칙을 준수하는 fake model을 사용해 첨부-only 근거 테스트를 추가한다.

**승인 조건**

- 프로젝트 DB에 없고 첨부에만 있는 사실을 근거 규칙 위반 없이 답할 수 있다.
- 답변에 사용된 첨부·세션 근거가 구조화된 provenance로 남는다.

### H-03. Tool Calling 미지원 provider/model에서 Q&A 전체 실패

**위치**

- `backend/agentic_graph.py:111-124`
- `backend/api/query.py:139-157`
- `backend/chat/router.py:316-329`
- `backend/llm/chat_model_factory.py:12-18, 29-42`
- `.env.example:1-20`

**의미**

Agentic-only 경로는 모든 Q&A 모델에 다음 기능을 요구한다.

- `bind_tools`
- Tool schema 처리
- `tool_choice="any"`
- Tool call 응답 형식

OpenAI-compatible chat endpoint라고 해서 이 기능을 모두 지원하는 것은 아니다. 기존 `main`은 Agentic 호출 실패 시 semantic 검색 경로로 fallback했지만, #18은 의도대로 레거시 실행 경로를 제거했다. 따라서 Tool Calling 미지원 모델에서는 프로젝트 Q&A와 세션 Q&A가 모두 503으로 실패한다.

**영향**

README와 설정은 OpenAI, Claude, Google, Local Q&A를 지원 대상으로 선언하지만, 테스트는 각 provider 객체 생성과 fake Tool Calling model만 확인한다. 실제 provider/model의 Tool 계약이 확인되지 않은 상태에서 Agentic-only로 전환하면 특정 배포의 Q&A 전체가 중단될 수 있다.

이 항목은 운영에서 Tool Calling이 검증된 모델만 사용하고 지원 범위를 명확히 제한한다면 심각도를 낮출 수 있다.

**권장 수정**

- 공식 지원 matrix를 Tool Calling 가능 provider/model로 제한한다.
- 서버 시작 시 capability 검증 또는 fail-fast 설정 검사를 추가한다.
- OpenAI, Claude, Google, Local provider 계약 테스트를 추가한다.
- Local 지원 조건과 필수 Tool Calling 기능을 문서화한다.

Agentic-only 방향을 유지할 수 있으며 레거시 fallback을 복원할 필요는 없다.

**승인 조건**

- 지원 대상으로 선언한 모든 provider/model의 Tool Calling 계약이 검증된다.
- 비지원 모델은 첫 사용자 요청이 아니라 기동 또는 설정 검증 단계에서 명확히 차단된다.

## 7. Medium 리스크

### M-01. 후속 질문이 이전 대화의 주제를 잃음

**위치**

- `backend/retriever/qa_tools.py:85-104`
- `backend/retriever/history_context.py:20-44`

**의미**

“그 전에는?”, “왜 바뀌었어?” 같은 후속 질문을 이전 주제와 결합하기 위한 `history_context` helper가 존재하지만 실제 Tool Calling runtime에서는 호출되지 않는다. `include_history=True`가 설정돼도 이전 질문의 주제를 검색어에 결합하지 않는다.

```text
사용자: 로그인 방식을 OAuth로 바꾼 이유가 뭐야?
사용자: 그 전에는?
```

두 번째 질문은 “OAuth 이전 로그인 방식”으로 검색해야 하지만 실제 검색 Tool에는 “그 전에는?”가 그대로 전달될 수 있다.

**권장 수정**

- Agentic state의 이전 메시지를 검색 Tool에 안전하게 주입한다.
- Tool 실행 전에 `resolve_history_context()`로 검색어와 scope를 결정한다.
- `run_agentic_qa()` 전체 경로의 deictic follow-up 테스트를 추가한다.

### M-02. 클라이언트 `rag_context`가 SystemMessage로 승격됨

**위치**

- `backend/chat/router.py:37-40, 84-119, 260-263, 316-325`
- `backend/chat/context_builder.py:131-137`
- `backend/agentic_graph.py:184-196`

**의미**

세션 Q&A 요청의 `rag_context`는 클라이언트가 전달할 수 있는 입력이다. ContextBuilder가 이를 `system` 역할로 만들고 Agentic 변환 경로가 그 역할을 보존한다. 사용자가 작성한 내용이 실제 오케스트레이터 시스템 프롬프트 뒤의 `SystemMessage`로 들어가 Tool 선택과 최종 답변을 강하게 조종할 수 있다.

직접적인 권한 우회 또는 쓰기 Tool 실행은 확인되지 않았으나, 검색 회피와 거짓 답변 유도 가능성이 있어 Medium으로 분류했다.

**권장 수정**

- 클라이언트·세션 유래 컨텍스트를 `HumanMessage`, Tool evidence 또는 명시적인 데이터 블록으로 처리한다.
- “명령이 아닌 자료”라는 신뢰 경계를 적용한다.
- prompt injection이 포함된 `rag_context` 회귀 테스트를 추가한다.

### M-03. 첨부가 많으면 프로젝트 검색 출처가 누락됨

**위치**

- `backend/api/query.py:35-38, 56-121`
- `backend/agentic_graph.py:258-266, 299-303`

**의미**

최종 `sources`는 첨부 출처를 먼저 넣고 프로젝트 검색 출처를 뒤에 붙인 다음 전체를 5개로 자른다. 첨부가 5개 이상이면 답변에 사용된 프로젝트 검색 출처가 provenance 목록에서 누락될 수 있다.

```text
첨부: a.pdf, b.pdf, c.pdf, d.pdf, e.pdf
프로젝트 검색 출처: project.md
```

답변 본문이 `project.md`를 인용해도 API의 `sources`에는 첨부 5개만 남을 수 있다.

**권장 수정**

- 첨부 출처와 프로젝트 출처를 별도 필드로 유지한다.
- 첨부 개수에 상한을 적용하거나 프로젝트 출처 슬롯을 별도로 보장한다.
- 실제 사용·인용된 출처를 우선 보존한다.
- 첨부 5개 이상과 Tool 출처 결합 테스트를 추가한다.

### M-04. Archive runner가 실제 답변 비교 결과를 재현하지 않음

**위치**

- `archive/legacy_qa_v1/README.md:34-41`
- `archive/legacy_qa_v1/tests/baseline_pytest.txt`
- `archive/legacy_qa_v1/tests/current_pytest.txt`

**의미**

Archive runner는 고정된 레거시 단위 테스트와 현재 단위 테스트를 각각 실행한다. 이는 과거 코드와 현재 코드의 unit regression을 재현하지만, 동일 질문·DB·Chroma·모델로 두 경로의 답변 정확도, 인용 품질, Tool 선택 또는 지연시간을 비교하지는 않는다.

현재 runner가 증명하는 것:

> 과거 코드와 현재 코드의 각 단위 테스트를 다시 실행할 수 있다.

현재 runner가 증명하지 못하는 것:

> 동일 데이터에서 Tool Calling 결과가 레거시 결과보다 어떻게 달라졌는지 다시 측정할 수 있다.

**권장 수정**

- 목적을 “unit regression baseline”으로 명확히 낮추거나,
- 고정 질문 corpus, DB/Chroma fixture, 모델·프롬프트·평가 설정, 결과 JSONL/hash를 포함하는 opt-in 비교 runner를 추가한다.

비교 결과 보존이 PR #18의 핵심 목적이라면 이 항목도 병합 전 승인 조건으로 올리는 것이 적절하다.

### M-05. Shallow clone에서 레거시 archive 실행 불가

**위치**

- `archive/legacy_qa_v1/manifest.json:5-8`
- `archive/legacy_qa_v1/scripts/verify_snapshot.py:62-82`
- `archive/legacy_qa_v1/scripts/run_suite.py:67-85, 139-145`

**의미**

Archive는 과거 소스 전체를 포함하지 않고 baseline commit SHA와 Git blob hash를 기록한다. 실행 시 로컬 저장소에 과거 Git object가 존재한다고 가정한다. `fetch-depth: 1`인 shallow clone 또는 source snapshot에서는 baseline commit을 찾지 못해 실행이 실패한다.

**권장 수정**

- CI의 `fetch-depth: 0` 요구사항을 문서화하고 immutable baseline tag를 명시적으로 fetch한다.
- 더 강한 독립 보존이 필요하면 고정 소스 또는 Git bundle을 archive에 포함한다.
- shallow clone 재현 테스트를 추가한다.

## 8. Low 리스크

### L-01. Current 비교 실행 로그에 후보 커밋 SHA가 남지 않음

**위치**

- `archive/legacy_qa_v1/README.md:29-32`
- `archive/legacy_qa_v1/scripts/run_suite.py:60-64, 148-163`

문서는 정확한 후보 커밋을 명명한다고 설명하지만, 실제 current 실행 로그에는 `current`라는 label만 남고 대상 SHA가 출력되지 않는다. 실행 시작 시 legacy SHA와 `git rev-parse <current-ref|HEAD>^{commit}` 결과를 출력하고 결과 artifact에도 기록하는 것이 좋다.

## 9. 확인된 긍정 요소

- `main`과 #18의 OpenAPI 경로, 메서드, request/response schema가 동일하다.
- `documents.py`와 `memory.py` 분리 후 공개 라우트가 보존됐다.
- 업로드 및 Project Memory 경로의 인증·인가 순서가 보존됐다.
- 삭제된 레거시 모듈을 참조하는 production import가 없다.
- Archive는 production runtime에서 import되지 않는다.
- Archive의 baseline commit, lockfile, source blob 무결성 검증이 동작한다.
- `git diff --check`와 Python compile 검사가 통과했다.

## 10. 동적 검증 결과

### 10.1 임시 `main + #18` 병합 트리

- 병합 충돌 없음
- OpenAPI 공개 계약 동일
- 비-DB 회귀 테스트: **934 passed, 2 skipped**
- Python compile: 통과
- `git diff --check`: 통과

외부 MySQL이 필요한 통합 테스트는 이 환경에서 실행하지 않았다. `main` 기준선의 별도 저장소 자산이 필요한 scope 검사도 #18 판정 대상에서 제외했다.

### 10.2 Archive 비교 runner

- Snapshot integrity: 통과
- Legacy suite: **109 passed**
- Current Tool Calling suite: **233 passed**

이 결과는 두 unit suite의 재현성을 증명하며, 실제 LLM 답변 품질 비교를 증명하지는 않는다.

## 11. 수정 우선순위

1. **H-01 검색 실패 처리**
2. **H-02 첨부·세션 RAG 근거 모델 정리**
3. **H-03 provider/model Tool Calling capability 확정**
4. M-01 후속 질문 runtime 연결
5. M-02 `rag_context` 신뢰 경계
6. M-03 출처 보존
7. M-04/M-05 archive 비교 수준과 실행 환경 확정
8. L-01 후보 SHA 기록

## 12. 병합 승인 조건

PR #18은 다음 조건을 만족한 뒤 새 통합 브랜치의 첫 번째 구조적 병합으로 사용하는 것을 권장한다.

- [ ] 검색 Tool 전체 실패가 정상 답변으로 반환되지 않는다.
- [ ] 최소 한 개의 성공한 evidence-bearing Tool 결과가 답변 전제조건으로 검증된다.
- [ ] 첨부-only 및 세션 RAG-only 질문이 근거 규칙과 모순 없이 동작한다.
- [ ] 클라이언트 입력이 `SystemMessage` 지시로 승격되지 않는다.
- [ ] 지원 provider/model의 Tool Calling capability가 명시되고 검증된다.
- [ ] 후속 이력 질문이 이전 주제와 결합된 검색어를 사용한다.
- [ ] 실제 사용된 프로젝트 출처가 첨부 출처 때문에 누락되지 않는다.
- [ ] Archive의 목적이 unit regression인지 실제 결과 비교인지 문서와 구현에서 일치한다.
- [ ] 평가 데이터셋·기대 tool·runner의 #18 호환성을 확인하고 #18용 현재 기준선을 새로 생성한다.
- [ ] supersede 5문항과 비-supersede 5문항의 history recall·precision·정합성을 기록한다.
- [ ] MVP에 포함되는 provider, 첨부, 세션 RAG 범위를 명시한다.
- [ ] 수정 후 Agentic, 첨부, 세션, history, archive 테스트를 재실행한다.
- [ ] 가능한 환경에서 MySQL 통합 테스트를 실행한다.

## 13. 브랜치 상태

- `integration/final-on-pr18-20260729`
  - 현재 `main`과 동일한 `9ca7d63e712e17364f4acde1a83abfb386a37a3d`
  - #18은 아직 병합되지 않음
- `integration/pr-stack-20260729`
  - #9, #14, #11, #13 및 #11 통합 보정 포함
  - 기능 비교 기준으로 보존
- `checkpoint/pre-pr18-20260729`
  - 기존 통합 브랜치의 #18 적용 전 체크포인트

## 14. 최종 판정

PR #18은 목표 아키텍처로 사용할 수 있으나 **현재 상태 그대로 병합하지 않는다**. H-01을 필수 수정하고, MVP provider 범위를 고정하며, M-01 이력 문맥 연결과 #18 contract에 맞는 현재 평가를 통과시킨 뒤 재리뷰한다. 첨부·세션 RAG가 MVP에 포함되면 H-02, M-02, M-03도 병합 전 해결한다.

레거시 runtime fallback을 복원하는 대신 Agentic-only 경로의 오류 처리, 근거 모델, provider capability를 강화하는 방향이 PR 의도와 가장 잘 맞는다. Production Roadmap의 MVP 범위를 존중해 모든 후속 개선을 한 번에 해결하려 하지 말고, 핵심 Q&A·supersede 데모와 직접 연결되는 게이트를 먼저 닫는 것이 적절하다.
