import { invoke } from "@tauri-apps/api/core";

import type {
  GithubAccessTokenResponse,
  GithubAvailableRepository,
  GithubDeviceCodeResponse,
  GithubPanelState,
  GithubUserProfile,
  GitHubTimelineEvent,
  GitRepositoryInfo,
} from "./types";
import { fetchPaimRootJson, fetchPaimRootJsonPreservingSession } from "./paimApi";

type GitHubRepoApiResponse = {
  default_branch: string;
  full_name: string;
  html_url: string;
  name: string;
  owner?: GitHubOwnerApiResponse | null;
  private: boolean;
};

type GitHubUserRepoApiResponse = GitHubRepoApiResponse & {
  updated_at?: string;
};

type GitHubInstallationApiResponse = {
  id: number;
};

type GitHubInstallationsApiResponse = {
  installations: GitHubInstallationApiResponse[];
};

type GitHubInstallationRepositoriesApiResponse = {
  repositories: GitHubUserRepoApiResponse[];
};

type GitHubUserApiResponse = {
  avatar_url: string;
  html_url: string;
  login: string;
  name?: string | null;
};

type GitHubOwnerApiResponse = {
  avatar_url?: string | null;
  html_url?: string | null;
  login?: string | null;
};

type GitHubCommitApiResponse = {
  author?: {
    login?: string;
  } | null;
  html_url: string;
  sha: string;
  commit: {
    author?: {
      date?: string;
      name?: string;
    };
    message: string;
  };
};

type GitHubIssueApiResponse = {
  closed_at?: string | null;
  html_url: string;
  number: number;
  pull_request?: unknown;
  state: string;
  title: string;
  updated_at: string;
  user?: {
    login?: string;
  } | null;
};

type GitHubPullApiResponse = {
  closed_at?: string | null;
  html_url: string;
  merged_at?: string | null;
  number: number;
  state: string;
  title: string;
  updated_at: string;
  user?: {
    login?: string;
  } | null;
};

type GithubAppSessionApiResponse = {
  state: string;
  status: "pending" | "connected";
  installUrl?: string;
  setupAction?: string;
};

type GithubRepositoriesApiResponse = {
  repositories: GithubAvailableRepository[];
  user?: GithubUserProfile;
};

type GithubRepositoryPreviewApiResponse = {
  events: GitHubTimelineEvent[];
  repository: GitRepositoryInfo;
};

type GithubRepositoryHead = {
  branch: string;
  remoteHeadSha: string | null;
};

const GITHUB_CLIENT_ID = (
  (import.meta.env.VITE_GITHUB_CLIENT_ID as string | undefined) ||
  (import.meta.env.VITE_GITHUB_APP_CLIENT_ID as string | undefined) ||
  ""
).trim();
const GITHUB_CLIENT_ID_STORAGE_KEY = "paim.githubClientId.v1";
const GITHUB_LOGIN_CONFIG_ERROR_MESSAGE =
  "이 앱 빌드에는 GitHub 로그인이 아직 설정되어 있지 않습니다. 개발팀에 문의해 주세요.";
const GITHUB_LOGIN_SCOPE = "public_repo read:user";
export const GITHUB_REMOTE_HEAD_TTL_MS = 5 * 60 * 1000;

function normalizeGithubCommitSha(value?: string | null) {
  return value?.trim().toLowerCase() ?? "";
}

export function githubCommitShasMatch(left?: string | null, right?: string | null) {
  const normalizedLeft = normalizeGithubCommitSha(left);
  const normalizedRight = normalizeGithubCommitSha(right);

  return Boolean(
    normalizedLeft &&
      normalizedRight &&
      (normalizedLeft === normalizedRight ||
        normalizedLeft.startsWith(normalizedRight) ||
        normalizedRight.startsWith(normalizedLeft)),
  );
}

export function getGithubRemoteCheckStatus(
  repository: GitRepositoryInfo,
  now = Date.now(),
) {
  if (
    repository.remoteCheckStatus === "checking" ||
    repository.remoteCheckStatus === "error"
  ) {
    return repository.remoteCheckStatus;
  }

  const attemptedAt = repository.remoteCheckAttemptedAt ?? repository.remoteCheckedAt;
  if (
    typeof attemptedAt !== "number" ||
    !Number.isFinite(attemptedAt) ||
    now < attemptedAt ||
    now - attemptedAt >= GITHUB_REMOTE_HEAD_TTL_MS
  ) {
    return "unknown" as const;
  }

  if (!repository.commitSha || !repository.remoteHeadSha) {
    return "unknown" as const;
  }

  return githubCommitShasMatch(repository.commitSha, repository.remoteHeadSha)
    ? "current" as const
    : "needs_sync" as const;
}

