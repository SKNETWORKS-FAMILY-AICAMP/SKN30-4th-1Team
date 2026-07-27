"""_sync_bg() background task status transition 테스트."""
from unittest.mock import patch, ANY

from backend.api.repository import _sync_bg


def test_sync_bg_success_sets_indexed():
    """sources 수집 성공 (warnings 없음) → status='indexed', sync_warning=None."""
    sources = {
        "README.md": {
            "content": "project overview content",
            "metadata": {"source_type": "readme", "source_path": "README.md", "source_ref": "abc1234", "source_url": ""},
        }
    }
    with patch("backend.api.repository._precheck_repository"), \
         patch("backend.api.repository._collect_repo_sources", return_value=(sources, "abc1234", [])), \
         patch("backend.api.repository._get_last_reconciled_pr", return_value=None), \
         patch("backend.api.repository._collect_merged_prs", return_value=[]), \
         patch("backend.api.repository._clear_repo_indexed_data") as mock_clear, \
         patch("backend.api.repository._set_repo_status") as mock_status, \
         patch("backend.api.repository.reconcile_repository_prs") as mock_reconcile, \
         patch("backend.pipeline.extractor.extract", return_value=[]), \
         patch("backend.pipeline.ingestor.ingest"):

        _sync_bg(project_id=1, repo_id=10, full_name="owner/repo", branch="main", token=None)

        mock_clear.assert_called_once_with(10)
        mock_status.assert_called_once_with(
            10, "indexed", commit_sha="abc1234", indexed_files=1,
            last_error=None, sync_warning=None,
        )
        mock_reconcile.assert_called_once_with(1, 10, [])


def test_sync_bg_empty_sources_preserves_index():
    """sources 빈 결과 → 기존 index 삭제 없음, status='failed', last_error 기록."""
    with patch("backend.api.repository._precheck_repository"), \
         patch("backend.api.repository._get_last_reconciled_pr", return_value=None), \
         patch("backend.api.repository._collect_repo_sources", return_value=({}, None, [])), \
         patch("backend.api.repository._clear_repo_indexed_data") as mock_clear, \
         patch("backend.api.repository._set_repo_status") as mock_status:

        _sync_bg(project_id=1, repo_id=10, full_name="owner/repo", branch="main", token=None)

        mock_clear.assert_not_called()
        mock_status.assert_called_once_with(10, "failed", last_error=ANY)


def test_sync_bg_network_exception_sets_failed():
    """GitHub API 예외 → status='failed', last_error 기록."""
    with patch("backend.api.repository._precheck_repository"), \
         patch("backend.api.repository._get_last_reconciled_pr", return_value=None), \
         patch("backend.api.repository._collect_repo_sources", side_effect=RuntimeError("timeout")), \
         patch("backend.api.repository._set_repo_status") as mock_status:

        _sync_bg(project_id=1, repo_id=10, full_name="owner/repo", branch="main", token=None)

        mock_status.assert_called_once_with(10, "failed", last_error="REPOSITORY_SYNC_FAILED")


def test_sync_bg_partial_failure_sets_warning():
    """일부 API 실패 (warnings 있음) → status='indexed' + sync_warning JSON 저장."""
    sources = {
        "commits.txt": {
            "content": "commit log",
            "metadata": {"source_type": "commits", "source_path": "commits.txt", "source_ref": "abc", "source_url": ""},
        }
    }
    warnings = [{"source_type": "issues", "reason": "GitHub API 응답 오류"}]
    with patch("backend.api.repository._precheck_repository"), \
         patch("backend.api.repository._collect_repo_sources", return_value=(sources, "abc", warnings)), \
         patch("backend.api.repository._get_last_reconciled_pr", return_value=None), \
         patch("backend.api.repository._collect_merged_prs", return_value=[]), \
         patch("backend.api.repository._clear_repo_indexed_data"), \
         patch("backend.api.repository._set_repo_status") as mock_status, \
         patch("backend.api.repository.reconcile_repository_prs"), \
         patch("backend.pipeline.extractor.extract", return_value=[]), \
         patch("backend.pipeline.ingestor.ingest"):

        _sync_bg(project_id=1, repo_id=10, full_name="owner/repo", branch="main", token=None)

        kwargs = mock_status.call_args.kwargs
        assert kwargs["last_error"] is None
        assert kwargs["sync_warning"] is not None
        assert "issues" in kwargs["sync_warning"]


def test_sync_bg_all_success_no_warning():
    """warnings 빈 리스트 → sync_warning=None (NULL 저장)."""
    sources = {
        "README.md": {
            "content": "readme",
            "metadata": {"source_type": "readme", "source_path": "README.md", "source_ref": "", "source_url": ""},
        }
    }
    with patch("backend.api.repository._precheck_repository"), \
         patch("backend.api.repository._collect_repo_sources", return_value=(sources, None, [])), \
         patch("backend.api.repository._get_last_reconciled_pr", return_value=None), \
         patch("backend.api.repository._collect_merged_prs", return_value=[]), \
         patch("backend.api.repository._clear_repo_indexed_data"), \
         patch("backend.api.repository._set_repo_status") as mock_status, \
         patch("backend.api.repository.reconcile_repository_prs"), \
         patch("backend.pipeline.extractor.extract", return_value=[]), \
         patch("backend.pipeline.ingestor.ingest"):

        _sync_bg(project_id=1, repo_id=10, full_name="owner/repo", branch="main", token=None)

        assert mock_status.call_args.kwargs["sync_warning"] is None
