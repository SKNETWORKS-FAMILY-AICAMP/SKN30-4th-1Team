# 문서 형식·업로드 제한 단일 기준화 변경 제안서

- 상태: 팀 리뷰 요청
- 백엔드 브랜치: `codex/document-capabilities-backend`
- 프론트 브랜치: `codex/runtime-capabilities-frontend`
- 대상: PaiM 백엔드 API, 데스크톱 앱
- 제외 범위: CORS, 배포 토폴로지, 인증 방식, Caddy 설정 변경

## 1. 제안 요약

백엔드가 실제로 처리할 수 있는 문서 형식과 크기 제한을 단일 레지스트리에서
관리하고, 데스크톱 앱은 인증 후 `GET /api/v1/capabilities`를 호출해 그 값을
사용한다.

현재 데스크톱은 DOCX를 선택할 수 있지만 `main` 백엔드는 DOCX를 거부한다.
지원 확장자도 파일 선택창과 검증 함수에 중복돼 있어 백엔드에 파서를 추가해도
기존 데스크톱에는 반영되지 않는다.

제안하는 기준:

| 용도 | 형식 | 파일당 제한 | 전체 제한 |
|---|---|---:|---:|
| 프로젝트 문서 | MD, TXT, PDF, DOCX | 10 MiB | 해당 없음 |
| 질의 첨부 | MD, TXT, PDF, DOCX | 8 MiB | 8 MiB |

DOCX는 실제 파서와 회귀 테스트가 포함된 경우에만 capabilities에 노출한다.

## 2. 해결해야 하는 문제

### 2.1 프론트와 백엔드의 지원 형식 불일치

- 기존 데스크톱: `md`, `txt`, `pdf`, `docx`
- 기존 백엔드: `.md`, `.txt`, `.pdf`

사용자는 DOCX를 정상적으로 선택한 뒤 서버에서 400을 받는다. 파일 선택창이 서버의
실제 처리 능력을 반영하지 못한다.

### 2.2 서버 내부 기준 분산

기존 `query.py`는 `upload.py`의 `_ALLOWED_SUFFIXES`, `_MAX_FILE_BYTES`,
`_extract_text`를 import한다. API 모듈이 다른 API 모듈의 private 구현에
의존하므로 제한을 독립적으로 변경하기 어렵고 확장자 기준도 재사용하기 어렵다.

### 2.3 Caddy 제한과 질의 첨부 크기 불일치

질의 첨부는 JSON의 `content_base64`로 전송된다. base64는 원본을 약 4/3로
팽창시킨다.

```text
10 MiB × 4 / 3 = 약 13.33 MiB
```

이는 질문, 대화 기록, JSON 문법을 더하기 전부터 Caddy의 12 MB 요청 제한보다
크다. 프론트의 10 MiB 검사를 통과해도 백엔드에 도달하기 전에 거절될 수 있다.

## 3. 제안 구조

```text
backend/document_content.py
 ├─ DOCUMENT_PARSERS
 ├─ 프로젝트/질의 크기 제한
 ├─ 확장자 검증과 오류 문구
 └─ MD/TXT/PDF/DOCX 파서
          │
          ├── upload.py: 서버 재검증 및 파싱
          ├── query.py: decoded 합계 검증 및 파싱
          └── capabilities.py: 동일 레지스트리와 제한을 응답

GET /api/v1/capabilities
          │
          └── desktop/src/capabilities.ts
                 ├─ 파일 선택 필터
                 ├─ 드래그앤드롭 검증
                 ├─ 프로젝트 업로드 검증
                 ├─ 질의 첨부 검증
                 └─ 지원 형식 및 MiB 안내
```

capabilities는 별도 수동 확장자 목록을 갖지 않는다. API 응답과 서버 검증이 모두
`DOCUMENT_PARSERS`에서 확장자를 파생한다.

## 4. API 계약

```http
GET /api/v1/capabilities
Authorization: Bearer <PaiM access token>
```

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

계약 규칙:

- 확장자는 점을 제외한 소문자이며 항상 정렬한다.
- 크기는 정수 byte 단위다.
- `schema_version`이 다르면 클라이언트는 응답을 임의 해석하지 않는다.
- capabilities는 UX 설정이며 서버 검증을 생략하게 하는 권한 토큰이 아니다.
- 기존 인증 미들웨어를 통과하며 프로젝트별 권한은 요구하지 않는다.

## 5. 백엔드 변경

### 5.1 파서 레지스트리

```python
DOCUMENT_PARSERS = {
    ".md": read_text,
    ".txt": read_text,
    ".pdf": read_pdf,
    ".docx": read_docx,
}
```

허용 확장자, capabilities 응답, 오류 메시지, 파서 선택은 모두 이 레지스트리에서
파생한다. Content-Type은 클라이언트가 지정할 수 있으므로 신뢰하지 않고 정규화한
파일명 확장자로 서버 파서를 선택한다.

### 5.2 프로젝트 문서 제한

기존 동작을 유지해 파일당 10 MiB로 설정한다. 프론트가 제한을 표시하더라도 서버는
파일을 읽은 뒤 byte 길이를 다시 검사한다.

### 5.3 질의 첨부 제한

파일당 및 전체 decoded 합계를 모두 8 MiB로 설정한다.

```text
8 MiB × 4 / 3 = 약 10.67 MiB
```