function canUseTauriRuntime() {
  return "__TAURI_INTERNALS__" in window;
}

// GitHub URL 입력값을 API 호출에 필요한 owner/repo로 정규화한다.
function parseGithubRepositoryUrl(rawUrl: string) {
  const trimmedUrl = rawUrl.trim().replace(/\.git$/, "");
  const sshMatch = trimmedUrl.match(/^git@github\.com:([^/]+)\/([^/]+)$/);

  if (sshMatch) {
    return { owner: sshMatch[1], repo: sshMatch[2] };
  }

  try {
    const url = new URL(trimmedUrl.startsWith("http") ? trimmedUrl : `https://${trimmedUrl}`);

    if (url.hostname !== "github.com") {
      return null;
    }

    const [owner, repo] = url.pathname.split("/").filter(Boolean);

    return owner && repo ? { owner, repo } : null;
  } catch {
    return null;
  }
}

export function getGithubOAuthErrorMessage(
  error: string | undefined,
  description: string | undefined,
  fallback: string,
) {
  if (error === "device_flow_disabled") {
    return "GitHub App 설정에서 Device Flow를 켜야 로그인할 수 있습니다.";
  }

  if (error === "incorrect_client_credentials") {
    return "GitHub 로그인 설정이 올바르지 않습니다. 개발팀에 문의해 주세요.";
  }

  return description || fallback;
}

function githubTimestamp(value: string | undefined) {
  const timestamp = value ? Date.parse(value) : NaN;
  return Number.isFinite(timestamp) ? timestamp : Date.now();
}

// GitHub API 응답 세 종류를 우측 패널 타임라인 이벤트로 합친다.
function createGithubEvents(
  commits: GitHubCommitApiResponse[],
  issues: GitHubIssueApiResponse[],
  pulls: GitHubPullApiResponse[],
): GitHubTimelineEvent[] {
  const commitEvents = commits.map((commit) => ({
    author: commit.author?.login ?? commit.commit.author?.name,
    id: `commit-${commit.sha}`,
    type: "commit" as const,
    title: commit.commit.message.split("\n")[0] || commit.sha.slice(0, 7),
    createdAt: githubTimestamp(commit.commit.author?.date),
    status: commit.sha.slice(0, 7),
    url: commit.html_url,
  }));
  const issueEvents = issues
    .filter((issue) => !issue.pull_request)
    .map((issue) => ({
      author: issue.user?.login,
      id: `issue-${issue.number}`,
      number: issue.number,
      type: "issue" as const,
      title: issue.title,
      createdAt: githubTimestamp(issue.closed_at ?? issue.updated_at),
      status: issue.state,
      url: issue.html_url,
    }));
  const pullEvents = pulls.map((pull) => ({
    author: pull.user?.login,
    id: `pull_request-${pull.number}`,
    number: pull.number,
    type: "pull_request" as const,
    title: pull.title,
    createdAt: githubTimestamp(pull.merged_at ?? pull.closed_at ?? pull.updated_at),
    status: pull.merged_at ? "merged" : pull.state,
    url: pull.html_url,
  }));

  return [...commitEvents, ...issueEvents, ...pullEvents]
    .sort((left, right) => right.createdAt - left.createdAt)
    .slice(0, 30);
}

// GitHub OAuth device flow 시작은 브라우저 CORS를 피하려고 Tauri 명령을 우선 사용한다.
export async function createGithubDeviceCode(signal?: AbortSignal) {
  const clientId = getGithubClientId();

  if (!clientId) {
    throw new Error(GITHUB_LOGIN_CONFIG_ERROR_MESSAGE);
  }

  if (!canUseTauriRuntime()) {
    return postGithubOAuthForm<GithubDeviceCodeResponse>(
      "https://github.com/login/device/code",
      {
        client_id: clientId,
        scope: GITHUB_LOGIN_SCOPE,
      },
      signal,
    );
  }

  return invoke<GithubDeviceCodeResponse>("github_oauth_device_code", {
    clientId,
    scope: GITHUB_LOGIN_SCOPE,
  });
}

