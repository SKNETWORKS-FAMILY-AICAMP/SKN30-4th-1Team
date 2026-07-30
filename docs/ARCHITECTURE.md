# PaiM 시스템 아키텍처

> 갱신: 2026-07-29
>
> 이 문서는 현재 저장소의 실제 디렉토리/코드 구조를 기준으로 작성되었습니다. `README.md`의 구조 설명이 이 문서와 다르다면 이 문서(코드 기준)를 우선하세요.

## 1. 개요

PaiM은 회의록·문서와 GitHub 저장소 활동을 하나의 "살아있는 프로젝트 메모리"로 통합하는 LLM 기반 AI 프로젝트 매니저입니다.

- **입력**: 회의록(.md/.txt/.pdf) 업로드, GitHub repo 연결
- **처리**: LLM이 결정(decision)·액션(action)·이슈(issue)·리스크(risk)로 구조화 추출 → MySQL + ChromaDB에 이중 저장
- **관찰**: repo sync 시 머지된 PR과 열린 액션을 LangGraph 기반 Reconciler가 대조해 완료 제안 생성 (승인은 항상 사람)
- **질의**: 프로젝트 Q&A는 Agentic 오케스트레이터가 SQL 상태·하이브리드 근거·프로젝트 조망 도구를 필요에 따라 호출
- **UI**: Tauri + React 데스크톱 앱 (macOS/Windows)

```
                         ┌─────────────────────────┐
                         │   Desktop App (Tauri)   │
                         │   React 19 + TS UI      │
                         └────────────┬─────────────┘
                                      │ HTTP (127.0.0.1:8000)
                                      ▼
                         ┌─────────────────────────┐
                         │      FastAPI Backend     │
                         │  api / chat / github 라우터│
                         └──┬───────┬───────┬───────┘
                            │       │       │
                 ┌──────────┘       │       └──────────┐
                 ▼                  ▼                  ▼
     ┌────────────────────┐ ┌──────────────┐ ┌──────────────────┐
     │ pipeline (추출/적재) │ │ Agentic Q&A  │ │ reconciler        │
     │ extractor·ingestor  │ │ 도구·하이브리드 │ │ PR↔액션 대조 그래프 │
     └─────────┬───────────┘ │ 하이브리드 RAG │ └─────────┬──────────┘
               │             └──────┬───────┘           │
               ▼                    ▼                    ▼
     ┌────────────────┐   ┌────────────────┐   ┌────────────────────┐
     │  MySQL (구조화)  │   │ ChromaDB (벡터) │   │ GitHub App (REST)  │
     └────────────────┘   └────────────────┘   └────────────────────┘
                                      ▲
                                      │
                        ┌─────────────┴─────────────┐
                        │  llm/ (OpenAI·Claude·      │
                        │  Google·Local 팩토리)        │
                        └─────────────────────────────┘
```

## 2. 저장소 레이아웃 (주석 포함)

