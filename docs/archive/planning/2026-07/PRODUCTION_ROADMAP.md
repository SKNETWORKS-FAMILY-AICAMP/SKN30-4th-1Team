# PaiM 실서비스 전환 로드맵 (4차 프로젝트 대비)

> 코드베이스 실사(2026-07-06) 결과를 바탕으로 한 7개 항목 자문 문서.
> 전제: 팀 5인, 가용 기간 약 한 달, AWS 배포 예정.
> 각 항목은 **추천 방향 → 트레이드오프 → 첫 실행 단계** 순으로 구성.

---

## 1. AWS 배포

### 추천 방향
**단일 EC2 + RDS(MySQL) + S3 + ALB(HTTPS) 구성으로 시작하고, ECS/Fargate는 다음 단계로 미룬다.**

Fargate 같은 스테이트리스 컨테이너 환경은 로컬 디스크가 없다는 전제라서, 현재 코드의 로컬 의존 3곳(ChromaDB PersistentClient, `data/uploads` 파일 저장, GitHub App 인메모리 세션)을 **전부 동시에** 외부화해야 배포 자체가 성립한다. 단일 EC2는 이 세 가지를 그대로 둔 채 배포할 수 있어, 문제를 하나씩 순서대로 풀 수 있다.

우선순위 구분:

| 배포 초기에 반드시 | 순차적으로 | 나중으로 미뤄도 됨 |
| --- | --- | --- |
| 시크릿을 SSM Parameter Store로 이관 | 파일 저장 S3 구현 (`storage.py` 교체 지점 활용) | ChromaDB 서버 모드/pgvector 전환 |
| `0.0.0.0` 바인딩 + ALB/nginx 뒤 TLS(ACM) | MySQL 커넥션 풀 도입 | ECS/Fargate 전환 |
| CORS를 실제 서비스 origin으로 | GitHub App 세션을 DB 테이블로 | 오토스케일링 |
| RDS 생성 + 스키마/마이그레이션 적용 | | |

주의: 단일 EC2라도 **uvicorn 워커를 2개 이상 띄우는 순간** GitHub App 인메모리 세션이 깨진다(요청이 다른 워커로 가면 state를 못 찾음). 워커 1개로 시작하거나, 세션을 DB 테이블로 옮기는 걸 앞당길 것.

### 트레이드오프
- 단일 EC2는 SPOF(단일 장애점)이지만, 개인/소규모 베타 단계에서는 EBS 스냅샷 + RDS 자동 백업으로 충분히 감당 가능.
- ChromaDB를 EC2 로컬 디스크(EBS)에 두면 당장은 동작하지만, 인스턴스 교체 시 재인덱싱 또는 EBS 이전 절차가 필요. 6번 항목에서 pgvector로 통합하면 이 문제 자체가 사라진다.

### 첫 실행 단계
1. AWS 계정에 예산 알람부터 설정 (LLM API + 인프라 이중 과금 주의)
2. SSM Parameter Store에 시크릿 등록, 앱 시작 시 로드하는 설정 로더 작성
3. RDS MySQL 생성 → `schema.sql` + `migrate_v2~v5` 적용 (DB는 프라이빗 서브넷, 보안그룹으로 EC2만 허용)
4. EC2 + docker + ALB/ACM으로 HTTPS 배포
5. `storage.py`에 S3 백엔드 구현 (인터페이스는 이미 마련돼 있음)

---

## 2. RAG 타임라인 컨텍스트 이슈 (최우선 제품 과제)

### 추천 방향
**(c) 병행 — 단, 순서는 (a) 적재 시 supersede 판별이 근본 해결이고, (b) recency 가중치는 그걸 보완하는 저비용 패치다.** 하나만 골라야 한다면 (a). 이유: recency 가중치만으로는 "오래됐지만 여전히 유효한 결정"과 "오래됐고 번복된 결정"을 구분할 수 없다. 문제의 본질은 시간이 아니라 **상태(superseded 여부)**다.

