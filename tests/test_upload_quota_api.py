import asyncio
import inspect
import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile
from fastapi.testclient import TestClient

from backend.api.documents import GitLogUpload, _process_upload_locked, upload_document, upload_git_log
from backend.pipeline.converters import convert
from backend import quota as quota_module
from backend.main import app


client = TestClient(app, raise_server_exceptions=False)
URL = "/api/v1/projects/1/documents"
FILE = {"file": ("quota.txt", b"payload", "text/plain")}


def quota_error():
    return HTTPException(
        status_code=413,
        detail={"code": "UPLOAD_QUOTA_EXCEEDED", "message": "업로드 저장 한도를 초과했습니다."},
    )


def user_error():
    return HTTPException(
        status_code=503,
        detail={"code": "UPLOAD_USER_REQUIRED", "message": "업로드 사용자를 확인할 수 없습니다."},
    )


def test_multipart_quota_rejection_has_stable_code_and_no_file_side_effect():
    with patch("backend.api.documents.require_project_access"), patch(
        "backend.api.documents.require_upload_user", return_value=1
    ), patch("backend.api.documents.reserve_document", side_effect=quota_error()), patch(
        "backend.api.documents.write_reserved_file"
    ) as write, patch("backend.api.documents.finalize_document") as finalize:
        response = client.post(URL, files=FILE)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "UPLOAD_QUOTA_EXCEEDED"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    write.assert_not_called()
    finalize.assert_not_called()


def test_dev_upload_requires_real_positive_user_before_reservation():
    with patch("backend.api.documents.require_project_access"), patch(
        "backend.api.documents.require_upload_user", side_effect=user_error()
    ), patch("backend.api.documents.reserve_document") as reserve, patch(
        "backend.api.documents.write_reserved_file"
    ) as write:
        response = client.post(URL, files=FILE)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "UPLOAD_USER_REQUIRED"
    reserve.assert_not_called()
    write.assert_not_called()


def test_git_quota_rejection_is_identical_and_does_not_extract():
    with patch("backend.api.documents.require_project_access"), patch(
        "backend.api.documents.require_upload_user", return_value=1
    ), patch("backend.api.documents.reserve_document", side_effect=quota_error()), patch(
        "backend.api.documents.extract"
    ) as extract:
        response = client.post(
            "/api/v1/projects/1/git",
            json={"content": "git content", "source": "git log"},
        )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "UPLOAD_QUOTA_EXCEEDED"
    extract.assert_not_called()


@pytest.mark.parametrize("dev_user_id", ["0", "-7", "not-an-integer"])
@pytest.mark.parametrize("endpoint_kind", ["multipart", "git"])
def test_invalid_dev_user_id_returns_upload_user_required_without_side_effects(
    monkeypatch, dev_user_id, endpoint_kind
):
    monkeypatch.setenv("PAIM_AUTH_MODE", "dev")
    monkeypatch.setenv("DEV_USER_ID", dev_user_id)

    with patch("backend.api.auth.get_connection") as auth_db, patch(
        "backend.quota.get_connection"
    ) as quota_db, patch("backend.api.documents.reserve_document") as multipart_reserve, patch(
        "backend.api.documents.write_reserved_file"
    ) as write, patch("backend.api.documents.finalize_document") as multipart_finalize, patch(
        "backend.api.documents.reserve_document"
    ) as git_reserve, patch("backend.api.documents.finalize_document") as git_finalize, patch(
        "backend.api.documents.extract"
    ) as git_extract:
        if endpoint_kind == "multipart":
            response = client.post(URL, files=FILE)
        else:
            response = client.post(
                "/api/v1/projects/1/git",
                json={"content": "git content", "source": "git log"},
            )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "UPLOAD_USER_REQUIRED"
    auth_db.assert_not_called()
    quota_db.assert_not_called()
    multipart_reserve.assert_not_called()
    write.assert_not_called()
    multipart_finalize.assert_not_called()
    git_reserve.assert_not_called()
    git_finalize.assert_not_called()
    git_extract.assert_not_called()