```text
.
├── .github/workflows/
│   └── release.yml                  # 태그 push(v*) 시 macOS/Windows 데스크톱 설치본 자동 빌드·릴리즈
│
├── backend/                         # FastAPI 백엔드 (Python, LangChain/LangGraph)
│   ├── main.py                      # FastAPI 앱 진입점 — 라우터 등록, CORS, lifespan(기동 시 복구 작업)
│   ├── project_memory.py            # 활성 memory 기반 프로젝트 요약 캐시
│   ├── agentic_graph.py             # 프로젝트 Q&A 도구 오케스트레이터
│   ├── startup.py                   # 서버 재시작 시 stale 문서/repo 작업 복구, watchdog
│   ├── storage.py                   # 업로드 파일 저장 추상화 (로컬 FS 기본, S3 등 교체 대비)
│   │
│   ├── api/                         # REST 엔드포인트 (prefix: /api/v1)
│   │   ├── auth.py                  # 개발용 임시 인증 (DEV_USER_ID 기반, 4차 로드맵에서 정식 로그인으로 대체 예정)
│   │   ├── project.py               # 프로젝트 CRUD
│   │   ├── documents.py             # 문서 업로드/삭제 + Git 로그 적재
│   │   ├── memory.py                # 수동 memory CRUD
│   │   ├── repository.py            # GitHub repo 연결/조회/삭제 + sync 트리거
│   │   ├── suggestion.py            # Reconciler가 만든 완료 제안 조회/승인/거절
│   │   ├── delta.py                 # "지난 확인 이후" 델타 브리핑 조회/생성
│   │   └── query.py                 # Q&A 질의 엔드포인트 (+첨부파일 임시 컨텍스트)
│   │
│   ├── chat/                        # deprecated 서버 세션 호환 계층 (구형 클라이언트용)
│   │   ├── router.py                # /projects/{id}/sessions — deprecated 세션 CRUD·질의
│   │   ├── session_store.py         # 레거시 세션·메시지 암호화 저장/조회
│   │   └── context_builder.py       # 레거시 세션 질의의 토큰 예산 관리
│   │
│   ├── pipeline/                    # 문서 → 구조화 메모리 변환
│   │   ├── extractor.py             # LLM 추출 — 소스 타입(회의록/README/커밋/이슈-PR)별 지침 분기, 청크 분할·중복 제거
│   │   ├── ingestor.py              # 추출 결과를 MySQL(구조화) + ChromaDB(벡터) 이중 적재
│   │   └── models.py                # MemoryItem 등 파이프라인 Pydantic 모델
│   │
│   ├── reconciler/                  # 머지 PR ↔ 열린 액션 완료 제안
│   │   └── pr_actions.py            # LangGraph 배치 매칭 — 워터마크 기반 증분 처리, high/medium 확신 + 근거만 제안
│   │
│   ├── retriever/                   # Agentic Q&A 도구와 검색 부품
│   │   ├── qa_tools.py              # 근거 검색·구조화 조회·조망 Tool 정의
│   │   ├── sql_project_state.py     # 조망 Tool의 읽기 전용 SQL 상태 조립
│   │   ├── history_context.py       # 이력 검색 범위 해석
│   │   ├── mysql_search.py          # 구조화 상태 조회
│   │   ├── qa_engine.py             # 하이브리드 RAG — BM25(한국어 형태소)+dense RRF 융합
│   │   └── memory_vector.py         # memory 테이블 행을 ChromaDB에 보조 인덱싱(백필 포함)
│   │
│   ├── llm/                         # LLM 프로바이더 추상화 (fast/quality 티어링)
│   │   ├── base.py                  # BaseLLMClient 인터페이스
│   │   ├── factory.py               # 구조화 추출용 클라이언트 팩토리 (OpenAI/Claude/Google SDK 직접 래핑)
│   │   ├── chat_model_factory.py    # 자유대화·RAG용 LangChain BaseChatModel 팩토리 (openai/claude/google/local)
│   │   ├── openai_client.py         # OpenAI 구조화 추출 클라이언트
│   │   ├── claude_client.py         # Anthropic(Claude) 구조화 추출 클라이언트
│   │   └── google_client.py         # Google Gemini 구조화 추출 클라이언트 (중첩 스키마 미지원으로 Q&A만)
│   │
│   ├── github/                      # GitHub App 연동
│   │   └── router.py                # /github/app — 설치(install) 세션, OAuth 콜백, repo preview, JWT 서명
│   │
│   ├── security/
│   │   └── session_crypto.py        # AES-256-GCM 세션 대화 암호화/복호화 (SESSION_MEMORY_KEY)
│   │
│   ├── db/                          # 저장소 연결 및 스키마
│   │   ├── mysql.py                 # PyMySQL 커넥션 헬퍼
│   │   ├── chroma.py                # ChromaDB 클라이언트 (OpenAI 임베딩 전용 컬렉션, cosine space)
│   │   ├── schema.sql               # 최초 스키마 — users/projects/documents/repositories/memory/... 12개 테이블
│   │   ├── migrate_v2.sql           # 문서 처리 상태·진행률 컬럼 추가 (idempotent)
│   │   ├── migrate_v3.sql           # 액션 완료(completed_at)·정렬(sort_order) 컬럼 추가
│   │   ├── migrate_v4.sql           # 액션 마감일(due_date) 컬럼 추가
│   │   └── migrate_v5.sql           # PR 워터마크 + memory_suggestions(완료 제안 인박스) 테이블 추가
│   │
│   └── test/                        # ⚠ pytest 스위트 아님 — RAG 검색 품질 수동 평가 스크립트
│       ├── rag_eval.py              # RAGAS 기반 하이브리드 검색 평가 (리트리버 파라미터 튜닝용, 환경변수로 실행)
│       ├── rag_eval_langsmith.py    # LangSmith 연동 평가 실행
│       └── rag_eval_*.csv           # 평가 실행 결과 스냅샷
│
├── tests/                           # pytest 자동화 테스트 스위트 (CI/로컬 `pytest` 대상)
│   ├── test_*.py                    # API·인증·암호화·Reconciler·QA 라우팅 등 단위/통합 테스트
│   └── integration/mysql/
│       ├── run.sh                   # 전체 백엔드 게이트 (비통합 pytest + 실제 MySQL)
│       ├── compose.yml              # 통합용 MySQL 컨테이너
│       └── fixtures/                # preflight 음성 fixture (의도적으로 깨진 compose)
│
├── evals/                           # 청킹 품질 평가 (golden fixture 기반, RAG 검색과 별개로 "추출 전 분할 단계"를 검증)
│   ├── eval_chunking.py             # 실행: `python -m evals.eval_chunking`
│   └── fixtures/*.md, *.golden.json # 문서 유형별(짧은 회의록/표 위주 등) 정답 청크 세트
│
├── data/samples/                    # 수동 업로드 데모/실험용 샘플 회의록 (코드에서 참조되지 않음)
├── meeting_notes/                   # 수동 검증용 합성 회의록 샘플 (현재 코드에서 직접 참조하지 않음)
│
├── desktop/                         # 데스크톱 앱 (Tauri 2 + React 19 + TypeScript) — 공식 사용자 UI
│   ├── src/                         # React 프론트엔드
│   │   ├── main.tsx                 # React 진입점
│   │   ├── App.tsx                  # 최상위 앱 셸 — 프로젝트 목록/선택, 채팅, 레이아웃 오케스트레이션 (최대 규모 파일)
│   │   ├── ProjectMemoryPanel.tsx   # 우측 프로젝트 메모리 패널 — 결정/액션/이슈/리스크 뷰, 델타 브리핑
│   │   ├── GithubPanel.tsx          # GitHub repo 연결·동기화 상태·완료 제안 인박스 UI
│   │   ├── projectFiles.tsx         # 문서 업로드/목록/드래그 첨부 UI
│   │   ├── paimApi.ts               # 백엔드 REST 클라이언트
│   │   ├── github.ts                # GitHub App 연동 API 클라이언트
│   │   ├── settings.ts              # 로컬 설정(서버 주소 등) 저장/조회
│   │   ├── format.ts                # 상대 시간 등 표시 포맷 유틸
│   │   └── types.ts                 # 공용 타입 정의
│   ├── src-tauri/                   # Tauri 2 Rust 런타임 셸
│   │   ├── src/main.rs, lib.rs      # 네이티브 앱 진입점 — 윈도우/트레이 구성
│   │   ├── tauri.conf.json          # 앱 메타데이터·번들 설정
│   │   └── capabilities/, icons/    # 권한 capability 정의, 앱 아이콘
│   ├── assets/                      # 앱 아이콘(app_icon), README용 스크린샷(readme), 기타(github)
│   ├── scripts/                     # 빌드 스모크 테스트 스크립트 (레이아웃/오프라인 번들)
│   └── .env.production              # 공개 빌드 설정 (OAuth client ID 등)
│
├── docs/                            # 프로젝트 문서
│   ├── README.md                    # 문서 정본·보관 자료 인덱스
│   ├── API_명세서.md, .html         # FastAPI 엔드포인트 명세
│   ├── ARCHITECTURE.md              # (본 문서) 시스템 아키텍처
│   ├── policies/, planning/         # 현재 정책과 남은 작업
│   ├── handovers/, reports/         # 담당자 계약과 검증 결과
│   ├── deliverables/                # 제출 산출물 작업 공간
│   └── archive/                     # 과거 평가·통합·핸드오버 기록
│
├── docker-compose.yml                # MySQL 컨테이너 (schema.sql 자동 적용)
├── start-paim.bat                    # Windows 원클릭 실행 (Docker·백엔드·앱 자동 기동)
├── pyproject.toml / uv.lock          # Python 패키지·의존성 (uv)
└── requirements.txt                  # pip 호환용 의존성 목록
```