추가로 짚을 점: 이 버그는 탐색형 RAG만이 아니라 **조회형의 "정답 보장"도 깨뜨리고 있다.** 번복된 결정 row가 그대로 남아 있으므로 "결정된 사항 몇 개야?" 같은 SQL 직조회 결과에 stale row가 포함된다. supersede를 고치면 조회형 정확도도 함께 회복된다 — 팀 발표 때 좋은 논거가 된다.

### 구체 설계

**① 스키마 (migrate_v7.sql)** — 기존 idempotent 패턴 그대로 (v6은 다중 사용자 지원이 선점):
```sql
ALTER TABLE memory ADD COLUMN superseded_by INT NULL;   -- 나를 대체한 항목의 id
ALTER TABLE memory ADD COLUMN superseded_at DATETIME NULL;
```
이전 row는 삭제하지 않는다. 이력은 남고, 검색·응답에서만 필터링된다.

**② 적재 시 supersede 판별 — Reconciler 패턴 재사용 가능 (확인됨).**
`pr_actions.py`의 `_invoke_reconciler_once` 패턴(여러 후보를 한 번에 LLM에 넣고 Pydantic 구조로 판정받기)이 그대로 이식된다:
- 새 문서 적재 후, 신규 decision/action 각각에 대해 같은 프로젝트의 미완료 기존 항목 중 후보를 추림 (이미 있는 `memory_vector` ChromaDB 인덱스로 유사도 top-5 — 전수 비교 방지)
- 배치 LLM 판정: `{new_id, old_id, verdict: supersedes|duplicate|unrelated, confidence, reason}`
- **high confidence → 자동 링크 적용** (row 삭제가 아닌 메타데이터 추가이므로 "추가는 자동" 원칙에 부합; 델타 브리핑에 "결정 X가 Y로 변경됨"으로 노출해 사람이 인지하게 함)
- **medium → `memory_suggestions`에 제안으로 등록** (kind 컬럼 추가) — 기존 제안 인박스 UI와 승인 플로우를 그대로 재사용
- `is_user_verified` row에는 자동 링크 금지, 항상 제안 경유 (기존 보호 원칙 유지)

**③ 검색 시 필터링 + recency:**
- `mysql_search.py`: 기본 `WHERE superseded_by IS NULL`. "왜 바뀌었어?", "원래 계획은?" 류 이력 질문에는 체인 포함
- `qa_engine.py`: 컨텍스트에 `[최신]` / `[→ #id로 대체됨]` 주석을 달아 LLM이 상태를 알게 함
- **recency는 세 번째 RRF 리스트로**: 현재 BM25 리스트 + dense 리스트를 RRF 융합하는 구조 그대로, 동일 후보군을 날짜 내림차순으로 정렬한 리스트를 하나 더 만들어 낮은 가중치(예: 0.4/0.4/0.2)로 융합. 기존 프레임워크 안에서 함수 하나 수정으로 끝난다.

**④ 평가:** 로드맵에 이미 있는 골든 질문 20~30개 구축 시, **타임라인 변경 케이스를 5~10개 명시적으로 포함**시켜 before/after로 `context_precision`(현재 0.571)을 측정할 것. 이게 없으면 고쳤는지 알 수 없다.

### 트레이드오프
- supersede 판별도 LLM 판단이므로 오판 가능. Reconciler와 같은 원칙(정확도 > 재현율, 애매하면 링크하지 않음)을 적용하면 놓친 링크는 다음 적재나 사람이 잡을 수 있지만, 잘못된 링크는 유효한 결정을 숨기므로 confidence 임계를 보수적으로.
- 적재 시 LLM 호출이 추가되어 업로드 처리 시간·비용 증가 — fast 티어 모델로 충분한 작업.

### 첫 실행 단계
migrate_v7 → supersede 판별 모듈(reconciler 패턴 이식) → ingest 훅 연결 → 검색 필터 + recency RRF → 타임라인 골든 케이스 평가.

---

## 3. 멀티모달 파일 수집

