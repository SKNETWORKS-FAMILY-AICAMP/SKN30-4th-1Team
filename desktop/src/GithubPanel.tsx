import { Check, Copy, GitBranch, Link2, LogOut, MoreHorizontal, RefreshCcw, Search, X } from "lucide-react";
import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Divider } from "@astryxdesign/core/Divider";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Spinner } from "@astryxdesign/core/Spinner";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useEffect, useState } from "react";

import githubMark from "../assets/github/github-mark.svg";
import tablerAlertCircle from "./assets/tabler-icons/alert-circle.svg?raw";
import tablerGitCommit from "./assets/tabler-icons/git-commit.svg?raw";
import tablerGitPullRequest from "./assets/tabler-icons/git-pull-request.svg?raw";
import { formatRelativeAge } from "./format";
import { GITHUB_REMOTE_HEAD_TTL_MS, getGithubRemoteCheckStatus } from "./github";
import { useI18n } from "./i18n";
import type { LanguageSetting } from "./settings";
import type {
  DemoStatus,
  GithubAvailableRepository,
  GithubLoginSessionState,
  GithubPanelState,
  GitHubEventType,
  GitHubTimelineEvent,
  GitRepositoryInfo,
  ProjectMemoryItem,
} from "./types";

type SvgIconProps = {
  className?: string;
  label?: string;
  svg: string;
};

type GithubPanelProps = {
  canManage: boolean;
  connectingRepositoryUrl: string | null;
  demoStatus: DemoStatus | null;
  events: GitHubTimelineEvent[];
  filteredRepositories: GithubAvailableRepository[];
  githubConnected?: boolean;
  isAuthChecking: boolean;
  isAuthStarting: boolean;
  isConnecting: boolean;
  isDisconnectConfirming: boolean;
  isRepoLoading: boolean;
  isSyncing: boolean;
  onCheckLogin: () => void;
  onConnectRepository: (repositoryUrl: string) => void;
  onDisconnect: () => void;
  onLoadRepositories: () => void;
  onOpenMemory: () => void;
  onOpenVerification: () => void;
  onQueryChange: (query: string) => void;
  onRefreshRepository: () => void;
  onResetLogin: () => void;
  onStartLogin: () => void;
  onStartPrivateLogin: () => void;
  onSyncRepository: () => void;
  panelState: GithubPanelState;
  memoryItems: ProjectMemoryItem[];
  repositories: GithubAvailableRepository[];
  repository?: GitRepositoryInfo;
  repositoryQuery: string;
  session: GithubLoginSessionState | null;
  statusRevision: number;
};

const githubFeatureCards = [
  {
    description: "최근 푸시·머지 이력",
    icon: tablerGitCommit,
    title: "커밋 타임라인",
    tone: "commit",
  },
  {
    description: "열린 작업 현황",
    icon: tablerGitPullRequest,
    title: "PR · 이슈",
    tone: "pull_request",
  },
  {
    description: "이슈와 리스크 연결",
    icon: tablerAlertCircle,
    title: "메모리 연동",
    tone: "issue",
  },
] as const;

function SvgIcon({ className = "", label, svg }: SvgIconProps) {
  return (
    <span
      aria-hidden={label ? undefined : true}
      aria-label={label}
      className={`tabler-icon ${className}`.trim()}
      role={label ? "img" : undefined}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

function getGithubEventIconSvg(eventType: GitHubEventType) {
  if (eventType === "pull_request") {
    return tablerGitPullRequest;
  }

  if (eventType === "commit") {
    return tablerGitCommit;
  }

  return tablerAlertCircle;
}

function getGithubEventMeta(event: GitHubTimelineEvent, language: LanguageSetting) {
  const items = [];

  if (event.status) {
    items.push(event.type === "commit" ? event.status : event.status.toUpperCase());
  }

  if (event.author) {
    items.push(event.author);
  }

  items.push(formatRelativeAge(event.createdAt, language));

  return items;
}

function getGithubEventLabel(event: GitHubTimelineEvent) {
  if (event.type === "pull_request") {
    return event.number ? `PR #${event.number}` : "PR";
  }

  if (event.type === "issue") {
    return event.number ? `ISSUE #${event.number}` : "ISSUE";
  }

  return "COMMIT";
}

function getGithubRepoShortName(repository: GitRepositoryInfo) {
  return (repository.remoteRepo ?? repository.name).split("/").pop() ?? repository.name;
}

function getGithubRepoOwner(repository: GitRepositoryInfo) {
  const [owner] = (repository.remoteRepo ?? "").split("/");

  return owner || "GitHub";
}

// 연결된 repo 이벤트를 카드 안의 요약 숫자로 압축한다.
function getGithubEventCounts(events: GitHubTimelineEvent[]) {
  const counts = { commit: 0, issue: 0, pull_request: 0 };

  events.forEach((event) => {
    if (
      (event.type === "pull_request" || event.type === "issue") &&
      event.status !== "open"
    ) {
      return;
    }

    counts[event.type] += 1;
  });

  return counts;
}

function getGithubAuthorStats(events: GitHubTimelineEvent[]) {
  const counts = new Map<string, number>();

  events.forEach((event) => {
    if (!event.author) {
      return;
    }

    counts.set(event.author, (counts.get(event.author) ?? 0) + 1);
  });

  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1])
    .slice(0, 3)
    .map(([author, count]) => ({ author, count }));
}