## 3. 백엔드 아키텍처

### 3.1 요청 진입 및 부트스트랩 (`backend/main.py`)

- FastAPI 앱을 생성하고 `api/*`, `chat/router`, `github/router`를 `/api/v1` prefix로 등록합니다 (`github/router`는 자체 `/github/app` prefix 사용).
- CORS는 데스크톱 앱의 Tauri origin(`tauri://localhost` 등)만 허용합니다.
- `lifespan`에서 서버 기동 시: 중단된 문서/repo 작업 복구(`startup.recover_stale_tasks`), 레거시 프로젝트 멤버십 백필, ChromaDB 벡터 백필을 실행하고 백그라운드 `stale_watchdog` 태스크를 띄웁니다.
- 백엔드는 `127.0.0.1`에만 바인딩 — LAN 노출 없이 로컬 우선으로 동작합니다.

### 3.2 API 레이어 (`backend/api/`, `backend/chat/router.py`, `backend/github/router.py`)

| 모듈 | 라우트 예시 | 역할 |
| --- | --- | --- |
| `project.py` | `POST/GET/PATCH/DELETE /projects` | 프로젝트 CRUD |
| `documents.py` | `POST /projects/{id}/documents`, `.../git` | 문서 업로드·삭제, Git 로그 적재 |
| `memory.py` | `GET/POST/PATCH/DELETE .../memory` | 수동 메모리(결정/액션/이슈/리스크) CRUD |
| `repository.py` | `POST /projects/{id}/repositories`, `.../sync` | GitHub repo 연결, 동기화 트리거 |
| `suggestion.py` | `.../suggestions/{id}/accept|reject` | 완료 제안 승인/거절 (상태 변경은 항상 사람) |
| `delta.py` | `GET/POST /projects/{id}/delta`, `.../briefing/delta` | 델타 브리핑 |
| `query.py` | `POST /projects/{id}/query` | 현재 데스크톱의 비영속 Q&A (로컬 최근 대화·첨부를 요청 컨텍스트로만 사용) |
| `chat/router.py` | `/projects/{id}/sessions/...` | 구형 클라이언트용 deprecated 세션 CRUD·질의 — 암호화 서버 이력 |
| `github/router.py` | `/github/app/sessions`, `/callback` | GitHub App 설치 플로우, JWT 서명, repo preview |
| `auth.py` | — | 개발용 임시 사용자 인증 (`DEV_USER_ID`) |