### 추천 방향
**"포맷 → 텍스트 변환 레이어"를 새 모듈(`pipeline/converters.py`)로 추가하고, 기존 `extract(text, source_kind=...)` 파이프라인을 그대로 태운다.** 조사 결과대로 구조적 준비는 이미 되어 있다.

**(1) STT: AWS Transcribe 추천.** 이유가 셋 있다:
- 어차피 AWS로 가므로 인프라 추가 없음 (S3 업로드 → Transcribe 잡 → 결과 폴링, 기존 문서 상태 폴링 UX와 동일 패턴)
- **화자 분리(speaker diarization)를 지원한다** — 이게 결정적이다. PaiM의 핵심 추출 대상이 "액션 + 담당자"인데, whisper 계열은 화자 분리가 없어서 "누가 하기로 했는지"를 텍스트만으로 추측해야 한다. 화자 라벨("Speaker 0: 제가 할게요")이 있어야 owner 추출 정확도가 산다.
- 한국어 지원 양호
- 로컬 whisper(faster-whisper)는 프라이버시 면에서 좋지만 GPU 인프라 + pyannote 화자분리까지 얹어야 해서 이 규모에는 과함.

**(2) Slack/Discord: 스냅샷 → 주기 동기화 순으로, 실시간은 하지 않는다.**
- 1단계(MVP): **export 파일 업로드** — Slack export zip / Discord 채팅 export를 업로드받아 파싱. 인프라 추가 제로, 업로드 플로우 재사용
- 2단계: **봇 토큰 기반 주기 폴링** — 기존 `repository.py`의 repo sync 패턴(워터마크 기반 증분, 백그라운드 태스크, 상태 폴링)이 1:1로 이식된다. 워터마크만 PR 번호 → 메시지 timestamp로 바뀔 뿐
- 실시간 webhook은 상시 수신 엔드포인트 + 이벤트 중복 처리가 필요한데, "프로젝트 메모리" 용도에는 몇 시간 단위 동기화로 충분해서 비용 대비 이득이 없다.

**(3) source_kind 확장 — 3종 추가:**

| 신규 타입 | 추출 지침 방향 |
| --- | --- |
| `transcript` (음성 전사) | 구어체·필러 관용. 화자 라벨 기반 담당자 추출. 명확하지 않으면 owner 비움 |
| `slides` (PPT/DOCX) | 불릿 파편은 액션 금지. 주로 맥락·이슈·리스크 소스로 취급 (README 지침과 유사한 보수성) |
| `chat` (Slack/Discord) | 파편화 심함 — 명시적 결정/합의만 추출, 임계 최고로. "애매하면 추출 금지" 원칙 그대로 |

### 트레이드오프
- Transcribe는 오디오 분당 과금 — 회의 1시간이면 수백 원 수준이지만 예산 알람에 포함할 것.
- chat 소스는 노이즈 대비 신호가 가장 낮다. 잘못 추출된 액션이 쌓이면 메모리 신뢰를 깎으므로, 추출 임계를 높게 시작해서 낮춰가는 방향이 안전하다.

### 첫 실행 단계
`python-pptx`/`python-docx` 의존성 추가 + converters 모듈 → `slides` source_kind → Slack export 업로드 파싱 → (AWS 배포 후) Transcribe 연동 + `transcript` 타입.

---

## 4. LangGraph 개발 보조 툴

### 추천 방향
**"결정 리서처(Decision Researcher)"부터 시작하라.** 읽기 전용이라 안전하고, PaiM의 데이터 모델과 정확히 맞물린다:

- 사용자가 결정 항목 하나를 지정 (예: "ChromaDB → pgvector 전환하기로 함")
- 에이전트가 웹 검색 → 근거/대안/리스크를 조사 → 조사 노트를 생성
- 결과는 메모리를 직접 수정하지 않고 **해당 결정에 첨부되는 노트 또는 제안**으로 저장 — "파괴적 변경은 제안-승인" 원칙과 일치

두 번째 후보는 "액션 사전조사(spike) 에이전트" — 열린 액션에 대해 이미 연동된 GitHub API로 관련 파일을 모아 구현 체크리스트 초안을 만들어주는 것. "테스트 실행" 툴은 코드 실행 샌드박스(보안 격리)가 필요해서 한 달 안에는 비추천.