// 사용자가 브라우저 인증을 끝냈는지 확인하고 access token을 받는다.
export async function fetchGithubAccessToken(deviceCode: string, signal?: AbortSignal) {
  const clientId = getGithubClientId();

  if (!clientId) {
    throw new Error(GITHUB_LOGIN_CONFIG_ERROR_MESSAGE);
  }

  if (!canUseTauriRuntime()) {
    return postGithubOAuthForm<GithubAccessTokenResponse>(
      "https://github.com/login/oauth/access_token",
      {
        client_id: clientId,
        device_code: deviceCode,
        grant_type: "urn:ietf:params:oauth:grant-type:device_code",
      },
      signal,
    );
  }

  return invoke<GithubAccessTokenResponse>("github_oauth_access_token", {
    clientId,
    deviceCode,
  });
}

function getGithubClientId() {
  return GITHUB_CLIENT_ID || localStorage.getItem(GITHUB_CLIENT_ID_STORAGE_KEY)?.trim() || "";
}

async function postGithubOAuthForm<T>(
  url: string,
  params: Record<string, string>,
  signal?: AbortSignal,
) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams(params),
    signal,
  });

  if (!response.ok) {
    throw new Error(`GitHub OAuth ${response.status}`);
  }

  return response.json() as Promise<T>;
}

function getGithubHeaders(accessToken?: string | null) {
  return {
    Accept: "application/vnd.github+json",
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
  };
}

async function fetchGithubJson<T>(
  path: string,
  accessToken?: string | null,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`https://api.github.com${path}`, {
    headers: getGithubHeaders(accessToken),
    signal,
  });

  if (!response.ok) {
    throw new Error(`GitHub API ${response.status}`);
  }

  return response.json() as Promise<T>;
}

function toGithubOwnerProfile(owner: GitHubOwnerApiResponse | null | undefined) {
  if (!owner?.login) {
    return undefined;
  }

  return {
    login: owner.login,
    avatarUrl: owner.avatar_url ?? "",
    htmlUrl: owner.html_url ?? `https://github.com/${owner.login}`,
    name: null,
  } satisfies GithubUserProfile;
}

function toGithubAvailableRepository(repository: GitHubRepoApiResponse): GithubAvailableRepository {
  return {
    fullName: repository.full_name,
    name: repository.name,
    private: repository.private,
    defaultBranch: repository.default_branch,
    url: repository.html_url,
    owner: toGithubOwnerProfile(repository.owner),
  };
}

async function fetchGithubUserRepositories(accessToken: string, signal?: AbortSignal) {
  return fetchGithubJson<GitHubUserRepoApiResponse[]>(
    "/user/repos?visibility=all&affiliation=owner,collaborator,organization_member&sort=updated&per_page=100",
    accessToken,
    signal,
  );
}

async function fetchGithubInstallationRepositories(accessToken: string, signal?: AbortSignal) {
  const response = await fetchGithubJson<GitHubInstallationsApiResponse>(
    "/user/installations?per_page=100",
    accessToken,
    signal,
  );
  const repositoryResponses = await Promise.all(
    response.installations.map((installation) =>
      fetchGithubJson<GitHubInstallationRepositoriesApiResponse>(
        `/user/installations/${installation.id}/repositories?per_page=100`,
        accessToken,
        signal,
      ),
    ),
  );

  return repositoryResponses.flatMap((repositoryResponse) => repositoryResponse.repositories);
}

export async function fetchGithubRepositories(accessToken: string, signal?: AbortSignal) {
  const [installationRepositories, userRepositories] = await Promise.all([
    fetchGithubInstallationRepositories(accessToken, signal).catch(() => null),
    fetchGithubUserRepositories(accessToken, signal).catch(() => null),
  ]);
  const repositories = [...(installationRepositories ?? []), ...(userRepositories ?? [])];
  const seenRepositories = new Set<string>();

  if (!installationRepositories && !userRepositories) {
    throw new Error("GitHub repo 목록을 불러올 수 없습니다");
  }

  const visibleRepositories = repositories
    .filter((repository) => {
      if (seenRepositories.has(repository.full_name)) {
        return false;
      }

      seenRepositories.add(repository.full_name);
      return true;
    })
    .map(toGithubAvailableRepository);

  return {
    repositories: visibleRepositories,
    user: visibleRepositories.find((repository) => repository.owner)?.owner,
  };
}

export async function fetchGithubUserProfile(
  accessToken: string,
  signal?: AbortSignal,
): Promise<GithubUserProfile> {
  const user = await fetchGithubJson<GitHubUserApiResponse>("/user", accessToken, signal);

  return {
    login: user.login,
    avatarUrl: user.avatar_url,
    htmlUrl: user.html_url,
    name: user.name ?? null,
  };
}

export async function createGithubAppSession(signal?: AbortSignal) {
  return fetchPaimRootJson<GithubAppSessionApiResponse>("/github/app/sessions", {
    method: "POST",
    signal,
  });
}

