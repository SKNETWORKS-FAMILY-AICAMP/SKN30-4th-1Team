import base64
import json
import logging
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Optional
from urllib import error, parse, request

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from ..db.mysql import get_connection
from ..reconciler import reconcile_repository_prs
from .auth import require_project_access

router = APIRouter()
logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_GITHUB_API_VERSION = "2022-11-28"
_SUPPORTED_PROVIDERS = {"github"}


class SyncFenceLost(RuntimeError):
    """The worker no longer owns the repository's current sync run."""


class GitHubAPIError(RuntimeError):
    """GitHub 응답 실패. 토큰이나 응답 본문은 보관하지 않는다."""

    def __init__(self, kind: str, source: str = "metadata"):
        super().__init__(kind)
        self.kind = kind
        self.source = source


def _utc_iso(value) -> str | None:
    """Serialize repository-run DATETIME values as explicit UTC RFC 3339."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat()
    return str(value)


# ── GitHub API 헬퍼 ───────────────────────────────────────────────

def _gh_get(path: str, token: str | None = None, source: str = "metadata"):
    """GitHub API GET. 정상 빈 응답과 전송/권한/404 실패를 구분한다."""
    url = path if path.startswith("https://") else f"{_GITHUB_API}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _GITHUB_API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, headers=headers)
    try:
        with request.urlopen(req, timeout=15) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except error.HTTPError as exc:
        kind = {401: "auth", 403: "permission", 404: "not_found"}.get(
            exc.code, "unavailable"
        )
        logger.warning("GitHub API HTTP 오류 %s: %s", exc.code, path)
        raise GitHubAPIError(kind, source) from exc
    except error.URLError as exc:
        logger.warning("GitHub API 네트워크 오류: %s — %s", path, exc.reason)
        raise GitHubAPIError("unavailable", source) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("GitHub API 예외: %s", path, exc_info=True)
        raise GitHubAPIError("unavailable", source) from exc
    except Exception as exc:
        # socket timeout 등 urllib이 URLError로 감싸지 않는 전송 실패도 같은
        # 안정된 unavailable 계약으로 변환한다. 토큰/응답 본문은 남기지 않는다.
        logger.warning("GitHub API 전송 예외: %s", path, exc_info=True)
        raise GitHubAPIError("unavailable", source) from exc


def _require_list(payload, source: str) -> list:
    if not isinstance(payload, list):
        logger.warning("GitHub API 응답 형식 오류 source=%s", source)
        raise GitHubAPIError("unavailable", source)
    return payload


def _sync_failure_code(exc: GitHubAPIError, source: str) -> str:
    if exc.kind == "auth":
        return f"GITHUB_AUTH_FAILED:{source}"
    if exc.kind == "permission":
        return f"GITHUB_PERMISSION_DENIED:{source}"
    if exc.kind == "not_found":
        if source == "metadata":
            return "GITHUB_REPOSITORY_NOT_FOUND:metadata"
        if source == "commits":
            return "GITHUB_BRANCH_NOT_FOUND:commits"
        return f"GITHUB_SOURCE_NOT_FOUND:{source}"
    return f"GITHUB_UNAVAILABLE:{source}"


def _connect_failure(exc: GitHubAPIError) -> HTTPException:
    status_code, code = {
        "not_found": (404, "GITHUB_REPOSITORY_NOT_FOUND"),
        "auth": (401, "GITHUB_AUTH_FAILED"),
        "permission": (403, "GITHUB_PERMISSION_DENIED"),
        "unavailable": (503, "GITHUB_UNAVAILABLE"),
    }[exc.kind]
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": "GitHub 저장소를 확인할 수 없습니다."},
    )


def _get_github_token(state: str | None) -> str | None:
    """GitHub App session state → installation token. state 없으면 None 반환."""
    if not state:
        return None
    try:
        from ..github.router import _installation_token
        return _installation_token(state)
    except HTTPException as exc:
        # state/session 오류와 installation-token upstream 실패를 repository API의
        # 안정된 계약으로 변환한다. 원 detail은 response·DB·log로 전달하지 않는다.
        kind = "permission" if exc.status_code == 403 else (
            "auth" if exc.status_code in {401, 404, 409} else "unavailable"
        )
        raise _connect_failure(GitHubAPIError(kind, "token")) from exc


def _parse_github_full_name(url: str) -> str:
    """'https://github.com/owner/repo' 형식을 'owner/repo'로 변환. 실패 시 HTTPException."""
    trimmed = url.strip().removesuffix(".git")
    try:
        parsed = parse.urlparse(trimmed if trimmed.startswith("http") else f"https://{trimmed}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid repository URL")
    if parsed.netloc != "github.com":
        raise HTTPException(status_code=400, detail="GitHub URL만 지원합니다 (github.com)")
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="URL에 owner/repo 형식이 포함되어야 합니다")
    return f"{parts[0]}/{parts[1]}"


def _collect_repo_sources(
    full_name: str, branch: str, token: str | None = None
) -> tuple[dict[str, dict], str | None, list[dict]]:
    """GitHub API로 README·commits·issues·PRs 텍스트 수집.
    Returns (sources_dict, latest_commit_sha, warnings).
    sources_dict 형태: {"README.md": {"content": str, "metadata": dict}, ...}
    warnings: API 호출 부분 실패 목록 [{"source_type": str, "reason": str}, ...]
    """
    sources: dict[str, dict] = {}
    latest_sha: str | None = None
    warnings: list[dict] = []

    # Capture branch HEAD once so all commit-bound sources belong to one
    # generation even if a push arrives during collection.
    head = _gh_get(
        f"/repos/{full_name}/commits/{parse.quote(branch, safe='')}",
        token=token,
        source="commits",
    )
    if not isinstance(head, dict) or not head.get("sha"):
        raise GitHubAPIError("unavailable", "commits")
    latest_sha = str(head["sha"])

    # Commits
    commits = _require_list(
        _gh_get(
            f"/repos/{full_name}/commits?sha={parse.quote(latest_sha)}&per_page=20",
            token=token,
            source="commits",
        ),
        "commits",
    )
    if commits:
        lines = []
        for c in commits:
            sha = (c.get("sha") or "")[:7]
            commit_info = c.get("commit") or {}
            msg = commit_info.get("message", "").split("\n")[0]
            date = (commit_info.get("author") or {}).get("date", "")[:10]
            lines.append(f"[{sha}] {date}: {msg}")
        if lines:
            sources["commits.txt"] = {
                "content": "\n".join(lines),
                "metadata": {
                    "source_type": "commits",
                    "source_path": "commits.txt",
                    "source_ref": latest_sha or "",
                    "source_url": "",
                },
            }

    # README (404는 README 없는 저장소로 정상 — warning 생략)
    try:
        readme = _gh_get(
            f"/repos/{full_name}/readme?ref={parse.quote(latest_sha)}",
            token=token,
            source="readme",
        )
    except GitHubAPIError as exc:
        if exc.kind != "not_found":
            warnings.append(
                {"source_type": "readme", "reason": _sync_failure_code(exc, "readme")}
            )
        readme = {}
    if isinstance(readme, dict) and readme.get("content"):
        try:
            decoded = base64.b64decode(readme["content"]).decode("utf-8", errors="replace")
            readme_url = (
                f"https://github.com/{full_name}/blob/{latest_sha}/README.md"
                if latest_sha else ""
            )
            sources["README.md"] = {
                "content": decoded,
                "metadata": {
                    "source_type": "readme",
                    "source_path": "README.md",
                    "source_ref": latest_sha or "",
                    "source_url": readme_url,
                },
            }
        except Exception:
            pass

    # Issues (PR 제외)
    try:
        issues = _require_list(
            _gh_get(
                f"/repos/{full_name}/issues?state=open&per_page=20",
                token=token,
                source="issues",
            ),
            "issues",
        )
    except GitHubAPIError as exc:
        warnings.append(
            {"source_type": "issues", "reason": _sync_failure_code(exc, "issues")}
        )
        issues = []
    issue_texts = [
        f"Issue #{i.get('number')} ({i.get('state', 'open')}): {i.get('title', '')}\n{i.get('body') or ''}"
        for i in issues if not i.get("pull_request")
    ]
    if issue_texts:
        sources["issues.txt"] = {
            "content": "\n\n".join(issue_texts),
            "metadata": {
                "source_type": "issues",
                "source_path": "issues.txt",
                "source_ref": latest_sha or "",
                "source_url": "",
            },
        }

    # Pull Requests
    try:
        pulls = _require_list(
            _gh_get(
                f"/repos/{full_name}/pulls?state=open&per_page=20",
                token=token,
                source="pulls",
            ),
            "pulls",
        )
    except GitHubAPIError as exc:
        warnings.append(
            {"source_type": "pulls", "reason": _sync_failure_code(exc, "pulls")}
        )
        pulls = []
    pr_texts = [
        f"PR #{p.get('number')} ({p.get('state', 'open')}): {p.get('title', '')}\n{p.get('body') or ''}"
        for p in pulls
    ]
    if pr_texts:
        sources["pulls.txt"] = {
            "content": "\n\n".join(pr_texts),
            "metadata": {
                "source_type": "pulls",
                "source_path": "pulls.txt",
                "source_ref": latest_sha or "",
                "source_url": "",
            },
        }

    return sources, latest_sha, warnings


def _extract_source_kind(source_type: str | None) -> str:
    """repo 수집 source_type을 extractor 전용 지침 키로 바꾼다."""
    return {
        "readme": "repo_readme",
        "commits": "repo_commits",
        "issues": "repo_issues",
        "pulls": "repo_prs",
    }.get(source_type or "", "document")


def _summarize_pr_body(body: str | None) -> str:
    """PR 본문을 Reconciler 입력용 짧은 요약 필드로 줄인다."""
    text = (body or "").strip()
    if len(text) <= 1200:
        return text
    return f"{text[:1200].rstrip()}..."


def _collect_merged_prs(full_name: str, last_reconciled_pr: int | None, token: str | None = None) -> list[dict]:
    """last_reconciled_pr 이후의 merged PR을 GitHub에서 조회해 Reconciler 입력으로 만든다."""
    watermark = int(last_reconciled_pr or 0)
    merged = []
    page = 1
    while True:
        pulls = _require_list(
            _gh_get(
                f"/repos/{full_name}/pulls?state=closed&sort=updated&direction=desc&per_page=100&page={page}",
                token=token,
                source="merged_pulls",
            ),
            "merged_pulls",
        )
        for pr in pulls:
            number = pr.get("number")
            if not number or int(number) <= watermark or not pr.get("merged_at"):
                continue
            merged.append(
                {
                    "number": int(number),
                    "title": pr.get("title") or "",
                    "body_summary": _summarize_pr_body(pr.get("body")),
                    "url": pr.get("html_url") or "",
                    "merged_at": pr.get("merged_at") or "",
                }
            )
        if len(pulls) < 100:
            break
        page += 1
    return sorted(merged, key=lambda item: item["number"])


# ── DB 헬퍼 ──────────────────────────────────────────────────────

class RepositoryConnect(BaseModel):
    provider: str = "github"
    repository_url: str
    branch: Optional[str] = None
    state: Optional[str] = None  # GitHub App session state (비공개 저장소용)


class SyncRequest(BaseModel):
    state: Optional[str] = None  # GitHub App session state (비공개 저장소용)


def _repo_or_404(cursor, project_id: int, repo_id: int) -> dict:
    cursor.execute(
        "SELECT * FROM repositories WHERE id = %s AND project_id = %s",
        (repo_id, project_id),
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Repository not found")
    return row


def _delete_repo_data(repo_id: int):
    """memory 행 + repositories 행 + ChromaDB 벡터 삭제."""
    project_id = None
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT project_id FROM repositories WHERE id = %s", (repo_id,))
            row = cursor.fetchone()
            if row:
                project_id = row.get("project_id")
            cursor.execute("DELETE FROM memory WHERE repo_id = %s", (repo_id,))
            cursor.execute("DELETE FROM repositories WHERE id = %s", (repo_id,))
        conn.commit()
    except Exception:
        logger.warning("MySQL delete failed for repo_id=%s", repo_id, exc_info=True)
    finally:
        if conn is not None:
            conn.close()

    try:
        # 위와 같은 이유로 키 불필요 경로를 쓴다.
        from ..db.chroma import delete_from_existing_collection
        delete_from_existing_collection(where={"repo_id": repo_id})
    except Exception:
        logger.warning("ChromaDB vector cleanup failed for repo_id=%s", repo_id, exc_info=True)
    if project_id is not None:
        from ..project_memory import refresh_project_memory_after_delete
        refresh_project_memory_after_delete(project_id)


def _cleanup_repo_generation(repo_id: int, run_id: str | None) -> None:
    """Best-effort deletion of exactly one non-active repository generation."""
    conn = None
    mysql_cleanup_succeeded = False
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT active_sync_run_id FROM repositories WHERE id=%s",
                (repo_id,),
            )
            repository = cursor.fetchone()
            if repository and repository.get("active_sync_run_id") == run_id:
                return
            cursor.execute(
                "DELETE m FROM memory m JOIN repositories r ON r.id=m.repo_id"
                " WHERE m.repo_id=%s AND m.repo_sync_run_id <=> %s"
                " AND NOT (r.active_sync_run_id <=> %s)",
                (repo_id, run_id, run_id),
            )
        conn.commit()
        mysql_cleanup_succeeded = True
    except Exception:
        if conn is not None:
            conn.rollback()
        logger.warning(
            "repository_mysql_generation_cleanup_failed repo_id=%s",
            repo_id,
            exc_info=True,
        )
    finally:
        if conn is not None:
            conn.close()

    if not mysql_cleanup_succeeded:
        return
    try:
        from ..db.chroma import get_existing_collection

        collection = get_existing_collection()
        if collection is not None:
            raw = collection.get(where={"repo_id": repo_id})
            delete_ids = [
                vector_id
                for vector_id, metadata in zip(
                    raw.get("ids") or [], raw.get("metadatas") or []
                )
                if ((metadata or {}).get("repo_sync_run_id") or None) == run_id
            ]
            if delete_ids:
                collection.delete(ids=delete_ids)
    except Exception:
        logger.warning(
            "repository_chroma_generation_cleanup_failed repo_id=%s",
            repo_id,
            exc_info=True,
        )


# None은 commit_sha=None처럼 DB에 저장될 유효한 값이므로 "미전달"을 구분하는 sentinel 사용
_UNSET = object()


def _claim_sync_run(project_id: int, repo_id: int) -> tuple[dict, dict, bool]:
    """Claim one repository worker fence and allocate its generation UUID."""
    run_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM repositories WHERE id=%s AND project_id=%s FOR UPDATE",
                (repo_id, project_id),
            )
            repo = cursor.fetchone()
            if not repo:
                raise HTTPException(status_code=404, detail="Repository not found")
            if repo.get("status") == "syncing" and repo.get("current_sync_run_id"):
                conn.commit()
                return (
                    repo,
                    {
                        "run_id": repo["current_sync_run_id"],
                        "started_at": repo.get("sync_started_at"),
                    },
                    False,
                )
            cursor.execute(
                "UPDATE repositories SET status='syncing',current_sync_run_id=%s,"
                " sync_started_at=UTC_TIMESTAMP(6),last_error=NULL,sync_warning=NULL"
                " WHERE id=%s",
                (run_id, repo_id),
            )
            cursor.execute(
                "SELECT sync_started_at FROM repositories WHERE id=%s",
                (repo_id,),
            )
            started = cursor.fetchone() or {}
        conn.commit()
        return repo, {"run_id": run_id, "started_at": started.get("sync_started_at")}, True
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _sync_owned(repo_id: int, run_id: str) -> bool:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT current_sync_run_id,status FROM repositories WHERE id=%s",
                (repo_id,),
            )
            repo = cursor.fetchone()
            return bool(
                repo
                and repo.get("current_sync_run_id") == run_id
                and repo.get("status") == "syncing"
            )
    finally:
        conn.close()


def _require_sync_ownership(repo_id: int, run_id: str) -> None:
    if not _sync_owned(repo_id, run_id):
        raise SyncFenceLost(run_id)


def _set_repo_status(
    repo_id: int,
    run_id: str,
    status: str,
    commit_sha=_UNSET,
    indexed_files=_UNSET,
    last_error=_UNSET,
    sync_warning=_UNSET,
    project_id: int | None = None,
) -> tuple[bool, str | None]:
    """Only the owning run may fail or atomically publish its generation."""
    if status not in {"indexed", "failed"}:
        raise ValueError(f"Unsupported repository terminal status: {status}")
    if status == "indexed":
        if project_id is None:
            raise ValueError("project_id is required to publish a repository generation")
        from ..project_memory import project_memory_write_lock

        status_guard = project_memory_write_lock(project_id)
    else:
        status_guard = nullcontext()

    updates: dict = {"status": status, "current_sync_run_id": None}
    if status == "indexed":
        updates["active_sync_run_id"] = run_id
    if commit_sha is not _UNSET and status == "indexed":
        updates["commit_sha"] = commit_sha
    if indexed_files is not _UNSET and status == "indexed":
        updates["indexed_files"] = indexed_files
    if last_error is not _UNSET:
        updates["last_error"] = last_error
    if sync_warning is not _UNSET:
        updates["sync_warning"] = sync_warning

    set_clause = ", ".join(f"{k}=%s" for k in updates)
    with status_guard:
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT active_sync_run_id FROM repositories"
                    " WHERE id=%s AND current_sync_run_id=%s AND status='syncing'"
                    " FOR UPDATE",
                    (repo_id, run_id),
                )
                owned_repo = cursor.fetchone()
                if not owned_repo:
                    conn.rollback()
                    return False, None
                previous_active_run_id = owned_repo.get("active_sync_run_id")
                cursor.execute(
                    f"UPDATE repositories SET {set_clause}"
                    " WHERE id=%s AND current_sync_run_id=%s AND status='syncing'",
                    list(updates.values()) + [repo_id, run_id],
                )
                if cursor.rowcount != 1:
                    conn.rollback()
                    return False, None
                if status == "indexed":
                    cursor.execute(
                        "UPDATE memory predecessor JOIN memory successor"
                        " ON successor.id=predecessor.superseded_by"
                        " SET predecessor.superseded_by=NULL,predecessor.superseded_at=NULL"
                        " WHERE successor.repo_id=%s"
                        " AND NOT (successor.repo_sync_run_id <=> %s)",
                        (repo_id, run_id),
                    )
                    cursor.execute(
                        "UPDATE memory_suggestions s"
                        " JOIN memory target ON target.id=s.memory_id"
                        " LEFT JOIN memory superseding"
                        " ON s.kind='supersede'"
                        " AND superseding.id=CAST(JSON_UNQUOTE(JSON_EXTRACT("
                        "s.evidence,'$.superseding_memory_id')) AS UNSIGNED)"
                        " SET s.status='rejected',s.resolved_at=NOW()"
                        " WHERE s.status='pending' AND ("
                        " (target.repo_id=%s AND NOT (target.repo_sync_run_id <=> %s))"
                        " OR (s.kind='supersede' AND superseding.repo_id=%s"
                        " AND NOT (superseding.repo_sync_run_id <=> %s)))",
                        (repo_id, run_id, repo_id, run_id),
                    )
                    cursor.execute(
                        "DELETE FROM project_memory WHERE project_id=%s",
                        (project_id,),
                    )
            conn.commit()
            return True, previous_active_run_id
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _get_last_reconciled_pr(repo_id: int) -> int | None:
    """repositories 워터마크를 읽는다. 컬럼이 없거나 읽기 실패 시 첫 실행처럼 처리한다."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT last_reconciled_pr FROM repositories WHERE id = %s", (repo_id,))
            row = cursor.fetchone()
        return row.get("last_reconciled_pr") if row else None
    except Exception:
        logger.warning("last_reconciled_pr 조회 실패 repo_id=%s", repo_id, exc_info=True)
        return None
    finally:
        conn.close()