@pytest.mark.parametrize("user_failure", ["ensure", "missing_row"])
@pytest.mark.parametrize("endpoint_kind", ["multipart", "git"])
def test_positive_dev_user_failure_precedes_access_and_payload_side_effects(
    monkeypatch, user_failure, endpoint_kind
):
    monkeypatch.setenv("PAIM_AUTH_MODE", "dev")
    monkeypatch.setenv("DEV_USER_ID", "7")
    quota_conn = MagicMock()
    quota_cursor = quota_conn.cursor.return_value.__enter__.return_value
    quota_cursor.fetchone.return_value = None
    ensure_error = OSError("dev user upsert unavailable") if user_failure == "ensure" else None
    ensure_result = None if ensure_error else 7

    with patch(
        "backend.api.auth.ensure_dev_user",
        return_value=ensure_result,
        side_effect=ensure_error,
    ), patch("backend.quota.get_connection", return_value=quota_conn) as quota_db, patch(
        "backend.api.documents.require_project_access"
    ) as multipart_access, patch(
        "backend.api.documents.require_project_access"
    ) as git_access, patch(
        # payload 처리의 최전방. 사용자 확인이 이보다 먼저 실패해야 한다는 것이
        # 이 테스트의 계약이므로, 변환(_convert_upload)이 아니라 검증 진입점을 잡는다.
        "backend.api.documents.validate_document_bytes"
    ) as multipart_extract, patch(
        "backend.api.documents.reserve_document"
    ) as multipart_reserve, patch(
        "backend.api.documents.write_reserved_file"
    ) as write, patch(
        "backend.api.documents.finalize_document"
    ) as multipart_finalize, patch(
        "backend.api.documents.reserve_document"
    ) as git_reserve, patch(
        "backend.api.documents.finalize_document"
    ) as git_finalize, patch(
        "backend.api.documents.extract"
    ) as git_extract:
        if endpoint_kind == "multipart":
            response = client.post(URL, files=FILE)
        else:
            response = client.post(
                "/api/v1/projects/1/git",
                json={"content": "git content", "source": "git log"},
            )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "UPLOAD_USER_REQUIRED"
    multipart_access.assert_not_called()
    git_access.assert_not_called()
    multipart_extract.assert_not_called()
    multipart_reserve.assert_not_called()
    write.assert_not_called()
    multipart_finalize.assert_not_called()
    git_reserve.assert_not_called()
    git_finalize.assert_not_called()
    git_extract.assert_not_called()
    if user_failure == "ensure":
        quota_db.assert_not_called()
    else:
        quota_db.assert_called_once_with()
        quota_conn.close.assert_called_once_with()


def test_multipart_cancellation_compensates_reservation_without_masking_cancel():
    reservation = {
        "reservation_id": "multipart-cancel",
        "temp_path": "/tmp/multipart-cancel.tmp",
        "target_path": "/tmp/multipart-cancel.txt",
    }
    endpoint = inspect.unwrap(upload_document)
    upload = UploadFile(filename="cancel.txt", file=io.BytesIO(b"payload"))

    async def invoke():
        return await endpoint(
            request=None,
            project_id=1,
            background_tasks=BackgroundTasks(),
            file=upload,
            date="",
        )

    with patch("backend.api.documents.require_project_access"), patch(
        "backend.api.documents.require_upload_user", return_value=1
    ), patch("backend.api.documents.reserve_document", return_value=reservation), patch(
        "backend.api.documents.write_reserved_file", side_effect=asyncio.CancelledError()
    ), patch("backend.api.documents.cleanup_failed_reservation") as cleanup:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(invoke())
    cleanup.assert_called_once_with("multipart-cancel")


def test_git_cancellation_compensates_reservation_without_masking_cancel():
    reservation = {"reservation_id": "git-cancel"}
    endpoint = inspect.unwrap(upload_git_log)
    with patch("backend.api.documents.require_project_access"), patch(
        "backend.api.documents.require_upload_user", return_value=1
    ), patch("backend.api.documents.reserve_document", return_value=reservation), patch(
        "backend.api.documents.finalize_document", side_effect=asyncio.CancelledError()
    ), patch("backend.api.documents.cleanup_failed_reservation") as cleanup:
        with pytest.raises(asyncio.CancelledError):
            endpoint(1, GitLogUpload(content="payload"))
    cleanup.assert_called_once_with("git-cancel")


@pytest.mark.parametrize("cancel_stage", ["extract", "ingest"])
def test_multipart_post_finalize_cancellation_compensates_document(cancel_stage):
    with patch("backend.api.documents.processing_owned", return_value=True), patch(
        "backend.api.documents.extract"
    ) as extract, patch("backend.api.documents.ingest") as ingest, patch(
        "backend.api.documents.compensate_cancelled_document"
    ) as compensate, patch("backend.api.documents.cleanup_failed_reservation") as reservation_cleanup:
        extract.return_value = []
        if cancel_stage == "extract":
            extract.side_effect = asyncio.CancelledError()
        else:
            ingest.side_effect = asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            _process_upload_locked(
                project_id=1,
                doc_id=41,
                old_doc_ids=[],
                # 변환 계층 도입으로 인자가 평문 content에서 ConvertedDocument로 바뀌었다.
                # 이 테스트의 관심사는 취소 보상이므로 최소 구조만 만들어 넘긴다.
                document=convert("cancel.txt", b"payload"),
                filename="cancel.txt",
                date="",
                doc_type="meeting",
                file_path="/uploads/1/cancel.txt",
                processing_token="token-41",
            )

    compensate.assert_called_once_with(41)
    reservation_cleanup.assert_not_called()


