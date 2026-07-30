"""Repository sync generation staging, fencing, publication, and cleanup."""

from unittest.mock import ANY, patch

from fastapi import BackgroundTasks

from backend.api.repository import (
    GitHubAPIError,
    SyncFenceLost,
    SyncRequest,
    _sync_bg,
    sync_repository,
)


RUN_ID = "11111111-1111-1111-1111-111111111111"
OLD_RUN_ID = "00000000-0000-0000-0000-000000000000"


def _source(name: str = "README.md", content: str = "project overview content"):
    return {
        name: {
            "content": content,
            "metadata": {
                "source_type": "readme",
                "source_path": name,
                "source_ref": "abc1234",
                "source_url": "",
            },
        }
    }


def _success_patches(sources=None, warnings=None):
    return (
        patch("backend.api.repository._require_sync_ownership"),
        patch(
            "backend.api.repository._collect_repo_sources",
            return_value=(sources or _source(), "abc1234", warnings or []),
        ),
        patch("backend.api.repository._get_last_reconciled_pr", return_value=None),
        patch("backend.api.repository._collect_merged_prs", return_value=[]),
        patch(
            "backend.api.repository._set_repo_status",
            return_value=(True, OLD_RUN_ID),
        ),
        patch("backend.api.repository._cleanup_repo_generation"),
        patch("backend.api.repository.reconcile_repository_prs"),
        patch("backend.api.repository._detect_published_generation_supersedes"),
        patch("backend.project_memory.refresh_project_memory_after_delete"),
        patch("backend.pipeline.extractor.extract", return_value=[]),
        patch("backend.pipeline.ingestor.ingest"),
    )


def test_sync_bg_stages_run_then_publishes_without_deleting_previous_generation():
    patches = _success_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4] as status,
        patches[5] as cleanup,
        patches[6] as reconcile,
        patches[7] as supersede,
        patches[8],
        patches[9],
        patches[10] as ingest,
    ):
        _sync_bg(1, 10, RUN_ID, "owner/repo", "main", None)

    assert ingest.call_args.kwargs["repo_sync_run_id"] == RUN_ID
    status.assert_called_once_with(
        10,
        RUN_ID,
        "indexed",
        commit_sha="abc1234",
        indexed_files=1,
        last_error=None,
        sync_warning=None,
        project_id=1,
    )
    cleanup.assert_not_called()
    supersede.assert_called_once_with(1, 10, RUN_ID)
    reconcile.assert_called_once_with(1, 10, [])


def test_sync_bg_empty_sources_fails_and_cleans_only_failed_run():
    with patch("backend.api.repository._require_sync_ownership"), patch(
        "backend.api.repository._get_last_reconciled_pr", return_value=None
    ), patch(
        "backend.api.repository._collect_repo_sources", return_value=({}, None, [])
    ), patch(
        "backend.api.repository._set_repo_status", return_value=(True, OLD_RUN_ID)
    ) as status, patch(
        "backend.api.repository._cleanup_repo_generation"
    ) as cleanup:
        _sync_bg(1, 10, RUN_ID, "owner/repo", "main", None)

    status.assert_called_once_with(10, RUN_ID, "failed", last_error=ANY)
    cleanup.assert_called_once_with(10, RUN_ID)


def test_sync_bg_github_failure_preserves_active_generation():
    with patch("backend.api.repository._require_sync_ownership"), patch(
        "backend.api.repository._get_last_reconciled_pr", return_value=None
    ), patch(
        "backend.api.repository._collect_repo_sources",
        side_effect=GitHubAPIError("not_found", "commits"),
    ), patch(
        "backend.api.repository._set_repo_status", return_value=(True, OLD_RUN_ID)
    ) as status, patch(
        "backend.api.repository._cleanup_repo_generation"
    ) as cleanup:
        _sync_bg(1, 10, RUN_ID, "owner/repo", "main", None)

    status.assert_called_once_with(
        10,
        RUN_ID,
        "failed",
        last_error="GITHUB_BRANCH_NOT_FOUND:commits",
    )
    cleanup.assert_called_once_with(10, RUN_ID)


def test_sync_bg_any_ingest_failure_rejects_whole_staged_generation():
    sources = {**_source("README.md", "readme"), **_source("commits.txt", "commits")}
    with patch("backend.api.repository._require_sync_ownership"), patch(
        "backend.api.repository._collect_repo_sources", return_value=(sources, "abc", [])
    ), patch(
        "backend.api.repository._get_last_reconciled_pr", return_value=None
    ), patch(
        "backend.api.repository._collect_merged_prs", return_value=[]
    ), patch(
        "backend.api.repository._set_repo_status", return_value=(True, OLD_RUN_ID)
    ) as status, patch(
        "backend.api.repository._cleanup_repo_generation"
    ) as cleanup, patch(
        "backend.pipeline.extractor.extract", return_value=[]
    ), patch(
        "backend.pipeline.ingestor.ingest",
        side_effect=[None, RuntimeError("second source failed")],
    ):
        _sync_bg(1, 10, RUN_ID, "owner/repo", "main", None)

    status.assert_called_once_with(
        10,
        RUN_ID,
        "failed",
        commit_sha="abc",
        indexed_files=1,
        last_error="REPOSITORY_INGEST_FAILED",
    )
    cleanup.assert_called_once_with(10, RUN_ID)


def test_sync_bg_lost_fence_never_changes_newer_run():
    with patch(
        "backend.api.repository._require_sync_ownership",
        side_effect=SyncFenceLost(RUN_ID),
    ), patch("backend.api.repository._set_repo_status") as status, patch(
        "backend.api.repository._cleanup_repo_generation"
    ) as cleanup:
        _sync_bg(1, 10, RUN_ID, "owner/repo", "main", None)

    status.assert_not_called()
    cleanup.assert_called_once_with(10, RUN_ID)


def test_repeated_sync_reuses_run_without_duplicate_worker():
    background = BackgroundTasks()
    repo = {"repository_url": "https://github.com/o/r", "branch": "main"}
    run = {"run_id": RUN_ID, "started_at": None}
    with patch("backend.api.repository.require_project_access"), patch(
        "backend.api.repository._get_github_token", return_value=None
    ), patch(
        "backend.api.repository._claim_sync_run", return_value=(repo, run, False)
    ):
        result = sync_repository(3, 7, background, SyncRequest())

    assert result["run_id"] == RUN_ID
    assert background.tasks == []
