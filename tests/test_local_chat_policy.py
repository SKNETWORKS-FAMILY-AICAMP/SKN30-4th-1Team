from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app, raise_server_exceptions=False)


def _recording_project_connection(statements):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value

    def execute(sql, params=()):
        statements.append((" ".join(sql.split()), params))

    cursor.execute.side_effect = execute
    cursor.fetchone.return_value = {"id": 1}
    return conn


def test_legacy_server_session_operations_are_deprecated_but_still_exposed():
    spec = app.openapi()
    session_operations = {
        ("post", "/api/v1/projects/{project_id}/sessions"),
        ("get", "/api/v1/projects/{project_id}/sessions"),
        ("patch", "/api/v1/projects/{project_id}/sessions/{session_id}"),
        ("delete", "/api/v1/projects/{project_id}/sessions/{session_id}"),
        ("get", "/api/v1/projects/{project_id}/sessions/{session_id}/messages"),
        ("post", "/api/v1/projects/{project_id}/sessions/{session_id}/query"),
    }

    for method, path in session_operations:
        assert spec["paths"][path][method]["deprecated"] is True


def test_stateless_query_does_not_write_server_chat_tables():
    statements = []
    connection = _recording_project_connection(statements)
    history = [{"role": "user", "content": "이전 질문"}]

    def answer(project_id, question, supplied_history):
        assert project_id == 1
        assert question == "후속 질문"
        assert supplied_history == history
        return {"answer": "답변", "sources": [], "route": "agentic", "debug": {}}

    with (
        patch("backend.api.query.require_project_access"),
        patch("backend.api.query.get_connection", return_value=connection),
        patch("backend.api.query._agentic_routing_enabled", return_value=True),
        patch("backend.api.query.run_agentic_qa", side_effect=answer),
    ):
        response = client.post(
            "/api/v1/projects/1/query",
            json={"question": "후속 질문", "history": history},
        )

    assert response.status_code == 200
    assert statements == [("SELECT id FROM projects WHERE id = %s", (1,))]
    assert all("chat_" not in sql.lower() for sql, _ in statements)

    operation = app.openapi()["paths"]["/api/v1/projects/{project_id}/query"]["post"]
    assert operation["x-paim-chat-persistence"] == "none"