def _detect_published_generation_supersedes(
    project_id: int,
    repo_id: int,
    run_id: str,
) -> None:
    """Run deferred decision supersede detection after a generation is visible."""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id,content,topic,reason,date FROM memory"
                " WHERE project_id=%s AND repo_id=%s AND repo_sync_run_id=%s"
                " AND category='decision' ORDER BY id",
                (project_id, repo_id, run_id),
            )
            rows = cursor.fetchall()
    finally:
        conn.close()
    decisions = [
        {
            "id": row["id"],
            "content": row.get("content") or "",
            "topic": row.get("topic"),
            "reason": row.get("reason"),
            "date": str(row["date"])[:10] if row.get("date") else None,
        }
        for row in rows
        if (row.get("content") or "").strip()
    ]
    if decisions:
        from ..reconciler.supersede import detect_supersede

        detect_supersede(project_id, decisions)


# ── 백그라운드 처리 ───────────────────────────────────────────────

def _sync_bg(
    project_id: int,
    repo_id: int,
    run_id: str,
    full_name: str,
    branch: str,
    token: str | None,
):
    """Collect and stage one generation, then publish it through a fence."""
    from ..pipeline.extractor import extract
    from ..pipeline.ingestor import ingest

    try:
        _require_sync_ownership(repo_id, run_id)
        last_reconciled_pr = _get_last_reconciled_pr(repo_id)
        sources, latest_sha, warnings = _collect_repo_sources(full_name, branch, token=token)
        _require_sync_ownership(repo_id, run_id)
        warnings = list(warnings)

        if not sources:
            _set_repo_status(
                repo_id,
                run_id,
                "failed",
                last_error="REPOSITORY_NO_INDEXABLE_CONTENT",
            )
            _cleanup_repo_generation(repo_id, run_id)
            return

        try:
            merged_prs = _collect_merged_prs(full_name, last_reconciled_pr, token=token)
        except GitHubAPIError as exc:
            warnings.append(
                {
                    "source_type": "merged_pulls",
                    "reason": _sync_failure_code(exc, "merged_pulls"),
                }
            )
            merged_prs = []
        _require_sync_ownership(repo_id, run_id)

        # Complete extraction before any staged write. Raw chunks remain useful
        # when structured extraction fails, so that case becomes a warning.
        prepared_sources = []
        for source_name, source_data in sources.items():
            _require_sync_ownership(repo_id, run_id)
            content = source_data["content"]
            src_metadata = source_data.get("metadata", {})
            if not content or not content.strip():
                continue
            try:
                items = extract(
                    content,
                    default_source=source_name,
                    source_kind=_extract_source_kind(src_metadata.get("source_type")),
                )
            except Exception:
                logger.warning(
                    "repository_extract_failed",
                    extra={"project_id": project_id, "code": "REPOSITORY_EXTRACT_FAILED"},
                )
                warnings.append(
                    {"source_type": source_name, "reason": "REPOSITORY_EXTRACT_FAILED"}
                )
                items = []
            prepared_sources.append((source_name, content, src_metadata, items))

        if not prepared_sources:
            _set_repo_status(
                repo_id,
                run_id,
                "failed",
                commit_sha=latest_sha,
                last_error="REPOSITORY_NO_INDEXABLE_CONTENT",
            )
            _cleanup_repo_generation(repo_id, run_id)
            return

        # Previous active rows remain queryable while these tagged rows stage.
        indexed = 0
        ingest_failed = False
        for source_name, content, src_metadata, items in prepared_sources:
            _require_sync_ownership(repo_id, run_id)
            try:
                ingest(
                    project_id=project_id,
                    doc_id=None,
                    repo_id=repo_id,
                    items=items,
                    raw_text=content,
                    source=source_name,
                    date="",
                    doc_type="repository",
                    source_metadata={"source_kind": "repository", "repo_id": repo_id, **src_metadata},
                    repo_sync_run_id=run_id,
                )
                indexed += 1
            except Exception:
                ingest_failed = True
                logger.warning(
                    "repository_ingest_failed",
                    extra={"project_id": project_id, "code": "REPOSITORY_INGEST_FAILED"},
                )
                warnings.append(
                    {"source_type": source_name, "reason": "REPOSITORY_INGEST_FAILED"}
                )
            _require_sync_ownership(repo_id, run_id)

        if ingest_failed or indexed == 0:
            _set_repo_status(
                repo_id,
                run_id,
                "failed",
                commit_sha=latest_sha,
                indexed_files=indexed,
                last_error="REPOSITORY_INGEST_FAILED",
            )
            _cleanup_repo_generation(repo_id, run_id)
            return

        import json as _json
        sync_warning = _json.dumps(warnings, ensure_ascii=False) if warnings else None
        if warnings:
            logger.warning(
                "repository_sync_partial",
                extra={"project_id": project_id, "code": "REPOSITORY_SYNC_PARTIAL"},
            )

        _require_sync_ownership(repo_id, run_id)
        published, _ = _set_repo_status(
            repo_id,
            run_id,
            "indexed",
            commit_sha=latest_sha,
            indexed_files=indexed,
            last_error=None,
            sync_warning=sync_warning,
            project_id=project_id,
        )
        if not published:
            raise SyncFenceLost(run_id)

        try:
            _detect_published_generation_supersedes(project_id, repo_id, run_id)
        except Exception:
            logger.warning(
                "repository_supersede_detection_failed",
                extra={"project_id": project_id, "code": "SUPERSEDE_DETECTION_FAILED"},
            )

        try:
            from ..project_memory import refresh_project_memory_after_delete

            refresh_project_memory_after_delete(project_id)
        except Exception:
            logger.warning(
                "repository_project_memory_refresh_failed",
                extra={"project_id": project_id, "code": "PROJECT_MEMORY_REFRESH_FAILED"},
            )

        try:
            reconcile_repository_prs(project_id, repo_id, merged_prs)
            logger.info("repository_reconciler_completed")
        except Exception:
            logger.warning("repository_reconciler_failed")

    except SyncFenceLost:
        logger.info("repository_sync_fence_lost repo_id=%s run_id=%s", repo_id, run_id)
        _cleanup_repo_generation(repo_id, run_id)
    except GitHubAPIError as exc:
        code = _sync_failure_code(exc, exc.source)
        logger.error("sync_bg GitHub 실패 repo_id=%s code=%s", repo_id, code)
        _set_repo_status(repo_id, run_id, "failed", last_error=code)
        _cleanup_repo_generation(repo_id, run_id)
    except Exception:
        logger.error("repository_sync_failed", extra={"code": "REPOSITORY_SYNC_FAILED"})
        try:
            _set_repo_status(
                repo_id,
                run_id,
                "failed",
                last_error="REPOSITORY_SYNC_FAILED",
            )
        except Exception:
            logger.error(
                "repository_sync_failure_persist_failed",
                extra={"code": "REPOSITORY_SYNC_FAILURE_PERSIST_FAILED"},
            )
        _cleanup_repo_generation(repo_id, run_id)


