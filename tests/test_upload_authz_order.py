"""업로드 인가가 본문 소비보다 먼저 일어나는지 고정한다 (F-012).

`AuthMiddleware` 는 무인증 요청을 라우팅 전에 막는다. 그러나 **로그인만 되어 있으면
해당 프로젝트의 구성원이 아니어도** 엔드포인트 본문까지 도달한다. 인가가
`await file.read()` 뒤에 있으면 그 사용자가 요청 본문 전체를 Python 메모리로 올릴 수
있고, 크기 상한 검사조차 read() 뒤라 상한 초과 요청도 전부 읽은 뒤에야 413 이 나간다.

**상태 코드만 확인하는 테스트로는 이 회귀를 잡을 수 없다.** 인가가 뒤에 있어도
결국 403 을 반환하기 때문이다. 그래서 `UploadFile.read` 가 호출되지 않았음을 단언한다.

Starlette multipart 파서는 엔드포인트 호출 전에 `write()`·`seek()` 를 쓰지만
`read()` 는 호출하지 않는다. 따라서 `read` 감시가 "엔드포인트가 본문을 메모리로
읽었는가"를 정확히 가린다.

한계: FastAPI 는 `UploadFile` 의존성을 만들려고 진입 전에 multipart 를 파싱·스풀한다.
이 테스트는 "메모리로 다시 읽는 것"까지만 검증한다. 네트워크 수신·임시 파일 스풀
차단은 별도 ASGI/프록시 작업의 몫이다.
"""
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from backend.main import app

_client = TestClient(app, raise_server_exceptions=False)
_URL = "/api/v1/projects/1/documents"
_FILE = ("spec.md", b"body that must not be read", "text/plain")


def _forbidden(*args, **kwargs):
    """인증은 됐으나 해당 프로젝트 구성원이 아닌 상태."""
    raise HTTPException(status_code=403, detail="이 프로젝트에 접근 권한이 없습니다")


def test_non_member_upload_does_not_read_body():
    """비구성원 업로드가 거부되고, 그 시점에 본문을 메모리로 읽지 않는다."""
    with patch("backend.api.upload.require_upload_user", return_value=1), \
         patch("backend.api.upload.require_project_access", side_effect=_forbidden), \
         patch.object(UploadFile, "read", new_callable=AsyncMock) as read:
        resp = _client.post(_URL, files={"file": _FILE}, data={"date": ""})

    assert resp.status_code == 403
    # 핵심 단언 — 인가가 read() 뒤로 돌아가면 여기서 실패한다.
    read.assert_not_awaited()


def test_unauthenticated_upload_does_not_read_body():
    """사용자 해석 자체가 실패해도 본문을 읽지 않는다."""
    def _no_user(*args, **kwargs):
        raise HTTPException(status_code=401, detail="인증이 필요합니다")

    with patch("backend.api.upload.require_upload_user", side_effect=_no_user), \
         patch.object(UploadFile, "read", new_callable=AsyncMock) as read:
        resp = _client.post(_URL, files={"file": _FILE}, data={"date": ""})

    assert resp.status_code == 401
    read.assert_not_awaited()


def test_member_upload_still_reads_body():
    """정상 구성원 경로에서는 본문을 읽는다 — 순서 이동이 기능을 막지 않았다."""
    with patch("backend.api.upload.require_upload_user", return_value=1), \
         patch("backend.api.upload.require_project_access"), \
         patch.object(UploadFile, "read", new_callable=AsyncMock,
                      return_value=b"x") as read:
        _client.post(_URL, files={"file": _FILE}, data={"date": ""})

    read.assert_awaited()