export async function fetchGithubAppSession(state: string, signal?: AbortSignal) {
  return fetchPaimRootJsonPreservingSession<GithubAppSessionApiResponse>(
    `/github/app/sessions/${encodeURIComponent(state)}`,
    { signal },
  );
}

export async function fetchGithubAppRepositories(state: string, signal?: AbortSignal) {
  return fetchPaimRootJsonPreservingSession<GithubRepositoriesApiResponse>(
    `/github/app/sessions/${encodeURIComponent(state)}/repositories`,
    { signal },
  );
}

export async function fetchGithubAppRepositoryPreview(
  repositoryUrl: string,
  state: string,
  signal?: AbortSignal,
  branch?: string,
) {
  return fetchPaimRootJsonPreservingSession<GithubRepositoryPreviewApiResponse>("/github/app/repository-preview", {
    method: "POST",
    body: JSON.stringify({ repository_url: repositoryUrl, state, branch }),
    signal,
  });
}

export async function fetchGithubAppRepositoryHead(
  repositoryUrl: string,
  branch: string,
  state: string,
  signal?: AbortSignal,
) {
  return fetchPaimRootJsonPreservingSession<GithubRepositoryHead>("/github/app/repository-preview", {
    method: "POST",
    body: JSON.stringify({
      repository_url: repositoryUrl,
      state,
      branch,
      head_only: true,
    }),
    signal,
  });
}

export async function fetchGithubRepository(
  rawUrl: string,
  accessToken?: string | null,
  signal?: AbortSignal,
  requestedBranch?: string,
) {
  const parsedRepo = parseGithubRepositoryUrl(rawUrl);

  if (!parsedRepo) {
    throw new Error("GitHub repository URL을 확인할 수 없습니다");
  }

  const repoPath = `/repos/${parsedRepo.owner}/${parsedRepo.repo}`;
  const repo = await fetchGithubJson<GitHubRepoApiResponse>(repoPath, accessToken, signal);
  const branch = requestedBranch?.trim() || repo.default_branch;
  const [commits, issues, pulls] = await Promise.all([
    fetchGithubJson<GitHubCommitApiResponse[]>(
      `${repoPath}/commits?sha=${encodeURIComponent(branch)}&per_page=24`,
      accessToken,
      signal,
    ),
    fetchGithubJson<GitHubIssueApiResponse[]>(
      `${repoPath}/issues?state=all&sort=updated&direction=desc&per_page=12`,
      accessToken,
      signal,
    ),
    fetchGithubJson<GitHubPullApiResponse[]>(
      `${repoPath}/pulls?state=all&sort=updated&direction=desc&per_page=12`,
      accessToken,
      signal,
    ),
  ]);
  const openIssues = issues.filter((issue) => !issue.pull_request);

  return {
    events: createGithubEvents(commits, issues, pulls),
    repository: {
      path: repo.html_url,
      name: repo.name,
      branch,
      isDirty: false,
      remoteRepo: repo.full_name,
      issuePrStatus: `${openIssues.length} open issues · ${pulls.length} open PRs`,
      visibility: repo.private ? "private" as const : "public" as const,
      authProvider: accessToken ? "github_oauth" as const : "public" as const,
      remoteHeadSha: commits[0]?.sha ?? null,
    } satisfies GitRepositoryInfo,
  };
}

export async function fetchGithubRepositoryHead(
  rawUrl: string,
  branch: string,
  accessToken?: string | null,
  signal?: AbortSignal,
): Promise<GithubRepositoryHead> {
  const parsedRepo = parseGithubRepositoryUrl(rawUrl);

  if (!parsedRepo) {
    throw new Error("GitHub repository URL을 확인할 수 없습니다");
  }

  const normalizedBranch = branch.trim();
  if (!normalizedBranch) {
    throw new Error("GitHub branch를 확인할 수 없습니다");
  }

  const commits = await fetchGithubJson<GitHubCommitApiResponse[]>(
    `/repos/${parsedRepo.owner}/${parsedRepo.repo}/commits?sha=${encodeURIComponent(normalizedBranch)}&per_page=1`,
    accessToken,
    signal,
  );

  return {
    branch: normalizedBranch,
    remoteHeadSha: commits[0]?.sha ?? null,
  };
}

export function getGithubPanelStateLabel(panelState: GithubPanelState) {
  const labels: Record<GithubPanelState, string> = {
    signedout: "미연결",
    authing: "로그인 중",
    repos: "로그인됨",
    connected: "연결됨",
  };

  return labels[panelState];
}
