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
        side_effect=[[], GitHubAPIError("not_found", "readme"), [], []],
    ):
        sources, sha, warnings = _collect_repo_sources("o/r", "main")
    assert sources == {}
    assert sha is None
    assert warnings == []


@pytest.mark.parametrize(
    ("kind", "source", "expected"),
    [
        ("not_found", "metadata", "GITHUB_REPOSITORY_NOT_FOUND:metadata"),
        ("not_found", "commits", "GITHUB_BRANCH_NOT_FOUND:commits"),
        ("not_found", "issues", "GITHUB_SOURCE_NOT_FOUND:issues"),
        ("not_found", "pulls", "GITHUB_SOURCE_NOT_FOUND:pulls"),
        ("not_found", "merged_pulls", "GITHUB_SOURCE_NOT_FOUND:merged_pulls"),
        ("auth", "commits", "GITHUB_AUTH_FAILED:commits"),
        ("permission", "issues", "GITHUB_PERMISSION_DENIED:issues"),
        ("unavailable", "pulls", "GITHUB_UNAVAILABLE:pulls"),
    ],
)
def test_sync_fatal_fetch_preserves_index_and_records_stable_code(kind, source, expected):
    failure = GitHubAPIError(kind, source)
    precheck = failure if source == "metadata" else None
    collect_failure = failure if source not in {"metadata", "merged_pulls"} else None
    merged_failure = failure if source == "merged_pulls" else None
    with patch("backend.api.repository._precheck_repository", side_effect=precheck), patch(
        "backend.api.repository._get_last_reconciled_pr", return_value=7
    ), patch(
        "backend.api.repository._collect_repo_sources",
        return_value=({"x": {"content": "x", "metadata": {}}}, "sha", []),
        side_effect=collect_failure,
    ), patch(
        "backend.api.repository._collect_merged_prs",
        return_value=[],
        side_effect=merged_failure,
    ), patch("backend.api.repository._clear_repo_indexed_data") as clear, patch(
        "backend.api.repository._set_repo_status"
    ) as status, patch("backend.api.repository.reconcile_repository_prs") as reconcile:
        _sync_bg(1, 2, "o/r", "main", None)
    clear.assert_not_called()
    reconcile.assert_not_called()
    status.assert_called_once_with(2, "failed", last_error=expected)


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


def test_one_failing_source_does_not_discard_the_others():
    """소스 1건 실패로 저장소 동기화 전체를 버리지 않는다.

    issues가 꺼진 저장소(410)나 일시적 5xx 하나에 commits·README·pulls까지 전부
    폐기되고 repo가 failed가 됐다. 부분 실패는 warnings로 남기고 나머지를 색인한다."""
    commits = [{"sha": "abc1234", "commit": {"message": "첫 커밋", "author": {"date": "2026-04-13T00:00:00Z"}}}]
    with patch(
        "backend.api.repository._gh_get",
        side_effect=[
            commits,                                    # commits 성공
            GitHubAPIError("not_found", "readme"),      # README 없음 — 정상
            GitHubAPIError("unavailable", "issues"),    # issues 실패 — warning
            [{"number": 3, "title": "PR 제목", "body": "본문"}],  # pulls 성공
        ],
    ):
        sources, sha, warnings = _collect_repo_sources("o/r", "main")

    assert sha == "abc1234"
    assert "commits.txt" in sources and "pulls.txt" in sources  # 나머지는 살아남는다
    assert [w["source_type"] for w in warnings] == ["issues"]
    assert warnings[0]["reason"]  # 사용자에게 보여줄 문구가 채워져 있다


def test_missing_branch_still_fails_the_whole_sync():
    """commits의 not_found(=브랜치 없음)는 warning으로 넘기지 않는다.

    그대로 진행하면 엉뚱한 기본 브랜치의 README·issues·pulls를 색인해 놓고
    동기화를 성공으로 보고하게 된다."""
    with patch(
        "backend.api.repository._gh_get",
        side_effect=GitHubAPIError("not_found", "commits"),
    ):
        with pytest.raises(GitHubAPIError) as exc_info:
            _collect_repo_sources("o/r", "없는브랜치")
    assert exc_info.value.kind == "not_found"
    assert exc_info.value.source == "commits"
