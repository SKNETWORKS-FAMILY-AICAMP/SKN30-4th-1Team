# Agentic Q&A MVP 검증 기준

## 지원 범위

- 대상: #18의 운영 Agentic 프로젝트 Q&A 경로
- provider: 공식 OpenAI API
- model: `gpt-4.1-mini`
- 첫 Agent 라운드: 검색 Tool 최소 1개 호출 강제
- 범위 밖: Claude, Google, local/OpenAI-compatible endpoint의 Agentic Q&A 호환성

일반 LLM factory에 남아 있는 다른 provider 분기는 문서 추출·기존 내부 기능을 위해
유지한다. 이 문서의 제한은 Agentic 프로젝트 Q&A 경로에만 적용한다.

통합 시 `backend/agentic_graph.py`의 기본 모델 생성만
`get_chat_model()`에서 `get_agentic_qa_model()`로 연결한다. 해당 파일은 Tool 오류·첨부
근거 작업과 동시에 수정되므로 provider 변경 커밋에서는 의도적으로 건드리지 않는다.
테스트에서 주입하는 fake model 경로는 이 설정 검사와 무관하게 유지한다.

## API 키 없는 계약 검증

다음 테스트는 dummy key로 모델 객체와 OpenAI Tool schema만 만들며 네트워크를
호출하지 않는다.

```bash
uv run pytest -q \
  tests/test_agentic_openai_contract.py \
  tests/test_chat_model_factory.py \
  tests/test_agentic_qa.py
```

검증 항목은 고정 모델, 공식 endpoint, 비지원 설정 fail-fast, Tool schema 변환,
`tool_choice="any"`가 OpenAI 요청의 `required`로 변환되는 계약이다.

## 선택적 live smoke

실제 키를 환경변수로만 주고 다음 명령을 명시적으로 실행한다. 테스트는
`gpt-4.1-mini`가 설치된 LangChain Tool schema를 받아 검색 Tool call을 반환하는지만
확인하며 DB나 Chroma에는 접근하지 않는다.

```bash
LLM_PROVIDER=openai \
OPENAI_MODEL=gpt-4.1-mini \
OPENAI_API_KEY='<real-key>' \
PAIM_RUN_LIVE_OPENAI_SMOKE=1 \
uv run pytest -q tests/test_agentic_openai_live.py
```

`PAIM_RUN_LIVE_OPENAI_SMOKE=1`이 없으면 비용과 외부 호출을 막기 위해 skip한다.

## #18 MVP 기능 기준선 후보 10개

아래 항목은 과거 `AGENTIC_TOOL_ROUTING` 점수를 #18 성능 기준선으로 재사용하지 않고,
#18 코드와 데이터로 새로 측정할 최소 시나리오다. Tool 오류·history·첨부 연결 수정이
통합된 뒤 동일한 프로젝트 fixture에서 실행한다.

| ID | 질문 유형 | 기대 경로·판정 |
|---|---|---|
| A01 | 특정 작업 담당자 | `search_project_evidence`, 근거의 담당자만 답변 |
| A02 | 결정 이유·배경 | `search_project_evidence`, 근거 없는 이유 추측 금지 |
| A03 | 특정 수치·비율 | `search_project_evidence`, 수치와 출처 일치 |
| A04 | 상태 조건 목록 | `query_structured_memory`, 질문의 명시 조건만 전달 |
| A05 | 상태 조건 개수 | `query_structured_memory`, 중복 제거된 개수 |
| A06 | 프로젝트 전반 브리핑 | `get_project_overview`, 전체 목록 과다 노출 금지 |
| A07 | 상태와 배경 혼합 | structured + evidence Tool 조합, 한 답변으로 합성 |
| A08 | “그 전에는?” 후속 질문 | 이전 대상이 실제 검색어에 반영되고 변경 이력 답변 |
| A09 | 임시 첨부에만 있는 사실 | 첨부를 임시 근거로 사용하고 실제 출처만 반환 |
| A10 | 검색 backend 장애 | 정상 답변으로 위장하지 않고 명시적 실패 처리 |

각 항목은 최소한 HTTP 상태, 최종 답변, Tool 이름·인자, Tool 결과 상태, 반환 출처를
함께 저장해야 한다. A01~A10 통과 결과가 만들어진 시점을 #18의 최초 MVP 기준선으로
삼고, 그 이후 프롬프트·검색 성능 개선을 비교한다.
