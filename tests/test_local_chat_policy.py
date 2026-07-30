from pathlib import Path

from backend.api.capabilities import get_capabilities
from backend.main import app


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_chat_capability_declares_local_only_storage():
    assert get_capabilities()["desktop_chat"] == {
        "storage": "local_only",
        "server_persistence": False,
        "legacy_session_api": "deprecated",
    }


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


def test_stateless_query_contract_declares_no_chat_persistence():
    operation = app.openapi()["paths"]["/api/v1/projects/{project_id}/query"]["post"]
    assert operation["x-paim-chat-persistence"] == "none"


def test_desktop_does_not_call_legacy_session_api():
    source = (ROOT / "desktop" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "/sessions" not in source
    assert "serverSessionId" in source  # legacy local payload is explicitly sanitized
    assert "delete localSession.serverSessionId" in source
    assert 'SESSION_DRAFT_STORAGE_SUFFIX = ".drafts"' in source
    assert "loadSessionDrafts(sessionDraftStorageKey)" in source
    assert "saveSessionDrafts(sessionDraftStorageKey" in source