function getGithubAuthorInitials(author: string) {
  const compact = author.replace(/[^a-zA-Z0-9]/g, "");

  return (compact || author).slice(0, 2).toUpperCase();
}

function getGithubCommitSparkBars(events: GitHubTimelineEvent[]) {
  const commitEvents = events.filter((event) => event.type === "commit");
  const buckets = Array(7).fill(0) as number[];

  if (commitEvents.length === 0) {
    return buckets;
  }

  const timestamps = commitEvents.map((event) => event.createdAt);
  const oldest = Math.min(...timestamps);
  const span = Math.max(1, Math.max(...timestamps) - oldest);

  commitEvents.forEach((event) => {
    const bucketIndex = Math.min(6, Math.floor(((event.createdAt - oldest) / span) * 7));
    buckets[bucketIndex] += 1;
  });

  const maxCount = Math.max(...buckets);

  return buckets.map((count) => (count === 0 ? 8 : 18 + Math.round((count / maxCount) * 82)));
}

function getGithubRepositorySyncLabel(repository: GitRepositoryInfo) {
  if (repository.syncStatus === "syncing") {
    return "진행 중";
  }

  if (repository.syncStatus === "indexed") {
    return "완료";
  }

  if (repository.syncStatus === "failed") {
    return "실패";
  }

  if (repository.syncStatus === "delayed") {
    return "처리 지연";
  }

  return "서버 연결됨";
}

function formatSyncElapsed(seconds: number, language: LanguageSetting) {
  if (seconds < 60) {
    return language === "en" ? `${seconds}s` : `${seconds}초`;
  }

  return language === "en"
    ? `${Math.floor(seconds / 60)}m ${seconds % 60}s`
    : `${Math.floor(seconds / 60)}분 ${seconds % 60}초`;
}

function getGithubRepositorySyncBadgeVariant(repository: GitRepositoryInfo) {
  if (repository.syncStatus === "indexed") {
    return "success";
  }

  if (repository.syncStatus === "syncing" || repository.syncStatus === "delayed") {
    return "warning";
  }

  if (repository.syncStatus === "failed") {
    return "error";
  }

  return "neutral";
}

function getGithubRepositorySyncError(lastError?: string | null) {
  const code = lastError?.split(":", 1)[0] ?? "";

  if (
    code === "REPOSITORY_SYNC_INTERRUPTED" ||
    lastError?.startsWith("Repository sync interrupted")
  ) {
    return "서버 재시작으로 동기화가 중단되었습니다. 다시 시도해 주세요.";
  }

  if (code === "REPOSITORY_INGEST_FAILED" || code === "REPOSITORY_SYNC_FAILED") {
    return "저장소 데이터를 검색에 반영하지 못했습니다. 기존 데이터는 유지됩니다.";
  }

  if (code === "REPOSITORY_NO_INDEXABLE_CONTENT") {
    return "저장소에서 검색에 반영할 내용을 찾지 못했습니다.";
  }

  if (code === "GITHUB_AUTH_FAILED" || code === "GITHUB_PERMISSION_DENIED") {
    return "GitHub 접근 권한을 확인한 뒤 다시 시도해 주세요.";
  }

  if (code === "INVALID_REPOSITORY_URL") {
    return "GitHub 저장소 주소가 올바르지 않습니다. 연결 정보를 확인해 주세요.";
  }

  if (code === "REPOSITORY_STATUS_PERMISSION_DENIED") {
    return "저장소 동기화 상태를 확인할 권한이 없습니다.";
  }

  if (code === "REPOSITORY_STATUS_UNAVAILABLE") {
    return "저장소 동기화 상태를 확인하지 못했습니다. 다시 시도해 주세요.";
  }

  if (
    code === "GITHUB_UNAVAILABLE" ||
    code === "GITHUB_REPOSITORY_NOT_FOUND" ||
    code === "GITHUB_BRANCH_NOT_FOUND" ||
    code === "GITHUB_SOURCE_NOT_FOUND"
  ) {
    return "GitHub 저장소 데이터를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.";
  }

  if (lastError && !/^[A-Z0-9_:.-]+$/.test(lastError)) {
    return lastError;
  }

  return "GitHub repo 동기화 실패";
}