### 3.3 pipeline — 기억 만들기

```
문서/repo 콘텐츠 → extractor.extract()
                     │  소스 타입별 지침 분기:
                     │   회의록 → 결정/액션(담당자)/이슈/리스크
                     │   README → 로드맵/TODO만 액션, 설치 안내문 제외
                     │   커밋 → 완료 상태 액션 또는 결정
                     │   열린 이슈/PR → 현재 문제·진행 중 작업
                     │  (대용량 문서는 문단 경계로 청크 분할 후 병합·중복 제거)
                     ▼
                  ingestor.ingest()
                     │  MySQL(memory 테이블, 구조화) 저장
                     └→ ChromaDB(벡터, 의미 검색) 저장
```

### 3.4 reconciler — 기억이 스스로 갱신

`pr_actions.py`가 LangGraph 그래프(`build_reconciler_graph`)로 머지된 PR과 열린 액션을 배치 대조합니다.

- 저장소별 `last_reconciled_pr` 워터마크로 증분 처리(이미 본 PR 재검사 방지)
- LLM 매칭은 `high`/`medium` 확신 + 한 줄 근거가 있을 때만 제안 생성 — 애매하면 보고하지 않음(정확도 > 재현율)
- 제안은 `memory_suggestions` 테이블에 삽입되며, 사람이 `suggestion.py`의 accept/reject로 확정할 때만 `memory.completed_at`이 갱신됨