**설계 — 기존 컨벤션 위에 도구 호출 루프 얹기:**
```
State(TypedDict): {task, messages, iterations, findings}
agent 노드: get_chat_model(tier="quality").bind_tools([web_search, read_memory, ...])
조건부 라우팅(named 함수): 응답에 tool_calls 있음 → tools 노드 → agent로 복귀
                          없음 → summarize 노드 → END
iterations >= MAX(예: 8) → 강제 종료 (기존 MAX_RETRY 무한루프 방지 관행 확장)
```
LangGraph의 prebuilt `ToolNode`를 쓰면 tools 노드 구현이 거의 공짜다. 기존 `chat_model_factory`가 `BaseChatModel`을 반환하므로 `bind_tools`가 provider 무관하게 동작한다 (단, 구조화 출력처럼 Google은 제약이 있을 수 있으니 openai/claude 기준으로 먼저).

### 트레이드오프
- 에이전틱 루프는 이 코드베이스 최초의 패턴이라 비용·시간 예측이 어렵다. iteration 캡과 태스크당 토큰 상한을 처음부터 걸 것.
- 웹 검색 툴은 외부 API(검색 프로바이더) 의존이 하나 추가된다.

### 첫 실행 단계
`backend/agent/` 모듈 신설 → web_search 툴 1개 + 결정 리서처 그래프 → 결과를 노트/제안으로 저장하는 엔드포인트 → UI는 결정 카드에 "조사하기" 버튼 하나.

---

## 5. GraphRAG 마이그레이션

### 추천 방향
**지금은 하지 마라. 대신 2번의 supersede 링크를 "그래프의 첫 엣지"로 삼는 점진 접근을 추천한다.**

근거:
1. **측정된 실패 모드가 GraphRAG가 푸는 문제가 아니다.** 현재 실패는 시간적 상태(어느 결정이 유효한가) 문제이고, GraphRAG의 강점은 대규모 코퍼스에서의 멀티홉 관계 추론·전역 조망이다. 전역 조망은 이미 `project_memory` 응축 요약(조망형 경로)이 담당하고 있다.
2. **코퍼스 규모가 안 맞는다.** 프로젝트당 회의록 수십 건, 메모리 항목 수백 개 수준에서는 엔티티 추출 + 커뮤니티 탐지 + 그래프 저장소의 오버헤드가 이득을 넘는다.
3. 5인 · 한 달 리소스에서 2번(측정된 문제)과 GraphRAG(가설적 개선)를 동시에 할 수 없다.

**통합 로드맵 (2번과 하나로):**
- 1단계: `superseded_by` 링크 (= 2번 해결) — 이것이 사실상 그래프의 첫 관계 타입
- 2단계: 필요가 확인되면 `memory_edges(from_id, to_id, relation)` 테이블 추가 — `relates_to`, `depends_on` 등. 이 규모에서는 SQL adjacency list로 충분하고 neo4j는 불필요
- 3단계: 골든셋 평가에서 멀티홉 실패("A 결정에 영향받는 액션 전부 보여줘" 류)가 실제로 관측될 때만 본격 GraphRAG 재검토

### 트레이드오프
점진 접근은 GraphRAG의 전역 요약 품질 향상(대형 코퍼스 기준)을 포기하는 것이지만, 현재 규모에서는 포기하는 것이 거의 없다.

### 첫 실행 단계
2번 항목 그대로. 별도 작업 없음.

---

## 6. 데이터베이스 대안

### 추천 방향
**PostgreSQL + pgvector로의 통합이 정답이고, 하려면 지금이 가장 싸다.** 프로덕션 사용자 데이터가 생기기 전인 지금은 마이그레이션 비용이 "스키마 방언 변환 + 드라이버 교체"뿐이지만, 서비스 시작 후에는 데이터 이전 + 무중단 전환 문제가 추가된다.