function getGithubRepositorySyncWarningReason(reason?: string) {
  const code = reason?.split(":", 1)[0] ?? "";

  if (code === "REPOSITORY_EXTRACT_FAILED") {
    return "저장소 내용을 읽지 못했습니다.";
  }

  if (code === "REPOSITORY_INGEST_FAILED") {
    return "읽은 저장소 내용을 검색에 반영하지 못했습니다.";
  }

  if (code.startsWith("GITHUB_")) {
    return getGithubRepositorySyncError(reason);
  }

  if (reason && !/^[A-Z0-9_:.-]+$/.test(reason)) {
    return reason;
  }

  return "일부 소스 수집 실패";
}

function getGithubMemorySourceRepoId(item: ProjectMemoryItem) {
  const rawRepoId = item.source_info?.repo_id ?? item.repo_id ?? null;

  return rawRepoId === null ? null : Number(rawRepoId);
}

function getGithubMemoryCategoryMeta(item: ProjectMemoryItem) {
  if (item.category === "action") {
    return { icon: tablerGitCommit, label: "액션", tone: "action" };
  }

  if (item.category === "decision") {
    return { icon: tablerGitCommit, label: "결정", tone: "decision" };
  }

  if (item.category === "issue") {
    return { icon: tablerAlertCircle, label: "이슈", tone: "issue" };
  }

  return { icon: tablerAlertCircle, label: "리스크", tone: "risk" };
}

function isGithubMemoryLinked(item: ProjectMemoryItem, repository?: GitRepositoryInfo) {
  if (!repository?.repoId) {
    return false;
  }

  return getGithubMemorySourceRepoId(item) === repository.repoId;
}

function getGithubMemoryDisplayItems(memoryItems: ProjectMemoryItem[], repository?: GitRepositoryInfo) {
  return [...memoryItems]
    .sort((left, right) => {
      const leftLinked = isGithubMemoryLinked(left, repository);
      const rightLinked = isGithubMemoryLinked(right, repository);

      if (leftLinked !== rightLinked) {
        return leftLinked ? -1 : 1;
      }

      return (left.sort_order ?? left.id) - (right.sort_order ?? right.id);
    })
    .slice(0, 3);
}

