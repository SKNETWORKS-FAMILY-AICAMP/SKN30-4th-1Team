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