통합 효과: 현재 3계층(MySQL + ChromaDB + 로컬 파일)이 "Postgres(구조화+벡터) + S3(파일)" 2계층이 된다. 1번의 ChromaDB 배포 문제가 통째로 사라지고, supersede 필터와 벡터 검색을 한 쿼리에서 조인할 수 있게 돼 2번 구현도 단순해진다.

**Supabase에 대한 판단:**
- Supabase의 실질 가치는 Postgres+pgvector 자체보다 **Auth(로그인)·Storage·API가 딸려온다는 것**. 7번(인증)까지 한 번에 해결된다는 점에서 5인 팀에게 진지하게 매력적이다.
- 단, 4차 목표가 명시적으로 "AWS 서버 전환"이라면: 관리형 Supabase는 AWS 외부 의존이 생기고, self-hosted Supabase는 운영 부담이 커서 비추천. 이 경우 **RDS PostgreSQL + pgvector + Cognito(또는 자체 JWT)**가 AWS-native 정석.
- 절충: 백엔드는 AWS EC2, DB+Auth만 Supabase 클라우드 — 가장 빠르지만 벤더 2곳 관리.

**기타 오픈소스 대안 평가:** Qdrant/Weaviate/Milvus는 벡터 전용이라 "통합" 목적에 안 맞고(ChromaDB를 다른 벡터DB로 바꾸는 것뿐), 이 규모에서 pgvector 대비 이점이 없다.

### 트레이드오프
- 마이그레이션 작업량: `schema.sql`+migrate 스크립트 Postgres 방언 재작성, PyMySQL→psycopg 교체, ChromaDB 호출부→pgvector 쿼리 전환. raw SQL 12테이블이라 범위는 명확하지만 **1~2인×1~2주**는 잡아야 한다.
- 한 달 안에 AWS 전환 + 인증 + supersede + DB 마이그레이션을 전부 하는 건 무리일 수 있다. DB 전환이 부담이면 **4차에서는 MySQL+Chroma를 단일 EC2에 그대로 올리고, DB 통합은 5차로** 미루는 것도 완전히 합리적인 선택이다. 단, 미루면 supersede(2번)는 MySQL 기준으로 구현하게 되므로 마이그레이션 시 이중 작업이 조금 생긴다.

### 첫 실행 단계
**1주차에 결정만 먼저 내려라** (팀 전체가 영향받는 결정이라 늦출수록 비싸진다). 전환한다면: 로컬 docker에서 Postgres+pgvector로 스키마 포팅 → 테스트 통과 → 그 위에 2번 구현.

---

## 7. 프로덕션 보안

### 추천 방향
**순서가 중요하다. "본격 인증 시스템"보다 먼저, 며칠 안에 되는 응급 처치부터:**

**0순위 — fail-open을 fail-closed로 (반나절).**
`require_project_access()`가 인증 정보 없으면 통과시키는 현재 로직을, **프로덕션 환경(`ENV=production`)에서는 인증 미설정 시 서버가 기동을 거부하거나 전 요청 403**이 되도록 뒤집는다. 로컬 개발 편의는 `ENV=dev`에서만 유지. 이 한 가지가 안 되면 나머지 보안 작업이 전부 무의미하다.

**1순위 — 임시 인증 (하루).**
정식 로그인 전 사설 베타 기간에는 **단일 공유 Bearer 토큰 미들웨어**로 API 전체를 잠근다. 조잡해 보여도 "인증 없음"과 "토큰 없으면 접근 불가"의 차이는 절대적이다. 특히 PaiM은 **요청마다 유료 LLM 호출이 발생**하므로, 인증 없는 공개 엔드포인트는 데이터 유출 이전에 과금 폭탄 벡터다.

**2순위 — 시크릿과 네트워크 (배포 작업과 동시).**
- 시크릿 → SSM Parameter Store (Secrets Manager는 로테이션 필요해질 때)
- RDS는 프라이빗 서브넷, 보안그룹 최소화, TLS는 ALB+ACM
- 업로드 크기 제한 (nginx `client_max_body_size` + FastAPI 검증) 및 rate limit (slowapi 또는 nginx) — LLM 비용 남용 방지 겸용