// 우측 패널의 GitHub 로그인, repo 선택, 이벤트 타임라인 화면을 렌더링한다.
export function GithubPanel({
  canManage,
  connectingRepositoryUrl,
  demoStatus,
  events,
  filteredRepositories,
  githubConnected,
  isAuthChecking,
  isAuthStarting,
  isConnecting,
  isDisconnectConfirming,
  isRepoLoading,
  isSyncing,
  onCheckLogin,
  onConnectRepository,
  onDisconnect,
  onLoadRepositories,
  onOpenMemory,
  onOpenVerification,
  onQueryChange,
  onRefreshRepository,
  onResetLogin,
  onStartLogin,
  onStartPrivateLogin,
  onSyncRepository,
  panelState,
  memoryItems,
  repositories,
  repository,
  repositoryQuery,
  session,
  statusRevision,
}: GithubPanelProps) {
  const { language, t } = useI18n();
  const eventCounts = getGithubEventCounts(events);
  const authorStats = getGithubAuthorStats(events);
  const sparkBars = getGithubCommitSparkBars(events);
  const memoryDisplayItems = getGithubMemoryDisplayItems(memoryItems, repository);
  const hiddenMemoryCount = Math.max(0, memoryItems.length - memoryDisplayItems.length);
  const isRepositorySyncing = repository?.syncStatus === "syncing";
  const [remoteFreshnessNow, setRemoteFreshnessNow] = useState(Date.now());
  const remoteCheckStatus = repository
    ? getGithubRemoteCheckStatus(repository, remoteFreshnessNow)
    : "unknown";
  const hasRemoteChanges = remoteCheckStatus === "needs_sync";
  const isRemoteCheckError = remoteCheckStatus === "error";
  const isRemoteCheckUnknown = remoteCheckStatus === "unknown";
  const isRemoteSessionExpired =
    isRemoteCheckError && repository?.remoteCheckError === "session_expired";
  const isRepositoryUnsynced = repository
    ? !repository.syncStatus || repository.syncStatus === "connected" || hasRemoteChanges
    : false;
  const isRepositoryIndexed = repository?.syncStatus === "indexed";
  const isRepositoryLatest =
    isRepositoryIndexed && remoteCheckStatus === "current";
  const repositoryWarning = repository?.syncWarnings?.[0] ?? null;
  const [syncElapsedSeconds, setSyncElapsedSeconds] = useState(0);
  const [isCodeCopied, setIsCodeCopied] = useState(false);
  const [isCodeCopyFailed, setIsCodeCopyFailed] = useState(false);
  const githubUser =
    session?.user ?? repositories.find((availableRepository) => availableRepository.owner)?.owner;
  const latestActivity = events[0] ? formatRelativeAge(events[0].createdAt, language) : t("기록 없음");

  useEffect(() => {
    if (!isRepositorySyncing || typeof repository?.syncStartedAt !== "number") {
      setSyncElapsedSeconds(0);
      return;
    }

    const startedAt = repository.syncStartedAt;
    const updateElapsed = () => {
      setSyncElapsedSeconds(Math.floor(Math.max(0, Date.now() - startedAt) / 1000));
    };

    updateElapsed();
    const intervalId = window.setInterval(updateElapsed, 1000);

    return () => window.clearInterval(intervalId);
  }, [isRepositorySyncing, repository?.syncStartedAt]);

  useEffect(() => {
    const checkedAt = repository?.remoteCheckedAt;
    if (
      typeof checkedAt !== "number" ||
      repository?.remoteCheckStatus === "checking" ||
      repository?.remoteCheckStatus === "error"
    ) {
      return;
    }

    const remainingMs = checkedAt + GITHUB_REMOTE_HEAD_TTL_MS - Date.now();
    if (remainingMs <= 0) {
      setRemoteFreshnessNow(Date.now());
      return;
    }

    const timeoutId = window.setTimeout(
      () => setRemoteFreshnessNow(Date.now()),
      remainingMs + 25,
    );
    return () => window.clearTimeout(timeoutId);
  }, [repository?.remoteCheckedAt, repository?.remoteCheckStatus]);

  async function handleCopyGithubCode() {
    if (!session?.userCode) {
      return;
    }

    try {
      await navigator.clipboard.writeText(session.userCode);
      setIsCodeCopied(true);
      setIsCodeCopyFailed(false);
      window.setTimeout(() => setIsCodeCopied(false), 1200);
    } catch {
      setIsCodeCopied(false);
      setIsCodeCopyFailed(true);
      window.setTimeout(() => setIsCodeCopyFailed(false), 2400);
    }
  }

  return (
    <div className="project-panel-content github-panel-content" data-state={panelState}>
      {demoStatus?.scope === "github" ? (
        <Banner
          className="runtime-status overview-github-status"
          container="card"
          key={statusRevision}
          status={demoStatus.kind ?? (demoStatus.ok ? "success" : "error")}
          title={t(demoStatus.message)}
        />
      ) : null}

      {panelState === "signedout" ? (
        <Card
          className="overview-github-card overview-github-login-card"
          padding={0}
          variant="transparent"
        >
          <div className="overview-github-login-intro">
            <span className="overview-github-logo-box" data-size="large" aria-hidden="true">
              <img className="overview-github-logo" src={githubMark} alt="" />
            </span>
            <p>{t("GitHub 연결")}</p>
            <small>{t("연결 후 동기화하면 최근 활동을 이 탭에서 확인할 수 있습니다.")}</small>
          </div>
          <Button
            className="overview-github-primary-button"
            icon={<img className="overview-github-button-logo" src={githubMark} alt="" />}
            isDisabled={!canManage || isAuthStarting}
            label={isAuthStarting ? t("여는 중...") : t("GitHub 로그인")}
            onClick={onStartLogin}
            variant="primary"
          />
          <div className="overview-github-private-guide">
            <Button
              className="overview-github-ghost-button"
              icon={<GitBranch size={14} />}
              isDisabled={!canManage || isAuthStarting}
              label={t("비공개 저장소 연결")}
              onClick={onStartPrivateLogin}
              variant="ghost"
            />
            <p>{t("비공개 저장소는 GitHub App 설치가 필요합니다")}</p>
          </div>
          <Divider className="overview-github-private-divider" />
          <p className="overview-github-list-label">{t("연결하면 볼 수 있어요")}</p>
          <div className="overview-github-feature-list" aria-label={t("GitHub 연결 후 볼 수 있는 정보")}>
            {githubFeatureCards.map((feature) => (
              <div
                className="overview-github-feature-row"
                data-tone={feature.tone}
                key={feature.title}
              >
                <span className="overview-github-feature-icon" aria-hidden="true">
                  <SvgIcon svg={feature.icon} />
                </span>
                <div>
                  <p>{t(feature.title)}</p>
                  <small>{t(feature.description)}</small>
                </div>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {panelState === "authing" ? (
        <Card
          className="overview-github-card overview-github-auth-card"
          padding={0}
          variant="transparent"
        >
          <span className="overview-github-logo-box" aria-hidden="true">
            <img className="overview-github-logo" src={githubMark} alt="" />
          </span>
          <p>{t("브라우저에서 GitHub 연결을 완료해 주세요")}</p>
          <small>
            {session?.userCode
              ? t("GitHub 인증 페이지에서 아래 코드를 입력한 뒤 완료 버튼을 눌러 주세요.")
              : t("GitHub App 설치 화면에서 접근할 repo를 선택한 뒤 완료 버튼을 눌러 주세요.")}
          </small>
          {session?.userCode ? (
            <>
              <span className="overview-github-code">{session.userCode}</span>
              <Button
                className="overview-github-ghost-button overview-github-code-copy"
                icon={
                  isCodeCopyFailed ? <X size={14} /> : isCodeCopied ? <Check size={14} /> : <Copy size={14} />
                }
                label={t(
                  isCodeCopyFailed ? "코드 복사 실패" : isCodeCopied ? "코드 복사됨" : "코드 복사",
                )}
                onClick={handleCopyGithubCode}
                variant="ghost"
              />
            </>
          ) : null}
          <Spinner
            className="overview-github-loader"
            label={session?.userCode ? t("로그인 대기 중...") : t("설치 대기 중...")}
            shade="subtle"
          />
          <div className="overview-github-action-buttons">
            <Button
              className="overview-github-ghost-button"
              icon={<Link2 size={14} />}
              label={session?.userCode ? t("브라우저 열기") : t("설치 화면 열기")}
              onClick={onOpenVerification}
              variant="ghost"
            />
            <Button
              className="overview-github-secondary-button"
              icon={<Check size={14} />}
              isDisabled={!canManage || isAuthChecking}
              label={
                isAuthChecking
                  ? t("확인 중...")
                  : session?.userCode
                    ? t("로그인 완료했어요")
                    : t("설치 완료했어요")
              }
              onClick={onCheckLogin}
              variant="secondary"
            />
            <Button
              className="overview-github-ghost-button"
              icon={<X size={14} />}
              isDisabled={!canManage}
              label={t("취소")}
              onClick={onResetLogin}
              variant="ghost"
            />
          </div>
        </Card>
      ) : null}

      {panelState === "repos" ? (
        <Card
          className="overview-github-card overview-github-repos-card"
          padding={0}
          variant="transparent"
        >
          <div className="overview-github-toolbar">
            <div className="overview-github-account">
              <Avatar
                alt={githubUser?.login ?? "GitHub"}
                name={githubUser?.login ?? "GitHub"}
                size={24}
                src={githubUser?.avatarUrl}
              />
              <span>{githubUser?.login ?? "GitHub"}</span>
            </div>
            <Button
              className="overview-github-ghost-button"
              icon={<LogOut size={13} />}
              isDisabled={!canManage}
              label={t("로그아웃")}
              onClick={onResetLogin}
              size="sm"
              variant="ghost"
            />
          </div>
          <TextInput
            className="overview-github-search"
            hasClear
            isLabelHidden
            label={t("GitHub repo 검색")}
            onChange={onQueryChange}
            placeholder={t("repo 검색...")}
            startIcon={<Search size={15} />}
            value={repositoryQuery}
            width="100%"
          />
          {!session?.state ? (
            <div className="overview-github-private-guide" data-compact="true">
              <p>{t("Private repo는 GitHub App 설치 후 볼 수 있어요")}</p>
              <Button
                className="overview-github-ghost-button"
                icon={<GitBranch size={14} />}
                isDisabled={!canManage || isAuthStarting}
                label={t("Private repo 연결")}
                onClick={onStartPrivateLogin}
                size="sm"
                variant="ghost"
              />
            </div>
          ) : null}
          <p className="overview-github-list-label">
            {t("내 repo")} · {filteredRepositories.length}
          </p>
          {repositories.length > 0 ? (
            <div className="overview-github-repo-list" aria-label={t("접근 가능한 GitHub repo")}>
              {filteredRepositories.length > 0 ? (
                filteredRepositories.map((availableRepository, index) => {
                  const isThisRepositoryConnecting =
                    connectingRepositoryUrl === availableRepository.url;

                  return (
                    <div
                    className="overview-github-repo-row"
                    data-last={index === filteredRepositories.length - 1}
                    key={availableRepository.fullName}
                  >
                    <GitBranch size={16} />
                    <div className="overview-github-repo-copy">
                      <div>
                        <p>{availableRepository.fullName}</p>
                        <Badge
                          className="overview-github-repo-visibility"
                          label={availableRepository.private ? "PRIVATE" : "PUBLIC"}
                          variant={availableRepository.private ? "purple" : "blue"}
                        />
                      </div>
                      <small>{t("기본 브랜치 {branch}", { branch: availableRepository.defaultBranch })}</small>
                    </div>
                    <Button
                      className="overview-github-secondary-button"
                      icon={<Link2 size={14} />}
                      isDisabled={!canManage || isConnecting}
                      label={isThisRepositoryConnecting ? t("연결 중...") : t("연결")}
                      onClick={() => onConnectRepository(availableRepository.url)}
                      size="sm"
                      variant="secondary"
                    />
                    </div>
                  );
                })
              ) : (
                <EmptyState
                  className="overview-github-empty"
                  icon={<Search size={17} />}
                  isCompact
                  title={t("\"{query}\" 검색 결과가 없습니다", { query: repositoryQuery })}
                />
              )}
            </div>
          ) : (
            <EmptyState
              actions={
                <Button
                  className="overview-github-secondary-button"
                  icon={<RefreshCcw size={14} />}
                  isDisabled={!canManage || isRepoLoading}
                  label={isRepoLoading ? t("불러오는 중...") : t("Repo 목록 불러오기")}
                  onClick={onLoadRepositories}
                  variant="secondary"
                />
              }
              className="overview-github-empty"
              isCompact
              title={t("아직 불러온 repo가 없습니다.")}
            />
          )}
        </Card>
      ) : null}

      {repository ? (
        <div className="overview-github-connected-shell">
          <div className="overview-github-repo-head overview-github-connected-card">
            <div className="overview-github-brand">
              <span className="overview-github-logo-box" data-tone="connected" aria-hidden="true">
                <img className="overview-github-logo" src={githubMark} alt="" />
              </span>
              <div className="overview-github-copy">
                <div className="overview-github-repo-title">
                  <p className="overview-github-repo-name">
                    {getGithubRepoShortName(repository)}
                  </p>
                  <Badge
                    className="overview-github-repo-visibility"
                    label={t(repository.visibility === "private" ? "비공개" : "공개")}
                    variant={repository.visibility === "private" ? "purple" : "blue"}
                  />
                </div>
                <p className="overview-github-meta">
                  {getGithubRepoOwner(repository)} · {repository.branch}
                </p>
                {isRepositoryIndexed ? (
                  <span
                    className="overview-github-sync-quiet"
                    data-verified={isRepositoryLatest ? "true" : "false"}
                  >
                    {t(
                      remoteCheckStatus === "current"
                        ? "최신 상태"
                        : remoteCheckStatus === "needs_sync"
                          ? "최신화 필요"
                          : remoteCheckStatus === "checking"
                            ? "최신 상태 확인 중"
                            : remoteCheckStatus === "error"
                              ? "최신 상태 확인 실패"
                              : "최신 상태 확인 필요",
                    )}
                  </span>
                ) : null}
              </div>
              <IconButton
                className="overview-github-sync-button"
                icon={<RefreshCcw size={15} />}
                isDisabled={
                  !canManage ||
                  isSyncing ||
                  isRepositorySyncing ||
                  isRemoteSessionExpired
                }
                label={t("GitHub 동기화")}
                onClick={onSyncRepository}
                size="sm"
                tooltip={isRepositorySyncing ? t("동기화 중") : t("GitHub 동기화")}
                variant="ghost"
              />
              <DropdownMenu
                button={{
                  className: "overview-github-more-menu",
                  icon: <MoreHorizontal size={15} />,
                  isIconOnly: true,
                  isDisabled: !canManage || isSyncing || isRepositorySyncing,
                  label: t("저장소 작업"),
                  size: "sm",
                  tooltip: t("저장소 작업"),
                  variant: "ghost",
                }}
                items={[
                  {
                    icon: <X size={13} />,
                    label: isDisconnectConfirming ? t("연결 해제 확인") : t("연결 해제"),
                    onClick: onDisconnect,
                  },
                ]}
                menuWidth={132}
              />
            </div>
          </div>

          {isRepositoryIndexed && (isRemoteCheckError || isRemoteCheckUnknown) ? (
            <div
              className="overview-github-sync-summary"
              data-status={isRemoteCheckError ? "error" : "unknown"}
            >
              <div>
                <Badge
                  label={t(
                    isRemoteSessionExpired
                      ? "GitHub 연결 만료"
                      : isRemoteCheckError
                        ? "확인 실패"
                        : "확인 필요",
                  )}
                  variant={isRemoteCheckError ? "warning" : "blue"}
                />
                <span>
                  <strong>
                    {t(
                      isRemoteSessionExpired
                        ? "GitHub 인증을 다시 연결해 주세요"
                        : isRemoteCheckError
                          ? "최신 상태를 확인하지 못했습니다"
                          : "최신 상태 확인 필요",
                    )}
                  </strong>
                  <small>
                    {t(
                      isRemoteSessionExpired
                        ? "검색 인덱스는 유지됩니다. 다시 인증하면 코드 최신 여부를 확인합니다."
                        : "마지막 성공 결과로 최신 상태를 표시하지 않습니다.",
                    )}
                  </small>
                </span>
              </div>
              <Button
                icon={<RefreshCcw size={13} />}
                isDisabled={!canManage || isSyncing}
                label={t(isRemoteSessionExpired ? "다시 인증" : "다시 확인")}
                onClick={isRemoteSessionExpired ? onStartPrivateLogin : onRefreshRepository}
                size="sm"
                variant="secondary"
              />
            </div>
          ) : null}

          {isRepositoryUnsynced ? (
            <div
              className="overview-github-sync-summary"
              data-status={hasRemoteChanges ? "needs_sync" : "connected"}
            >
              <div>
                <Badge
                  label={t(hasRemoteChanges ? "최신화 필요" : "동기화 필요")}
                  variant="warning"
                />
                <span>
                  <strong>
                    {t(hasRemoteChanges ? "새 GitHub 코드 변경사항이 있습니다" : "저장소만 연결된 상태입니다")}
                  </strong>
                  <small>
                    {t(
                      hasRemoteChanges
                        ? "최신 커밋을 검색과 프로젝트 메모리에 반영해 주세요."
                        : "커밋·이슈·PR을 사용하려면 첫 동기화를 실행해 주세요.",
                    )}
                  </small>
                </span>
              </div>
              <Button
                icon={<RefreshCcw size={13} />}
                isDisabled={!canManage || isSyncing}
                label={isSyncing ? t("동기화 중") : t("지금 동기화")}
                onClick={onSyncRepository}
                size="sm"
                variant="secondary"
              />
            </div>
          ) : null}

          <div className="overview-github-summary-strip">
            <span className="overview-github-strip-stat" data-type="commit">
              <strong>{eventCounts.commit}</strong>
              {t("커밋")}
            </span>
            <Divider className="overview-github-stat-divider" orientation="vertical" />
            <span className="overview-github-strip-stat" data-type="pull_request">
              <strong>{eventCounts.pull_request}</strong>
              PR
            </span>
            <Divider className="overview-github-stat-divider" orientation="vertical" />
            <span className="overview-github-strip-stat" data-type="issue">
              <strong>{eventCounts.issue}</strong>
              {t("이슈")}
            </span>
            <div
              className="overview-github-spark"
              aria-label={t("최근 커밋 {count}개 흐름", { count: eventCounts.commit })}
              role="img"
            >
              {sparkBars.map((height, index) => (
                <span key={index} style={{ height: `${height}%` }} />
              ))}
            </div>
            <div className="overview-github-contributors" aria-label={t("기여자")}>
              {authorStats.map((author) => (
                <span key={author.author} title={`${author.author} · ${author.count}`}>
                  {getGithubAuthorInitials(author.author)}
                </span>
              ))}
              <small>{latestActivity}</small>
            </div>
          </div>

          <div className="overview-github-connected-grid">
            <section className="overview-github-sync-column">
              <div className="overview-github-context-heading">
                <div>
                  <p className="overview-github-context-title">{t("프로젝트 컨텍스트")}</p>
                  <small>{t("AI 답변에 반영되는 프로젝트 요약과 관련 기억")}</small>
                </div>
                <div className="overview-github-context-actions">
                  <span className="overview-github-active-memory-count">
                    <i aria-hidden="true" />
                    {t("활성 기억 {count}개", { count: memoryItems.length })}
                  </span>
                  <Button
                    label={t("관리")}
                    onClick={onOpenMemory}
                    size="sm"
                    variant="ghost"
                  />
                </div>
              </div>
              {repository.syncStatus === "syncing" ? (
                <Spinner
                  aria-label={t("GitHub 동기화 중")}
                  className="overview-github-sync-progress"
                  label={
                    <div>
                      <p>{t("커밋·이슈·PR 수집·분석 중")}</p>
                      <small>
                        {repository.syncStatusCheck === "retrying"
                          ? t("상태 재확인 중")
                          : typeof repository.syncStartedAt === "number"
                            ? t("{elapsed} 경과", {
                                elapsed: formatSyncElapsed(syncElapsedSeconds, language),
                              })
                            : t("시작 시간 확인 중")}
                      </small>
                    </div>
                  }
                  shade="subtle"
                />
              ) : null}
              {repository.syncStatus === "failed" || repository.syncStatus === "delayed" ? (
                <div className="overview-github-sync-state" data-status={repository.syncStatus}>
                  <Badge
                    label={t(getGithubRepositorySyncLabel(repository))}
                    variant={getGithubRepositorySyncBadgeVariant(repository)}
                  />
                  <small>{t(getGithubRepositorySyncError(repository.lastError))}</small>
                  <Button
                    icon={<RefreshCcw size={13} />}
                    isDisabled={!canManage || isSyncing}
                    label={isSyncing ? t("재시도 중...") : t("재시도")}
                    onClick={onSyncRepository}
                    size="sm"
                    variant="secondary"
                  />
                </div>
              ) : null}
              {repositoryWarning ? (
                <small className="overview-github-sync-warning">
                  {repositoryWarning.source_type && repositoryWarning.reason
                    ? t("{source} 수집 실패: {reason}", {
                        reason: t(
                          getGithubRepositorySyncWarningReason(repositoryWarning.reason),
                        ),
                        source: repositoryWarning.source_type,
                      })
                    : t("일부 소스 수집 실패")}
                </small>
              ) : null}
              {memoryItems.length > 0 ? (
                <>
                  <section
                    aria-label={t("프로젝트 요약")}
                    className="overview-github-context-summary"
                  >
                    <span className="overview-github-context-summary-icon" aria-hidden="true">
                      <GitBranch size={16} />
                    </span>
                    <div>
                      <strong>{t("프로젝트 요약")}</strong>
                      <p>{t("프로젝트의 핵심 방향과 현재 상태를 응축한 요약")}</p>
                      <small>{t("탐색형 답변의 관점과 방향에 우선 반영됩니다")}</small>
                    </div>
                    <Badge
                      className="overview-github-context-default-badge"
                      label={t("답변 기본 컨텍스트")}
                      variant="success"
                    />
                  </section>

                  <div className="overview-github-related-memory-heading">
                    <p>{t("관련 기억")}</p>
                    <small>{t("질문과 관련된 항목만 검색됩니다")}</small>
                  </div>
                </>
              ) : null}
              <div className="overview-github-memory-link-list">
                {memoryDisplayItems.length > 0 ? (
                  memoryDisplayItems.map((item) => {
                    const meta = getGithubMemoryCategoryMeta(item);

                    return (
                      <article
                        className="overview-github-memory-link-card"
                        data-category={meta.tone}
                        key={item.id}
                      >
                        <div className="overview-github-memory-link-title">
                          <SvgIcon svg={meta.icon} />
                          <p>{item.content}</p>
                          <Badge
                            className="overview-github-memory-category-badge"
                            label={t(meta.label)}
                            variant="purple"
                          />
                        </div>
                        <small>{t("관련 질문에 우선 참고")}</small>
                      </article>
                    );
                  })
                ) : (
                  <div className="overview-github-memory-empty">
                    <SvgIcon svg={tablerAlertCircle} />
                    <p>{t("연결된 메모리가 없습니다")}</p>
                    <small>{t("GitHub 동기화를 실행하면 repo 기반 메모리가 표시됩니다.")}</small>
                  </div>
                )}
              </div>
              {hiddenMemoryCount > 0 ? (
                <Button
                  className="overview-github-memory-more"
                  label={t("그 외 활성 기억 {count}개 보기", { count: hiddenMemoryCount })}
                  onClick={onOpenMemory}
                  size="sm"
                  variant="ghost"
                />
              ) : null}
              {memoryItems.length > 0 ? (
                <small className="overview-github-context-footnote">
                  {t("{branch} 브랜치 기준 · 대체된 결정 제외", {
                    branch: repository.branch,
                  })}
                </small>
              ) : null}
            </section>

            <section className="overview-github-timeline-section">
              <p className="overview-github-list-label">{t("최근 활동")}</p>
              {events.length > 0 ? (
                <div className="overview-timeline-list">
                  {events.map((event, index) => {
                    const age = formatRelativeAge(event.createdAt, language);
                    const previousAge =
                      index > 0
                        ? formatRelativeAge(events[index - 1].createdAt, language)
                        : null;

                    return (
                      <div className="overview-timeline-entry" key={event.id}>
                        {age !== previousAge ? (
                          <p className="overview-timeline-day">{age}</p>
                        ) : null}
                        <div className="overview-timeline-row">
                          <span className="overview-timeline-label" data-hidden="true">
                            {getGithubEventLabel(event)}
                          </span>
                          <div
                            className="overview-timeline-icon"
                            data-event-type={event.type}
                            data-status={event.status ?? ""}
                          >
                            <SvgIcon svg={getGithubEventIconSvg(event.type)} />
                            {index < events.length - 1 ? <span /> : null}
                          </div>
                          <div className="overview-timeline-copy">
                            <p>{event.title}</p>
                            <small>
                              {getGithubEventMeta(event, language).map((item) => (
                                <span key={item}>{item}</span>
                              ))}
                            </small>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <EmptyState
                  className="overview-empty-text"
                  icon={<SvgIcon svg={tablerAlertCircle} />}
                  isCompact
                  title={t("아직 GitHub 이벤트가 없습니다.")}
                />
              )}
            </section>
          </div>
        </div>
      ) : githubConnected ? (
        <EmptyState
          className="overview-empty-text"
          icon={<SvgIcon svg={tablerAlertCircle} />}
          isCompact
          title={t("아직 GitHub 이벤트가 없습니다.")}
        />
      ) : null}
    </div>
  );
}
