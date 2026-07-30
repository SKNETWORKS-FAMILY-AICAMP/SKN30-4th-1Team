import base64
import calendar
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

router = APIRouter(prefix="/github/app", tags=["github"])
logger = logging.getLogger(__name__)


class SessionExpiredException(Exception):
    """GitHub App 세션 만료 — main.py exception_handler가 410 top-level JSON으로 변환."""

GITHUB_API_BASE = "https://api.github.com"
GITHUB_WEB_BASE = "https://github.com"
GITHUB_API_VERSION = "2022-11-28"
SESSION_TTL_SECONDS = 30 * 60


@dataclass
class GithubAppSession:
    created_at: float
    installation_id: int | None = None
    setup_action: str = ""


# ponytail: in-memory install sessions; move to DB/Redis when user auth or multi-worker API exists.
_sessions: dict[str, GithubAppSession] = {}
# 만료된 state를 5분간 기억 — prune 이후에도 410 반환 가능하게 보장
_expired_states: dict[str, float] = {}
_EXPIRED_GRACE_SECONDS = 5 * 60


class GithubRepositoryPreviewRequest(BaseModel):
    repository_url: str
    state: str | None = None
    branch: str | None = None
    head_only: bool = False


def _base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _json_request(method: str, path: str, token: str | None = None, body: dict[str, Any] | None = None):
    url = path if path.startswith("https://") else f"{GITHUB_API_BASE}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(url, data=data, headers=headers, method=method)

    try:
        with request.urlopen(req, timeout=15) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except error.HTTPError as exc:
        # GitHub 원문은 토큰·조직 정책 등 민감한 진단을 포함할 수 있으므로 읽거나
        # 전달하지 않는다. 호출자는 status/code만으로 안정적으로 분기한다.
        status_code, code = {
            401: (401, "GITHUB_APP_AUTH_FAILED"),
            403: (403, "GITHUB_APP_PERMISSION_DENIED"),
            404: (404, "GITHUB_APP_RESOURCE_NOT_FOUND"),
        }.get(exc.code, (503, "GITHUB_APP_UNAVAILABLE"))
        logger.warning("GitHub App API HTTP 오류 status=%s path=%s", exc.code, path)
        raise HTTPException(
            status_code=status_code,
            detail={"code": code, "message": "GitHub App 요청에 실패했습니다."},
        ) from exc
    except error.URLError as exc:
        # reason에도 upstream hostname/transport 진단이 들어갈 수 있어 외부 응답과
        # 로그에 싣지 않는다.
        logger.warning("GitHub App API 네트워크 오류 path=%s", path)
        raise HTTPException(
            status_code=503,
            detail={"code": "GITHUB_APP_UNAVAILABLE", "message": "GitHub App 요청에 실패했습니다."},
        ) from exc


def _private_key_pem() -> str:
    key = os.getenv("GITHUB_APP_PRIVATE_KEY", "").replace("\\n", "\n").strip()
    key_path = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "").strip()

    if key:
        return key

    if key_path:
        with open(key_path, encoding="utf-8") as key_file:
            return key_file.read()

    raise HTTPException(status_code=503, detail="GITHUB_APP_PRIVATE_KEY is not configured")


def _github_app_jwt() -> str:
    app_id = os.getenv("GITHUB_APP_ID", "").strip()

    if not app_id:
        raise HTTPException(status_code=503, detail="GITHUB_APP_ID is not configured")

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iat": now - 60,
        "exp": now + 9 * 60,
        "iss": app_id,
    }
    signing_input = (
        f"{_base64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_base64url(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    private_key = serialization.load_pem_private_key(
        _private_key_pem().encode("utf-8"),
        password=None,
    )
    signature = private_key.sign(
        signing_input.encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )

    return f"{signing_input}.{_base64url(signature)}"


def _prune_sessions() -> None:
    now = time.time()
    expires_before = now - SESSION_TTL_SECONDS
    for state in [s for s, sess in _sessions.items() if sess.created_at < expires_before]:
        _expired_states[state] = now
        del _sessions[state]
    # 그레이스 기간 지난 tombstone 정리
    stale_before = now - _EXPIRED_GRACE_SECONDS
    for state in [s for s, t in _expired_states.items() if t < stale_before]:
        del _expired_states[state]