**3순위 — 상태 저장소.**
GitHub App 세션을 인메모리 dict → **MySQL 테이블**로. Redis를 이것 하나 때문에 추가하지 말 것 — TTL 30분짜리 세션 몇 개는 DB 테이블 + 만료 컬럼으로 충분하다.

**4순위 — 정식 인증.**
직접 만들지 말고 Cognito 또는 Supabase Auth(6번 선택과 연동)로 JWT 발급 → FastAPI 의존성에서 검증. 코드 주석에 이미 "`get_current_user_id()`만 교체하면 됨"이라고 설계돼 있으므로 교체 지점은 명확하다.

### 트레이드오프
공유 토큰은 사용자 구분이 안 되므로 팀 협업 기능(4차 목표)에는 못 쓴다 — 어디까지나 정식 인증 전 "문 잠그기"용.

### 첫 실행 단계
fail-closed 전환 → Bearer 토큰 미들웨어 → SSM 이관 → 업로드 제한/rate limit → GitHub 세션 DB화 → Cognito/Supabase Auth.

---

## 8. 다중 사용자 지원 (로그인 · 프로젝트 공유 · 팀장 권한)

> **✅ 백엔드 구현 완료 (7/8):** JWT 인증(signup/login/me) + contextvar 미들웨어 + fail-closed 전환 + `migrate_v6.sql`(password_hash, chat_sessions.user_id, resolved_by, last_seen_at) + 멤버 관리 API(`/projects/{id}/members` GET/POST/PATCH/DELETE) + 세션 소유자 격리. 단위 테스트 174개 통과, 2계정 E2E 27개 시나리오 검증 완료.
> **남은 것:** 데스크톱 로그인 화면 + 토큰 저장 + `paimApi.ts` Authorization 헤더 + 멤버 관리 UI (⑤). 데스크톱 팀은 UI가 나오기 전까지 `PAIM_AUTH_MODE=dev`로 기존 흐름 유지 가능.

### 코드 조사 결과 — 기반이 이미 절반은 있다
- `users`, `projects.owner_user_id`, `project_members(project_id, user_id, role)` 테이블이 **이미 존재**.
- `backend/api/auth.py`에 `_ROLE_RANK = {viewer:0, member:1, admin:2, owner:3}` — 4단계 역할 체계가 이미 정의돼 있고, `require_project_access(project_id, min_role)`가 멤버십+역할 검사까지 이미 수행함. **빠진 것은 "진짜 인증"(현재 `DEV_USER_ID` env fallback)과 멤버 관리 API·UI뿐.**
- **구멍 (멀티유저 전 필수 수정): `chat_sessions`에 `user_id` 컬럼이 없음** — 프로젝트를 공유하면 멤버가 서로의 대화 세션을 목록·열람할 수 있게 됨. AES 암호화는 저장 암호화일 뿐 사용자 간 격리가 아님.
- 델타 브리핑의 "지난 확인 시점"도 사용자별 개념이 되어야 함 (현재는 프로젝트 단위).

### 추천 방향

**① 인증: 이번 사이클은 자체 JWT (email+password)를 권장.**
- Cognito가 "직접 만들지 마라" 관점의 정석이지만, Tauri 데스크톱 앱과의 OAuth 연동(루프백 리다이렉트)·팀의 학습 비용을 감안하면 3주 일정에는 리스크.
- 자체 구현 범위: `POST /auth/signup`, `POST /auth/login` (비밀번호는 bcrypt/argon2 해시), JWT 액세스 토큰 발급 (만료 12~24h, 이번 사이클엔 refresh token 생략 — 데스크톱 앱이 재로그인).
- **핵심 마이그레이션 트릭**: `get_current_user_id()`가 일반 함수라 FastAPI request 컨텍스트가 없음 → **JWT 검증 미들웨어가 `contextvar`에 user_id를 심고, `get_current_user_id()`는 contextvar를 읽도록** 교체하면 기존 호출부 전체가 무수정으로 동작한다. 코드 주석의 "이 함수만 교체" 설계 의도를 그대로 실현하는 방법.
- fail-closed: production에서 토큰 없음/무효 → 401. `ensure_dev_user`·`backfill_dev_user_membership` 시작 로직은 dev 환경으로 게이팅.