### 3.5 retriever — Agentic Q&A 도구

`agentic_graph.py`의 오케스트레이터가 다음 읽기 전용 도구를 하나 이상 호출하고, 반환된 근거로 최종 답변을 작성합니다. `overview`는 별도 경로나 공개 route가 아니라 필요한 도구를 조합하는 질문 유형입니다.

| 도구 | 처리 |
| --- | --- |
| `search_project_evidence` | `qa_engine.py`의 멀티쿼리·BM25(한국어 형태소) + dense RRF로 특정 사실·이유·변경 이력을 검색 |
| `query_structured_memory` | `mysql_search.py`로 제한된 구조화 상태 목록·개수를 조회 |
| `get_project_overview` | `sql_project_state.py`로 프로젝트 요약과 유효 Action Plan을 근거로 제공 |

`memory_vector.py`는 `memory` 테이블 행이 생성/수정될 때 ChromaDB에도 보조 인덱싱해 하이브리드 검색이 구조화 데이터도 커버하도록 합니다.

### 3.6 LangGraph 사용 지점

- `agentic_graph.py` Q&A 그래프: 질문(+ 임시 첨부 근거) → 오케스트레이터 LLM → Tool 호출/결과 반환 반복 → 근거 기반 최종 답변
- `reconciler/pr_actions.py` 그래프: 머지 PR ↔ 열린 Action 대조 → 확신도·근거가 있는 완료 제안만 생성
- 문서·Git 적재는 `documents.py`의 백그라운드/동기 처리로 실행하며, 별도 ingest 그래프는 두지 않습니다.
- 기존 라우터 분기·검증·재기획 그래프는 [archive/legacy_qa_v1](../archive/legacy_qa_v1/README.md)의 비교 기준선으로만 보존합니다.

### 3.7 chat — 데스크톱 local-only 기본 경로와 레거시 호환

- 현재 데스크톱은 채팅 제목·질문·답변·작성 중 초안을 계정·서버 범위의 WebView `localStorage`에 저장하고, `POST /projects/{id}/query`에 최근 대화를 요청 컨텍스트로 전달합니다.
- `/query`가 받은 질문과 최근 대화는 답변 생성 중 PaiM 서버와 설정된 외부 LLM에 전달될 수 있지만, `chat_sessions`, `chat_messages`, `chat_summaries`에는 저장하지 않습니다.
- `chat/router.py`, `session_store.py`, `context_builder.py`는 deprecated `/sessions/*`를 사용하는 구형 클라이언트 호환용입니다. 이 경로는 `security/session_crypto.py`로 서버 세션을 암호화 저장하며 현재 데스크톱의 기본 저장 경로가 아닙니다.
- WebView `localStorage`는 현재 앱 전용 암호화 저장소가 아닙니다. 안전한 전용 저장소 이전은 별도 후속 범위입니다.

### 3.8 llm — 프로바이더 추상화

두 개의 별도 팩토리가 존재합니다 (용도가 다름):

- `factory.py` (`get_llm_client`): 구조화 추출 전용, Anthropic/OpenAI/Google SDK를 직접 래핑 (`ClaudeClient`/`OpenAIClient`/`GoogleClient`)
- `chat_model_factory.py` (`get_chat_model`): 자유 대화형 Q&A/RAG용 LangChain `BaseChatModel` 반환, `LLM_PROVIDER` 환경변수로 openai/claude/google/local 선택, `tier="fast"|"quality"` 티어링 지원 (local은 Ollama/vLLM 등 OpenAI 호환 서버)

Google Gemini는 중첩 스키마 구조화 출력을 지원하지 않아 구조화 추출에는 사용하지 않고 Q&A에만 사용합니다.

### 3.9 github — GitHub App 연동

`github/router.py`가 GitHub App 설치(install) 세션 발급, OAuth 콜백, JWT 서명, repo preview를 처리합니다. 설치 세션은 현재 인메모리(`_sessions` dict)로 관리되며, 코드 주석상 다중 워커/정식 사용자 인증 도입 시 DB/Redis로 이전 예정입니다.

