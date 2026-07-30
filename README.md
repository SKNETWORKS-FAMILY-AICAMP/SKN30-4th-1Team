# PaiM — Project AI Manager

> 회의와 코드 사이의 맥락을 기억하는 AI 프로젝트 매니저

PaiM은 회의록, 문서, 음성 기록과 GitHub 활동을 하나의 **프로젝트 메모리**로 연결합니다.
흩어진 기록에서 결정·할 일·이슈·리스크를 정리하고, 프로젝트의 현재 상태를 근거와 함께 답하며, 머지된 PR이 기존 할 일을 해결했는지 찾아 완료를 제안합니다.

[최신 버전 다운로드](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-4th-1Team/releases) · [문서 모음](docs/README.md) · [API 명세](docs/API_명세서.md) · [배포 가이드](deploy/README.md)

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?style=flat-square&logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-Agentic_AI-1C3C3C?style=flat-square)
![OpenAI](https://img.shields.io/badge/OpenAI-LLM-412991?style=flat-square&logo=openai&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-8.0-4479A1?style=flat-square&logo=mysql&logoColor=white)
![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_Search-FF6B6B?style=flat-square)
![Tauri](https://img.shields.io/badge/Tauri-2.0-24C8DB?style=flat-square&logo=tauri&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-Desktop-3178C6?style=flat-square&logo=typescript&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-Deployed-232F3E?style=flat-square&logo=amazonwebservices&logoColor=white)

![PaiM 데스크톱 화면 구성](desktop/assets/readme/v1.0.6-screen-overview.png)

## Team

<table>
  <tr>
    <td align="center" width="180">
      <a href="https://github.com/hellohaeyeon">
        <img src="https://github.com/hellohaeyeon.png" width="100" height="100" alt="서해연"/><br/>
        <b>서해연</b>
      </a><br/>
      <sub>Team Lead · PM</sub><br/>
      <sub>FastAPI · 인증 · Supersede<br/>평가 파이프라인 · 배포 하드닝</sub>
    </td>
    <td align="center" width="180">
      <a href="https://github.com/j3s30p">
        <img src="https://github.com/j3s30p.png" width="100" height="100" alt="박제섭"/><br/>
        <b>박제섭</b>
      </a><br/>
      <sub>Developer</sub><br/>
      <sub>Tauri Desktop · Agentic Q&A<br/>GitHub 연동 · 릴리즈</sub>
    </td>
    <td align="center" width="180">
      <a href="https://github.com/star9906">
        <img src="https://github.com/star9906.png" width="100" height="100" alt="김동휘"/><br/>
        <b>김동휘</b>
      </a><br/>
      <sub>Developer</sub><br/>
      <sub>세션 보안 · 대화 암호화<br/>업로드 정합성 · 멀티포맷</sub>
    </td>
    <td align="center" width="180">
      <a href="https://github.com/attatae01-svg">
        <img src="https://github.com/attatae01-svg.png" width="100" height="100" alt="이동욱"/><br/>
        <b>이동욱</b>
      </a><br/>
      <sub>Developer</sub><br/>
      <sub>LangGraph · Hybrid Reranker<br/>RAGAS 평가 · 검색 품질 개선</sub>
    </td>
    <td align="center" width="180">
      <a href="https://github.com/robinlee3803-ai">
        <img src="https://github.com/robinlee3803-ai.png" width="100" height="100" alt="이승민"/><br/>
        <b>이승민</b>
      </a><br/>
      <sub>Team Support</sub><br/>
      <sub>팀 운영 지원<br/>식사 및 현장 지원</sub>
    </td>
  </tr>
</table>

## PaiM이 하는 일

- **프로젝트 메모리** — 문서에서 결정, 액션, 이슈, 리스크를 구조화해 관리합니다.
- **근거 기반 Q&A** — SQL 상태 조회와 하이브리드 검색을 조합해 출처가 있는 답변을 만듭니다.
- **GitHub 동기화** — README, 커밋, Issue, PR을 프로젝트 맥락에 연결합니다.
- **완료 제안** — 머지된 PR과 진행 중인 액션을 대조하고, 사용자의 승인 전까지 제안으로만 남깁니다.
- **델타 브리핑** — 마지막 확인 이후의 진행, 신규 항목, 마감 임박 사항을 요약합니다.
- **문서·음성 입력** — 텍스트, Markdown, PDF, DOCX와 회의 녹음을 프로젝트 메모리로 변환합니다.
- **팀 워크스페이스** — 로그인, 프로젝트 멤버와 역할, 공유 프로젝트를 지원합니다.
- **데스크톱 경험** — React와 Tauri 기반의 macOS·Windows 앱을 제공합니다.

## 프로젝트 목표

- 비정형 회의 기록을 결정·액션·이슈·리스크로 구조화할 수 있는가?
- 회의에서 정한 할 일을 GitHub의 실제 코드 변경과 연결할 수 있는가?
- 담당자·상태·마감처럼 정확해야 하는 질문에 LLM의 추측 없이 답할 수 있는가?
- 자동화의 편의성과 사람의 최종 결정권을 함께 지킬 수 있는가?

## 작동 방식

```mermaid
flowchart LR
    CONNECT["1 · 연결<br/>회의 · 문서 · GitHub"]
    REMEMBER["2 · 기억<br/>결정 · 할 일 · 이슈 · 리스크"]
    ASSIST["3 · 도움<br/>Q&A · 브리핑 · 완료 제안"]
    DECIDE["4 · 사용자 결정<br/>검토 · 승인 · 거절"]

    CONNECT --> REMEMBER --> ASSIST --> DECIDE

    classDef connect fill:#EAF2FF,stroke:#4F7CAC,color:#172A3A,stroke-width:2px
    classDef remember fill:#6D28D9,stroke:#4C1D95,color:#FFFFFF,stroke-width:3px
    classDef assist fill:#E7F8F2,stroke:#159A80,color:#075E54,stroke-width:2px
    classDef decide fill:#FFF4D6,stroke:#D97706,color:#78350F,stroke-width:2px

    class CONNECT connect
    class REMEMBER remember
    class ASSIST assist
    class DECIDE decide
    linkStyle default stroke:#94A3B8,stroke-width:3px
```

사용자는 프로젝트 자료를 연결하고, PaiM은 그 안의 핵심 맥락을 기억합니다. 이후 질문·브리핑·완료 제안을 통해 업무 판단을 돕되, 프로젝트 상태를 바꾸는 최종 결정은 사용자에게 남겨 둡니다.

## AI 아키텍처

PaiM은 질문 유형을 미리 고정하는 라우터 대신, 하나의 **Agentic 오케스트레이터**가 질문에 필요한 읽기 전용 도구를 직접 선택합니다. 정답이 명확해야 하는 상태 정보는 MySQL에서 조회하고, 문서의 맥락은 키워드와 벡터를 결합한 하이브리드 검색으로 찾습니다.

아래 구조에서 Q&A는 사용자의 요청으로, 완료 감지는 GitHub의 PR 머지 이벤트로 각각 독립 실행되며 프로젝트 메모리만 공유합니다.

```mermaid
flowchart TB
    subgraph Inputs["1 · Knowledge Sources"]
        direction LR
        INPUT["문서 · PDF · DOCX<br/>회의 음성"]
        REPO["README · 커밋<br/>Issue · PR"]
    end

    subgraph Ingestion["2 · Ingestion & Indexing"]
        direction LR
        CONVERT["텍스트 변환 · 청킹"]
        EXTRACT["Extractor LLM<br/>결정 · 액션 · 이슈 · 리스크"]
        INDEX["소스별 규칙으로<br/>정규화 · 인덱싱"]
    end

    INPUT --> CONVERT --> EXTRACT
    REPO --> INDEX

    subgraph Storage["3 · Project Memory"]
        direction LR
        MYSQL[("MySQL<br/>구조화 상태 · 권한 · 이력")]
        CHROMA[("ChromaDB<br/>문서 · 코드 근거 벡터")]
    end

    EXTRACT --> MYSQL & CHROMA
    INDEX --> MYSQL & CHROMA

    subgraph QAFlow["4-A · Agentic Q&A — 사용자 요청 시 실행"]
        direction TB
        QUESTION["사용자 질문<br/>+ 임시 첨부"]
        AGENT["LangGraph<br/>Agentic 오케스트레이터"]
        ANSWER["근거와 출처가 있는 답변"]

        subgraph ToolLayer["Read-only Tool Layer · 질문에 필요한 도구만 선택"]
            direction LR
            SQL_TOOL(["TOOL 01<br/>Structured Memory<br/>목록 · 상태 · 개수"])
            SEARCH_TOOL(["TOOL 02<br/>Hybrid Evidence Search<br/>BM25 + Vector RRF"])
            OVERVIEW_TOOL(["TOOL 03<br/>Project Overview<br/>요약 · Action Plan"])
        end

        QUESTION --> AGENT
        AGENT -->|"tool_call"| SQL_TOOL
        AGENT -->|"tool_call"| SEARCH_TOOL
        AGENT -->|"tool_call"| OVERVIEW_TOOL
        SQL_TOOL -. "observation" .-> AGENT
        SEARCH_TOOL -. "observation" .-> AGENT
        OVERVIEW_TOOL -. "observation" .-> AGENT
        AGENT -->|"근거 종합"| ANSWER
    end

    MYSQL --> SQL_TOOL & SEARCH_TOOL & OVERVIEW_TOOL
    CHROMA --> SEARCH_TOOL

    subgraph ReconcileFlow["4-B · Action Reconciliation — PR 머지 시 실행"]
        direction TB
        MERGED["머지된 PR"]
        RECONCILER["Reconciler LLM<br/>진행 중 액션과 대조"]
        INBOX["완료 제안 Inbox<br/>PR 링크 · 판단 근거"]
        APPROVAL{"사용자 승인"}
        APPLY["프로젝트 상태 반영"]
        KEEP["기존 상태 유지"]

        MERGED --> RECONCILER --> INBOX --> APPROVAL
        APPROVAL -->|승인| APPLY
        APPROVAL -->|거절| KEEP
    end

    MYSQL --> RECONCILER

    classDef input fill:#EAF2FF,stroke:#4F7CAC,color:#172A3A,stroke-width:2px
    classDef transform fill:#F2ECFF,stroke:#7C3AED,color:#3B1768,stroke-width:2px
    classDef datastore fill:#172A3A,stroke:#0F172A,color:#FFFFFF,stroke-width:3px
    classDef agent fill:#6D28D9,stroke:#4C1D95,color:#FFFFFF,stroke-width:3px
    classDef tool fill:#EDE9FE,stroke:#8B5CF6,color:#3B1768,stroke-width:2px
    classDef success fill:#E7F8F2,stroke:#159A80,color:#075E54,stroke-width:2px
    classDef approval fill:#FFF4D6,stroke:#D97706,color:#78350F,stroke-width:2px
    classDef reject fill:#FDECEC,stroke:#DC2626,color:#7F1D1D,stroke-width:2px

    class INPUT,REPO,QUESTION,MERGED input
    class CONVERT,EXTRACT,INDEX,RECONCILER transform
    class MYSQL,CHROMA datastore
    class AGENT agent
    class SQL_TOOL,SEARCH_TOOL,OVERVIEW_TOOL tool
    class ANSWER,INBOX,APPLY success
    class APPROVAL approval
    class KEEP reject

    style Inputs fill:#F8FAFC,stroke:#CBD5E1,color:#172A3A,stroke-width:1px
    style Ingestion fill:#F8FAFC,stroke:#CBD5E1,color:#172A3A,stroke-width:1px
    style Storage fill:#F5F3FF,stroke:#8B5CF6,color:#3B1768,stroke-width:2px
    style QAFlow fill:#F0FDFA,stroke:#5EEAD4,color:#075E54,stroke-width:2px
    style ToolLayer fill:#FFFFFF,stroke:#8B5CF6,color:#3B1768,stroke-width:2px,stroke-dasharray:5 5
    style ReconcileFlow fill:#FFFBEB,stroke:#FCD34D,color:#78350F,stroke-width:2px
    linkStyle default stroke:#94A3B8,stroke-width:2px
```

### 핵심 기술 선택

| 문제 | 구현 | 선택 이유 |
| --- | --- | --- |
| 담당자·상태·개수처럼 정확해야 하는 질문 | MySQL 구조화 조회 | LLM의 추측과 검색 누락 방지 |
| 문서 표현이 달라도 같은 맥락 찾기 | BM25 + Vector Search를 RRF로 결합 | 키워드 일치와 의미 유사도의 장점 결합 |
| 질문마다 필요한 근거가 다름 | LangGraph Agentic 도구 호출 | 고정 라우팅 없이 여러 근거를 조합 |
| README·커밋·회의록의 의미가 다름 | 소스 유형별 추출 프롬프트 | 설치 문구를 할 일로 오인하는 문제 방지 |
| PR 머지를 액션 완료와 연결 | Reconciler LLM + 근거 기반 제안 | 자동화하면서도 잘못된 완료 처리 방지 |
| AI가 기존 상태를 바꾸는 위험 | 승인·거절이 있는 Human-in-the-loop | 최종 결정권을 사용자에게 유지 |

### 서비스 구성

| 영역 | 기술 |
| --- | --- |
| Desktop | Tauri 2 · React 19 · TypeScript · Vite |
| Backend | FastAPI · Python 3.11+ |
| AI | LangGraph · LangChain · OpenAI |
| Data | MySQL 8 · ChromaDB |
| Search | BM25 · Vector Search · Reciprocal Rank Fusion |
| Operations | Docker Compose · Caddy · AWS · GitHub Actions |
| Security | JWT 인증 · 프로젝트 역할 기반 권한 · Rate Limit · Storage Quota |

### 검증 결과

| 검증 항목 | 결과 |
| --- | --- |
| 헤더 없는 서술형 회의록 액션 추출 | 9/9건 추출, 담당자 100% 일치 |
| README 설치 문구의 액션 오추출 | 소스별 지침 적용 전 4건 → 적용 후 0건 |
| PR과 진행 중 액션 완료 매칭 | 6/6건 high confidence 제안 |
| 구조화 상태 질문 | Agentic 도구가 SQL 상태 근거를 선택해 답변 |
| 승인 전후 상태 반영 | 진행 중 → 사용자 승인 후 PR 근거와 함께 완료 |

## 주요 화면

### 프로젝트 채팅

프로젝트 자료와 GitHub 활동을 근거로 질문하고, 오른쪽 도구에서 메모리·자료·저장소를 함께 확인합니다.

![PaiM 프로젝트 채팅 화면설계](desktop/assets/readme/v1.0.6-screen-chat.png)

| 프로젝트 메모리 | GitHub 연결 |
| --- | --- |
| ![PaiM 프로젝트 메모리 화면설계](desktop/assets/readme/v1.0.6-screen-memory.png) | ![PaiM GitHub 저장소 연결 화면설계](desktop/assets/readme/v1.0.6-screen-github.png) |

## 시작하기

### 데스크톱 앱 설치

1. [GitHub Releases](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-4th-1Team/releases)에서 운영체제에 맞는 설치 파일을 받습니다.
   - macOS: `.dmg`
   - Windows: `-setup.exe` 또는 `.msi`
2. PaiM을 설치하고 실행합니다.
3. 계정을 만들거나 로그인한 뒤 프로젝트를 생성합니다.
4. 문서나 회의 녹음을 추가하고, 필요하면 GitHub 저장소를 연결합니다.

> macOS에서 확인되지 않은 개발자 경고가 표시되면 **시스템 설정 → 개인정보 보호 및 보안 → 그래도 열기**를 선택하세요.

데스크톱 앱은 배포된 PaiM 서버에 연결됩니다. 사용자가 별도로 백엔드나 데이터베이스를 실행할 필요는 없습니다.

## 개발

### 데스크톱

요구사항:

- Node.js LTS
- Rust와 Cargo
- macOS: Xcode Command Line Tools
- Windows: MSVC Build Tools, WebView2

```bash
npm ci --prefix desktop
npm run demo --prefix desktop
```

프로덕션 설치본 빌드:

```bash
npm run app:build --prefix desktop
```

## 문서

- [시스템 아키텍처](docs/ARCHITECTURE.md)
- [API 명세](docs/API_명세서.md)
- [배포 운영 가이드](deploy/README.md)
- [Agentic Q&A 검증](docs/AGENTIC_QA_MVP_VALIDATION.md)