**② 역할·권한: 기존 4단계에서 실제로는 2단계만 사용.**
- 팀장급 = `owner`(프로젝트 생성자, 자동 부여). 멤버 추가/제외는 `min_role="owner"` (또는 admin 이상).
- 일반 팀원 = `member` (콘텐츠 읽기/쓰기, 제안 승인 가능).
- `viewer`/`admin`은 스키마에 있으니 두되, 이번 사이클 UI에는 노출하지 않음 — 과설계 방지.

**③ 멤버 관리 API + 초대 방식:**
- `GET/POST/DELETE /projects/{id}/members` — 추가/제외는 owner 전용, `require_project_access` 재사용.
- 초대는 **가입된 사용자의 email로 직접 추가** 방식. 이메일 발송 초대는 SMTP 인프라가 필요하므로 이번 사이클에서 제외.
- owner가 자기 자신을 제외하거나 마지막 owner가 나가는 것 방지 로직 필수.

**④ 데이터 격리 수정 (migrate_v6 — 구현 완료):**
- `chat_sessions`에 `user_id` 추가, 세션 목록/조회를 본인 것만으로 필터 — **프로젝트 메모리는 공유, 대화는 개인** 원칙.
- `project_members`에 `last_seen_at` 추가 → 델타 브리핑 기준을 사용자별로.
- `memory_suggestions` 승인/거절에 `resolved_by(user_id)` 기록 — 팀 협업에서 "누가 승인했나" 감사 추적.

**⑤ 데스크톱 앱:** 로그인 화면 + 토큰 저장(Tauri secure storage) + `paimApi.ts`에 Authorization 헤더 + 프로젝트 설정에 멤버 관리 패널. `App.tsx`가 약 5,800줄이라 UI 작업량을 과소평가하지 말 것 — 전담 1인 배정 권장.

### 트레이드오프
- 자체 JWT는 비밀번호 재설정·이메일 인증이 없는 상태로 시작 — 4차 데모/베타에는 수용 가능하나, 공개 서비스 전에 Cognito/Supabase Auth 전환 재검토.
- 이 항목이 들어오면서 7번의 "공유 Bearer 토큰 임시방편"은 건너뛰고 바로 정식 인증으로 간다 — 대신 #3(멀티모달)·#4(에이전트)를 이번 사이클에서 잘라내야 한다 (아래 일정 참고).

### 첫 실행 단계
~~JWT 미들웨어 + contextvar 교체 → fail-closed → migrate_v6 (chat_sessions.user_id, last_seen_at, resolved_by) → 멤버 API~~ (완료) → **데스크톱 로그인/멤버 UI** → 2인 동시 사용 E2E 테스트 (백엔드 레벨은 완료, 데스크톱 통합 후 재검증).

---

## 종합 우선순위 — 실제 일정 반영 (5인, 7/6~7/27, 발표 7/28 오후)

가용 기간은 **3주 + 1일**. 7/28 오전은 데이터 정리·발표 자료 작성에 쓰이므로, **기능 개발은 7/23(목)에 동결하고 이후는 안정화·리허설**에 배정한다.

