import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import app
from backend.pipeline.converters import ConversionError, ErrorCode


_client = TestClient(app, raise_server_exceptions=False)


def _project_conn():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = {"id": 1}
    return conn


def test_query_attachment_becomes_temporary_agentic_evidence():
    encoded = base64.b64encode("첨부 전용 사실: 릴리즈명은 Nebula".encode()).decode()

    def fake_run_agentic_qa(**kwargs):
        assert kwargs["attachment_sources"] == ["attachment:note.txt"]
        assert kwargs["attachment_evidence"] == [{
            "filename": "note.txt",
            "file_type": "txt",
            "extraction_status": "ok",
            "source_location": "attachment:note.txt",
            "truncated": False,
        }]
        assert "[첨부 자료]" in kwargs["attachment_context"]
        assert "릴리즈명은 Nebula" in kwargs["attachment_context"]
        return {
            "answer": "Nebula",
            "sources": kwargs["attachment_sources"],
            "route": "semantic",
            "debug": {
                "attachments": kwargs["attachment_sources"],
                "route": "semantic",
                "router_stage": "tool_agent",
            },
        }

    with patch("backend.api.query.require_project_access"), \
         patch("backend.api.query.get_connection", return_value=_project_conn()), \
         patch("backend.api.query.run_agentic_qa", side_effect=fake_run_agentic_qa):
        response = _client.post(
            "/api/v1/projects/1/query",
            json={
                "question": "릴리즈명이 뭐야?",
                "attachments": [{"filename": "note.txt", "content_base64": encoded}],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Nebula"
    assert body["sources"] == ["attachment:note.txt"]
    assert body["route"] == "semantic"
    assert body["debug"]["router_stage"] == "tool_agent"
    assert body["debug"]["attachments"] == ["attachment:note.txt"]


def test_query_without_attachment_still_uses_agentic_orchestrator():
    captured = {}

    def fake_run_agentic_qa(**kwargs):
        captured.update(kwargs)
        return {
            "answer": "답",
            "sources": [],
            "route": "semantic",
            "debug": {"route": "semantic", "router_stage": "tool_agent"},
        }

    with patch("backend.api.query.require_project_access"), \
         patch("backend.api.query.get_connection", return_value=_project_conn()), \
         patch("backend.api.query.run_agentic_qa", side_effect=fake_run_agentic_qa):
        response = _client.post(
            "/api/v1/projects/1/query",
            json={"question": "배포 주기가 왜 바뀌었어?"},
        )

    assert response.status_code == 200
    assert captured == {
        "project_id": 1,
        "question": "배포 주기가 왜 바뀌었어?",
        "history": [],
        "attachment_context": "",
        "attachment_sources": [],
        "attachment_evidence": [],
    }


def test_model_contexts_remain_internal_to_evaluation_calls():
    from backend.api import query as query_api

    internal_result = {
        "answer": "답",
        "sources": ["meeting.md"],
        "route": "semantic",
        "debug": {
            "route": "semantic",
            "model_contexts": ["(출처: meeting.md) 공개 응답에 포함하면 안 되는 원문"],
        },
    }

    with patch("backend.api.query.require_project_access"), \
         patch("backend.api.query.get_connection", return_value=_project_conn()), \
         patch("backend.api.query.run_agentic_qa", return_value=internal_result):
        response = _client.post(
            "/api/v1/projects/1/query",
            json={"question": "현재 상태는?"},
        )

    assert response.status_code == 200
    assert "model_contexts" not in response.json()["debug"]
    assert internal_result["debug"]["model_contexts"] == [
        "(출처: meeting.md) 공개 응답에 포함하면 안 되는 원문"
    ]

    with patch("backend.api.query.get_connection", return_value=_project_conn()), \
         patch("backend.api.query.run_agentic_qa", return_value=internal_result):
        evaluation_result = query_api.execute_project_query(
            1,
            query_api.QueryRequest(question="현재 상태는?"),
        )

    assert evaluation_result["debug"]["model_contexts"] == [
        "(출처: meeting.md) 공개 응답에 포함하면 안 되는 원문"
    ]


def test_agentic_tool_failure_is_hidden_as_503_at_query_boundary():
    with patch("backend.api.query.require_project_access"), \
         patch("backend.api.query.get_connection", return_value=_project_conn()), \
         patch(
             "backend.api.query.run_agentic_qa",
             side_effect=ConnectionError("database credentials must stay private"),
         ):
        response = _client.post(
            "/api/v1/projects/1/query",
            json={"question": "현재 상태는?"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Q&A 처리 중 오류가 발생했습니다. 서버 로그를 확인하세요."
    assert "credentials" not in response.text


def test_query_attachment_context_marks_truncation(monkeypatch):
    from backend.api import query as query_api

    monkeypatch.setattr(query_api, "_ATTACHMENT_MAX_CHARS_PER_FILE", 16)
    monkeypatch.setattr(query_api, "_ATTACHMENT_MAX_CHARS_TOTAL", 30)

    encoded = base64.b64encode("12345678901234567890".encode()).decode()
    evidence = query_api._prepare_attachment_evidence([
        query_api.QueryAttachment(filename="long.md", content_base64=encoded)
    ])
    context, sources = query_api._render_attachment_evidence(evidence)

    assert sources == ["attachment:long.md"]
    assert "12345" in context
    assert "첨부 내용 잘림" in context
    assert evidence[0].truncated is True
    assert evidence[0].extraction_status == "ok"
    assert evidence[0].source_location == "attachment:long.md"
    assert len(evidence[0].content) == 16


def test_query_attachment_marks_conversion_failure(monkeypatch):
    """검증 후 추출 실패는 diagnostics에만 남고 모델 근거에서는 빠진다."""
    from backend.api import query as query_api

    monkeypatch.setattr(
        query_api,
        "convert",
        lambda *args: (_ for _ in ()).throw(
            ConversionError(ErrorCode.EMPTY_DOCUMENT, "추출 가능한 텍스트 없음")
        ),
    )
    attachment = query_api.QueryAttachment(
        filename="empty.txt",
        content_base64=base64.b64encode(b"valid text").decode(),
    )

    evidence = query_api._prepare_attachment_evidence([attachment])
    context, sources = query_api._render_attachment_evidence(evidence)

    assert evidence[0].extraction_status == "failed"
    assert evidence[0].source_location == "attachment:empty.txt"
    assert evidence[0].truncated is False
    assert sources == []
    assert context == ""
    assert evidence[0].content == ""


def test_every_decoded_attachment_is_validated_before_budget_skip(monkeypatch):
    """본문 예산이 소진돼도 뒤 첨부의 입력 경계 검증은 생략하지 않는다."""
    from backend.api import query as query_api

    monkeypatch.setattr(query_api, "_ATTACHMENT_MAX_CHARS_PER_FILE", 1)
    monkeypatch.setattr(query_api, "_ATTACHMENT_MAX_CHARS_TOTAL", 1)
    attachments = [
        query_api.QueryAttachment(
            filename="first.txt",
            content_base64=base64.b64encode(b"A").decode(),
        ),
        query_api.QueryAttachment(
            filename="invalid.txt",
            content_base64=base64.b64encode(b"\x00").decode(),
        ),
    ]

    with patch.object(query_api, "convert") as convert, pytest.raises(
        HTTPException
    ) as exc:
        query_api._prepare_attachment_evidence(attachments)

    assert exc.value.status_code == 415
    convert.assert_not_called()


def test_attachment_text_budgets_include_truncation_markers(monkeypatch):
    """파일·전체 예산 모두 최종 본문과 잘림 마커를 합친 길이에 적용된다."""
    from backend.api import query as query_api

    per_file = query_api._clip_attachment_text(
        "X" * 30,
        16,
        "첨부 내용 잘림",
    )
    assert len(per_file) == 16
    assert per_file.endswith("\n[첨부 내용 잘림]")

    monkeypatch.setattr(query_api, "_ATTACHMENT_MAX_CHARS_PER_FILE", 30)
    monkeypatch.setattr(query_api, "_ATTACHMENT_MAX_CHARS_TOTAL", 40)
    evidence = query_api._prepare_attachment_evidence([
        query_api.QueryAttachment(
            filename="first.txt",
            content_base64=base64.b64encode(b"A" * 20).decode(),
        ),
        query_api.QueryAttachment(
            filename="second.txt",
            content_base64=base64.b64encode(b"B" * 30).decode(),
        ),
    ])

    assert [len(item.content) for item in evidence] == [20, 20]
    assert sum(len(item.content) for item in evidence) == 40
    assert evidence[1].content.endswith("\n[전체 첨부 한도 초과로 잘림]")


def test_budget_exhaustion_records_skipped_diagnostic(monkeypatch):
    """예산 이후 첨부도 provenance에 남되 인용 가능한 출처로 내보내지 않는다."""
    from backend.api import query as query_api

    monkeypatch.setattr(query_api, "_ATTACHMENT_MAX_CHARS_PER_FILE", 3)
    monkeypatch.setattr(query_api, "_ATTACHMENT_MAX_CHARS_TOTAL", 3)
    evidence = query_api._prepare_attachment_evidence([
        query_api.QueryAttachment(
            filename="first.txt",
            content_base64=base64.b64encode(b"abc").decode(),
        ),
        query_api.QueryAttachment(
            filename="second.txt",
            content_base64=base64.b64encode(b"def").decode(),
        ),
    ])
    context, sources = query_api._render_attachment_evidence(evidence)

    assert [item.extraction_status for item in evidence] == [
        "ok",
        "skipped_budget",
    ]
    assert evidence[1].content == ""
    assert evidence[1].truncated is True
    assert evidence[1].debug()["extraction_status"] == "skipped_budget"
    assert sources == ["attachment:first.txt"]
    assert "second.txt" not in context


def test_empty_attachment_is_diagnostic_not_usable_source(monkeypatch):
    """성공적으로 변환됐지만 본문이 빈 첨부는 출처 목록에서 제외한다."""
    from backend.api import query as query_api

    monkeypatch.setattr(
        query_api,
        "convert",
        lambda *args: SimpleNamespace(text=" \n "),
    )
    evidence = query_api._prepare_attachment_evidence([
        query_api.QueryAttachment(
            filename="blank.txt",
            content_base64=base64.b64encode(b"valid text").decode(),
        )
    ])
    context, sources = query_api._render_attachment_evidence(evidence)

    assert evidence[0].extraction_status == "empty"
    assert evidence[0].is_usable_source is False
    assert sources == []
    assert context == ""


def test_duplicate_basenames_receive_stable_request_local_source_ids():
    """같은 basename의 첨부가 Agentic 출처 dedupe에서 하나로 합쳐지지 않는다."""
    from backend.api import query as query_api

    evidence = query_api._prepare_attachment_evidence([
        query_api.QueryAttachment(
            filename="folder/report.txt",
            content_base64=base64.b64encode(b"first report").decode(),
        ),
        query_api.QueryAttachment(
            filename=r"C:\fakepath\report.txt",
            content_base64=base64.b64encode(b"second report").decode(),
        ),
    ])
    context, sources = query_api._render_attachment_evidence(evidence)

    assert [item.filename for item in evidence] == ["report.txt", "report.txt"]
    assert [item.source_location for item in evidence] == [
        "attachment:report.txt",
        "attachment:report.txt#2",
    ]
    assert sources == ["attachment:report.txt", "attachment:report.txt#2"]
    assert "(출처: attachment:report.txt)" in context
    assert "(출처: attachment:report.txt#2)" in context