# ── Endpoints ────────────────────────────────────────────────────

@router.post("/projects/{project_id}/repositories", status_code=201)
def connect_repository(project_id: int, body: RepositoryConnect):
    require_project_access(project_id, min_role="member")
    if body.provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 provider입니다: {body.provider}")

    full_name = _parse_github_full_name(body.repository_url)
    token = _get_github_token(body.state)

    # 저장소 존재 확인 + default branch 조회
    try:
        repo_meta = _gh_get(f"/repos/{full_name}", token=token, source="metadata")
    except GitHubAPIError as exc:
        raise _connect_failure(exc) from exc
    if not isinstance(repo_meta, dict) or not repo_meta.get("id"):
        detail = "저장소를 찾을 수 없습니다."
        if not token:
            detail += " 비공개 저장소라면 GitHub App 인증 후 state를 전달해주세요."
        raise HTTPException(status_code=404, detail=detail)
    branch = body.branch or repo_meta.get("default_branch") or "main"

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Project not found")
            cursor.execute(
                "INSERT INTO repositories (project_id, provider, repository_url, branch, status)"
                " VALUES (%s, %s, %s, %s, 'connected')",
                (project_id, body.provider, body.repository_url, branch),
            )
            repo_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    # 연결만 등록 (status='connected'). sync는 POST .../repositories/{id}/sync 로 별도 트리거
    return {"repo_id": repo_id, "status": "connected", "branch": branch}