> **스코프 확정:** 다중 사용자 지원(#8)이 이번 사이클에 포함되면서, #3(멀티모달)과 #4(에이전트)는 이번 사이클에서 제외하고 발표에서 로드맵으로 처리한다. 3주 안에 "AWS 배포 + 정식 인증/공유 + supersede"가 이미 꽉 찬 스코프다.

### 주차별 계획

**W1 (7/6~7/12) — 문 잠그고 골격 세우기**
- ✅ #8 인증 백엔드 (7/8 완료): JWT 미들웨어 + contextvar `get_current_user_id()` 교체 + signup/login + fail-closed + migrate_v6 + 멤버 API + 세션 격리 — W2 예정분까지 선완료
- #1 배포 골격: SSM 시크릿 로더 → RDS 생성/마이그레이션 → EC2+ALB+TLS (인프라 1인)
- #2 착수: migrate_v7 스키마 + supersede 판별 모듈 + **타임라인 골든 케이스 5~10개 작성** (2인)
- 데스크톱: 로그인 화면 + 토큰 저장 + API Authorization 헤더 착수 (1인)
- #6 결정: **7/8(수)까지 결론만** — 이번 사이클 보류 권장

**W2 (7/13~7/19) — 공유와 핵심 결함 해결**
- #8 완성: 데스크톱 로그인 화면 + 토큰 저장 + Authorization 헤더 + 멤버 관리 UI (백엔드는 W1에 선완료)
- #2 완성: ingest 훅 + 검색 필터 + recency RRF → **골든셋 before/after 측정** (발표 자료의 핵심 수치)
- #1 마무리: S3 스토리지 구현, GitHub App 세션 DB 테이블화

**W3 (7/20~7/26) — 통합과 동결**
- **2인 동시 사용 E2E 테스트** (팀장 초대 → 멤버 활동 → 권한 경계 확인 — 멀티유저는 단독 테스트로는 못 잡는 버그가 많다)
- supersede × 멀티유저 교차 검증 (멤버가 올린 회의록의 supersede 제안을 팀장이 승인하는 흐름)
- **7/23(목) 기능 동결** → 7/24~26 실서버 E2E 리허설 + 데모 시나리오 확정 + 발표 자료 초안
- (여력 시에만) #3 slides 파서 스트레치

**7/27(월)** — 버그픽스만 허용. 데모 리허설 2회, 발표 자료 완성.
**7/28(화)** — 오전: 데이터 정리·최종 자료 / 오후: 발표.

### 일정 반영에 따른 조정 세 가지

1. **#6(DB 전환)은 이번 사이클 보류.** 3주 안에 AWS 전환 + 인증/공유 + supersede와 DB 스왑까지 동시에 하면 **발표 데모의 안정성이 인질**이 된다. 검증된 스택(MySQL+ChromaDB)을 단일 EC2에 올리고, Postgres+pgvector 전환은 발표 직후(8월 초) — 그때도 실사용자 데이터가 거의 없어 마이그레이션 비용 논리는 유지된다.
2. **#3(멀티모달)·#4(에이전트)는 #8에 자리를 내준다.** 발표에서 "다음 로드맵"으로 제시 — 특히 Transcribe(화자 분리)와 결정 리서처는 로드맵 슬라이드로도 설득력이 있다.
3. **#2의 골든셋 측정이 발표 스토리의 중심.** "타임라인 변경 질문에서 context_precision 0.571 → 개선치"가 가장 강한 슬라이드다. **W2 말까지 측정 완료**해야 W3에 개선 반복할 시간이 남는다.

### 데모 시나리오 제안 (발표용)

**멀티유저와 supersede를 한 흐름으로:**
1. 팀장 계정으로 로그인 → 프로젝트 생성 → 멤버 2명 추가 (권한 관리 시연)
2. 멤버 계정으로 로그인 → 같은 프로젝트 메모리가 보임 → 회의록 업로드 (동일 안건이 A → B → C로 변경되는 시나리오)
3. "X는 어떻게 하기로 했어?" 질문 → **최신 결정 C + "이전에 A → B로 변경된 이력" 언급**
4. 팀장이 제안 인박스에서 supersede 제안 승인 (승인자 기록 표시)
5. RAGAS before/after 수치 슬라이드로 마무리 — "문제 정의 → 해결 → 검증 → 협업" 완결

**인원 배분:** 인프라 1인(#1), 인증/멀티유저 백엔드 1인(#8), 데스크톱 1인(#8 UI), RAG 2인(#2). W3에는 전원 통합 테스트·리허설·발표 준비로 전환.

**한 문장 요약:** 3주의 승부처는 #2(supersede)·#8(멀티유저)·fail-closed이고, 이를 위해 #3·#4를 잘라내는 결단과 7/23 동결선이 발표의 성패를 가른다.