### 3.10 db — 저장소

- `mysql.py`: PyMySQL 커넥션 헬퍼
- `chroma.py`: OpenAI 임베딩 전용 별도 컬렉션 사용(cosine space) — 기본 chromadb 임베딩(384-dim, L2)과 분리
- `schema.sql`: 최초 스키마 — `users`, `projects`, `project_members`, `documents`, `repositories`, `memory`, `memory_sources`, `memory_suggestions`, `chat_sessions`, `chat_messages`, `chat_summaries`, `project_memory` (12개 테이블)
- `migrate_v2~v5.sql`: 문서 처리 상태 컬럼 → 액션 완료/정렬 컬럼 → 마감일 컬럼 → PR 워터마크+완료 제안 인박스 순으로 idempotent 마이그레이션 적용 (컨테이너 기동 시 자동 실행)

## 4. 데스크톱 아키텍처 (`desktop/`)

Tauri 2(Rust 셸) 위에 React 19 + TypeScript로 구성된 공식 사용자 UI입니다.

- `App.tsx`가 최상위 앱 셸로 프로젝트 선택, 채팅, 레이아웃을 오케스트레이션하는 최대 규모 컴포넌트(약 5,800줄)이며, `ProjectMemoryPanel.tsx`(메모리/브리핑), `GithubPanel.tsx`(repo 연동/제안 인박스), `projectFiles.tsx`(문서 업로드)가 주요 기능 패널로 분리되어 있습니다.
- `paimApi.ts`/`github.ts`가 백엔드 REST 호출을 캡슐화하고, `settings.ts`가 서버 주소 등 로컬 설정을 관리합니다.
- `src-tauri/`는 네이티브 윈도우/트레이/권한(capabilities)을 구성하는 Rust 셸로, 실제 비즈니스 로직은 담지 않습니다.
- CI(`.github/workflows/release.yml`)가 태그 push 시 이 앱을 macOS/Windows용으로 빌드해 릴리즈합니다.

## 5. 테스트·평가 자산

세 디렉토리가 목적이 다른 테스트/평가 도구입니다.

| 디렉토리 | 목적 | 실행 방식 |
| --- | --- | --- |
| `tests/` | pytest 자동화 스위트 (API, 인증, 암호화, Reconciler, QA 라우팅 등) | `pytest` |
| `backend/test/` | RAGAS 기반 하이브리드 검색(리트리버) 품질 수동 평가 — 파라미터 튜닝용 | `python backend/test/rag_eval.py` (환경변수로 K/거리 임계값 조정) |
| `evals/` | 문서 청킹 품질 평가 — golden fixture 대비 청크 분할 정확도 검증 | `python -m evals.eval_chunking` |

`meeting_notes/`와 `data/samples/`는 현재 코드에서 직접 참조하지 않는 수동 업로드·검증용 샘플입니다.

## 6. 데이터 모델 핵심

| 카테고리 | 설명 |
| --- | --- |
| `decision` | 결정 사항 (기록된 이유 포함) |
| `action` | 할 일 — `owner`(담당)·`due_date`(마감)·`completed_at`(완료)·`sort_order`(정렬) |
| `issue` | 현재 문제 |
| `risk` | 잠재 위험 |

- `memory.date` = 회의/문서의 기록 날짜, `memory.due_date` = 마감일 (별개 컬럼, migrate_v4)
- `memory.is_user_verified` = 사용자가 수정한 기록 보호 플래그 — LLM 재처리가 덮어쓰지 않음
- `memory_suggestions` = Reconciler가 만든 완료 제안, 근거·승인 이력과 함께 보존 (migrate_v5)
- `chat_sessions`/`chat_messages`/`chat_summaries` = deprecated 서버 세션 API의 구형 클라이언트 호환 테이블 (AES-256-GCM 암호화)
- `project_memory` = 조망형 질문에 쓰이는 응축 요약

## 7. 핵심 흐름

### 7.1 문서 업로드 → 기억 적재

