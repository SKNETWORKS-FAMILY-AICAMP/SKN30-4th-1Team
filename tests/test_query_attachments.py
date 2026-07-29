import base64
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app


_client = TestClient(app, raise_server_exceptions=False)


def _project_conn():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = {"id": 1}
    return conn


def test_query_attachment_becomes_temporary_agentic_evidence():
    encoded = base64.b64encode("첨부 전용 사실: 릴리즈명은 Bluefin".encode()).decode()

    def fake_run_agentic_qa(**kwargs):
        assert kwargs["attachment_sources"] == ["note.txt"]
        assert "[첨부 자료]" in kwargs["attachment_context"]
        assert "릴리즈명은 Bluefin" in kwargs["attachment_context"]
        return {
            "answer": "Bluefin",
            "sources": kwargs["attachment_sources"],
            "route": "semantic",
            "debug": {"attachments": kwargs["attachment_sources"]},
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
    assert body["answer"] == "Bluefin"
    assert body["sources"] == ["note.txt"]
    assert body["route"] == "semantic"
    assert body["debug"]["router_stage"] == "tool_agent"
    assert body["debug"]["attachments"] == ["note.txt"]


def test_query_without_attachment_still_uses_agentic_orchestrator():
    captured = {}

    def fake_run_agentic_qa(**kwargs):
        captured.update(kwargs)
        return {"answer": "답", "sources": [], "route": "semantic", "debug": {}}

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
    }


def test_legacy_routing_mode_cannot_bypass_agentic_runtime():
    with patch("backend.api.query.require_project_access"), \
         patch("backend.api.query.get_connection", return_value=_project_conn()), \
         patch.dict("os.environ", {"PAIM_QUERY_ROUTING_MODE": "legacy"}), \
         patch(
             "backend.api.query.run_agentic_qa",
             return_value={"answer": "답", "sources": [], "route": "semantic", "debug": {}},
         ) as run_agentic_qa:
        response = _client.post(
            "/api/v1/projects/1/query",
            json={"question": "현재 상태는?"},
        )

    assert response.status_code == 200
    run_agentic_qa.assert_called_once()


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

    monkeypatch.setattr(query_api, "_ATTACHMENT_MAX_CHARS_PER_FILE", 5)
    monkeypatch.setattr(query_api, "_ATTACHMENT_MAX_CHARS_TOTAL", 20)

    encoded = base64.b64encode("1234567890".encode()).decode()
    context, sources = query_api._prepare_attachment_context([
        query_api.QueryAttachment(filename="long.md", content_base64=encoded)
    ])

    assert sources == ["long.md"]
    assert "12345" in context
    assert "첨부 내용 잘림" in context