def _session_or_404(state: str) -> GithubAppSession:
    session = _sessions.get(state)

    if session is not None:
        if session.created_at < time.time() - SESSION_TTL_SECONDS:
            _expired_states[state] = time.time()
            del _sessions[state]
            raise SessionExpiredException()
        return session

    _prune_sessions()
    if state in _expired_states:
        raise SessionExpiredException()
    raise HTTPException(status_code=404, detail="GitHub App session not found")


def _install_url(state: str) -> str:
    configured_url = os.getenv("GITHUB_APP_INSTALL_URL", "").strip()
    app_slug = os.getenv("GITHUB_APP_SLUG", "").strip()

    if configured_url:
        base_url = configured_url
    elif app_slug:
        base_url = f"{GITHUB_WEB_BASE}/apps/{app_slug}/installations/new"
    else:
        raise HTTPException(status_code=503, detail="GITHUB_APP_SLUG is not configured")

    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}state={parse.quote(state)}"


def _repo_full_name(raw_url: str) -> str:
    trimmed = raw_url.strip().removesuffix(".git")
    ssh_match = trimmed.startswith("git@github.com:")

    if ssh_match:
        owner_repo = trimmed.removeprefix("git@github.com:")
    else:
        try:
            url = parse.urlparse(trimmed if trimmed.startswith("http") else f"https://{trimmed}")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid GitHub repository URL")

        if url.netloc != "github.com":
            raise HTTPException(status_code=400, detail="Invalid GitHub repository URL")

        owner_repo = url.path.strip("/")

    parts = [part for part in owner_repo.split("/") if part]

    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Invalid GitHub repository URL")

    return f"{parts[0]}/{parts[1]}"


def _installation_token(state: str) -> str:
    session = _session_or_404(state)

    if not session.installation_id:
        raise HTTPException(status_code=409, detail="GitHub App installation is not complete")

    response = _json_request(
        "POST",
        f"/app/installations/{session.installation_id}/access_tokens",
        token=_github_app_jwt(),
    )

    token = response.get("token")

    if not token:
        raise HTTPException(status_code=502, detail="GitHub did not return an installation token")

    return token


def _github_repo_preview(
    repository_url: str,
    state: str | None = None,
    requested_branch: str | None = None,
):
    full_name = _repo_full_name(repository_url)
    token = _installation_token(state) if state else None
    auth_provider = "github_app" if token else "public"

    try:
        repo = _json_request("GET", f"/repos/{full_name}", token=token)
        branch = (requested_branch or "").strip() or repo.get("default_branch") or "main"
        commits = _json_request(
            "GET",
            f"/repos/{full_name}/commits?sha={parse.quote(branch, safe='')}&per_page=6",
            token=token,
        )
        issues = _json_request(
            "GET",
            f"/repos/{full_name}/issues?state=open&per_page=6",
            token=token,
        )
        pulls = _json_request(
            "GET",
            f"/repos/{full_name}/pulls?state=open&per_page=6",
            token=token,
        )
    except HTTPException as exc:
        if not token and exc.status_code in {401, 403, 404}:
            raise HTTPException(
                status_code=401,
                detail="Private repository requires GitHub App login",
            )
        raise

    open_issues = [issue for issue in issues if not issue.get("pull_request")]
    events = _github_events(commits, issues, pulls)

    return {
        "events": events,
        "repository": {
            "path": repo.get("html_url", f"https://github.com/{full_name}"),
            "name": repo.get("name", full_name.split("/")[-1]),
            "branch": branch,
            "isDirty": False,
            "remoteRepo": repo.get("full_name", full_name),
            "issuePrStatus": f"{len(open_issues)} open issues · {len(pulls)} open PRs",
            "visibility": "private" if repo.get("private") else "public",
            "authProvider": auth_provider,
            "remoteHeadSha": commits[0].get("sha") if commits else None,
        },
    }


def _github_owner_profile(owner: dict[str, Any] | None):
    if not owner or not owner.get("login"):
        return None

    return {
        "login": owner.get("login"),
        "avatarUrl": owner.get("avatar_url", ""),
        "htmlUrl": owner.get("html_url", f"{GITHUB_WEB_BASE}/{owner.get('login')}"),
        "name": None,
    }