@pytest.mark.parametrize("cancel_stage", ["extract", "ingest"])
def test_git_post_finalize_cancellation_compensates_document(cancel_stage):
    reservation = {"reservation_id": "git-finalized"}
    finalized = {
        "doc_id": 42,
        "processing_token": "token-42",
        "old_doc_ids": [],
    }
    endpoint = inspect.unwrap(upload_git_log)
    with patch("backend.api.documents.require_project_access"), patch(
        "backend.api.documents.require_upload_user", return_value=1
    ), patch("backend.api.documents.reserve_document", return_value=reservation), patch(
        "backend.api.documents.finalize_document", return_value=finalized
    ), patch("backend.api.documents.extract") as extract, patch(
        "backend.api.documents.ingest"
    ) as ingest, patch(
        "backend.api.documents.compensate_cancelled_document"
    ) as compensate, patch("backend.api.documents.cleanup_failed_reservation") as reservation_cleanup:
        extract.return_value = []
        if cancel_stage == "extract":
            extract.side_effect = asyncio.CancelledError()
        else:
            ingest.side_effect = asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            endpoint(1, GitLogUpload(content="payload"))

    compensate.assert_called_once_with(42)
    reservation_cleanup.assert_not_called()


def test_cancel_compensation_keeps_original_cancel_on_cleanup_exception():
    with patch.object(quota_module, "fail_document", side_effect=OSError("cleanup unavailable")):
        with pytest.raises(asyncio.CancelledError):
            try:
                raise asyncio.CancelledError()
            except asyncio.CancelledError:
                quota_module.compensate_cancelled_document(44)
                raise


@pytest.mark.parametrize("signal_type", [KeyboardInterrupt, SystemExit])
def test_cancel_compensation_does_not_consume_base_exception(signal_type):
    with patch.object(quota_module, "fail_document", side_effect=signal_type()):
        with pytest.raises(signal_type):
            quota_module.compensate_cancelled_document(45)


def _cleanup_conns(doc_status: str):
    """transfer_document_to_cleanup용 get_connection 목록(snapshot conn, 본 conn)."""
    snap_cur = MagicMock()
    snap_cur.fetchone.return_value = {"project_id": 1, "uploaded_by": 7}
    snap = MagicMock()
    snap.cursor.return_value.__enter__.return_value = snap_cur
    snap.cursor.return_value.__exit__.return_value = False

    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"id": 7},                       # 사용자 행 잠금
        {"id": 1},                       # 프로젝트 행 잠금
        {                                # 대상 문서
            "id": 5, "project_id": 1, "status": doc_status,
            "uploaded_by": 7, "file_path": None, "size_bytes": 0,
            "processing_token": None,
        },
    ]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    conn.cursor.return_value.__exit__.return_value = False
    return [snap, conn], cur


def test_user_delete_removes_failed_document():
    """failed 문서도 사용자 삭제로 지워져야 한다.

    delete_document는 204를 돌려주는데 행이 남아 재시도해도 지울 수 없었다. LLM 실패로
    생긴 failed 문서가 목록에 영구히 쌓이고 정리할 방법이 없다."""
    conns, cur = _cleanup_conns("failed")
    with patch.object(quota_module, "get_connection", side_effect=conns):
        project_id = quota_module.transfer_document_to_cleanup(
            5, "DOCUMENT_DELETED", delete_row=True
        )

    assert project_id == 1
    deletes = [c.args[0] for c in cur.execute.call_args_list if c.args[0].startswith("DELETE FROM documents")]
    assert deletes == ["DELETE FROM documents WHERE id=%s"]  # status 필터로 다시 막지 않는다


def test_failure_path_still_skips_already_failed_document():
    """실패 처리 경로는 이미 failed인 문서를 다시 정리 큐에 넣지 않는다(멱등성).

    위 수정이 이 구분까지 지우지 않았는지 고정한다 — 지우면 fail_document가 반복 호출될
    때마다 cleanup 행과 파일 삭제를 다시 시도한다."""
    conns, cur = _cleanup_conns("failed")
    with patch.object(quota_module, "get_connection", side_effect=conns):
        project_id = quota_module.transfer_document_to_cleanup(5, "UPLOAD_INGEST_FAILED")

    assert project_id is None
    assert not any(
        "storage_cleanup_pending" in c.args[0] for c in cur.execute.call_args_list
    )
