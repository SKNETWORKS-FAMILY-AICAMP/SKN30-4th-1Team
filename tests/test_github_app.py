import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.github import router as github_api
from backend.main import app


def test_github_app_session_callback(monkeypatch):
    github_api._sessions.clear()
    monkeypatch.setenv("GITHUB_APP_SLUG", "paim-test")
    client = TestClient(app)

    created = client.post("/github/app/sessions", json={})

    assert created.status_code == 201
    state = created.json()["state"]
    assert created.json()["installUrl"].startswith(
        "https://github.com/apps/paim-test/installations/new?",
    )
    assert f"state={state}" in created.json()["installUrl"]

    pending = client.get(f"/github/app/sessions/{state}")

    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"

    callback = client.get(
        f"/github/app/callback?state={state}&installation_id=123&setup_action=install",
    )

    assert callback.status_code == 200

    connected = client.get(f"/github/app/sessions/{state}")

    assert connected.status_code == 200
    assert connected.json()["status"] == "connected"
    assert connected.json()["setupAction"] == "install"


def test_github_repo_full_name_parses_supported_urls():
    assert github_api._repo_full_name("https://github.com/acme/pocket.git") == "acme/pocket"
    assert github_api._repo_full_name("github.com/acme/pocket") == "acme/pocket"
    assert github_api._repo_full_name("git@github.com:acme/pocket.git") == "acme/pocket"


def test_desktop_origin_is_allowed_by_cors():
    client = TestClient(app)

    response = client.options(
        "/github/app/sessions",
        headers={
            "Origin": "http://127.0.0.1:7420",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:7420"


def test_repository_preview_head_only_uses_encoded_requested_branch():
    client = TestClient(app)

    with patch(
        "backend.github.router._json_request",
        return_value=[{"sha": "abc123"}],
    ) as github_request:
        response = client.post(
            "/github/app/repository-preview",
            json={
                "repository_url": "https://github.com/acme/pocket",
                "branch": "release/1.x",
                "head_only": True,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "branch": "release/1.x",
        "remoteHeadSha": "abc123",
    }
    github_request.assert_called_once_with(
        "GET",
        "/repos/acme/pocket/commits?sha=release%2F1.x&per_page=1",
        token=None,
    )


def test_repository_preview_uses_requested_branch_for_activity():
    client = TestClient(app)

    with patch(
        "backend.github.router._json_request",
        side_effect=[
            {
                "default_branch": "main",
                "full_name": "acme/pocket",
                "html_url": "https://github.com/acme/pocket",
                "name": "pocket",
                "private": False,
            },
            [{"sha": "abc123", "commit": {"message": "release", "author": {}}}],
            [],
            [],
        ],
    ) as github_request:
        response = client.post(
            "/github/app/repository-preview",
            json={
                "repository_url": "https://github.com/acme/pocket",
                "branch": "release/1.x",
            },
        )

    assert response.status_code == 200
    assert response.json()["repository"]["branch"] == "release/1.x"
    assert response.json()["repository"]["remoteHeadSha"] == "abc123"
    assert github_request.call_args_list[1].args[1] == (
        "/repos/acme/pocket/commits?sha=release%2F1.x&per_page=6"
    )


def test_repository_preview_head_only_preserves_expired_app_session_signal():
    state = "expired-preview-state"
    client = TestClient(app, raise_server_exceptions=False)
    github_api._sessions.clear()
    github_api._expired_states.clear()
    github_api._expired_states[state] = time.time()
    try:
        response = client.post(
            "/github/app/repository-preview",
            json={
                "repository_url": "https://github.com/acme/pocket",
                "state": state,
                "branch": "main",
                "head_only": True,
            },
        )

        assert response.status_code == 410
        assert response.json()["code"] == "SESSION_EXPIRED"
    finally:
        github_api._expired_states.clear()
