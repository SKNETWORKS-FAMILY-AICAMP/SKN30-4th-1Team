# PaiM FastAPI 명세서

<!-- auth-mode: jwt-fail-closed -->
<!-- updated: 2026-07-22 -->

**Base URL (로컬)**: `http://127.0.0.1:8000`  
**API Prefix**: `/api/v1` (단, GitHub App 연동 엔드포인트는 prefix 없이 `/github/app/*`)  
**Content-Type**: `application/json` (파일 업로드는 `multipart/form-data`)  
**에러 형식**: FastAPI 기본 `{"detail": "..."}`

---

## 인증·권한

> **인증 모드·갱신일 단일 출처**: 이 섹션이 인증 정책의 정본이다(위 문서
> 상단의 `auth-mode`·`updated` 표식과 값이 일치). 다른 섹션에 인증 정책을
> 중복 서술하지 않는다.

**인증 모드**: 서버는 기본적으로 **`jwt` 모드(fail-closed)** 로 동작한다
(`PAIM_AUTH_MODE=jwt`). 이 모드에서는 모든 보호 엔드포인트가 유효한 Bearer
토큰을 요구하며, 토큰이 없거나 무효면 **401**을 반환한다. `PAIM_JWT_SECRET`이
없거나 약하면(플레이스홀더·32바이트 미만) 서버 기동이 거부된다.

`PAIM_AUTH_MODE=dev`는 **로컬 개발 전용**이다. JWT 검증을 생략하고
`DEV_USER_ID` 환경변수로 단일 사용자를 대체한다(배포 금지 — 기동 시 경고 로그).

**관련 환경변수**

| 키 | 기본값 | 설명 |
|----|--------|------|
| `PAIM_AUTH_MODE` | `jwt` | `jwt`(fail-closed) 또는 `dev`(로컬 전용) |
| `PAIM_JWT_SECRET` | (없음) | HS256 서명키. jwt 모드 필수, ≥32바이트·비플레이스홀더 |
| `PAIM_JWT_TTL_HOURS` | `12` | access token 유효시간(시간) |

**요청 헤더**: 보호 엔드포인트는 `Authorization: Bearer <access_token>`를 부착한다.

모든 HTTP 응답은 서버가 생성한 `X-Request-ID` 헤더를 포함한다. JSON 오류 응답은
기존 `detail`과 함께 같은 값의 top-level `request_id`를 반환한다.

**공개 경로(토큰 불필요)**: `GET /`, `GET /health`, `GET /health/ready`, `POST /api/v1/auth/signup`,
`POST /api/v1/auth/login`, `GET /github/app/callback`(`/github/app/callback`
prefix). CORS `OPTIONS` 프리플라이트도 통과.

<!-- perms: see role-matrix -->
**프로젝트 역할 서열**: `viewer < member < admin < owner` (프로젝트별,
`project_members`). 각 엔드포인트의 최소 역할은 아래 표를 정본으로 한다. jwt
모드에서 멤버가 아니면 403(`이 프로젝트에 접근 권한이 없습니다`), 역할이
부족하면 403(`최소 '<role>' 권한이 필요합니다`). dev 모드에서 `DEV_USER_ID`가
설정돼 있으면 그 사용자의 실제 역할로 검사하고, 미설정이면 단일 사용자
동작으로 검사를 생략한다(no-op은 `DEV_USER_ID` 미설정 시에 한함).

**멤버 API 권한 요약**(회귀 기준): 멤버 목록 조회 = viewer, 멤버 초대 = owner,
역할 변경 = owner, 멤버 제거는 본인 탈퇴 = member / 타인 제거 = owner.

| 엔드포인트 | 인증 | 최소 역할 |
|-----------|------|-----------|
| `POST /api/v1/auth/signup`·`/auth/login` | 공개 | — |
| `GET /api/v1/auth/me` | 인증 | (프로젝트 무관) |
| `GET /api/v1/capabilities` | 인증 | (프로젝트 무관) |
| `GET·POST /api/v1/projects` | 인증 | (프로젝트 무관) |
| `GET /api/v1/projects/{id}` | 인증 | viewer |
| `PATCH /api/v1/projects/{id}` | 인증 | member |
| `DELETE /api/v1/projects/{id}` | 인증 | owner |
| 문서·저장소·메모리 조회(`GET`) | 인증 | viewer |
| 문서 업로드·삭제, 저장소 연결/sync/삭제 | 인증 | member |
| 메모리 `POST`·`PATCH`·`DELETE` | 인증 | member |
| `POST /api/v1/projects/{id}/query` | 인증 | viewer |
| `POST /api/v1/projects/{id}/git` | 인증 | member |
| `GET /api/v1/projects/{id}/delta` | 인증 | viewer |
| `POST /api/v1/projects/{id}/briefing/delta` | 인증 | member |
| `GET /api/v1/projects/{id}/suggestions` | 인증 | viewer |
| `POST .../suggestions/{sid}/accept`·`/reject` | 인증 | member |
| 세션 조회(`GET`) | 인증 | viewer |
| 세션 생성·수정·삭제, 세션 query | 인증 | member |
| `GET·POST /api/v1/projects/{id}/members` 등 멤버 관리 | 인증 | 아래 멤버 섹션 참조 |
| `GET /github/app/callback` | 공개 + **state 필수** | — |
| 그 외 `/github/app/*` 4개 | jwt 모드 로그인 필요 | — |

---

## 서버 상태

### `GET /`

서비스 식별 및 구동 확인.

**응답 `200`**
```json
{
  "service": "PaiM",
  "status": "ok"
}
```

---

### `GET /health`

서버 정상 구동 여부 확인 (헬스체크 전용).

**응답 `200`**
```json
{
  "status": "ok"
}
```

---

### `GET /health/ready`

MySQL, schema, ChromaDB, upload 저장소의 준비 상태를 확인한다. 인증은 필요 없다.

**응답 `200` / `503`**
```json
{
  "status": "ready",
  "components": {
    "mysql": {"status": "ok"},
    "schema": {"status": "ok"},
    "chroma": {"status": "ok"},
    "upload": {"status": "ok"}
  },
  "request_id": "<uuid>"
}
```

---

### `GET /api/v1/capabilities`

데스크톱 앱이 사용할 문서 형식과 업로드 크기 제한을 조회한다. 인증이 필요하다.

**응답 `200`**
```json
{
  "schema_version": 1,
  "project_documents": {
    "extensions": ["docx", "md", "pdf", "txt"],
    "max_file_bytes": 10485760
  },
  "query_attachments": {
    "extensions": ["docx", "md", "pdf", "txt"],
    "max_file_bytes": 8388608,
    "max_total_bytes": 8388608
  }
}
```

---

## 인증 API

### `POST /api/v1/auth/signup`

회원가입. 성공 시 access token과 사용자 정보를 반환한다. (공개)

