from io import BytesIO
from unittest.mock import patch
from urllib import error

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.api.repository import (
    GitHubAPIError,
    RepositoryConnect,
    _collect_repo_sources,
    _gh_get,
    _sync_bg,
    connect_repository,
)
from backend.github import router as github_app
from backend.main import app


_client = TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("status", "kind"),
    [(401, "auth"), (403, "permission"), (404, "not_found"), (500, "unavailable")],
)
def test_gh_get_preserves_http_failure_type(status, kind):
    failure = error.HTTPError("https://api.github.test", status, "failure", None, None)
    with patch("backend.api.repository.request.urlopen", side_effect=failure):
        with pytest.raises(GitHubAPIError) as exc_info:
            _gh_get("/repos/o/r", source="metadata")
    assert exc_info.value.kind == kind
    assert exc_info.value.source == "metadata"


def test_gh_get_maps_raw_timeout_to_unavailable():
    with patch("backend.api.repository.request.urlopen", side_effect=TimeoutError()):
        with pytest.raises(GitHubAPIError) as exc_info:
            _gh_get("/repos/o/r", source="metadata")
    assert exc_info.value.kind == "unavailable"


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("not_found", 404, "GITHUB_REPOSITORY_NOT_FOUND"),
        ("auth", 401, "GITHUB_AUTH_FAILED"),
        ("permission", 403, "GITHUB_PERMISSION_DENIED"),
        ("unavailable", 503, "GITHUB_UNAVAILABLE"),
    ],
)
def test_connect_maps_github_failures(kind, status, code):
    body = RepositoryConnect(repository_url="https://github.com/o/r")
    with patch("backend.api.repository.require_project_access"), patch(
        "backend.api.repository._gh_get",
        side_effect=GitHubAPIError(kind, "metadata"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            connect_repository(1, body)
    assert exc_info.value.status_code == status
    assert exc_info.value.detail["code"] == code


def test_readme_404_is_normal_absence_and_empty_lists_are_success():
    with patch(
        "backend.api.repository._gh_get",
        side_effect=[
            {"sha": "head-sha"},
            [],
            GitHubAPIError("not_found", "readme"),
            [],
            [],
        ],
    ):
        sources, sha, warnings = _collect_repo_sources("o/r", "main")
    assert sources == {}
    assert sha == "head-sha"
    assert warnings == []


@pytest.mark.parametrize(
    ("kind", "source", "expected"),
    [
        ("not_found", "metadata", "GITHUB_REPOSITORY_NOT_FOUND:metadata"),
        ("not_found", "commits", "GITHUB_BRANCH_NOT_FOUND:commits"),
        ("auth", "commits", "GITHUB_AUTH_FAILED:commits"),
    ],
)
def test_sync_fatal_fetch_preserves_index_and_records_stable_code(kind, source, expected):
    failure = GitHubAPIError(kind, source)
    with patch("backend.api.repository._require_sync_ownership"), patch(
        "backend.api.repository._get_last_reconciled_pr", return_value=7
    ), patch(
        "backend.api.repository._collect_repo_sources",
        side_effect=failure,
    ), patch(
        "backend.api.repository._collect_merged_prs",
        return_value=[],
    ), patch("backend.api.repository._set_repo_status") as status, patch(
        "backend.api.repository._cleanup_repo_generation"
    ), patch(
        "backend.api.repository.reconcile_repository_prs"
    ) as reconcile:
        _sync_bg(1, 2, "run-1", "o/r", "main", None)
    reconcile.assert_not_called()
    status.assert_called_once_with(2, "run-1", "failed", last_error=expected)


@pytest.mark.parametrize(
    ("kind", "source", "expected"),
    [
        ("unavailable", "readme", "GITHUB_UNAVAILABLE:readme"),
        ("not_found", "issues", "GITHUB_SOURCE_NOT_FOUND:issues"),
        ("permission", "issues", "GITHUB_PERMISSION_DENIED:issues"),
        ("unavailable", "pulls", "GITHUB_UNAVAILABLE:pulls"),
    ],
)
def test_optional_source_failure_returns_warning(kind, source, expected):
    side_effect = [
        {"sha": "head-sha"},
        [{"sha": "head-sha", "commit": {"message": "latest", "author": {}}}],
        {},
        [],
        [],
    ]
    source_call_index = {"readme": 2, "issues": 3, "pulls": 4}[source]
    side_effect[source_call_index] = GitHubAPIError(kind, source)

    with patch("backend.api.repository._gh_get", side_effect=side_effect):
        sources, sha, warnings = _collect_repo_sources("o/r", "main")

    assert sha == "head-sha"
    assert "commits.txt" in sources
    assert {"source_type": source, "reason": expected} in warnings


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/projects/1/repositories", {
            "provider": "github",
            "repository_url": "https://github.com/o/r",
            "state": "token-state",
        }),
        ("/api/v1/projects/1/repositories/2/sync", {"state": "token-state"}),
    ],
)
def test_installation_token_failure_is_sanitized_before_response_db_and_log(
    path, payload, caplog
):
    sentinel = "UPSTREAM-SECRET-SENTINEL"
    github_app._sessions.clear()
    github_app._sessions["token-state"] = github_app.GithubAppSession(
        created_at=__import__("time").time(), installation_id=123
    )
    failure = error.HTTPError(
        "https://api.github.test/token",
        401,
        "failure",
        None,
        BytesIO(sentinel.encode()),
    )
    try:
        with patch("backend.api.repository.require_project_access"), patch(
            "backend.github.router._github_app_jwt", return_value="signed-jwt"
        ), patch(
            "backend.github.router.request.urlopen", side_effect=failure
        ), patch("backend.api.repository.get_connection") as get_connection:
            response = _client.post(path, json=payload)
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "GITHUB_AUTH_FAILED"
        assert sentinel not in response.text
        assert sentinel not in caplog.text
        get_connection.assert_not_called()
    finally:
        github_app._sessions.clear()