def _github_timestamp(value: str | None) -> int:
    if not value:
        return int(time.time() * 1000)

    try:
        return int(calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")) * 1000)
    except ValueError:
        return int(time.time() * 1000)


def _github_events(commits: list[dict[str, Any]], issues: list[dict[str, Any]], pulls: list[dict[str, Any]]):
    commit_events = [
        {
            "id": f"commit-{commit.get('sha', '')}",
            "type": "commit",
            "title": (commit.get("commit", {}).get("message", "").split("\n")[0])
            or commit.get("sha", "")[:7],
            "createdAt": _github_timestamp(
                commit.get("commit", {}).get("author", {}).get("date"),
            ),
            "status": commit.get("sha", "")[:7],
            "url": commit.get("html_url"),
        }
        for commit in commits
    ]
    issue_events = [
        {
            "id": f"issue-{issue.get('number')}",
            "type": "issue",
            "title": f"issue #{issue.get('number')} {issue.get('title', '')}",
            "createdAt": _github_timestamp(issue.get("updated_at")),
            "status": issue.get("state"),
            "url": issue.get("html_url"),
        }
        for issue in issues
        if not issue.get("pull_request")
    ]
    pull_events = [
        {
            "id": f"pull_request-{pull.get('number')}",
            "type": "pull_request",
            "title": f"PR #{pull.get('number')} {pull.get('title', '')}",
            "createdAt": _github_timestamp(pull.get("updated_at")),
            "status": pull.get("state"),
            "url": pull.get("html_url"),
        }
        for pull in pulls
    ]

    return sorted(
        [*commit_events, *issue_events, *pull_events],
        key=lambda item: item["createdAt"],
        reverse=True,
    )[:10]


@router.post("/sessions", status_code=201)
def create_github_app_session():
    _prune_sessions()
    state = secrets.token_urlsafe(32)
    _sessions[state] = GithubAppSession(created_at=time.time())

    return {
        "state": state,
        "status": "pending",
        "installUrl": _install_url(state),
        "expiresIn": SESSION_TTL_SECONDS,
    }


@router.get("/sessions/{state}")
def get_github_app_session(state: str):
    session = _session_or_404(state)

    return {
        "state": state,
        "status": "connected" if session.installation_id else "pending",
        "setupAction": session.setup_action,
    }


@router.get("/sessions/{state}/repositories")
def list_github_app_repositories(state: str):
    token = _installation_token(state)
    response = _json_request("GET", "/installation/repositories?per_page=100", token=token)
    repositories = response.get("repositories", [])

    return {
        "repositories": [
            {
                "fullName": repo.get("full_name"),
                "name": repo.get("name"),
                "private": bool(repo.get("private")),
                "defaultBranch": repo.get("default_branch"),
                "url": repo.get("html_url"),
                "owner": _github_owner_profile(repo.get("owner")),
            }
            for repo in repositories
        ],
        "user": next(
            (
                profile
                for profile in (_github_owner_profile(repo.get("owner")) for repo in repositories)
                if profile
            ),
            None,
        ),
    }


@router.post("/repository-preview")
def preview_github_repository(body: GithubRepositoryPreviewRequest):
    if body.head_only:
        full_name = _repo_full_name(body.repository_url)
        token = _installation_token(body.state) if body.state else None
        branch = (body.branch or "").strip()
        if not branch:
            raise HTTPException(status_code=400, detail="branch is required")

        commits = _json_request(
            "GET",
            f"/repos/{full_name}/commits?sha={parse.quote(branch, safe='')}&per_page=1",
            token=token,
        )
        return {
            "branch": branch,
            "remoteHeadSha": commits[0].get("sha") if commits else None,
        }

    return _github_repo_preview(
        body.repository_url,
        state=body.state,
        requested_branch=body.branch,
    )


@router.get("/callback", response_class=HTMLResponse)
def github_app_callback(
    installation_id: int | None = None,
    setup_action: str = "",
    state: str = "",
):
    if not state:
        raise HTTPException(status_code=400, detail="state is required")

    session = _session_or_404(state)

    if not installation_id:
        raise HTTPException(status_code=400, detail="installation_id is required")

    session.installation_id = installation_id
    session.setup_action = setup_action

    return HTMLResponse(
        """
        <!doctype html>
        <html lang="ko">
          <head><meta charset="utf-8"><title>PaiM GitHub 연결</title></head>
          <body>
            <h1>PaiM GitHub 연결 완료</h1>
            <p>PaiM 데스크톱 앱으로 돌아가서 설치 완료 확인을 누르세요.</p>
          </body>
        </html>
        """,
    )
