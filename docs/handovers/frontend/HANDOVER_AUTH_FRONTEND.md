# 인증·권한(다중 사용자) — 프론트엔드 핸드오버

- 작성: 2026-07-15, 백엔드 TASK-001 완료 기준 (브랜치 `develop/hyseo`, 검증 PASS)
- 대상 독자: 데스크톱(desktop/) 작업자

## 0. 가장 중요한 사실

**지금 데스크톱에는 백엔드 로그인 연동이 없다** (App.tsx의 token은 전부 GitHub
연동용). 현재 동작하는 이유는 서버가 `PAIM_AUTH_MODE=dev`(JWT 검증 꺼짐 +
`DEV_USER_ID` 대체)로 떠 있기 때문이다. **jwt 모드로 전환하는 순간, 로그인 UI가
없는 데스크톱은 모든 보호 API에서 401을 받는다.** 즉 로그인/토큰 작업은
supersede UI보다 우선순위가 높은 프론트 작업이다.

## 1. 동작 모드

| 모드 | 서버 동작 | 용도 |
|---|---|---|
| `PAIM_AUTH_MODE=dev` (현행) | JWT 검증 안 함, `DEV_USER_ID`로 사용자 대체 | 로컬 개발 전용. **배포 금지** (서버가 기동 시 경고 로그) |
| `PAIM_AUTH_MODE=jwt` | Bearer 토큰 필수. `PAIM_JWT_SECRET` 미설정/약하면 서버가 기동 거부 | 실서비스 |

## 2. 인증 API

```
POST /api/v1/auth/signup   (201)   body: { email, password, name }
POST /api/v1/auth/login    (200)   body: { email, password }
GET  /api/v1/auth/me       (200)   현재 토큰의 사용자 정보
```

signup/login 성공 응답(동일 형태):

```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "user": { "id": 1, "email": "a@b.c", "name": "이름" }
}
```

- 로그인 실패는 이유 불문 **동일 401 메시지**("이메일 또는 비밀번호가 올바르지
  않습니다") — 계정 존재 여부 노출 방지 설계라 프론트에서 세분화하지 말 것.
- **refresh 토큰 없음** — 만료되면 401("토큰이 만료되었습니다. 다시 로그인해주세요.")
  → 재로그인 화면으로 보내는 게 정답.

## 3. 모든 보호 API 공통 규칙

- 요청 헤더: `Authorization: Bearer <access_token>` — **모든 API 호출에 부착**.
- 공개 경로(토큰 불필요): `/`, `/health`, `/api/v1/auth/signup`,
  `/api/v1/auth/login`, `/github/app/callback*` (OPTIONS 프리플라이트도 통과).
- 401 두 종류: "로그인이 필요합니다"(토큰 없음/무효) / "토큰이 만료되었습니다…"
  — 둘 다 처리 방식은 같음: 토큰 폐기 후 로그인 화면.
- 권장 구현: fetch 래퍼/인터셉터 한 곳에서 헤더 부착 + 401 공통 처리.

## 4. 권한(역할) 모델

역할 서열: `viewer < member < admin < owner` (프로젝트별, `project_members`).

- 403 두 종류: "이 프로젝트에 접근 권한이 없습니다"(비멤버) /
  "최소 '<role>' 권한이 필요합니다"(권한 부족) — UI에서 버튼 비활성화 근거로 사용.
- 대략의 기준: **조회 = viewer**, **상태 변경(제안 accept/reject, memory
  PATCH/DELETE, 업로드 등) = member**, **멤버 초대·역할 변경 = owner**.
  화면별 정확한 요구 역할은 API 호출해보고 403 메시지로 확인 가능.

## 5. 멤버 관리 API (신규 화면 필요)

```
GET    /api/v1/projects/{id}/members                  (viewer)  멤버 목록
POST   /api/v1/projects/{id}/members                  (owner)   멤버 추가
PATCH  /api/v1/projects/{id}/members/{member_user_id} (owner)   역할 변경
DELETE /api/v1/projects/{id}/members/{member_user_id}           제거
```

- **DELETE 권한 규칙**: 엔드포인트 진입은 member 이상이지만, **본인 탈퇴는
  member**, **다른 멤버 제거는 owner**만 가능하다(owner가 아닌 사용자가 타인을
  제거하면 403). owner 본인은 탈퇴 불가(400 — 프로젝트 삭제를 이용).

## 6. 채팅 세션 격리 (동작 변화)

- 채팅 세션에 `user_id`가 기록되고, **본인 세션만** 조회/접근된다
  (마이그레이션 이전의 레거시 세션은 `user_id`가 NULL이라 멤버 전원 접근 허용).
- UI 영향: 같은 프로젝트라도 사용자마다 세션 목록이 다르게 보이는 게 정상.

## 7. 프론트 작업 체크리스트

1. 로그인/회원가입 화면 + `access_token` 저장(Tauri 보안 저장소 권장, localStorage 지양)
2. 공통 fetch 래퍼: Authorization 헤더 부착 + 401 → 토큰 폐기·로그인 화면
3. 앱 시작 시 `GET /auth/me`로 세션 복원, 실패 시 로그인 화면
4. 403 처리: 권한 부족 안내 + 해당 액션 버튼 역할 기반 비활성화
5. 멤버 관리 화면(목록/초대/역할 변경/제거 — owner 중심)
6. 로그아웃 = 로컬 토큰 삭제 (서버 무상태, 별도 API 없음)

## 8. 전환 시점 협의 필요

- jwt 모드 전환은 **프론트 로그인 작업 완료와 동시에** 해야 한다(먼저 켜면 앱 전체 401).
- `PAIM_JWT_SECRET` 발급·보관 방식(≥32바이트, 플레이스홀더 금지), 토큰 TTL
  (`PAIM_JWT_TTL_HOURS`, 기본 12시간) 협의.
- CORS는 tauri origin이 이미 허용 목록에 있음(`tauri://localhost` 등).

## 9. 관련 문서

- supersede 기능 계약: [HANDOVER_SUPERSEDE_FRONTEND.md](HANDOVER_SUPERSEDE_FRONTEND.md)
- 과거 백엔드 변경 정리: [BACKEND_CHANGES_SUMMARY.md](../../archive/integration/2026-07/BACKEND_CHANGES_SUMMARY.md)