@router.get("/projects/{project_id}/repositories")
def list_repositories(project_id: int):
    require_project_access(project_id)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Project not found")
            cursor.execute(
                "SELECT id, provider, repository_url, branch, status, connected_at"
                " FROM repositories WHERE project_id = %s ORDER BY connected_at DESC",
                (project_id,),
            )
            return cursor.fetchall()
    finally:
        conn.close()


@router.get("/projects/{project_id}/repositories/{repo_id}")
def get_repository(project_id: int, repo_id: int):
    require_project_access(project_id)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            row = _repo_or_404(cursor, project_id, repo_id)
            return {
                "id": row["id"],
                "provider": row["provider"],
                "repository_url": row["repository_url"],
                "branch": row["branch"],
                "status": row["status"],
                "commit_sha": row["commit_sha"],
                "indexed_files": row["indexed_files"],
                "sync_warning": row.get("sync_warning"),
                "active_sync_run_id": row.get("active_sync_run_id"),
                "current_sync_run_id": row.get("current_sync_run_id"),
                "sync_started_at": _utc_iso(row.get("sync_started_at")),
                "connected_at": row["connected_at"],
            }
    finally:
        conn.close()


@router.get("/projects/{project_id}/repositories/{repo_id}/status")
def get_repository_status(project_id: int, repo_id: int):
    require_project_access(project_id)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            row = _repo_or_404(cursor, project_id, repo_id)
            cursor.execute(
                "SELECT category,COUNT(*) as cnt FROM memory"
                " WHERE repo_id=%s AND ((repo_sync_run_id=%s)"
                " OR (%s IS NULL AND repo_sync_run_id IS NULL)) GROUP BY category",
                (
                    repo_id,
                    row.get("active_sync_run_id"),
                    row.get("active_sync_run_id"),
                ),
            )
            counts = {"decision": 0, "action": 0, "issue": 0, "risk": 0}
            for r in cursor.fetchall():
                if r["category"] in counts:
                    counts[r["category"]] = r["cnt"]
    finally:
        conn.close()

    return {
        "repo_id": row["id"],
        "status": row["status"],
        "provider": row["provider"],
        "repository_url": row["repository_url"],
        "branch": row["branch"],
        "commit_sha": row["commit_sha"],
        "indexed_files": row["indexed_files"],
        "last_error": row.get("last_error"),
        "sync_warning": row.get("sync_warning"),
        "run_id": row.get("current_sync_run_id"),
        "sync_started_at": _utc_iso(row.get("sync_started_at")),
        "active_sync_run_id": row.get("active_sync_run_id"),
        "extracted": counts,
    }