**요청 Body**
```json
{
  "email": "a@b.c",
  "password": "at-least-8-chars",
  "name": "이름"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `email` | string | ✅ | 3~255자, `@` 포함 |
| `password` | string | ✅ | 8~128자 (UTF-8 72바이트 초과 시 400) |
| `name` | string | ✅ | 1~255자 |

**응답 `201`**
```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "user": { "id": 1, "email": "a@b.c", "name": "이름" }
}
```

**응답 `400`** — 이메일 형식 오류 / 비밀번호 길이 초과  
**응답 `409`**
```json
{ "detail": "이미 가입된 이메일입니다." }
```
**응답 `503`** — `PAIM_JWT_SECRET` 미설정/약함 (계정은 생성되지 않음)

---

### `POST /api/v1/auth/login`

로그인. 성공 시 signup과 동일한 형태를 반환한다. (공개)

**요청 Body**
```json
{ "email": "a@b.c", "password": "..." }
```

**응답 `200`** — signup과 동일한 `{ access_token, token_type, user }`

**응답 `401`**
```json
{ "detail": "이메일 또는 비밀번호가 올바르지 않습니다." }
```

> 미가입/비밀번호 불일치 모두 동일한 401 메시지 — 계정 존재 여부 노출 방지.
> 프론트에서 사유를 세분화하지 말 것.

---

### `GET /api/v1/auth/me`

현재 토큰의 사용자 정보 조회. (인증 필요)

**응답 `200`**
```json
{
  "id": 1,
  "email": "a@b.c",
  "name": "이름",
  "created_at": "2026-07-01T12:00:00"
}
```

**응답 `401`** — 토큰 없음/무효/만료, 또는 존재하지 않는 사용자

---

## 프로젝트

### `POST /api/v1/projects`

프로젝트 생성.

**요청 Body**
```json
{
  "name": "PaiM MVP"
}
```

**응답 `201`**
```json
{
  "id": 1,
  "name": "PaiM MVP",
  "created_at": "2026-07-01T12:00:00"
}
```

---

### `GET /api/v1/projects`

프로젝트 목록 조회 (최신순).

**응답 `200`**
```json
[
  {
    "id": 1,
    "name": "PaiM MVP",
    "created_at": "2026-07-01T12:00:00"
  }
]
```

---

### `GET /api/v1/projects/{project_id}`

프로젝트 단건 조회.

**응답 `200`**
```json
{
  "id": 1,
  "name": "PaiM MVP",
  "created_at": "2026-07-01T12:00:00"
}
```

**응답 `404`**
```json
{ "detail": "Project not found" }
```

---

### `PATCH /api/v1/projects/{project_id}`

프로젝트 이름 수정. (최소 역할: member)

**요청 Body**
```json
{ "name": "새 이름" }
```

**응답 `200`**
```json
{
  "id": 1,
  "name": "새 이름",
  "created_at": "2026-07-01T12:00:00"
}
```

**응답 `400`** — 빈 이름  
**응답 `404`** — 프로젝트 없음

---

### `DELETE /api/v1/projects/{project_id}`

프로젝트 삭제. (최소 역할: **owner** — 공유 멤버 전체의 데이터를 지우므로)
하위 문서·저장소·메모리·세션·멤버십과 Vector DB·원본 파일을 함께 삭제한다.

**응답 `204`** (No Content)

**응답 `404`** — 프로젝트 없음

---

## 문서

### `POST /api/v1/projects/{project_id}/documents`

문서 업로드. 서버가 파일을 저장하고 텍스트 추출 → 청킹 → Vector DB → LLM 추출 → DB 저장을 처리한다.

**요청** `multipart/form-data`

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `file` | File | ✅ | `.md` / `.markdown` / `.txt` / `.docx` / `.pdf` (최대 10 MB) |
| `date` | string | - | 문서 날짜 `YYYY-MM-DD` |

> **멀티포맷 지원 (2026-07-25)**: `.docx`와 텍스트 기반 PDF를 지원합니다. 스캔 이미지 PDF(OCR)는
> 지원하지 않으며 `no_text_layer` 오류로 거절됩니다. 전처리 규칙은 [문서 전처리 정책서](DOCUMENT_INGESTION_POLICY.md) 참고.

> **`doc_type` 변경 (2026-07-02)**: 프론트에서 전송하지 않습니다. 서버가 파일명 기반으로 자동 추론합니다.
> - `회의`, `meeting`, `minutes` 포함 → `meeting`
> - `기획`, `plan`, `planning`, `roadmap`, `spec` 포함 → `planning`
> - 그 외 → `document`

**응답 `201`**
```json
{
  "doc_id": 12,
  "status": "processing",
  "format": "pdf",
  "blocks": 87,
  "pages": 12,
  "warnings": [
    { "code": "table_flattened",
      "message": "표를 행 단위 텍스트로 변환했습니다. 열 구조는 보존되지 않습니다.",
      "location": "table 2" }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `format` | string | `docx` / `pdf` / `text` |
| `blocks` | int | 추출된 문단·표행 수 |
| `pages` | int\|null | PDF 페이지 수. DOCX·평문은 `null` |
| `warnings` | array | 변환 경고 목록(비치명적 손실). 없으면 `[]` |

`warnings[]` 원소는 `{ code, message, location }`입니다. **`location`은 `null`일 수 있습니다.**

| `code` | 의미 | `location` |
|--------|------|-----------|
| `page_no_text` | 해당 페이지에서 텍스트를 추출하지 못함 | `page N` |
| `page_extract_failed` | 해당 페이지 파싱 실패 | `page N` |
| `table_flattened` | 표를 행 단위 텍스트로 평탄화(열 구조 유실) | `table N` |
| `unsupported_element` | 이미지·도형·텍스트 상자 등 비텍스트 요소 유실 | `null` |
| `unsupported_element` | 중첩 깊이 상한(5단) 초과 표의 내용 유실 | `table N` |
| `repeated_line_dropped` | 머리말·꼬리말로 판단해 제거(개수 요약 1건) | `null` |
| `duplicate_block_dropped` | 중복 문단 제거(**개수 요약 1건**) | `null` |
| `decode_fallback` | UTF-8 실패로 다른 인코딩 사용 | `null` |

> **변환 경고**: 변환은 요청 경로에서 수행되므로 폴링 없이 즉시 확인할 수 있습니다.
> `duplicate_block_dropped`와 `repeated_line_dropped`는 블록마다 발생해도 **개수만
> 요약한 1건**으로 반환됩니다(`location` 없음). 나머지는 위치마다 별도 항목입니다.
> 각 규칙의 판정 기준은 [문서 전처리 정책서](DOCUMENT_INGESTION_POLICY.md) 참고.

**응답 `400`** — 미지원 확장자
```json
{ "detail": "지원하지 않는 파일 형식입니다. (.docx / .markdown / .md / .pdf / .txt)",
  "code": "unsupported_format" }
```

**응답 `400`** — 변환 실패
```json
{
  "detail": "PDF에서 텍스트를 추출하지 못했습니다. 스캔 이미지 PDF는 지원하지 않습니다.",
  "code": "no_text_layer"
}
```

`detail`은 **문자열**(사람이 읽는 사유), `code`는 응답 **최상위**의 기계 판독용 식별자입니다.
`code`는 아래 중 하나입니다.

| `code` | 의미 | 사용자 조치 |
|--------|------|-------------|
| `unsupported_format` | 등록되지 않은 확장자 | 지원 포맷으로 변환 후 재업로드 |
| `missing_dependency` | 서버에 변환 라이브러리 미설치 | 운영자 문의 |
| `corrupt_file` | 파일을 열 수 없음, 암호 보호 PDF | 원본 확인 / 암호 해제 |
| `empty_document` | 추출된 텍스트가 0건 | 내용이 있는 문서인지 확인 |
| `no_text_layer` | PDF 전 페이지에 텍스트 레이어 없음 | 스캔본 대신 원본 PDF 사용 |
| `file_too_large` | 구조는 정상이나 안전 처리 한도 초과 | 문서를 나누거나 내용을 줄여 재업로드 |

> `file_too_large`는 `corrupt_file`과 **구분해서 표시**해야 합니다. 파일이 손상된 것이
> 아니라 크기·압축률 한도를 넘은 것이므로, "손상"으로 안내하면 사용자가 복구·재다운로드
> 같은 불필요한 조치를 하게 됩니다. HTTP 상태는 다른 변환 실패와 동일하게 `400`입니다
> (`413`은 업로드 원본이 10 MB를 넘는 경우 전용).

**응답 `415`** — 입력 경계 위반 (형식·내용 불일치)
```json
{
  "detail": { "code": "INVALID_DOCUMENT_CONTENT",
              "message": "PDF 확장자와 실제 파일 형식이 일치하지 않습니다." },
  "request_id": "<uuid>"
}
```

`400`(변환 실패)과 **성격이 다릅니다.** `415`는 파일을 파서에 넘기기 **전에** 걸러낸
경우입니다.

| 상황 | 예 |
|------|-----|
| 확장자와 실제 형식 불일치 | `.pdf`인데 `%PDF-`로 시작하지 않음, `.docx`인데 ZIP이 아님 |
| 지원하지 않는 문자 인코딩 | `.txt`/`.md`가 UTF-8·CP949 어느 쪽으로도 디코딩되지 않음 |
| 바이너리·과다 제어 문자 | NUL 포함, 제어 문자 비율 2% 초과 |

`415`의 `detail`은 **객체**(`{code, message}`)이고 `400`의 `detail`은 **문자열**입니다.
두 형식이 다른 것은 의도된 것이며, 데스크톱 클라이언트(`desktop/src/paimApi.ts`)는
양쪽을 모두 읽습니다.

**구분 기준**: 매직 바이트 검사를 통과했는지가 경계입니다.

| 입력 | 결과 |
|------|------|
| `%PDF-`로 시작하지 않는 `.pdf` | `415` |
| `%PDF-`는 맞으나 내부 파싱 실패 | `400 corrupt_file` |
| `PK\x03\x04`로 시작하지 않는 `.docx` | `415` |
| ZIP은 맞으나 DOCX 구조 손상 | `400 corrupt_file` |
| ZIP은 맞으나 압축 해제 한도 초과 | `400 file_too_large` |

> **`detail`을 객체로 바꾸지 마세요.** 데스크톱 클라이언트(`desktop/src/paimApi.ts`)는
> `detail`이 문자열이 아니면 사유를 버리고 `"PaiM API 요청 실패"`만 표시합니다.
> 구조화 정보가 필요하면 최상위 필드로 추가하세요.

**응답 `404`**
```json
{ "detail": "Project not found" }
```

**응답 `413`**
```json
{ "detail": "파일 크기는 10 MB를 초과할 수 없습니다." }
```

> **처리 흐름**: 업로드 즉시 `processing` 반환 → 백그라운드 처리 완료 후 `indexed` 또는 `failed` 로 상태 갱신.

---

### `GET /api/v1/projects/{project_id}/documents`

문서 목록 조회.

**응답 `200`**
```json
[
  {
    "id": 12,
    "filename": "planning.pdf",
    "doc_type": "planning",
    "status": "indexed",
    "uploaded_at": "2026-07-01T12:00:00"
  }
]
```

---

### `GET /api/v1/projects/{project_id}/documents/{doc_id}/status`

문서 처리 상태 조회. 데스크톱 앱이 폴링으로 사용.

**상태값**

| 값 | 의미 |
|----|------|
| `uploaded` | 업로드 완료, 처리 대기 |
| `processing` | 처리 중 |
| `indexed` | 처리 완료 |
| `failed` | 처리 실패 |

**응답 `200`**
```json
{
  "doc_id": 12,
  "status": "indexed",
  "extracted": {
    "decision": 2,
    "action": 4,
    "issue": 1,
    "risk": 1
  }
}
```

**응답 `404`**
```json
{ "detail": "Document not found" }
```

---

### `DELETE /api/v1/projects/{project_id}/documents/{doc_id}`

문서 삭제. 아래 데이터를 함께 삭제한다.

- 문서 메타데이터 (DB)
- 해당 문서에서 생성된 Project Memory (DB)
- 해당 문서의 Vector DB chunks
- 서버에 저장한 원본 파일

**응답 `204`** (No Content)

**응답 `404`**
```json
{ "detail": "Document not found" }
```

---

## Git Repository

### `POST /api/v1/projects/{project_id}/repositories`

GitHub repository 연결. MVP는 public repo만 지원.

**요청 Body**
```json
{
  "provider": "github",
  "repository_url": "https://github.com/org/repo",
  "branch": "main"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `provider` | string | ✅ | `github` 고정 (MVP) |
| `repository_url` | string | ✅ | public GitHub repo URL |
| `branch` | string | - | 미지정 시 default branch 사용 |

**응답 `201`**
```json
{
  "repo_id": 3,
  "status": "connected",
  "branch": "main"
}
```

**응답 `400`**
```json
{ "detail": "Invalid repository URL" }
```

> 연결 후 서버가 README / commits / issues / PRs 수집 → 처리 시작.

---

### `GET /api/v1/projects/{project_id}/repositories`

연결된 repository 목록 조회.

**응답 `200`**
```json
[
  {
    "id": 3,
    "provider": "github",
    "repository_url": "https://github.com/org/repo",
    "branch": "main",
    "status": "indexed",
    "connected_at": "2026-07-01T12:00:00"
  }
]
```

---

### `GET /api/v1/projects/{project_id}/repositories/{repo_id}`

Repository 단건 조회.

**응답 `200`**
```json
{
  "id": 3,
  "provider": "github",
  "repository_url": "https://github.com/org/repo",
  "branch": "main",
  "status": "indexed",
  "commit_sha": "abc123",
  "indexed_files": 3,
  "sync_warning": null,
  "connected_at": "2026-07-01T12:00:00"
}
```

---

### `GET /api/v1/projects/{project_id}/repositories/{repo_id}/status`

Repository sync 상태 조회. 데스크톱 앱이 폴링으로 사용.

**상태값**

| 값 | 의미 |
|----|------|
| `connected` | 연결 완료, 수집 대기 |
| `syncing` | 수집 및 처리 중 |
| `indexed` | 처리 완료 |
| `failed` | 처리 실패 |

**응답 `200`**
```json
{
  "repo_id": 3,
  "status": "indexed",
  "provider": "github",
  "repository_url": "https://github.com/org/repo",
  "branch": "main",
  "commit_sha": "abc123",
  "indexed_files": 3,
  "last_error": null,
  "sync_warning": null,
  "extracted": {
    "decision": 3,
    "action": 7,
    "issue": 4,
    "risk": 2
  }
}
```

---

### `POST /api/v1/projects/{project_id}/repositories/{repo_id}/sync`

Repository 재동기화 요청.

**응답 `202`**
```json
{
  "repo_id": 3,
  "status": "syncing"
}
```

---

### `DELETE /api/v1/projects/{project_id}/repositories/{repo_id}`

Repository 연결 해제. 아래 데이터를 함께 삭제한다.

- repo 연결 정보 (DB)
- 해당 repo에서 생성된 Project Memory (DB)
- 해당 repo의 Vector DB chunks
- 서버에 캐시한 repo 파일

**응답 `204`** (No Content)

**응답 `404`**
```json
{ "detail": "Repository not found" }
```

---

## Project Memory

LLM이 문서 또는 repository에서 추출한 구조화된 프로젝트 기억.

**카테고리**: `decision` / `action` / `issue` / `risk`

### `GET /api/v1/projects/{project_id}/memory`

Memory 목록 조회.

**Query Parameters**

| 파라미터 | 타입 | 설명 |
|---------|------|------|
| `category` | string | `decision` \| `action` \| `issue` \| `risk` |
| `owner` | string | 담당자 이름 필터 |

**응답 `200`**
```json
[
  {
    "id": 1,
    "project_id": 1,
    "doc_id": 12,
    "repo_id": null,
    "category": "action",
    "content": "API 규약을 정리한다",
    "owner": "지훈",
    "date": "2026-06-30",
    "topic": "API 설계",
    "reason": null,
    "source": "planning.pdf",
    "created_by": "llm",
    "updated_by": null,
    "is_user_verified": false,
    "created_at": "2026-07-01T12:00:00",
    "source_info": {
      "kind": "document",
      "doc_id": 12,
      "repo_id": null,
      "type": "meeting",
      "path": "planning.pdf",
      "ref": null,
      "url": null
    }
  }
]
```

---

### `POST /api/v1/projects/{project_id}/memory`

Memory 항목 수동 추가.

**요청 Body**
```json
{
  "category": "action",
  "content": "배포 전 보안 점검 수행",
  "owner": "지훈",
  "date": "2026-07-05",
  "topic": "배포 준비"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `category` | string | ✅ | `decision`/`action`/`issue`/`risk` |
| `content` | string | ✅ | |
| `owner` | string | - | 담당자 |
| `date` | string | - | `YYYY-MM-DD` |
| `due_date` | string | - | 마감일 `YYYY-MM-DD` (주로 `action`) |
| `topic` | string | - | |
| `reason` | string | - | |

**응답 `201`** — 생성된 memory row(DB raw). `due_date`·`completed_at`·
`sort_order` 등 컬럼을 포함하나, **`source_info`는 포함되지 않는다** — 이
중첩 객체는 `GET .../memory` 목록에서만 계산돼 붙는다. 수동 생성은
`created_by: "user"`, `is_user_verified: true`.
```json
{
  "id": 99,
  "category": "action",
  "content": "배포 전 보안 점검 수행",
  "owner": "지훈",
  "date": "2026-07-05",
  "due_date": "2026-07-10",
  "topic": "배포 준비",
  "reason": null,
  "created_by": "user",
  "updated_by": null,
  "is_user_verified": true,
  "completed_at": null,
  "created_at": "2026-07-01T12:00:00"
}
```

---

### `PATCH /api/v1/projects/{project_id}/memory/{memory_id}`

Memory 항목 수정. (최소 역할: member) 수정할 필드만 부분 전송한다(PATCH 시맨틱).
의미 필드(`category`/`content`/`owner`/`date`/`due_date`/`topic`/`reason`)를 수정하면
`is_user_verified: true`로 마킹되어 LLM 재처리 시 덮어쓰지 않는다.
`due_date`를 직접 설정하거나 해제하면 해당 action에 남아 있던 pending
`set_due_date` 제안은 자동으로 거절 처리된다.

**요청 Body** (수정할 필드만 포함)
```json
{
  "content": "API 규약을 이번 주 내로 정리한다",
  "owner": "지훈",
  "due_date": "2026-07-12",
  "completed": true,
  "sort_order": 3
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `category`·`content`·`owner`·`date`·`topic`·`reason` | string | 의미 필드(부분 수정). 이 중 하나라도 바뀌면 `is_user_verified: true` |
| `due_date` | string \| null | 마감일. `null`이면 마감 해제 |
| `completed` | boolean | `true`→`completed_at = NOW()`, `false`→`completed_at = NULL`. `null` 전송은 400 |
| `sort_order` | integer \| null | 표시 정렬 순서. 명시적 `null` 전송 시 정렬값 해제 |

> **`completed` ↔ `completed_at`**: 요청은 boolean `completed`로 보내지만
> 저장·응답은 timestamp `completed_at`으로 표현된다. `completed: true`면
> `completed_at`이 현재 시각으로, `false`면 `null`로 설정된다.
>
> 수정할 필드가 하나도 없으면 **400**(`수정할 필드가 없습니다.`).
> `category`를 `decision` 밖으로 바꾸는 변경이 supersede 관계와 충돌하면 **409**
> (상세는 [HANDOVER_SUPERSEDE_FRONTEND.md](HANDOVER_SUPERSEDE_FRONTEND.md) §4).

**응답 `200`**
```json
{
  "id": 1,
  "category": "action",
  "content": "API 규약을 이번 주 내로 정리한다",
  "owner": "지훈",
  "date": "2026-06-30",
  "topic": "API 설계",
  "updated_by": "user",
  "is_user_verified": true
}
```

**응답 `404`**
```json
{ "detail": "Memory item not found" }
```

---

### `DELETE /api/v1/projects/{project_id}/memory/{memory_id}`

Memory 항목 삭제.

**응답 `204`** (No Content)

**응답 `404`**
```json
{ "detail": "Memory item not found" }
```

---

## 멤버 관리

프로젝트별 멤버·역할 관리. 역할 서열은 `viewer < member < admin < owner`.
`owner`는 프로젝트 생성 시에만 부여되며 API로 두 번째 owner를 만들거나
이관할 수 없다. 할당 가능한 role은 `viewer`/`member`/`admin`.

### `GET /api/v1/projects/{project_id}/members`

멤버 목록 조회. (최소 역할: viewer)

**응답 `200`**
```json
[
  {
    "user_id": 1,
    "email": "a@b.c",
    "name": "이름",
    "role": "owner",
    "created_at": "2026-07-01T12:00:00",
    "last_seen_at": null
  }
]
```

---

### `POST /api/v1/projects/{project_id}/members`

멤버 추가. (최소 역할: **owner**) 대상은 이미 가입된 사용자여야 한다.

**요청 Body**
```json
{ "email": "new@b.c", "role": "member" }
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `email` | string | ✅ | 가입된 사용자 이메일 |
| `role` | string | - | `viewer`/`member`/`admin` (기본 `member`) |

**응답 `201`**
```json
{ "user_id": 5, "email": "new@b.c", "name": "새 멤버", "role": "member" }
```

**응답 `400`** — 허용되지 않는 role  
**응답 `404`** — 해당 이메일로 가입된 사용자 없음  
**응답 `409`** — 이미 이 프로젝트의 멤버

---

### `PATCH /api/v1/projects/{project_id}/members/{member_user_id}`

멤버 역할 변경. (최소 역할: **owner**)

**요청 Body**
```json
{ "role": "admin" }
```

**응답 `200`**
```json
{ "user_id": 5, "role": "admin" }
```

**응답 `400`** — 허용되지 않는 role / 자신의 역할 변경 시도  
**응답 `403`** — owner의 역할은 변경 불가  
**응답 `404`** — 이 프로젝트의 멤버가 아님

---

### `DELETE /api/v1/projects/{project_id}/members/{member_user_id}`

멤버 제외. **권한 규칙**: owner는 다른 멤버를 제외할 수 있고, owner가 아닌
멤버는 **자기 자신만** 제외(프로젝트 탈퇴)할 수 있다. 즉 **본인 탈퇴 = member,
타인 제거 = owner**. (엔드포인트 진입 최소 역할: member)

**응답 `204`** (No Content)

**응답 `400`** — owner는 탈퇴 불가(프로젝트 삭제 이용)  
**응답 `403`** — 다른 멤버 제외는 owner 권한 필요 / owner는 제외 불가  
**응답 `404`** — 이 프로젝트의 멤버가 아님

---

## 제안 (Suggestions)

LLM이 만든 메모리 변경 제안(pending)을 사람이 승인/거절한다. `kind`는
`complete_action`(액션 완료), `set_due_date`(상대 마감일 후보 확정) 또는
`supersede`(결정 번복). 상세 supersede 계약·에러는
[HANDOVER_SUPERSEDE_FRONTEND.md](HANDOVER_SUPERSEDE_FRONTEND.md).

### `GET /api/v1/projects/{project_id}/suggestions`

제안 목록 조회. (최소 역할: viewer)

**Query Parameters**

| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `status` | string | `pending` | `pending`/`accepted`/`rejected` |
| `kind` | string | `complete_action` | `complete_action`/`set_due_date`/`supersede`/`all`. 구 클라이언트 보호를 위해 기본은 `complete_action`만 |

**응답 `200`**
```json
[
  {
    "id": 8,
    "project_id": 1,
    "memory_id": 10,
    "kind": "complete_action",
    "evidence": { "type": "pr", "number": 42, "title": "...", "url": "...", "merged_at": "..." },
    "rationale": "...",
    "confidence": "high",
    "status": "pending",
    "created_at": "2026-07-02T10:00:00",
    "resolved_at": null,
    "resolved_by": null
  }
]
```

`set_due_date`의 `evidence` 예:

```json
{
  "type": "due_date",
  "suggested_due_date": "2026-08-07",
  "raw_text": "다음 주 금요일까지",
  "reference_date": "2026-07-30",
  "source": "회의록.md"
}
```

연도·월·일이 원문에 모두 명시된 action 마감은 제안 없이 즉시 `memory.due_date`에
저장된다. 상대 또는 연도 생략 표현은 기준일로 단일 날짜를 계산할 수 있고 원문 구절이
실제 입력에 존재할 때만 `set_due_date` pending 제안이 생성된다. 단일 후보를 정할 수
없는 표현은 날짜를 만들지 않고 action `content`에만 보존한다.

**응답 `400`** — 잘못된 `status`/`kind`  
**응답 `404`** — 프로젝트 없음

---

### `POST /api/v1/projects/{project_id}/suggestions/{suggestion_id}/accept`

제안 승인. (최소 역할: member) `complete_action`은 대상 action을 완료 처리,
`set_due_date`는 아직 마감이 없는 action에 제안 날짜를 설정하고,
`supersede`는 대상 decision을 번복 처리한다.

**응답 `200`** — 갱신된 suggestion 객체(위 목록 항목과 동일 스키마, `status: "accepted"`)

**응답 `400`** — 이미 해소된 제안 / 지원하지 않는 kind  
**응답 `409`** — 제안 생성 후 action 마감이 다른 값으로 변경됨, supersede 대상/대체 결정 충돌, 동시 경합 (상세: supersede 핸드오버 §4)
**응답 `404`** — 제안 없음

---

### `POST /api/v1/projects/{project_id}/suggestions/{suggestion_id}/reject`

제안 거절. (최소 역할: member)

**응답 `200`** — 갱신된 suggestion 객체(`status: "rejected"`)

**응답 `400`** — 이미 해소된 제안  
**응답 `409`** — 동시 경합  
**응답 `404`** — 제안 없음

---

## 델타 (Delta)

지난 확인 이후의 변화 집계·브리핑.

### `GET /api/v1/projects/{project_id}/delta`

델타 배너 데이터(LLM 없이 SQL 집계). (최소 역할: viewer)

**Query Parameters**

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| `since` | string | ✅ | ISO8601 기준 시각 |
| `due_within_days` | integer | - | 마감 임박 판정 일수(1~7, 기본 3) |

**응답 `200`**
```json
{
  "since": "2026-07-01T00:00:00",
  "new_memory": { "decision": 1, "action": 2, "issue": 0, "risk": 0 },
  "pending_suggestions": 1,
  "pending_suggestions_by_kind": { "complete_action": 1, "supersede": 1 },
  "completed_actions": 2,
  "due_soon": [ { "id": 3, "content": "...", "owner": "지훈", "due_date": "2026-07-05" } ],
  "overdue": []
}
```

**응답 `400`** — `since`가 ISO8601 아님  
**응답 `404`** — 프로젝트 없음

---

### `POST /api/v1/projects/{project_id}/briefing/delta`

델타 브리핑 생성(LLM). (최소 역할: member)

**요청 Body**
```json
{ "since": "2026-07-01T00:00:00" }
```

**응답 `200`**
```json
{ "answer": "지난 확인 이후 ...", "sources": [] }
```

> 변화가 없으면 `{ "answer": "지난 확인 이후 새 변화가 없습니다.", "sources": [] }`.

**응답 `400`** — `since`가 ISO8601 아님  
**응답 `404`** — 프로젝트 없음

---

## Git 로그 업로드

### `POST /api/v1/projects/{project_id}/git`

Git 로그 텍스트를 동기 처리해 메모리로 추출·적재한다. (최소 역할: member)
문서 상태 추적(`documents.status`)은 없다.

**요청 Body**
```json
{ "content": "커밋 로그 텍스트", "source": "git log", "date": "2026-07-05" }
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `content` | string | ✅ | git 로그 원문 |
| `source` | string | - | 출처 라벨 (기본 `git log`) |
| `date` | string | - | `YYYY-MM-DD` |

**응답 `201`**
```json
{ "doc_id": 42, "extracted": { "decision": 1, "action": 3, "issue": 0, "risk": 0 } }
```

**응답 `400`** — 빈 content  
**응답 `404`** — 프로젝트 없음

---

## 채팅 세션

> **경로 확정 (2026-07-02)**: 세션 엔드포인트는 `/api/v1/projects/{id}/sessions/*` 로 확정되었습니다.

### `POST /api/v1/projects/{project_id}/sessions`

채팅 세션 생성.

**요청 Body**
```json
{ "title": "스프린트 3 리뷰" }
```

**응답 `201`**
```json
{
  "id": "sess_a1b2c3d4e5f6",
  "project_id": 1,
  "title": "스프린트 3 리뷰",
  "created_at": "2026-07-02T10:00:00",
  "updated_at": "2026-07-02T10:00:00"
}
```

---

### `GET /api/v1/projects/{project_id}/sessions`

세션 목록 조회 (최신순).

**응답 `200`**
```json
[
  {
    "id": "sess_a1b2c3d4e5f6",
    "project_id": 1,
    "title": "스프린트 3 리뷰",
    "created_at": "2026-07-02T10:00:00",
    "updated_at": "2026-07-02T10:00:00"
  }
]
```

---

### `PATCH /api/v1/projects/{project_id}/sessions/{session_id}`

세션 제목 수정.

**요청 Body**
```json
{ "title": "새 제목" }
```

**응답 `200`** — 수정된 세션 객체 반환

**응답 `404`**
```json
{ "detail": "해당 프로젝트에서 요청하신 세션을 찾을 수 없습니다." }
```

---

### `DELETE /api/v1/projects/{project_id}/sessions/{session_id}`

세션 삭제. 하위 메시지(`chat_messages`)와 요약(`chat_summaries`)도 함께 삭제됨.

**응답 `204`** (No Content)

**응답 `404`**
```json
{ "detail": "해당 프로젝트에서 요청하신 세션을 찾을 수 없습니다." }
```

---

### `GET /api/v1/projects/{project_id}/sessions/{session_id}/messages`

세션 메시지 이력 조회. 메시지 본문은 AES-256-GCM으로 저장되며 응답 시 복호화됨.

**응답 `200`**
```json
[
  {
    "id": 1,
    "role": "user",
    "text": "로그인 기능은 왜 제외했나요?",
    "token_count": 12,
    "created_at": "2026-07-02T10:00:00"
  },
  {
    "id": 2,
    "role": "assistant",
    "text": "MVP 범위에서 제외됐습니다...",
    "token_count": 47,
    "created_at": "2026-07-02T10:00:01"
  }
]
```

---

### `POST /api/v1/projects/{project_id}/sessions/{session_id}/query`

세션 기반 Agentic 대화형 질의. 암호화된 대화 이력과 롤링 요약을 컨텍스트로 사용하고, 프로젝트 질의와 같은 읽기 전용 근거 도구로 답변을 생성함.

**요청 Body**
```json
{
  "current_question": "현재 가장 큰 리스크가 뭐야?",
  "rag_context": ""
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `current_question` | string | 현재 질문 |
| `rag_context` | string | 이번 질의 전용 RAG 참고 평문 (선택, 저장하지 않음) |

**응답 `200`**
```json
{
  "status": "success",
  "session_id": "sess_a1b2c3d4e5f6",
  "answer": "현재 가장 큰 리스크는 API 계약 변경 가능성입니다."
}
```

**응답 `503`**
```json
{ "detail": "LLM 응답 생성 중 오류가 발생했습니다. 서버 로그를 확인하세요." }
```

---

## 질의 (Q&A)

### `POST /api/v1/projects/{project_id}/query`

프로젝트 기반 자연어 질의. (최소 역할: viewer)

**요청 Body**
```json
{
  "question": "현재 가장 큰 리스크가 뭐야?",
  "history": [
    { "role": "user", "content": "이전 질문" },
    { "role": "assistant", "content": "이전 답변" }
  ],
  "attachments": [
    { "filename": "meeting.md", "content_base64": "<base64>" }
  ]
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `question` | string | ✅ | 질문 |
| `history` | array | - | `{role, content}` 대화 이력 |
| `attachments` | array | - | 첨부 자료 `{filename, content_base64}`. `.md`/`.markdown`/`.txt`/`.docx`/`.pdf`, **파일당 최대 8 MB · 전체 합계 8 MB** |

> **`attachments`**: 형식·크기를 검증하고 텍스트를 추출한 뒤, 같은 Agentic Q&A 실행의
> 이번 질문 전용 임시 근거로 전달한다. 별도 라우트나 영구 저장 분기는 없다. 형식 미지원 시
> **400**, 내용 불일치 시 **415**, 8 MB 초과 시 **413**.
> 첨부 상한(`QUERY_ATTACHMENT_MAX_FILE_BYTES` = 8 MB)은 문서 업로드 상한
> (`PROJECT_DOCUMENT_MAX_FILE_BYTES` = 10 MB)과 다른 값이다.

**응답 `200`**
```json
{
  "answer": "현재 가장 큰 리스크는 API 계약 변경 가능성입니다. (출처: planning.pdf)",
  "plan": [],
  "sources": ["planning.pdf", "meeting_notes.md"],
  "route": "semantic",
  "debug": {
    "router_stage": "tool_agent",
    "tools_used": ["search_project_evidence"],
    "tool_rounds": 1,
    "filters": { "category": null },
    "mysql_rows": [
      { "category": "risk", "content": "...", "source": "planning.pdf", "source_label": "planning.pdf" }
    ],
    "chroma_chunks": [
      { "text": "...(200자)", "source": "planning.pdf", "source_label": "planning.pdf", "date": "2026-06-30" }
    ]
  }
}
```

> **`route`**: 기존 클라이언트 호환을 위해 이 엔드포인트는 항상 `semantic`을 반환한다.
> 질문 유형은 Agentic 오케스트레이터가 `search_project_evidence`,
> `query_structured_memory`, `get_project_overview`를 필요에 따라 조합해 처리한다.
> 사용한 도구와 라운드는 `debug.tools_used`/`debug.tool_rounds`에서 확인할 수 있으며,
> 검색 도구에 따라 `debug.mysql_rows`/`debug.chroma_chunks`가 포함될 수 있다.
>
> **`plan`**: 하위호환을 위해 유지하는 필드이며 현재 기본 Agentic Q&A에서는 빈 배열 `[]`이다.
>
> **`answer` 출처 마커 (2026-07-22 추가)**: 답변 본문에 근거의 출처가
> `(출처: 파일명)` 형태로 포함된다. 프론트는 이 마커를 파싱해 출처 칩/링크로
> 렌더링하거나 그대로 표시할 수 있다(선택). 저장소 연결 파일은 동명 충돌
> 방지를 위해 `(출처: 파일명 (repo#N))` 형태가 될 수 있다. 상세는 프론트
> 핸드오버 [HANDOVER_CITATION_FRONTEND.md](HANDOVER_CITATION_FRONTEND.md).
>
> **`sources`**: 변경 없음 — 답변 근거로 검색된 출처 파일명 리스트. `answer`
> 마커와 별개로 그대로 제공된다.
>
> **`debug.*.source_label` (2026-07-22 추가)**: `mysql_rows[]`·`chroma_chunks[]`에
> 충돌 없는 출처 라벨이 추가됐다(additive — 무시 가능). `answer` 마커가 이
> 라벨을 사용한다.

**응답 `503`**
```json
{ "detail": "Q&A 처리 중 오류가 발생했습니다. 서버 로그를 확인하세요." }
```

---

## GitHub App 연동

GitHub App 설치 세션 흐름. **경로에 `/api/v1` prefix가 없다** (`/github/app/*`).
`callback`을 제외한 4개는 jwt 모드에서 **로그인(Bearer)** 이 필요하다. 세션 state는
서버 메모리에 보관되며 TTL이 지나면 만료된다.

### `POST /github/app/sessions`

설치 세션 생성. (jwt 모드 로그인 필요, state 입력 없음)

**응답 `201`**
```json
{
  "state": "<opaque-token>",
  "status": "pending",
  "installUrl": "https://github.com/apps/.../installations/new?state=...",
  "expiresIn": 1800
}
```

---

### `GET /github/app/sessions/{state}`

세션 상태 조회. (jwt 모드 로그인 필요 + state 필수)

**응답 `200`**
```json
{ "state": "<token>", "status": "connected", "setupAction": "install" }
```
> `status`는 설치 완료 전 `pending`, 완료 후 `connected`.

**응답 `404`** — 존재하지 않는 state · **응답 `410`** — 만료된 state

---

### `GET /github/app/sessions/{state}/repositories`

설치된 저장소 목록. (jwt 모드 로그인 필요 + state 필수)

**응답 `200`**
```json
{
  "repositories": [
    {
      "fullName": "org/repo",
      "name": "repo",
      "private": false,
      "defaultBranch": "main",
      "url": "https://github.com/org/repo",
      "owner": { "login": "org", "avatarUrl": "https://...", "htmlUrl": "https://github.com/org", "name": null }
    }
  ],
  "user": { "login": "org", "avatarUrl": "https://...", "htmlUrl": "https://github.com/org", "name": null }
}
```

| 필드 | 설명 |
|------|------|
| `repositories[].owner` | 소유자 프로필 `{login, avatarUrl, htmlUrl, name}`. login 없으면 `null` |
| `user` | 대표 소유자 프로필(위와 동일 구조). **선택된 저장소가 없으면 `repositories: []`, `user: null`** — 프론트는 null 가드 필요 |

**응답 `404`** 미지 state · **`410`** 만료 state · **`409`** 설치 미완료
(`GitHub App installation is not complete` — callback 전이라 installation_id 없음)

---

### `POST /github/app/repository-preview`

저장소 미리보기(최근 활동 요약). (jwt 모드 로그인 필요, state 선택)

**요청 Body**
```json
{ "repository_url": "https://github.com/org/repo", "state": "<token-선택>" }
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `repository_url` | string | ✅ | GitHub repo URL |
| `state` | string | - | 있으면 설치 토큰으로 private repo 접근 |

**응답 `200`**
```json
{
  "events": [
    { "id": "commit-abc123", "type": "commit", "title": "커밋 메시지", "createdAt": 1719900000000, "status": "abc123", "url": "https://github.com/org/repo/commit/abc123" }
  ],
  "repository": {
    "path": "https://github.com/org/repo",
    "name": "repo",
    "branch": "main",
    "isDirty": false,
    "remoteRepo": "org/repo",
    "issuePrStatus": "2 open issues · 1 open PRs",
    "visibility": "public",
    "authProvider": "public"
  }
}
```

| 필드 | 설명 |
|------|------|
| `events[]` | 최근 commit/issue/pull_request 이벤트 최대 10건. `type`은 `commit`/`issue`/`pull_request`, `createdAt`은 epoch ms |
| `repository.visibility` | `public` \| `private` |
| `repository.authProvider` | `public`(무토큰) \| `github_app`(state로 설치 토큰 사용) |

**응답 `400`** — 잘못된 repo URL  
**응답 `401`**
```json
{ "detail": "Private repository requires GitHub App login" }
```
> private repo인데 `state`(설치 토큰)가 없으면 401.

**응답 `404`** 미지 state · **`410`** 만료 state · **`409`** 설치 미완료 —
`state`를 넘긴 경우 위 세션 오류가 그대로 전파된다(설치 토큰 발급 단계).

---

### `GET /github/app/callback`

GitHub 설치 완료 후 리다이렉트되는 콜백. **공개(무인증)이나 `state` 쿼리
파라미터가 필수**다. 사용자 브라우저에서 직접 열리므로 `Authorization` 헤더가
붙지 않는다. 응답은 `text/html`(JSON 아님).

**Query Parameters**

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| `state` | string | ✅ | 세션 state. 없으면 400 |
| `installation_id` | integer | ✅ | GitHub 설치 ID. 없으면 400 |
| `setup_action` | string | - | GitHub이 전달하는 설치 액션 |

**응답 `200`** — `text/html` (앱으로 복귀 안내 페이지)

**응답 `400`**
```json
{ "detail": "state is required" }
```
> `installation_id` 누락 시에도 400. **`404`** — 존재하지 않는 state,
> **`410`** — 만료된 state(TTL 초과).

---

## 공통 에러 코드

| 상태 코드 | 의미 |
|----------|------|
| `400` | 잘못된 요청 (빈 content, 잘못된 날짜 형식 등) |
| `401` | 인증 실패 (토큰 없음/무효/만료, 로그인 실패) |
| `403` | 권한 없음 (프로젝트 비멤버 또는 최소 역할 미달) |
| `404` | 리소스 없음 |
| `409` | 충돌 (중복 멤버, supersede 경합, 동시 해소 등) |
| `422` | Pydantic 유효성 검사 실패 |
| `503` | LLM / 외부 서비스 오류, 또는 `PAIM_JWT_SECRET` 미설정/약함 |

---

## 구현 현황

> 갱신: 2026-07-22 (TASK-010 반영 — 누락 20 operation·인증/권한·query
> attachments·memory 필드 문서화. 전체 46 operation, origin/main `5240f40` 기준)

| 엔드포인트 | 상태 |
|-----------|------|
| `GET /` | ✅ 구현 완료 |
| `GET /health` | ✅ 구현 완료 |
| `GET /health/ready` | ✅ 구현 완료 |
| `POST /api/v1/projects` | ✅ 구현 완료 (DEV user 시 project_members 자동 등록) |
| `GET /api/v1/projects` | ✅ 구현 완료 (DEV user 시 membership JOIN 필터) |
| `GET /api/v1/projects/{id}` | ✅ 구현 완료 |
| `POST /api/v1/projects/{id}/documents` | ✅ 구현 완료 (BackgroundTask async) |
| `GET /api/v1/projects/{id}/documents` | ✅ 구현 완료 |
| `GET /api/v1/projects/{id}/documents/{doc_id}/status` | ✅ 구현 완료 (last_error 포함) |
| `DELETE /api/v1/projects/{id}/documents/{doc_id}` | ✅ 구현 완료 (memory + chroma + file cleanup) |
| `POST /api/v1/projects/{id}/repositories` | ✅ 구현 완료 (async sync 시작) |
| `GET /api/v1/projects/{id}/repositories` | ✅ 구현 완료 |
| `GET /api/v1/projects/{id}/repositories/{repo_id}` | ✅ 구현 완료 (sync_warning 포함) |
| `POST .../repositories/{repo_id}/sync` | ✅ 구현 완료 (기존 index 삭제 후 재수집) |
| `GET .../repositories/{repo_id}/status` | ✅ 구현 완료 (last_error, sync_warning 포함) |
| `DELETE .../repositories/{repo_id}` | ✅ 구현 완료 (memory + chroma cleanup) |
| `GET /api/v1/projects/{id}/memory` | ✅ 구현 완료 (source_info 중첩 객체 포함) |
| `POST /api/v1/projects/{id}/memory` | ✅ 구현 완료 |
| `PATCH /api/v1/projects/{id}/memory/{memory_id}` | ✅ 구현 완료 |
| `DELETE /api/v1/projects/{id}/memory/{memory_id}` | ✅ 구현 완료 |
| `POST /api/v1/projects/{id}/query` | ✅ 구현 완료 |
| `POST /api/v1/projects/{id}/sessions` | ✅ 구현 완료 (require_project_access member) |
| `GET /api/v1/projects/{id}/sessions` | ✅ 구현 완료 (require_project_access viewer) |
| `PATCH /api/v1/projects/{id}/sessions/{sid}` | ✅ 구현 완료 |
| `DELETE /api/v1/projects/{id}/sessions/{sid}` | ✅ 구현 완료 (messages + summaries cascade) |
| `GET /api/v1/projects/{id}/sessions/{sid}/messages` | ✅ 구현 완료 (AES-256-GCM 복호화) |
| `POST /api/v1/projects/{id}/sessions/{sid}/query` | ✅ 구현 완료 (롤링 요약, 토큰 예산 관리) |
| `POST /api/v1/auth/signup` | ✅ 구현 완료 (공개) |
| `POST /api/v1/auth/login` | ✅ 구현 완료 (공개) |
| `GET /api/v1/auth/me` | ✅ 구현 완료 (인증) |
| `PATCH /api/v1/projects/{id}` | ✅ 구현 완료 (member) |
| `DELETE /api/v1/projects/{id}` | ✅ 구현 완료 (owner) |
| `GET /api/v1/projects/{id}/members` | ✅ 구현 완료 (viewer) |
| `POST /api/v1/projects/{id}/members` | ✅ 구현 완료 (owner) |
| `PATCH /api/v1/projects/{id}/members/{member_user_id}` | ✅ 구현 완료 (owner) |
| `DELETE /api/v1/projects/{id}/members/{member_user_id}` | ✅ 구현 완료 (본인 탈퇴 member / 타인 제거 owner) |
| `GET /api/v1/projects/{id}/suggestions` | ✅ 구현 완료 (viewer) |
| `POST /api/v1/projects/{id}/suggestions/{sid}/accept` | ✅ 구현 완료 (member) |
| `POST /api/v1/projects/{id}/suggestions/{sid}/reject` | ✅ 구현 완료 (member) |
| `GET /api/v1/projects/{id}/delta` | ✅ 구현 완료 (viewer) |
| `POST /api/v1/projects/{id}/briefing/delta` | ✅ 구현 완료 (member) |
| `POST /api/v1/projects/{id}/git` | ✅ 구현 완료 (member) |
| `POST /github/app/sessions` | ✅ 구현 완료 (로그인) |
| `GET /github/app/sessions/{state}` | ✅ 구현 완료 (로그인 + state) |
| `GET /github/app/sessions/{state}/repositories` | ✅ 구현 완료 (로그인 + state) |
| `POST /github/app/repository-preview` | ✅ 구현 완료 (로그인) |
| `GET /github/app/callback` | ✅ 구현 완료 (공개 + state, text/html) |

---

## 응답 필드 노트

### documents/{doc_id}/status 응답

`last_error` 필드가 추가됨. 처리 실패 시 오류 메시지 포함, 성공 시 null.

```json
{
  "doc_id": 12,
  "status": "failed",
  "last_error": "텍스트 추출 실패: 빈 파일",
  "extracted": { "decision": 0, "action": 0, "issue": 0, "risk": 0 }
}
```

### repositories/{repo_id}/status 응답

`last_error`, `sync_warning` 필드가 추가됨.

```json
{
  "repo_id": 3,
  "status": "indexed",
  "provider": "github",
  "repository_url": "https://github.com/org/repo",
  "branch": "main",
  "commit_sha": "abc123",
  "indexed_files": 3,
  "last_error": null,
  "sync_warning": "[{\"source_type\": \"issues\", \"reason\": \"GitHub API 응답 오류\"}]",
  "extracted": { "decision": 3, "action": 7, "issue": 4, "risk": 2 }
}
```

- `last_error`: 전체 실패 원인. 성공 시 null
- `sync_warning`: 부분 실패 목록 (JSON string). 일부 GitHub API 호출 실패 시 설정. 완전 성공 시 null. 새 sync 시작 시 초기화됨

### memory 응답 — 구조 (코드 기준 정정)

응답은 **배열** (`[ {...} ]`). `{ items: [] }` 래퍼 없음.

- `doc_id`, `repo_id`, `source`(문자열) — 최상위 필드
- `source_info` — 출처 상세 객체 (추가 제공, 무시 가능)

```json
[
  {
    "id": 1,
    "project_id": 1,
    "doc_id": 12,
    "repo_id": null,
    "source": "planning.pdf",
    "source_info": {
      "kind": "document",
      "doc_id": 12,
      "repo_id": null,
      "type": "meeting",
      "path": "planning.pdf",
      "ref": null,
      "url": null
    }
  }
]
```

- `source_info.kind`: `"document"` 또는 `"repository"`
- `source_info.ref`: repository 출처인 경우 commit SHA
- `source_info.url`: repository 출처인 경우 GitHub 파일 URL
- 출처 정보가 없으면 각 필드 `null`

---

## 상태 폴링 흐름

### 문서 처리

```
POST /documents → { "doc_id": N, "status": "processing" }
  → GET /documents/{N}/status 폴링
  → status: "processing" → 계속 대기
  → status: "indexed"    → 처리 완료
  → status: "failed"     → last_error 확인
```

### Repository sync

```
POST /repositories 또는 /repositories/{id}/sync → { "status": "syncing" }
  → GET /repositories/{id}/status 폴링
  → status: "syncing" → 계속 대기
  → status: "indexed" → 완료 (sync_warning 확인 권장)
  → status: "failed"  → last_error 확인
```

---

## 주의 사항

1. `sync_warning`은 JSON-encoded string (null 또는 `"[{...}]"`) — 프론트에서 파싱 필요
2. 서버 재시작 시 30분 이상 stale `processing`/`syncing` → 자동으로 `failed`로 전환 (`BACKGROUND_TASK_STALE_MINUTES` 설정)
3. 인증·권한 정책은 상단 [인증·권한](#인증권한) 섹션이 정본이다(중복 서술 금지).