Caddy의 12 MB 제한 아래에 질문, 대화 기록, JSON 문법을 위한 여유를 남긴다.
텍스트 컨텍스트가 이미 가득 찬 경우에도 남은 첨부를 디코딩하고 합계에 포함해
순서 기반 우회를 막는다.

### 5.4 DOCX 처리

DOCX는 ZIP/XML 형식이므로 UTF-8 텍스트처럼 decode하지 않는다. `python-docx`로
문단과 표를 원문 순서대로 추출한다.

포함된 방어:

- 유효한 ZIP인지 사전 검사
- 단일 압축 항목과 전체 전개 크기 제한
- 비정상 압축률 제한
- 손상된 DOCX를 구조화된 415 오류로 정규화
- 실제 DOCX 본문 및 표 추출 테스트

현재 제한:

- 이미지와 도형의 비텍스트 정보는 추출하지 않는다.
- 복잡한 중첩 표와 스타일 의미는 완전히 보존하지 않는다.
- `origin/KDH`의 전체 블록/출처 추적 변환기를 통합한 것은 아니다.

DOCX를 정식 지원으로 확정하기 전 KDH 변환기의 출처 추적 구조를 현재 ingest
파이프라인에 포함할지 별도 리뷰가 필요하다.

## 6. 데스크톱 변경

- 로그인 및 서버 연결 후 capabilities를 조회한다.
- 서버 주소 변경 시 이전 응답을 즉시 폐기하고 새 서버에서 재조회한다.
- 조회 실패 시 하드코딩 목록으로 폴백하지 않고 파일 선택을 비활성화한다.
- 오류와 재시도 버튼을 표시한다.
- 서버 확장자를 두 파일 선택창, 드래그앤드롭, 프로젝트 업로드, 질의 첨부 검증에
  공통 적용한다.
- 프로젝트 화면에 파일당 10 MiB를 표시한다.
- 채팅 첨부 화면에 파일당·전체 8 MiB를 표시한다.
- 확장자별 MIME 하드코딩을 제거하고 `application/octet-stream`을 사용한다.

## 7. 변경 파일

### 백엔드 PR

- `backend/document_content.py`
- `backend/api/capabilities.py`
- `backend/api/upload.py`
- `backend/api/query.py`
- `backend/main.py`
- `pyproject.toml`
- `requirements.txt`
- `uv.lock`
- `tests/test_document_capabilities.py`
- `docs/DOCUMENT_CAPABILITIES_CHANGE_PROPOSAL.md`

### 프론트 PR

- `desktop/src/capabilities.ts`
- `desktop/src/App.tsx`
- `desktop/scripts/layout-smoke.mjs`

## 8. 검증 결과

| 명령 | 결과 |
|---|---|
| `npm run build --prefix desktop` | 통과 |
| `npm run test:offline --prefix desktop` | 통과 |
| `npm run test:layout --prefix desktop` | 통과 |
| 전체 pytest | 602 통과, 2 스킵, 6 실패 |

전체 pytest 실패 6건은 기존 macOS 배포 스크립트에서 재현된다.

```text
env: unsetenv nset=DB_NAME: Invalid argument
```

실패 위치는 `tests/test_deploy_stack.py`이며 이번 변경 경로와 관련이 없다.

## 9. 배포와 롤백

배포 순서:

1. 백엔드 PR 병합 및 배포
2. 운영 환경에서 인증된 capabilities 호출 확인
3. 데스크톱 PR 병합 및 배포

데스크톱을 먼저 배포하면 capabilities가 404로 실패해 파일 선택이 비활성화된다.
따라서 백엔드 선배포가 필수다.

롤백:

- 데스크톱만 롤백: capabilities API가 남아 있어도 영향 없음
- 백엔드만 롤백: 새 데스크톱의 파일 선택이 중단되므로 권장하지 않음
- 전체 롤백: 백엔드와 데스크톱을 함께 이전 버전으로 복구

## 10. 보안 검토

- 프론트 검증은 UX 보조이며 서버 검증을 대체하지 않는다.
- Content-Type은 신뢰하지 않는다.
- 기존 `safe_upload_name` 정규화를 유지한다.
- DOCX는 파싱 전에 ZIP 전개 크기와 압축률을 검사한다.
- base64는 엄격하게 디코딩하며 잘못된 입력은 400으로 처리한다.
- 질의 첨부 합계는 decoded byte 기준으로 검사한다.

## 11. 팀 결정 요청

1. capabilities와 공통 파서 레지스트리를 백엔드 표준으로 채택할지
2. 질의 첨부 파일당·전체 제한을 8 MiB로 확정할지
3. DOCX 최소 파서를 먼저 배포할지, KDH 전체 변환기를 통합한 뒤 광고할지
4. capabilities를 API 명세에 추가하고 OpenAPI에 노출할지
5. 백엔드 PR을 먼저 병합한 뒤 프론트 PR을 병합하는 순서를 승인할지

권장안:

- capabilities와 8 MiB 제한은 우선 반영한다.
- DOCX는 실제 테스트를 통과했지만 정식 지원 선언 전 KDH 출처 추적 통합 여부를
  리뷰한다.
- capabilities endpoint를 API 명세와 OpenAPI에 함께 노출한다.
- 백엔드와 프론트 PR을 분리하고 백엔드를 먼저 병합한다.