@router.post("/projects/{project_id}/repositories/{repo_id}/sync", status_code=202)
def sync_repository(
    project_id: int,
    repo_id: int,
    background_tasks: BackgroundTasks,
    body: SyncRequest = SyncRequest(),
):
    require_project_access(project_id, min_role="member")
    # token 먼저 검증 — 실패 시 DB 변경 없이 즉시 401 반환
    token = _get_github_token(body.state)

    repo_row, run, created = _claim_sync_run(project_id, repo_id)
    if not created:
        return {
            "repo_id": repo_id,
            "status": "syncing",
            "run_id": run["run_id"],
            "sync_started_at": _utc_iso(run["started_at"]),
        }

    try:
        full_name = _parse_github_full_name(repo_row["repository_url"])
    except HTTPException:
        _set_repo_status(
            repo_id,
            run["run_id"],
            "failed",
            last_error="INVALID_REPOSITORY_URL",
        )
        raise
    branch = repo_row["branch"] or "main"

    background_tasks.add_task(
        _sync_bg,
        project_id,
        repo_id,
        run["run_id"],
        full_name,
        branch,
        token,
    )

    return {
        "repo_id": repo_id,
        "status": "syncing",
        "run_id": run["run_id"],
        "sync_started_at": _utc_iso(run["started_at"]),
    }


@router.delete("/projects/{project_id}/repositories/{repo_id}", status_code=204)
def delete_repository(project_id: int, repo_id: int):
    require_project_access(project_id, min_role="member")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            _repo_or_404(cursor, project_id, repo_id)
    finally:
        conn.close()

    _delete_repo_data(repo_id)