```
사용자 업로드 (api/documents.py)
  → storage.py 로 파일 저장 (BackgroundTasks로 비동기 처리)
  → pipeline/extractor.py: 소스 지침 기반 LLM 구조화 추출
  → pipeline/ingestor.py: MySQL(memory) + ChromaDB 이중 저장
  → 문서 상태(status)를 polling(api/documents.py: GET .../documents/{id}/status)으로 확인
```

### 7.2 GitHub repo 동기화 → 완료 제안

```
repo 연결/동기화 (api/repository.py: POST .../sync)
  → GitHub App API로 머지 PR·열린 이슈/README/커밋 수집
  → pipeline/extractor.py 로 README/커밋/이슈 구조화 적재 (소스 타입별 지침)
  → reconciler/pr_actions.py: 워터마크 이후 머지 PR × 열린 액션 LLM 배치 대조
  → high/medium 확신 매칭만 memory_suggestions 에 제안 생성
  → 사용자가 GithubPanel.tsx 의 제안 인박스에서 승인/거절 (api/suggestion.py)
  → 승인 시에만 memory.completed_at 갱신
```

### 7.3 질문 → 답변

```
프로젝트 Q&A (api/query.py)
  → 데스크톱의 로컬 최근 대화를 요청 history로 전달 (서버 chat 테이블에는 저장하지 않음)
  → 첨부 검증·텍스트 추출 (있을 때만, 임시 근거)
  → agentic_graph.py: 오케스트레이터 LLM
      → search_project_evidence / query_structured_memory / get_project_overview
      → 도구 근거 반환 → 필요한 경우 다음 도구 호출
  → 최종 답변 + 출처 반환 (`route`는 호환성상 `semantic`)
  → 데스크톱이 질문·답변을 로컬 대화에 저장

레거시 세션 질의 (chat/router.py, deprecated)
  → context_builder.py 로 암호화 대화 이력과 함께 컨텍스트 조립
  → Agentic Q&A (프로젝트 질의와 동일한 도구 오케스트레이터)
  → 구형 클라이언트 호환을 위해 서버 세션 저장·롤링 요약·응답 형식 유지
```

### 7.4 델타 브리핑

```
앱 재오픈 (api/delta.py: GET/POST .../delta, .../briefing/delta)
  → 마지막 확인 시점 이후 변경분 조회
     (완료된 액션·새 완료 제안 → 새 결정/액션/이슈/리스크 → 마감 임박/기한 초과 순)
  → LLM이 스탠드업 대체 브리핑으로 요약 (약 8문장)
```

## 8. 설계 원칙

- **정확도 > 재현율**: Reconciler의 완료 매칭은 애매하면 보고하지 않음(high/medium 확신 + 근거 필수). 놓친 제안은 다음 동기화나 사람이 잡을 수 있지만, 틀린 완료 처리는 신뢰를 무너뜨림.
- **파괴적 변경은 제안-승인, 추가는 자동**: 메모리 적재는 자동이지만 완료 처리처럼 상태를 바꾸는 일은 반드시 사람의 승인을 거침 (human-in-the-loop).
- **근거 우선 Agentic Q&A**: 오케스트레이터는 읽기 전용 도구를 하나 이상 호출해 근거를 확인한 뒤 답한다. 검증·재계획 같은 안전장치는 평가 결과가 필요할 때만 추가한다.
- **데스크톱 채팅은 local-only**: 새 데스크톱은 대화와 초안을 현재 WebView `localStorage`에 저장합니다. `/query`에는 답변 생성에 필요한 최근 대화를 전송하지만 서버 chat 테이블에는 저장하지 않으며, 암호화 서버 세션은 deprecated 호환 경로에만 남아 있습니다.

## 9. CI/CD

`.github/workflows/release.yml`이 버전 태그(`v*`) push 시 `desktop/`(Tauri) 앱을 macOS `.dmg`, Windows `-setup.exe`/`.msi`로 빌드해 GitHub Releases에 게시합니다. 백엔드는 별도 CI 없이 로컬(`docker compose` + `uv run uvicorn`) 또는 `start-paim.bat`(Windows 원클릭)으로 구동합니다.
