import {
  AlertTriangle,
  AudioLines,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Brain,
  ChevronRight,
  Check,
  Copy,
  FileText,
  Files,
  Flag,
  FolderOpen,
  FolderPlus,
  GitBranch,
  Ellipsis,
  LogOut,
  Maximize2,
  MessageSquare,
  Minimize2,
  Minus,
  PanelLeft,
  PanelRight,
  Pencil,
  Plus,
  Settings as SettingsIcon,
  Square,
  UserRound,
  X,
  Zap,
} from "lucide-react";
import { AppShell } from "@astryxdesign/core/AppShell";
import { Theme } from "@astryxdesign/core/theme";
import { neutralTheme } from "@astryxdesign/theme-neutral/built";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { DropdownMenu, DropdownMenuItem } from "@astryxdesign/core/DropdownMenu";
import { IconButton } from "@astryxdesign/core/IconButton";
import { LayoutContent, LayoutPanel } from "@astryxdesign/core/Layout";
import { ResizeHandle, useResizable } from "@astryxdesign/core/Resizable";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { SideNav } from "@astryxdesign/core/SideNav";
import { Spinner } from "@astryxdesign/core/Spinner";
import { TextArea } from "@astryxdesign/core/TextArea";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Tooltip } from "@astryxdesign/core/Tooltip";
import { invoke } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { open } from "@tauri-apps/plugin-dialog";
import { openUrl } from "@tauri-apps/plugin-opener";
import {
  type CSSProperties,
  FormEvent,
  KeyboardEvent,
  MouseEvent,
  PointerEvent as ReactPointerEvent,
  UIEvent as ReactUIEvent,
  type SetStateAction,
  Suspense,
  lazy,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";
import packageJson from "../package.json";
import {
  clearPaimAuthSession,
  loadPaimAuthSession,
  savePaimAuthSession,
  setPaimUnauthorizedHandler,
  type PaimAuthResponse,
  type PaimUser,
} from "./auth";
import { I18nProvider, translate, useI18n } from "./i18n";
import { formatRelativeAge, parsePaimTimestamp } from "./format";
import {
  canRole,
  fetchProjectMembers,
  getCurrentProjectMember,
  type ProjectMember,
  type ProjectRole,
} from "./members";
import { fillMissingProjectRoles } from "./projectRoleCompatibility";
import {
  createGithubDeviceCode,
  createGithubAppSession,
  fetchGithubAccessToken,
  fetchGithubAppRepositories,
  fetchGithubAppRepositoryHead,
  fetchGithubAppRepositoryPreview,
  fetchGithubAppSession,
  fetchGithubRepositories,
  fetchGithubRepository,
  fetchGithubRepositoryHead,
  fetchGithubUserProfile,
  GITHUB_REMOTE_HEAD_TTL_MS,
  getGithubOAuthErrorMessage,
  getGithubPanelStateLabel,
  githubCommitShasMatch,
} from "./github";
import {
  fetchPaimFormData,
  fetchPaimJson,
  fetchPaimJsonPreservingSession,
  fetchPaimSessionJson,
  fetchPaimRootJson,
  getErrorMessage,
  isPaimApiError,
} from "./paimApi";
import {
  createPendingDocumentDeleteQueue,
  getPendingDocumentDeletesStorageKey,
  type PendingDocumentDeleteAttemptResult,
  type PendingDocumentDeleteQueue,
  type PendingDocumentDeleteTarget,
} from "./pendingDocumentDeletes";
import {
  fetchPaimCapabilities,
  formatBytesAsMiB,
  formatExtensions,
  supportsExtension,
  type PaimCapabilities,
} from "./capabilities";
import {
  clampProjectFileTreeWidth,
  countProjectFileEntries,
  createProjectFileEntry,
  DEFAULT_PROJECT_FILE_TREE_WIDTH,
  deleteProjectFileEntry,
  filterProjectFileEntries,
  getProjectFileVisualMeta,
  groupProjectSourcesByUploadedDate,
  MIN_PROJECT_FILE_TREE_WIDTH,
  sortProjectSourcesByUploadedAt,
  updateProjectFileEntry,
  type ProjectFileVisualMeta,
} from "./projectFileUtils";
import {
  needsProjectDocumentStatusHydration,
  reconcileProjectDocumentAttachments,
  removeOlderMeetingDocumentGenerations,
  type ServerDocumentAttachment,
} from "./projectDocumentSync";
import {
  DEFAULT_PAIM_API_ROOT_URL,
  getPaimApiRootUrl,
  loadPaimSettings,
  normalizePaimServerUrl,
  normalizePaimSettings,
  savePaimSettings,
  type LanguageSetting,
  type PaiMSettings,
  type SuggestionMinConfidence,
  type ThemeSetting,
} from "./settings";
import { AudioUploadDialog } from "./AudioUploadDialog";
import {
  getExtractionTotal,
  getLocalISODate,
  getSttFailureMessage,
  isISODate,
  isKnownAudioFileName,
  isMeetingDocument,
  isSupportedAudioFileName,
  STT_DOCUMENT_TYPE,
  STT_SAFE_EXTENSIONS,
  STT_SAFE_MAX_FILE_BYTES,
  type AudioUploadDraft,
  type AudioUploadResponse,
  type DocumentExtractionCounts,
} from "./stt";
import { WorkspacePageLayout } from "./WorkspacePageLayout";
import { ProjectPortfolioPage } from "./ProjectPortfolioPage";
import { ProfileAvatar } from "./ProfileAvatar";
import { normalizeApiProjectSetup } from "./projectSetup";
import { isProjectSetupComplete } from "./types";
import { useProjectWorkspaceDomain } from "./useProjectWorkspaceDomain";
import {
  type MainView,
  useWorkspaceRoute,
} from "./workspaceRoute";
import type {
  Attachment,
  ChatSession,
  DemoStatus,
  DirectoryChildEntry,
  GithubAvailableRepository,
  GithubLoginSessionState,
  GithubPanelState,
  GitRepositoryInfo,
  GitRepositorySyncWarning,
  Message,
  ProjectDocumentStatus,
  ProjectFilePreview,
  ProjectMemoryCategory,
  ProjectMemoryItem,
  ProjectSourcesMode,
  ProjectState,
  ProjectWorkspace,
} from "./types";

const LazyGithubPanel = lazy(() =>
  import("./GithubPanel").then((module) => ({ default: module.GithubPanel })),
);
const LazyProjectDetailPage = lazy(() =>
  import("./ProjectDetailPage").then((module) => ({
    default: module.ProjectDetailPage,
  })),
);
const LazyProjectManagementPage = lazy(() =>
  import("./ProjectManagementPage").then((module) => ({
    default: module.ProjectManagementPage,
  })),
);
const LazyAuthScreen = lazy(() =>
  import("./AuthScreen").then((module) => ({ default: module.AuthScreen })),
);
const LazyProjectMemoryPanel = lazy(() =>
  import("./ProjectMemoryPanel").then((module) => ({ default: module.ProjectMemoryPanel })),
);
const LazyProjectMembersPanel = lazy(() =>
  import("./ProjectMembersPanel").then((module) => ({ default: module.ProjectMembersPanel })),
);
const LazyProjectFilesPanel = lazy(() =>
  import("./projectFiles").then((module) => ({ default: module.ProjectFilesPanel })),
);
const LazyMarkdown = lazy(() =>
  import("@astryxdesign/core/Markdown").then((module) => ({ default: module.Markdown })),
);
const LazySlider = lazy(() =>
  import("@astryxdesign/core/Slider").then((module) => ({ default: module.Slider })),
);

const PROJECT_PANEL_TOOL_VIEWS = ["memory", "files", "github"] as const;
type ProjectPanelToolView = (typeof PROJECT_PANEL_TOOL_VIEWS)[number];
type ProjectPanelView = "menu" | ProjectPanelToolView;
type ProjectPanelMode = "closed" | "open" | "maximized";
type VisibleProjectPanelMode = Exclude<ProjectPanelMode, "closed">;
type GithubOperationKind = "auth-check" | "auth-start" | "connect" | "repo-load" | "sync";
type GithubOperationState = {
  kind: GithubOperationKind;
  repositoryUrl?: string;
};
type GithubRepositoryRefreshOptions = {
  force?: boolean;
  onlyIfRemoteStale?: boolean;
  session?: GithubLoginSessionState | null;
};
type LatestProjectOperationToken = {
  controller: AbortController;
  generation: number;
  projectId: string;
};
type ProjectFileImportState = {
  kind: "drop" | "folder";
};
type LatestProjectOperationRegistry = {
  controllers: Record<string, AbortController>;
  generations: Record<string, number>;
};

type ProjectPanelTab = {
  id: string;
  view: ProjectPanelToolView;
  fileQuery: string;
  filePreview: ProjectFilePreview | null;
  projectSourcesMode: ProjectSourcesMode;
  selectedProjectSourceId: string | null;
};
type ProjectMemoryCounts = Record<ProjectMemoryCategory, number>;

const PROJECT_MEMORY_CATEGORIES: ProjectMemoryCategory[] = ["action", "decision", "issue", "risk"];

function createEmptyProjectMemoryCounts(): ProjectMemoryCounts {
  return {
    action: 0,
    decision: 0,
    issue: 0,
    risk: 0,
  };
}

const EMPTY_PROJECT_MEMORY_COUNTS = createEmptyProjectMemoryCounts();
const EMPTY_PROJECT_MEMORY_ITEMS: ProjectMemoryItem[] = [];
const EMPTY_PROJECT_ATTACHMENTS: Attachment[] = [];

function createLatestProjectOperationRegistry(): LatestProjectOperationRegistry {
  return { controllers: {}, generations: {} };
}

function beginLatestProjectOperation(
  registry: LatestProjectOperationRegistry,
  projectId: string,
): LatestProjectOperationToken | null {
  if (registry.controllers[projectId]) {
    return null;
  }

  const controller = new AbortController();
  const generation = (registry.generations[projectId] ?? 0) + 1;
  registry.generations[projectId] = generation;
  registry.controllers[projectId] = controller;
  return { controller, generation, projectId };
}

function replaceLatestProjectOperation(
  registry: LatestProjectOperationRegistry,
  projectId: string,
): LatestProjectOperationToken {
  cancelLatestProjectOperation(registry, projectId);
  return beginLatestProjectOperation(registry, projectId)!;
}

function isLatestProjectOperationCurrent(
  registry: LatestProjectOperationRegistry,
  token: LatestProjectOperationToken,
) {
  return (
    registry.generations[token.projectId] === token.generation &&
    registry.controllers[token.projectId] === token.controller
  );
}

function finishLatestProjectOperation(
  registry: LatestProjectOperationRegistry,
  token: LatestProjectOperationToken,
) {
  if (!isLatestProjectOperationCurrent(registry, token)) {
    return false;
  }

  delete registry.controllers[token.projectId];
  return true;
}

function cancelLatestProjectOperation(
  registry: LatestProjectOperationRegistry,
  projectId: string,
) {
  registry.generations[projectId] = (registry.generations[projectId] ?? 0) + 1;
  registry.controllers[projectId]?.abort();
  delete registry.controllers[projectId];
}

function abortLatestProjectOperations(registry: LatestProjectOperationRegistry) {
  Object.values(registry.controllers).forEach((controller) => controller.abort());
  registry.controllers = {};
}

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() =>
    typeof window === "undefined" ? false : window.matchMedia(query).matches,
  );

  useEffect(() => {
    const mediaQuery = window.matchMedia(query);
    const handleChange = () => setMatches(mediaQuery.matches);

    handleChange();
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [query]);

  return matches;
}

function applyPageZoomLayoutScale(scale: number) {
  const normalizedScale = clampZoomScale(scale);
  document.documentElement.style.setProperty("--page-zoom-render-scale", String(normalizedScale));
  document.documentElement.dataset.pageZoomMode =
    "__TAURI_INTERNALS__" in window ? "native" : "css";
}

function getProjectMemorySlotState(canOpenProjectMemory: boolean, count: number) {
  if (!canOpenProjectMemory) {
    return "dormant";
  }

  return count > 0 ? "active" : "empty";
}

type ApiProjectCreateResponse = {
  id: number;
  name: string;
  description?: string | null;
  current_user_role?: ProjectRole | null;
  setup_status?: "draft" | "ready";
  setup_mode?: "analyzed" | "chat_only" | "existing" | null;
  setup_completed_at?: string | null;
  setup_completed_by?: number | null;
};

type ApiProjectResponse = ApiProjectCreateResponse & {
  created_at?: string;
};

type ApiHealthResponse = {
  status?: string;
};

type ApiDocumentStatus = "uploaded" | "processing" | "indexed" | "failed";

type ApiDocumentUploadResponse = {
  doc_id: number;
  status: ApiDocumentStatus;
  format?: string;
  blocks?: number;
  pages?: number | null;
  warnings?: Array<{
    code: string;
    message: string;
    location?: string | null;
  }>;
};

type ApiDocumentListItem = {
  id: number;
  filename: string;
  doc_type?: string | null;
  status: ApiDocumentStatus;
  uploaded_at?: string | null;
};

type ApiDocumentStatusResponse = {
  doc_id: number;
  status: ApiDocumentStatus;
  last_error?: string | null;
  progress_done?: number | null;
  progress_total?: number | null;
  extracted?: DocumentExtractionCounts;
};

type ApiQueryHistoryMessage = {
  role: "assistant" | "user";
  content: string;
};

type ApiQueryAttachment = {
  filename: string;
  content_base64: string;
};

type ApiQueryResponse = {
  answer: string;
  sources?: string[];
  route?: string;
  debug?: unknown;
};

type ProjectQueryOptions = {
  attachments?: ApiQueryAttachment[];
  history?: ApiQueryHistoryMessage[];
  intent?: "delta_briefing";
  setupMode?: "analyzed";
  signal?: AbortSignal;
  since?: string;
};

type ApiProjectSetupResponse = {
  project_id: number;
  setup_status: "ready";
  setup_mode: "analyzed" | "chat_only" | "existing";
  setup_completed_at: string;
  setup_completed_by?: number | null;
};

type ApiRepositoryStatus = "connected" | "syncing" | "indexed" | "failed";

type ApiRepositoryConnectResponse = {
  repo_id: number;
  status: ApiRepositoryStatus;
  branch?: string;
  run_id?: string | null;
};

type ApiRepositoryListItem = {
  id: number;
  provider: string;
  repository_url: string;
  branch: string;
  status: ApiRepositoryStatus;
  run_id?: string | null;
  connected_at?: string | null;
};

type ApiRepositoryStatusResponse = {
  repo_id: number;
  status: ApiRepositoryStatus;
  provider: string;
  repository_url: string;
  branch: string;
  run_id?: string | null;
  commit_sha?: string | null;
  indexed_files?: number | null;
  last_error?: string | null;
  sync_warning?: string | null;
  extracted?: Record<string, number>;
};

type ApiProjectDeltaAction = {
  id: number;
  content: string;
  owner?: string | null;
  due_date?: string | null;
};

type ApiProjectDeltaResponse = {
  since: string;
  new_memory: {
    decision: number;
    action: number;
    issue: number;
    risk: number;
  };
  pending_suggestions: number;
  pending_suggestions_by_kind?: Partial<Record<"complete_action" | "supersede", number>>;
  completed_actions: number;
  due_soon: ApiProjectDeltaAction[];
  overdue: ApiProjectDeltaAction[];
};

type ProjectDeltaBannerState = {
  projectId: string;
  since: string;
  delta: ApiProjectDeltaResponse;
};

type ServerStatus = "online" | "offline";
type SubmitQuestionOptions = {
  intent?: "delta_briefing";
  forceNewSession?: boolean;
  onSuccess?: () => void;
  preserveCurrentDraft?: boolean;
  question?: string;
  sessionTitle?: string;
  since?: string;
};
type ActionMenuOrigin = "bottom-left" | "bottom-right" | "top-left" | "top-right";

type ActionMenuState = {
  type: "session";
  projectId: string;
  sessionId: string;
  top: number;
  left: number;
  origin: ActionMenuOrigin;
};

type RenameDraft = {
  type: "session";
  projectId: string;
  sessionId: string;
  value: string;
};

type SessionDraft = {
  attachments: Attachment[];
  prompt: string;
};

const SERVER_SYNC_TIMEOUT_MS = 3000;
const DOCUMENT_STATUS_POLL_INTERVAL_MS = 3000;
const DOCUMENT_STATUS_POLL_TIMEOUT_MS = 180000;
const AUDIO_STATUS_POLL_INTERVAL_MS = 5000;
const AUDIO_STATUS_POLL_TIMEOUT_MS = 15 * 60 * 1000;
const GITHUB_REPOSITORY_SYNC_POLL_INTERVAL_MS = 3000;
const GITHUB_REPOSITORY_SYNC_TIMEOUT_MS = 600000;
const QUERY_TIMEOUT_MS = 60000;
const ACTION_MENU_WIDTH = 132;
const ACTION_MENU_SESSION_HEIGHT = 76;
const ACTION_MENU_GAP = 12;
const DESTRUCTIVE_CONFIRMATION_TIMEOUT_MS = 6000;
const PROJECT_STORAGE_KEY = "paim.projects.v8";
const SESSION_DRAFT_STORAGE_SUFFIX = ".drafts";
const PROJECT_ROLE_RETRY_DELAYS_MS = [400, 1200] as const;
const PROJECT_BRIEFING_QUESTION =
  "이 프로젝트의 목적, 현재 상태(완료된 것과 진행 중인 것), 그리고 다음에 해야 할 액션을 프로젝트 기록을 근거로 간결하게 브리핑해줘. 담당자와 마감일이 있는 액션은 함께 표기해줘.";
const LEGACY_PROJECT_STORAGE_KEYS = [
  "paim.projects.v7",
  "paim.projects.v6",
  "paim.projects.v5",
  "paim.projects.v4",
  "paim.projects.v3",
  "paim.projects.v2",
  "paim.projects.v1",
];
const SIDEBAR_STORAGE_KEY = "paim.sidebarCollapsed.v1";
const SIDEBAR_WIDTH_STORAGE_KEY = "paim.sidebarWidth.v1";
const PROJECT_PANEL_COLLAPSED_STORAGE_KEY = "paim.projectPanelCollapsed.v2";
const PROJECT_PANEL_WIDTH_STORAGE_KEY = "paim.projectPanelWidth.v1";
const ZOOM_STORAGE_KEY = "paim.zoomScale.v1";
const DEFAULT_SIDEBAR_WIDTH = 264;
const COLLAPSED_SIDEBAR_WIDTH = 52;
const MIN_SIDEBAR_WIDTH = 232;
const MAX_SIDEBAR_WIDTH = 332;
const DEFAULT_PROJECT_PANEL_WIDTH = 330;
const MIN_PROJECT_PANEL_WIDTH = 300;
const MAX_PROJECT_PANEL_WIDTH = 520;
const MIN_MAIN_CONTENT_WIDTH = 580;
const PANEL_RAIL_WIDTH = 44;
const DEFAULT_ZOOM_SCALE = 1;
const MIN_ZOOM_SCALE = 0.5;
const MAX_ZOOM_SCALE = 2;
const ZOOM_STEP = 0.05;
const LEGACY_WELCOME_CONTENT = "안녕하세요! 😊";
const FOCUSABLE_ELEMENT_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[contenteditable='true']",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function useDestructiveConfirmationTimeout(value: unknown, clear: () => void) {
  const clearRef = useRef(clear);
  clearRef.current = clear;

  useEffect(() => {
    if (!value) {
      return;
    }

    const timeoutId = window.setTimeout(
      () => clearRef.current(),
      DESTRUCTIVE_CONFIRMATION_TIMEOUT_MS,
    );
    return () => window.clearTimeout(timeoutId);
  }, [value]);
}

function isWindowsHost() {
  return window.navigator.userAgent.includes("Windows");
}

function isMacHost() {
  return window.navigator.userAgent.includes("Mac");
}

function isWindowControlTarget(target: EventTarget) {
  return (
    target instanceof HTMLElement &&
    Boolean(target.closest("button, a, input, textarea, select, [role='button']"))
  );
}

function WindowsTitlebar({ inert = false }: { inert?: boolean }) {
  const { t } = useI18n();

  function handleDragStart(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || isWindowControlTarget(event.target)) {
      return;
    }

    void getCurrentWindow().startDragging();
  }

  function handleToggleMaximize(event: MouseEvent<HTMLDivElement>) {
    if (isWindowControlTarget(event.target)) {
      return;
    }

    void getCurrentWindow().toggleMaximize();
  }

  return (
    <div
      className="windows-titlebar"
      inert={inert}
      onDoubleClick={handleToggleMaximize}
      onPointerDown={handleDragStart}
    >
      <div className="windows-titlebar-title">PaiM</div>
      <div className="windows-titlebar-controls">
        <IconButton
          className="windows-titlebar-button"
          icon={<Minus size={14} />}
          label={t("최소화")}
          onClick={() => void getCurrentWindow().minimize()}
          tooltip={t("최소화")}
          variant="ghost"
        />
        <IconButton
          className="windows-titlebar-button"
          icon={<Square size={12} />}
          label={t("최대화")}
          onClick={() => void getCurrentWindow().toggleMaximize()}
          tooltip={t("최대화")}
          variant="ghost"
        />
        <IconButton
          className="windows-titlebar-button windows-close-button"
          icon={<X size={15} />}
          label={t("닫기")}
          onClick={() => void getCurrentWindow().close()}
          tooltip={t("닫기")}
          variant="ghost"
        />
      </div>
    </div>
  );
}

function createId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

function createProject(name: string): ProjectWorkspace {
  return {
    id: createId("project"),
    currentUserRole: "owner",
    name,
    files: [],
    createdAt: Date.now(),
    sessions: [],
  };
}

function createProjectFromApi(serverProject: ApiProjectResponse): ProjectWorkspace {
  const createdAt = parsePaimTimestamp(serverProject.created_at);
  const setup = normalizeApiProjectSetup(serverProject);

  return {
    id: createId("project"),
    apiProjectId: serverProject.id,
    currentUserRole: serverProject.current_user_role,
    name: serverProject.name,
    description: serverProject.description ?? undefined,
    files: [],
    createdAt: Number.isFinite(createdAt) ? createdAt : Date.now(),
    ...setup,
    sessions: [],
  };
}

function createEmptySession(title: string): ChatSession {
  return {
    id: createId("session"),
    createdExplicitly: true,
    title,
    createdAt: Date.now(),
    messages: [],
  };
}

function isEmptyDefaultSession(session: ChatSession) {
  return (
    !session.createdExplicitly &&
    session.title === "New Chat" &&
    session.messages.length === 0
  );
}

// 이전 버전이 자동으로 넣던 첫 assistant 인사는 새 empty state와 중복되므로 로딩 때만 걷어낸다.
function removeLegacyWelcomeMessages(messages: Message[]) {
  if (
    messages.length === 1 &&
    messages[0].role === "assistant" &&
    messages[0].content === LEGACY_WELCOME_CONTENT
  ) {
    return [];
  }

  return messages;
}

function createUniqueProjectName(projects: ProjectWorkspace[], baseName: string) {
  const projectNames = new Set(projects.map((project) => project.name));
  const safeBaseName = baseName.trim() || "New Project";

  if (!projectNames.has(safeBaseName)) {
    return safeBaseName;
  }

  for (let index = 2; ; index += 1) {
    const candidateName = `${safeBaseName} ${index}`;

    if (!projectNames.has(candidateName)) {
      return candidateName;
    }
  }
}

function createNextProjectName(projects: ProjectWorkspace[]) {
  const projectNames = new Set(projects.map((project) => project.name.trim()));

  for (let index = 1; ; index += 1) {
    const candidateName = `New Project ${index}`;

    if (!projectNames.has(candidateName)) {
      return candidateName;
    }
  }
}

// 액션 메뉴를 트리거에 고정하되 화면 가장자리에서는 같은 축을 따라 반대 방향으로 연다.
function getActionMenuPosition(button: HTMLButtonElement, menuHeight: number) {
  const rect = button.getBoundingClientRect();
  const opensAbove = rect.bottom + ACTION_MENU_GAP + menuHeight > window.innerHeight - 8;

  return {
    top: opensAbove
      ? Math.max(8, rect.top - ACTION_MENU_GAP - menuHeight)
      : rect.bottom + ACTION_MENU_GAP,
    left: Math.max(8, rect.right - ACTION_MENU_WIDTH),
    origin: opensAbove ? "bottom-right" : "top-right" as ActionMenuOrigin,
  };
}

function getActionMenuPositionAtPoint(clientX: number, clientY: number, menuHeight: number) {
  const opensAbove = clientY + menuHeight > window.innerHeight - 8;
  const opensLeft = clientX + ACTION_MENU_WIDTH > window.innerWidth - 8;

  return {
    top: opensAbove ? Math.max(8, clientY - menuHeight) : clientY,
    left: opensLeft ? Math.max(8, clientX - ACTION_MENU_WIDTH) : clientX,
    origin: `${opensAbove ? "bottom" : "top"}-${opensLeft ? "right" : "left"}` as ActionMenuOrigin,
  };
}

function getAccountDisplayName(user: PaimUser | null) {
  const name = user?.name?.trim();

  if (name) {
    return name;
  }

  const emailName = user?.email?.trim().split("@")[0];
  return emailName || "PaiM";
}

function getAccountInitials(user: PaimUser | null) {
  const displayName = getAccountDisplayName(user);
  const words = displayName.split(/\s+/).filter(Boolean);

  if (words.length > 1) {
    return `${Array.from(words[0])[0] ?? ""}${Array.from(words[words.length - 1] ?? "")[0] ?? ""}`
      .toLocaleUpperCase()
      .slice(0, 2);
  }

  return Array.from(words[0] ?? "P").slice(0, 2).join("").toLocaleUpperCase();
}

function AccountAvatar({
  className,
  user,
}: {
  className: string;
  user: PaimUser | null;
}) {
  return (
    <ProfileAvatar
      ariaHidden
      className={`account-avatar ${className}`}
      fallback={getAccountInitials(user)}
      imageUrl={user?.profile_image_url}
      label={getAccountDisplayName(user)}
    />
  );
}

function formatAccountCreatedAt(value: string | null | undefined, language: LanguageSetting) {
  if (!value) {
    return language === "ko" ? "확인할 수 없음" : "Unavailable";
  }

  const date = new Date(parsePaimTimestamp(value));
  if (Number.isNaN(date.getTime())) {
    return language === "ko" ? "확인할 수 없음" : "Unavailable";
  }

  return new Intl.DateTimeFormat(language === "ko" ? "ko-KR" : "en-US", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(date);
}

function createProjectState(
  projects: ProjectWorkspace[],
  selectedProjectId?: string | null,
  selectedSessionId?: string | null,
): ProjectState {
  const validProjects = projects
    .map((project) => {
      const sessions = (project.sessions ?? [])
        .map((session) => {
          // Older clients stored the server row id beside otherwise local chat data.
          // Preserve the chat while dropping that obsolete linkage.
          const localSession = { ...session } as ChatSession & {
            serverSessionId?: unknown;
          };
          delete localSession.serverSessionId;
          return {
            ...localSession,
            messages: removeLegacyWelcomeMessages(localSession.messages),
          };
        })
        .filter((session) => !isEmptyDefaultSession(session));
      const hasLegacyConversation = sessions.some((session) =>
        session.messages.some(
          (message) => message.role === "user" || message.role === "assistant",
        ),
      );

      return {
        ...project,
        setupCompletedAt:
          project.setupCompletedAt ??
          (hasLegacyConversation ? project.createdAt || Date.now() : undefined),
        setupMode:
          project.setupMode ??
          (hasLegacyConversation ? "existing" : undefined),
        sessions,
      };
    });

  if (validProjects.length === 0) {
    return {
      projects: [],
      selectedProjectId: null,
      selectedSessionId: null,
    };
  }

  const selectedProject =
    validProjects.find((project) => project.id === selectedProjectId) ?? validProjects[0];
  const selectedSession =
    selectedSessionId === null || !isProjectSetupComplete(selectedProject)
      ? null
      : selectedProject.sessions.find((session) => session.id === selectedSessionId) ?? null;

  return {
    projects: validProjects,
    selectedProjectId: selectedProject.id,
    selectedSessionId: selectedSession?.id ?? null,
  };
}

// 서버 목록을 정본으로 삼되, 로컬 전용 작업 상태는 보존한다.
function mergeServerProjects(
  localProjects: ProjectWorkspace[],
  serverProjects: ApiProjectResponse[],
) {
  const usedLocalProjectIds = new Set<string>();
  const localProjectsByApiId = new Map<number, ProjectWorkspace>();

  for (const project of localProjects) {
    if (typeof project.apiProjectId === "number" && !localProjectsByApiId.has(project.apiProjectId)) {
      localProjectsByApiId.set(project.apiProjectId, project);
    }
  }

  const syncedProjects = serverProjects.map((serverProject) => {
    const localProject = localProjectsByApiId.get(serverProject.id);

    if (!localProject) {
      return createProjectFromApi(serverProject);
    }

    usedLocalProjectIds.add(localProject.id);
    const setup = normalizeApiProjectSetup(serverProject, localProject);

    return {
      ...localProject,
      apiProjectId: serverProject.id,
      currentUserRole:
        serverProject.current_user_role === undefined
          ? localProject.currentUserRole
          : serverProject.current_user_role,
      description:
        serverProject.description === undefined
          ? localProject.description
          : serverProject.description ?? undefined,
      name: serverProject.name,
      serverMissing: undefined,
      ...setup,
    };
  });

  // 성공한 서버 목록을 권한의 정본으로 삼는다. 목록에서 사라진 서버 프로젝트는
  // 삭제·멤버 권한 회수 가능성이 있으므로 계정 캐시에 남기지 않는다.
  const cachedOnlyProjects = localProjects
    .filter(
      (project) =>
        !usedLocalProjectIds.has(project.id) && typeof project.apiProjectId !== "number",
    )
    .map((project) => ({ ...project, serverMissing: undefined }));

  return [...syncedProjects, ...cachedOnlyProjects];
}

function getProjectStorageKey(
  authUser: PaimUser | null,
  hasAuthSession: boolean,
  serverUrl = getPaimApiRootUrl(),
) {
  const serverScope = normalizePaimServerUrl(serverUrl) || DEFAULT_PAIM_API_ROOT_URL;

  if (!authUser || !hasAuthSession) {
    return `${PROJECT_STORAGE_KEY}.server.${encodeURIComponent(serverScope)}`;
  }

  const accountScope = encodeURIComponent(
    `${serverScope}|${authUser.id}|${authUser.email.trim().toLowerCase()}`,
  );
  return `${PROJECT_STORAGE_KEY}.account.${accountScope}`;
}

function loadProjectState(storageKey: string, allowLegacyFallback = false) {
  const savedValue =
    window.localStorage.getItem(storageKey) ??
    (allowLegacyFallback
      ? window.localStorage.getItem(PROJECT_STORAGE_KEY) ??
        LEGACY_PROJECT_STORAGE_KEYS
          .map((legacyStorageKey) => window.localStorage.getItem(legacyStorageKey))
          .find((value): value is string => Boolean(value))
      : null);

  if (!savedValue) {
    return createProjectState([]);
  }

  try {
    const savedState = JSON.parse(savedValue) as Partial<ProjectState>;
    const projects = (savedState.projects ?? []).map((project) => {
      const repository = project.githubRepository;
      if (!repository || repository.remoteCheckStatus !== "checking") {
        return project;
      }

      return {
        ...project,
        githubRepository: {
          ...repository,
          remoteCheckAttemptedAt: repository.remoteCheckedAt ?? null,
          remoteCheckStatus: "unknown" as const,
          remoteCheckError: null,
        },
      };
    });

    return createProjectState(projects, savedState.selectedProjectId, savedState.selectedSessionId);
  } catch {
    return createProjectState([]);
  }
}

// 데스크톱 앱을 다시 열 때 마지막 사이드바 접힘 상태를 복원한다.
function loadSidebarCollapsed() {
  return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true";
}

// 우측 프로젝트 패널 접힘 상태를 앱 재실행 후에도 유지한다.
function loadProjectPanelCollapsed() {
  return window.localStorage.getItem(PROJECT_PANEL_COLLAPSED_STORAGE_KEY) !== "false";
}

function clampSidebarWidth(width: number) {
  return Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, width));
}

function clampProjectPanelWidth(width: number) {
  return Math.min(MAX_PROJECT_PANEL_WIDTH, Math.max(MIN_PROJECT_PANEL_WIDTH, width));
}

function loadSidebarWidth() {
  const savedWidth = Number(window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY));

  if (!Number.isFinite(savedWidth)) {
    return DEFAULT_SIDEBAR_WIDTH;
  }

  return clampSidebarWidth(savedWidth);
}

function loadProjectPanelWidth() {
  const savedWidth = Number(window.localStorage.getItem(PROJECT_PANEL_WIDTH_STORAGE_KEY));

  if (!Number.isFinite(savedWidth)) {
    return DEFAULT_PROJECT_PANEL_WIDTH;
  }

  if (savedWidth === 360) {
    return DEFAULT_PROJECT_PANEL_WIDTH;
  }

  return clampProjectPanelWidth(savedWidth);
}

function clampZoomScale(scale: number) {
  const clampedScale = Math.min(MAX_ZOOM_SCALE, Math.max(MIN_ZOOM_SCALE, scale));
  const steppedScale =
    MIN_ZOOM_SCALE +
    Math.round((clampedScale - MIN_ZOOM_SCALE) / ZOOM_STEP) * ZOOM_STEP;

  return Math.round(steppedScale * 100) / 100;
}

function loadZoomScale() {
  const savedValue = window.localStorage.getItem(ZOOM_STORAGE_KEY);

  if (savedValue === null || savedValue.trim() === "") {
    return DEFAULT_ZOOM_SCALE;
  }

  const savedScale = Number(savedValue);

  if (!Number.isFinite(savedScale)) {
    return DEFAULT_ZOOM_SCALE;
  }

  return clampZoomScale(savedScale);
}

function resizePromptTextarea(textarea: HTMLTextAreaElement | null) {
  if (!textarea) {
    return;
  }

  const computedStyle = window.getComputedStyle(textarea);
  const lineHeight = Number.parseFloat(computedStyle.lineHeight) || 22;
  const verticalPadding =
    (Number.parseFloat(computedStyle.paddingTop) || 0) +
    (Number.parseFloat(computedStyle.paddingBottom) || 0);
  const maxHeight = lineHeight * 6 + verticalPadding;

  textarea.style.height = "auto";
  const nextHeight = Math.min(textarea.scrollHeight, maxHeight);
  textarea.style.height = `${nextHeight}px`;
  textarea.style.overflowY = textarea.scrollHeight > maxHeight + 1 ? "auto" : "hidden";
}

function getZoomShortcutDirection(event: globalThis.KeyboardEvent, isWindows: boolean) {
  if (isWindows ? !event.ctrlKey : !event.metaKey) {
    return null;
  }

  if (event.altKey) {
    return null;
  }

  if (event.key === "+" || event.key === "=") {
    return "in";
  }

  if (event.key === "-") {
    return "out";
  }

  if (event.key === "0") {
    return "reset";
  }

  return null;
}

function getFileName(path: string) {
  const normalizedPath = path.replace(/[\\/]+$/, "");
  return normalizedPath.split(/[\\/]/).pop() || normalizedPath || path;
}

function getUploadName(rootPath: string, filePath: string) {
  const root = rootPath.replace(/\\/g, "/").replace(/\/$/, "");
  const file = filePath.replace(/\\/g, "/");
  const prefix = `${root}/`;
  const relative = file.startsWith(prefix) ? file.slice(prefix.length) : getFileName(filePath);
  return `${getFileName(rootPath)}/${relative}`;
}

function normalizeDialogPaths(selectedPaths: string | string[] | null) {
  if (!selectedPaths) {
    return [];
  }

  return (Array.isArray(selectedPaths) ? selectedPaths : [selectedPaths]).filter(Boolean);
}

function getBase64ByteLength(encoded: string) {
  const padding = encoded.endsWith("==") ? 2 : encoded.endsWith("=") ? 1 : 0;
  return Math.floor((encoded.length * 3) / 4) - padding;
}

function base64ToBytes(encoded: string) {
  const binary = window.atob(encoded);
  const bytes = new Uint8Array(binary.length);

  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }

  return bytes;
}

function toProjectDocumentStatus(status: ApiDocumentStatus): ProjectDocumentStatus {
  return status;
}

function isProjectDocumentTerminal(status?: ProjectDocumentStatus) {
  return status === "indexed" || status === "failed" || status === "delayed";
}

// 랜딩 화면은 서버 연동 문서 상태를 저장하지 않고 현재 첨부 목록에서만 집계한다.
function getProjectDocumentStatusSummary(attachments: Attachment[]) {
  const serverDocuments = collectFileAttachments(attachments).filter(
    (attachment) =>
      typeof attachment.docId === "number" || typeof attachment.documentStatus === "string",
  );
  const terminalCount = serverDocuments.filter((attachment) =>
    isProjectDocumentTerminal(attachment.documentStatus),
  ).length;
  const incompleteCount = serverDocuments.filter(
    (attachment) => attachment.documentStatus !== "indexed",
  ).length;

  return {
    incompleteCount,
    inProgressCount: serverDocuments.length - terminalCount,
    terminalCount,
    totalCount: serverDocuments.length,
  };
}

function getProjectSetupSourceStatusLabel(attachment: Attachment) {
  if (attachment.documentStatus === "uploading") {
    return "업로드 중";
  }

  if (attachment.documentStatus === "uploaded" || attachment.documentStatus === "processing") {
    return "처리 중";
  }

  if (attachment.documentStatus === "indexed") {
    return "완료";
  }

  if (attachment.documentStatus === "failed") {
    return "실패";
  }

  if (attachment.documentStatus === "delayed") {
    return "지연";
  }

  return attachment.kind === "directory" ? "폴더" : "로컬";
}

function createServerDocumentAttachment(
  document: ApiDocumentListItem,
): ServerDocumentAttachment {
  const uploadedAt = parsePaimTimestamp(document.uploaded_at);

  return {
    id: `project-document-${document.id}`,
    name: document.filename,
    path: `server-document://${document.id}/${document.filename}`,
    kind: "file",
    docId: document.id,
    documentType: document.doc_type ?? null,
    documentStatus: toProjectDocumentStatus(document.status),
    serverOnly: true,
    uploadedAt: Number.isFinite(uploadedAt) ? uploadedAt : Date.now(),
  };
}

function collectFileAttachments(attachments: Attachment[]): Attachment[] {
  return attachments.flatMap((attachment) =>
    attachment.kind === "directory"
      ? collectFileAttachments(attachment.children ?? [])
      : [attachment],
  );
}

function getAttachmentDocIds(attachments: Attachment[]) {
  return new Set(
    collectFileAttachments(attachments)
      .map((attachment) => attachment.docId)
      .filter((docId): docId is number => typeof docId === "number"),
  );
}

function mergeServerDocumentsIntoAttachments(
  attachments: Attachment[],
  documents: ApiDocumentListItem[],
  tombstonedDocumentIds: ReadonlySet<number> = new Set<number>(),
) {
  return reconcileProjectDocumentAttachments(
    attachments,
    documents.map(createServerDocumentAttachment),
    tombstonedDocumentIds,
  );
}

function getGithubRepositoryUrl(repository: GitRepositoryInfo) {
  return repository.path || (repository.remoteRepo ? `https://github.com/${repository.remoteRepo}` : "");
}

function getGithubRemoteRepo(repositoryUrl: string) {
  try {
    const parsed = new URL(repositoryUrl);
    const [owner, repo] = parsed.pathname.replace(/\.git$/, "").split("/").filter(Boolean);

    return owner && repo ? `${owner}/${repo}` : undefined;
  } catch {
    return undefined;
  }
}

function getGithubRepositoryName(repositoryUrl: string) {
  const remoteRepo = getGithubRemoteRepo(repositoryUrl);

  if (remoteRepo) {
    return remoteRepo.split("/").pop() ?? remoteRepo;
  }

  return repositoryUrl.replace(/\/+$/, "").split("/").pop()?.replace(/\.git$/, "") || "GitHub repo";
}

function parseGithubSyncWarnings(rawWarning?: string | null): GitRepositorySyncWarning[] | undefined {
  if (!rawWarning) {
    return undefined;
  }

  try {
    const parsed = JSON.parse(rawWarning) as unknown;

    if (!Array.isArray(parsed)) {
      return [{ reason: "일부 소스 수집 실패" }];
    }

    return parsed
      .filter((warning): warning is Record<string, unknown> => warning !== null && typeof warning === "object")
      .map((warning) => ({
        source_type: typeof warning.source_type === "string" ? warning.source_type : undefined,
        reason: typeof warning.reason === "string" ? warning.reason : undefined,
      }));
  } catch {
    return [{ reason: "일부 소스 수집 실패" }];
  }
}

function mergeGithubRepositoryInfo(
  currentRepository: GitRepositoryInfo | undefined,
  repository: ApiRepositoryListItem,
): GitRepositoryInfo {
  const isSameRepository =
    currentRepository?.repoId === repository.id ||
    (currentRepository !== undefined &&
      typeof currentRepository.repoId !== "number" &&
      getGithubRepositoryUrl(currentRepository) === repository.repository_url);
  const preservedRepository = isSameRepository ? currentRepository : undefined;
  const canPreserveBranchState = preservedRepository?.branch === repository.branch;
  const nextRunId =
    repository.status === "syncing"
      ? repository.run_id ?? preservedRepository?.syncRunId ?? null
      : null;
  const canPreserveRunState =
    !repository.run_id || preservedRepository?.syncRunId === repository.run_id;

  return {
    path: repository.repository_url,
    name: preservedRepository?.name ?? getGithubRepositoryName(repository.repository_url),
    branch: repository.branch,
    isDirty: false,
    remoteRepo: preservedRepository?.remoteRepo ?? getGithubRemoteRepo(repository.repository_url),
    issuePrStatus: preservedRepository?.issuePrStatus ?? "서버 연결됨",
    visibility: preservedRepository?.visibility ?? "public",
    authProvider: preservedRepository?.authProvider ?? "public",
    repoId: repository.id,
    syncStatus: repository.status,
    syncRunId: nextRunId,
    syncStartedAt:
      repository.status === "syncing"
        ? (canPreserveRunState ? preservedRepository?.syncStartedAt : undefined) ?? Date.now()
        : undefined,
    connectedAt: repository.connected_at ?? undefined,
    commitSha: canPreserveBranchState ? preservedRepository?.commitSha : undefined,
    remoteHeadSha: canPreserveBranchState ? preservedRepository?.remoteHeadSha : null,
    remoteCheckedAt: canPreserveBranchState ? preservedRepository?.remoteCheckedAt : null,
    remoteCheckAttemptedAt: canPreserveBranchState
      ? preservedRepository?.remoteCheckAttemptedAt
      : null,
    remoteCheckStatus: canPreserveBranchState
      ? preservedRepository?.remoteCheckStatus
      : "unknown",
    remoteCheckError: canPreserveBranchState
      ? preservedRepository?.remoteCheckError
      : null,
    indexedFiles: canPreserveBranchState ? preservedRepository?.indexedFiles : undefined,
    lastError: canPreserveRunState ? preservedRepository?.lastError : null,
    syncWarnings: canPreserveRunState ? preservedRepository?.syncWarnings : undefined,
  };
}

function applyGithubRepositoryStatus(
  repository: GitRepositoryInfo,
  status: ApiRepositoryStatusResponse,
): GitRepositoryInfo {
  const nextCommitSha = status.commit_sha ?? null;
  const currentCommitSha = repository.commitSha ?? null;
  const hasSameCommitSha =
    (currentCommitSha === null && nextCommitSha === null) ||
    githubCommitShasMatch(currentCommitSha, nextCommitSha);
  const canPreserveRemoteCheck =
    repository.branch === status.branch &&
    hasSameCommitSha;
  const canPreserveRunState =
    !status.run_id || repository.syncRunId === status.run_id;

  return {
    ...repository,
    path: status.repository_url,
    name: repository.name || getGithubRepositoryName(status.repository_url),
    branch: status.branch,
    remoteRepo: repository.remoteRepo ?? getGithubRemoteRepo(status.repository_url),
    repoId: status.repo_id,
    syncStatus: status.status,
    syncRunId:
      status.status === "syncing"
        ? status.run_id ?? repository.syncRunId ?? null
        : null,
    syncStartedAt:
      status.status === "syncing"
        ? (canPreserveRunState ? repository.syncStartedAt : undefined) ?? Date.now()
        : undefined,
    commitSha: nextCommitSha,
    remoteHeadSha: canPreserveRemoteCheck ? repository.remoteHeadSha : null,
    remoteCheckedAt: canPreserveRemoteCheck ? repository.remoteCheckedAt : null,
    remoteCheckAttemptedAt: canPreserveRemoteCheck
      ? repository.remoteCheckAttemptedAt
      : null,
    remoteCheckStatus: canPreserveRemoteCheck
      ? repository.remoteCheckStatus
      : "unknown",
    remoteCheckError: canPreserveRemoteCheck ? repository.remoteCheckError : null,
    indexedFiles: status.indexed_files ?? null,
    lastError: status.last_error ?? null,
    syncWarnings: parseGithubSyncWarnings(status.sync_warning),
  };
}

function canUseTauriDialog() {
  return "__TAURI_INTERNALS__" in window;
}

async function openExternalUrl(url: string) {
  if (canUseTauriDialog()) {
    await openUrl(url);
    return;
  }

  window.open(url, "_blank", "noopener,noreferrer");
}

// GitHub 이벤트는 최신순으로만 정렬해서 Overview에 보여준다.
function getProjectGithubEvents(project: ProjectWorkspace) {
  return [...(project.githubEvents ?? [])].sort((left, right) => right.createdAt - left.createdAt);
}

// 우측 패널은 Codex류 보조 패널처럼 메뉴와 상세 화면을 오간다.
function getProjectPanelTitle(view: ProjectPanelView) {
  const titles: Record<ProjectPanelView, string> = {
    menu: "도구 선택",
    memory: "프로젝트 메모리",
    files: "자료",
    github: "GitHub",
  };

  return titles[view];
}

// 새 탭은 자료 탭일 때만 독립 상태를 사용한다. 다른 탭은 같은 화면을 여러 개 열 수만 있으면 충분하다.
function createProjectPanelTab(view: ProjectPanelToolView): ProjectPanelTab {
  return {
    id: createId("project-panel-tab"),
    view,
    fileQuery: "",
    filePreview: null,
    projectSourcesMode: "library",
    selectedProjectSourceId: null,
  };
}

function resolveStateAction<T>(action: SetStateAction<T>, currentValue: T) {
  return typeof action === "function"
    ? (action as (value: T) => T)(currentValue)
    : action;
}

// 패널 탭은 열린 파일이 있으면 자료 탭 대신 파일명과 파일 아이콘을 보여준다.
function getProjectPanelTabVisualMeta(
  view: ProjectPanelToolView,
  preview: ProjectFilePreview | null,
) {
  if (view === "files" && preview) {
    return getProjectFileVisualMeta(preview.name);
  }

  const icons: Record<ProjectPanelToolView, ProjectFileVisualMeta> = {
    memory: { Icon: Brain, color: "var(--muted)" },
    files: { Icon: Files, color: "var(--muted)" },
    github: { Icon: GitBranch, color: "var(--muted)" },
  };

  return icons[view];
}

function getGithubLoginErrorMessage(error: unknown) {
  const message = getErrorMessage(error, "GitHub 로그인을 시작할 수 없습니다");

  return /failed to fetch|load failed/i.test(message)
    ? "GitHub 로그인 서버에 연결할 수 없습니다. 네트워크를 확인해 주세요."
    : message;
}

// private repo가 실제로 포함됐는지 로그인/새로고침 결과에서 바로 보이게 한다.
function getGithubRepositoryLoadMessage(
  repositories: GithubAvailableRepository[],
  language: LanguageSetting,
) {
  const privateCount = repositories.filter((repository) => repository.private).length;

  return translate(language, "{count}개 repo를 불러왔습니다 · private {privateCount}개", {
    count: repositories.length,
    privateCount,
  });
}

// GitHub App 설치는 user API가 없어서 repo owner를 계정 표시 fallback으로 쓴다.
function getGithubRepositoryOwner(repositories: GithubAvailableRepository[]) {
  return repositories.find((repository) => repository.owner)?.owner;
}

// localStorage에는 큰 data URL을 저장하지 않도록 첨부 미리보기를 제외한다.
function createStoredAttachments(attachments: Attachment[] = []): Attachment[] {
  return attachments.map((attachment) => ({
    id: attachment.id,
    name: attachment.name,
    uploadName: attachment.uploadName,
    path: attachment.path,
    kind: attachment.kind,
    children: attachment.children
      ? createStoredAttachments(attachment.children)
      : undefined,
    childrenLoaded: attachment.childrenLoaded,
    docId: attachment.docId,
    documentType: attachment.documentType,
    documentStatus: attachment.documentStatus,
    diarization: attachment.diarization,
    extracted: attachment.extracted,
    isExpanded: attachment.isExpanded,
    lastError: attachment.lastError,
    processingProgressDone: attachment.processingProgressDone,
    processingProgressTotal: attachment.processingProgressTotal,
    serverOnly: attachment.serverOnly,
    transcriptionProvider: attachment.transcriptionProvider,
    uploadedAt: attachment.uploadedAt,
  }));
}

function loadSessionDrafts(storageKey: string) {
  const drafts = new Map<string, SessionDraft>();
  try {
    const saved = JSON.parse(
      window.localStorage.getItem(storageKey) || "{}",
    ) as Record<string, Partial<SessionDraft>>;
    Object.entries(saved).forEach(([key, draft]) => {
      const prompt = typeof draft.prompt === "string" ? draft.prompt : "";
      const attachments = Array.isArray(draft.attachments)
        ? createStoredAttachments(draft.attachments)
        : [];
      if (prompt.trim() || attachments.length > 0) {
        drafts.set(key, { attachments, prompt });
      }
    });
  } catch {
    return drafts;
  }
  return drafts;
}

function saveSessionDrafts(storageKey: string, drafts: Map<string, SessionDraft>) {
  const saved = Object.fromEntries(
    Array.from(drafts.entries()).map(([key, draft]) => [
      key,
      {
        attachments: createStoredAttachments(draft.attachments),
        prompt: draft.prompt,
      },
    ]),
  );
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(saved));
    return true;
  } catch {
    return false;
  }
}

function createStoredSessions(sessions: ChatSession[]) {
  return sessions.map((session) => ({
    ...session,
    messages: session.messages.map((message) => ({
      ...message,
      attachments: message.attachments ? createStoredAttachments(message.attachments) : undefined,
    })),
  }));
}

// 프로젝트 저장 시에도 큰 data URL 미리보기는 제외하고 파일 경로만 남긴다.
function createStoredProjectState(
  projects: ProjectWorkspace[],
  selectedProjectId: string | null,
  selectedSessionId: string | null,
): ProjectState {
  return {
    projects: projects.map((project) => ({
      ...project,
      files: createStoredAttachments(project.files),
      sessions: createStoredSessions(project.sessions),
    })),
    selectedProjectId,
    selectedSessionId,
  };
}

function getProjectDeltaNewMemoryCount(delta: ApiProjectDeltaResponse) {
  return Object.values(delta.new_memory).reduce((sum, count) => sum + count, 0);
}

function getProjectDeltaSupersedeCount(delta: ApiProjectDeltaResponse) {
  return delta.pending_suggestions_by_kind?.supersede ?? 0;
}

function canBriefProjectDelta(delta: ApiProjectDeltaResponse) {
  return (
    getProjectDeltaNewMemoryCount(delta) +
    delta.pending_suggestions +
    delta.completed_actions +
    delta.due_soon.length +
    delta.overdue.length
  ) > 0;
}

function shouldShowProjectDelta(delta: ApiProjectDeltaResponse) {
  return canBriefProjectDelta(delta) || getProjectDeltaSupersedeCount(delta) > 0;
}

function formatProjectDeltaSummary(
  delta: ApiProjectDeltaResponse,
  translateValue: (key: string, vars?: Record<string, number | string>) => string,
) {
  const parts = [
    translateValue("메모리 +{count}", { count: getProjectDeltaNewMemoryCount(delta) }),
  ];

  if (delta.pending_suggestions > 0) {
    parts.push(translateValue("완료 제안 {count}건", { count: delta.pending_suggestions }));
  }
  if (getProjectDeltaSupersedeCount(delta) > 0) {
    parts.push(
      translateValue("결정 변경 제안 {count}건", {
        count: getProjectDeltaSupersedeCount(delta),
      }),
    );
  }
  if (delta.completed_actions > 0) {
    parts.push(translateValue("완료 {count}건", { count: delta.completed_actions }));
  }
  if (delta.due_soon.length > 0) {
    parts.push(translateValue("마감 임박 {count}건", { count: delta.due_soon.length }));
  }
  if (delta.overdue.length > 0) {
    parts.push(translateValue("기한 초과 {count}건", { count: delta.overdue.length }));
  }

  return parts.join(" · ");
}

type AttachmentListProps = {
  attachments: Attachment[];
  label: string;
  onRemove?: (attachmentId: string) => void;
};

// 이미지 파일은 썸네일로, 나머지 파일은 파일칩으로 표시한다.
function AttachmentList({ attachments, label, onRemove }: AttachmentListProps) {
  const { t } = useI18n();

  return (
    <div className="attachment-list" aria-label={label}>
      {attachments.map((attachment) => {
        const isImage = Boolean(attachment.previewUrl);

        if (isImage) {
          return (
            <div className="attachment-preview" key={attachment.id}>
              <img
                src={attachment.previewUrl}
                alt={t("{name} 미리보기", { name: attachment.name })}
              />
              <span>{attachment.name}</span>
              {onRemove ? (
                <IconButton
                  className="remove-attachment-button"
                  icon={<X size={14} />}
                  label={t("{name} 제거", { name: attachment.name })}
                  onClick={() => onRemove(attachment.id)}
                  size="sm"
                  tooltip={t("{name} 제거", { name: attachment.name })}
                  variant="ghost"
                />
              ) : null}
            </div>
          );
        }

        if (onRemove) {
          return (
            <Badge
              className="attachment-chip"
              key={attachment.id}
              label={
                <>
                  <span className="attachment-name">{attachment.name}</span>
                  <IconButton
                    className="remove-attachment-button"
                    icon={<X size={13} />}
                    label={t("{name} 제거", { name: attachment.name })}
                    onClick={() => onRemove(attachment.id)}
                    size="sm"
                    tooltip={t("{name} 제거", { name: attachment.name })}
                    variant="ghost"
                  />
                </>
              }
            />
          );
        }

        return (
          <Badge
            className="attachment-chip"
            key={attachment.id}
            label={<span className="attachment-name">{attachment.name}</span>}
          />
        );
      })}
    </div>
  );
}

function PanelLoadingState({ label }: { label: string }) {
  return (
    <div
      className="panel-loading-state"
      aria-busy="true"
    >
      <Spinner aria-label={label} shade="subtle" size="sm" />
      <span>{label}</span>
    </div>
  );
}

type AuthGateState =
  | { status: "checking" }
  | { status: "anonymous"; message: string }
  | { status: "ready"; isOffline: boolean; user: PaimUser | null };

const AUTH_HEALTH_TIMEOUT_MS = 700;
const AUTH_SESSION_TIMEOUT_MS = 3000;

// 인증 확인이 끝난 뒤에만 보호 API를 사용하는 작업공간을 마운트한다.
export function App() {
  const [authState, setAuthState] = useState<AuthGateState>({ status: "checking" });
  const initialSettings = useMemo(loadPaimSettings, []);
  const initialZoomScale = useMemo(loadZoomScale, []);

  useLayoutEffect(() => {
    applyPageZoomLayoutScale(initialZoomScale);
    if ("__TAURI_INTERNALS__" in window) {
      void getCurrentWebview().setZoom(initialZoomScale).catch(() => undefined);
    }
  }, [initialZoomScale]);

  useEffect(() => {
    let active = true;
    const healthController = new AbortController();
    const sessionController = new AbortController();

    setPaimUnauthorizedHandler((message) => {
      if (active) {
        setAuthState({ status: "anonymous", message });
      }
    });

    async function restoreAuth() {
      const storedSession = loadPaimAuthSession();
      const healthTimeoutId = window.setTimeout(
        () => healthController.abort(),
        AUTH_HEALTH_TIMEOUT_MS,
      );

      try {
        await fetchPaimRootJson<ApiHealthResponse>("/health", { signal: healthController.signal });
      } catch {
        if (active) {
          setAuthState({
            status: "ready",
            isOffline: true,
            user: storedSession?.user ?? null,
          });
        }
        return;
      } finally {
        window.clearTimeout(healthTimeoutId);
      }

      const sessionTimeoutId = window.setTimeout(
        () => sessionController.abort(),
        AUTH_SESSION_TIMEOUT_MS,
      );
      try {
        const user = await fetchPaimSessionJson<PaimUser>("/auth/me", {
          signal: sessionController.signal,
        });
        if (active) {
          setAuthState({ status: "ready", isOffline: false, user });
        }
      } catch (error) {
        if (!active) {
          return;
        }

        if (isPaimApiError(error) && error.status === 404) {
          // 구버전 또는 인증 비활성 개발 서버와도 기존 오프라인 흐름을 유지한다.
          setAuthState({
            status: "ready",
            isOffline: false,
            user: storedSession?.user ?? null,
          });
          return;
        }

        if (isPaimApiError(error) && error.status === 401) {
          clearPaimAuthSession();
          setAuthState({ status: "anonymous", message: "" });
          return;
        }

        setAuthState({
          status: "anonymous",
          message: getErrorMessage(error, "인증 서버에 연결할 수 없습니다."),
        });
      } finally {
        window.clearTimeout(sessionTimeoutId);
      }
    }

    void restoreAuth();

    return () => {
      active = false;
      healthController.abort();
      sessionController.abort();
      setPaimUnauthorizedHandler(null);
    };
  }, []);

  function handleAuthenticated(response: PaimAuthResponse) {
    savePaimAuthSession({
      accessToken: response.access_token,
      user: response.user,
    });
    setAuthState({ status: "ready", isOffline: false, user: response.user });
  }

  function handleLogout() {
    clearPaimAuthSession();
    setAuthState({ status: "anonymous", message: "" });
  }

  if (authState.status === "checking") {
    return (
      <I18nProvider language={initialSettings.language}>
        <Theme theme={neutralTheme} mode={initialSettings.theme}>
          <main className="auth-screen auth-loading" aria-live="polite">
            <div aria-hidden="true" className="native-titlebar-drag-region" data-tauri-drag-region />
            <Spinner aria-label={translate(initialSettings.language, "로그인 상태 확인 중")} size="md" />
            <p>{translate(initialSettings.language, "로그인 상태를 확인하고 있습니다")}</p>
          </main>
        </Theme>
      </I18nProvider>
    );
  }

  if (authState.status === "anonymous") {
    return (
      <I18nProvider language={initialSettings.language}>
        <Theme theme={neutralTheme} mode={initialSettings.theme}>
          <Suspense
            fallback={
              <main className="auth-screen auth-loading" aria-live="polite">
                <div aria-hidden="true" className="native-titlebar-drag-region" data-tauri-drag-region />
                <Spinner
                  aria-label={translate(initialSettings.language, "로그인 화면 준비 중")}
                  size="md"
                />
              </main>
            }
          >
            <>
              <div
                aria-hidden="true"
                className="native-titlebar-drag-region"
                data-tauri-drag-region
              />
              <LazyAuthScreen
                initialMessage={authState.message}
                onAuthenticated={handleAuthenticated}
              />
            </>
          </Suspense>
        </Theme>
      </I18nProvider>
    );
  }

  return (
    <WorkspaceApp
      authUser={authState.user}
      canLogout={Boolean(loadPaimAuthSession())}
      initialServerOffline={authState.isOffline}
      onLogout={handleLogout}
    />
  );
}

type WorkspaceAppProps = {
  authUser: PaimUser | null;
  canLogout: boolean;
  initialServerOffline: boolean;
  onLogout: () => void;
};

// 프로젝트 Home을 최상위 진입점으로 두고, 상세 화면에서 시작한 대화를
// 프로젝트 하위 세션으로 관리한다.
function WorkspaceApp({ authUser, canLogout, initialServerOffline, onLogout }: WorkspaceAppProps) {
  const isWindows = useMemo(isWindowsHost, []);
  const isMac = useMemo(isMacHost, []);
  const initialProjectApiRootUrl = useMemo(getPaimApiRootUrl, []);
  const projectStorageKey = useMemo(
    () => getProjectStorageKey(authUser, canLogout, initialProjectApiRootUrl),
    [authUser, canLogout, initialProjectApiRootUrl],
  );
  const sessionDraftStorageKey = useMemo(
    () => `${projectStorageKey}${SESSION_DRAFT_STORAGE_SUFFIX}`,
    [projectStorageKey],
  );
  const pendingDocumentDeletesStorageKey = useMemo(
    () => getPendingDocumentDeletesStorageKey(projectStorageKey),
    [projectStorageKey],
  );
  const allowLegacyProjectCacheFallback =
    !canLogout &&
    normalizePaimServerUrl(initialProjectApiRootUrl) === DEFAULT_PAIM_API_ROOT_URL;
  const [initialProjectState] = useState(() =>
    loadProjectState(projectStorageKey, allowLegacyProjectCacheFallback),
  );
  const [initialSessionDrafts] = useState(() =>
    loadSessionDrafts(sessionDraftStorageKey),
  );
  const {
    canDeleteSelectedProject,
    canMutateSelectedProject,
    isSelectedProjectOwner,
    projects,
    projectsRef,
    selectedProject,
    selectedProjectId,
    selectedProjectIdRef,
    selectedProjectRole,
    selectedSession,
    selectedSessionId,
    selectedSessionIdRef,
    setProjects,
    setSelectedProjectId,
    setSelectedSessionId,
  } = useProjectWorkspaceDomain({
    hasAuthenticatedUser: Boolean(authUser),
    initialState: initialProjectState,
  });
  const [zoomScale, setZoomScaleState] = useState(loadZoomScale);
  const [prompt, setPrompt] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [expandedProjectSourcesId, setExpandedProjectSourcesId] = useState<string | null>(null);
  const [pendingProjectId, setPendingProjectId] = useState<string | null>(null);
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null);
  const [thinkingStartedAt, setThinkingStartedAt] = useState<number | null>(null);
  const [thinkingElapsedSeconds, setThinkingElapsedSeconds] = useState(0);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [showLatestMessageButton, setShowLatestMessageButton] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(loadSidebarCollapsed);
  const hasProjects = projects.length > 0;
  // 200% WebView 확대에서 960px 창은 약 480 CSS px가 된다. 이는 모바일 IA가 아니라
  // 데스크톱 접근성 확대 상태이므로 프로젝트 트리를 rail로 접어 작업 공간을 보존한다.
  const isHighZoomViewport = useMediaQuery(`(max-width: ${720 * zoomScale}px)`);
  const isSidebarCollapsedForLayout = isSidebarCollapsed || !hasProjects || isHighZoomViewport;
  const [sidebarWidth, setSidebarWidth] = useState(loadSidebarWidth);
  const [isSidebarResizing, setIsSidebarResizing] = useState(false);
  const [projectPanelMode, setProjectPanelMode] = useState<ProjectPanelMode>(
    () => (loadProjectPanelCollapsed() ? "closed" : "open"),
  );
  const isProjectPanelCollapsed = projectPanelMode === "closed";
  const isProjectPanelMaximized = projectPanelMode === "maximized";
  const [initialProjectPanelWidth] = useState(loadProjectPanelWidth);
  const projectPanelResizable = useResizable({
    defaultSize: initialProjectPanelWidth,
    maxSizePx: MAX_PROJECT_PANEL_WIDTH,
    minSizePx: MIN_PROJECT_PANEL_WIDTH,
  });
  const projectPanelWidth = projectPanelResizable.size;
  const projectPanelOverlayBreakpoint =
    (isSidebarCollapsedForLayout ? COLLAPSED_SIDEBAR_WIDTH : sidebarWidth) +
    projectPanelWidth +
    MIN_MAIN_CONTENT_WIDTH;
  const isProjectPanelOverlay = useMediaQuery(
    `(max-width: ${projectPanelOverlayBreakpoint * zoomScale}px)`,
  );
  const [isDragActive, setIsDragActive] = useState(false);
  const [activeDropZone, setActiveDropZone] = useState<"project-files" | "prompt" | null>(null);
  const [demoStatus, setDemoStatusState] = useState<DemoStatus | null>(null);
  const [noticeStackHeight, setNoticeStackHeight] = useState(0);
  const [statusRevision, setStatusRevision] = useState(0);
  const [projectPanelTabs, setProjectPanelTabs] = useState<ProjectPanelTab[]>([]);
  const [activeProjectPanelTabId, setActiveProjectPanelTabId] = useState<string | null>(null);
  const [projectPanelTabScrollState, setProjectPanelTabScrollState] = useState({
    canScrollEnd: false,
    canScrollStart: false,
  });
  const [projectDeltaBanner, setProjectDeltaBanner] = useState<ProjectDeltaBannerState | null>(null);
  const [postSyncRefreshRevision, setPostSyncRefreshRevision] = useState(0);
  const [projectMemoryCountsByProjectId, setProjectMemoryCountsByProjectId] = useState<
    Record<string, ProjectMemoryCounts>
  >({});
  const [projectMemoryItemsByProjectId, setProjectMemoryItemsByProjectId] = useState<
    Record<string, ProjectMemoryItem[]>
  >({});
  const [pendingSetupDeleteProjectFileId, setPendingSetupDeleteProjectFileId] = useState<string | null>(
    null,
  );
  const [audioUploadDraft, setAudioUploadDraft] = useState<AudioUploadDraft | null>(null);
  const [isAudioUploadStarting, setIsAudioUploadStarting] = useState(false);
  // 앱 진입점은 프로젝트 포트폴리오다. 프로젝트 선택은 상세 화면으로,
  // 새 프로젝트 생성은 설정 흐름으로 이동하고 채팅은 첫 전송 때만 만들어진다.
  const {
    mainView,
    membersReturnView,
    navigateTo,
    openMembers,
    openProjectDetail,
    openProjectManagement,
    projectDetailTab,
    projectManagementSection,
    setProjectDetailTab,
    setProjectManagementSection,
  } = useWorkspaceRoute();
  const [settings, setSettingsState] = useState(loadPaimSettings);
  const t = (key: string, vars?: Record<string, number | string>) =>
    translate(settings.language, key, vars);
  const [isSettingsResetConfirming, setIsSettingsResetConfirming] = useState(false);
  const [appVersion, setAppVersion] = useState(`개발 모드 ${packageJson.version}`);
  const [latestReleaseTag, setLatestReleaseTag] = useState("");
  const [projectFileTreeWidth, setProjectFileTreeWidth] = useState(
    DEFAULT_PROJECT_FILE_TREE_WIDTH,
  );
  const [isProjectFileTreeCollapsed, setIsProjectFileTreeCollapsed] = useState(false);
  const [isProjectFileTreeResizing, setIsProjectFileTreeResizing] = useState(false);
  const [projectFileImportsByProjectId, setProjectFileImportsByProjectId] = useState<
    Record<string, ProjectFileImportState>
  >({});
  const [loadingProjectFileEntryKeys, setLoadingProjectFileEntryKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const [openActionMenu, setOpenActionMenu] = useState<ActionMenuState | null>(null);
  const [isAccountMenuOpen, setIsAccountMenuOpen] = useState(false);
  const [renameDraft, setRenameDraft] = useState<RenameDraft | null>(null);
  const [githubLoginSessions, setGithubLoginSessions] = useState<Record<string, GithubLoginSessionState>>({});
  const [githubRepositories, setGithubRepositories] = useState<Record<string, GithubAvailableRepository[]>>({});
  const [githubRepositoryQueries, setGithubRepositoryQueries] = useState<Record<string, string>>({});
  const [githubOperationsByProjectId, setGithubOperationsByProjectId] = useState<
    Record<string, GithubOperationState>
  >({});
  const [pendingGithubDisconnectProjectId, setPendingGithubDisconnectProjectId] = useState<string | null>(null);
  const [pendingDeleteProjectId, setPendingDeleteProjectId] = useState<string | null>(null);
  const [pendingDeleteSession, setPendingDeleteSession] = useState<{
    projectId: string;
    sessionId: string;
  } | null>(null);
  const [serverStatus, setServerStatus] = useState<ServerStatus>(
    initialServerOffline ? "offline" : "online",
  );
  const [capabilities, setCapabilities] = useState<PaimCapabilities | null>(null);
  const [capabilitiesError, setCapabilitiesError] = useState("");
  const [capabilitiesRevision, setCapabilitiesRevision] = useState(0);
  const projectPanelReopenModeRef = useRef<VisibleProjectPanelMode>("open");
  const sidebarResizeRef = useRef<{
    pointerId: number | null;
    startX: number;
    startWidth: number;
    target: HTMLDivElement | null;
  }>({
    pointerId: null,
    startX: 0,
    startWidth: DEFAULT_SIDEBAR_WIDTH,
    target: null,
  });
  const projectFileTreeResizeRef = useRef<{
    pointerId: number | null;
    startX: number;
    startWidth: number;
    target: HTMLDivElement | null;
  }>({
    pointerId: null,
    startX: 0,
    startWidth: DEFAULT_PROJECT_FILE_TREE_WIDTH,
    target: null,
  });
  const projectPanelTabsRef = useRef<HTMLDivElement | null>(null);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const noticeStackRef = useRef<HTMLDivElement | null>(null);
  const mainViewHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const mainViewReturnFocusRef = useRef<HTMLElement | null>(null);
  const mainViewReturnFocusSelectorRef = useRef<string | null>(null);
  const promptTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const activeQueryControllerRef = useRef<AbortController | null>(null);
  const userCancelledQueryControllersRef = useRef(new WeakSet<AbortController>());
  const apiProjectEnsurePromisesRef = useRef(
    new Map<string, Promise<ProjectWorkspace>>(),
  );
  const isScrollingToChatBottomRef = useRef(false);
  const shouldStickToChatBottomRef = useRef(true);
  const actionMenuTriggerRef = useRef<HTMLElement | null>(null);
  const accountMenuTriggerRef = useRef<HTMLButtonElement | null>(null);
  const didHydrateAttachmentPreviewsRef = useRef(false);
  const didSyncProjectsRef = useRef(false);
  const documentPollTimeoutsRef = useRef(new Map<string, number>());
  const documentStatusHydrationTimeoutsRef = useRef(new Map<string, number>());
  const documentStatusHydrationsRef = useRef(new Set<string>());
  const documentStatusRequestsRef = useRef(
    new Map<string, Promise<ApiDocumentStatusResponse>>(),
  );
  const manualDocumentStatusRefreshesRef = useRef(new Set<string>());
  const postDocumentProcessingSyncTimeoutsRef = useRef(new Set<number>());
  const documentUploadControllersRef = useRef(new Map<string, AbortController>());
  const pendingDocumentDeleteQueueRef = useRef<PendingDocumentDeleteQueue | null>(null);
  const pendingDocumentDeleteRetryTimeoutRef = useRef<number | null>(null);
  if (!pendingDocumentDeleteQueueRef.current) {
    pendingDocumentDeleteQueueRef.current = createPendingDocumentDeleteQueue({
      deleteDocument: ({ apiProjectId, docId }) =>
        fetchPaimJson<void>(`/projects/${apiProjectId}/documents/${docId}`, {
          method: "DELETE",
        }),
      onPersistenceError: () => {
        setDemoStatusState({
          kind: "warning",
          message:
            "삭제 예약을 저장하지 못했습니다. 앱을 닫기 전에 서버 정리를 다시 시도합니다",
          ok: false,
          scope: "overview",
        });
      },
      storage: window.localStorage,
      storageKey: pendingDocumentDeletesStorageKey,
    });
  }
  const pendingDocumentDeleteQueue = pendingDocumentDeleteQueueRef.current;
  const githubRepositoryPollTimeoutsRef = useRef(new Map<string, number>());
  const postGithubSyncRefreshTimeoutsRef = useRef<number[]>([]);
  const demoStatusTimeoutRef = useRef<number | null>(null);
  const githubOperationRegistryRef = useRef(createLatestProjectOperationRegistry());
  const githubRepositoryActivityRegistryRef = useRef(createLatestProjectOperationRegistry());
  const githubRepositoryPollRegistryRef = useRef(createLatestProjectOperationRegistry());
  const githubRepositoryReconcileRegistryRef = useRef(createLatestProjectOperationRegistry());
  const projectFileImportRegistryRef = useRef(createLatestProjectOperationRegistry());
  const ignoredProjectDeltaRef = useRef<Record<string, string>>({});
  const githubLoginSessionsRef = useRef(githubLoginSessions);
  const sessionDraftsRef = useRef(initialSessionDrafts);
  const attachmentsRef = useRef(attachments);
  attachmentsRef.current = attachments;
  const localPersistenceFailureLatchRef = useRef({
    conversation: false,
    draft: false,
  });
  const projectSetupDescriptionBeforeEditRef = useRef<string | null>(null);
  const projectSetupNameBeforeEditRef = useRef<string | null>(null);
  const zoomScaleRef = useRef(zoomScale);
  const mainViewRef = useRef<MainView>(mainView);
  const projectDocumentExtensions = capabilities?.project_documents.extensions ?? [];
  const queryAttachmentExtensions = capabilities?.query_attachments.extensions ?? [];
  const supportedDocumentLabel = capabilities
    ? formatExtensions(capabilities.project_documents.extensions)
    : "";
  const projectDocumentCapabilityLabel = capabilities
    ? `${supportedDocumentLabel} · 파일당 최대 ${formatBytesAsMiB(capabilities.project_documents.max_file_bytes)}`
    : "";
  const queryAttachmentCapabilityLabel = capabilities
    ? `${formatExtensions(queryAttachmentExtensions)} · 파일당 최대 ${formatBytesAsMiB(
        capabilities.query_attachments.max_file_bytes,
      )} · 전체 최대 ${formatBytesAsMiB(capabilities.query_attachments.max_total_bytes)}`
    : "";

  useLayoutEffect(() => {
    const root = document.documentElement;
    if (settings.theme === "system") {
      delete root.dataset.theme;
      root.style.colorScheme = "light dark";
    } else {
      root.dataset.theme = settings.theme;
      root.style.colorScheme = settings.theme;
    }
  }, [settings.theme]);

  function retryCapabilities() {
    setCapabilitiesRevision((revision) => revision + 1);
  }

  const isPrimaryProjectContext =
    mainView === "chat" ||
    mainView === "project-detail" ||
    mainView === "project-management" ||
    mainView === "project-setup";
  const canMutateSelectedProjectRef = useRef(canMutateSelectedProject);
  canMutateSelectedProjectRef.current = canMutateSelectedProject;
  const selectedProjectReadOnlyReason = !canMutateSelectedProject
    ? t("조회 권한으로 열려 있어 메시지와 파일을 보낼 수 없습니다.")
    : undefined;
  const showProjectPanel =
    Boolean(selectedProject) &&
    ((mainView === "chat" && Boolean(selectedSession)) ||
      mainView === "project-detail" ||
      mainView === "project-management");
  const visibleProjectPanelMode = showProjectPanel ? projectPanelMode : "closed";
  const activeProjectPanelTab = useMemo(
    () => projectPanelTabs.find((tab) => tab.id === activeProjectPanelTabId) ?? null,
    [activeProjectPanelTabId, projectPanelTabs],
  );
  const projectPanelView: ProjectPanelView = activeProjectPanelTab?.view ?? "menu";
  const isCurrentSessionSending =
    isSending &&
    Boolean(selectedProjectId) &&
    Boolean(selectedSessionId) &&
    pendingProjectId === selectedProjectId &&
    pendingSessionId === selectedSessionId;
  const pendingQueryProject = pendingProjectId
    ? projects.find((project) => project.id === pendingProjectId) ?? null
    : null;
  const pendingQuerySession =
    pendingQueryProject?.sessions.find((session) => session.id === pendingSessionId) ?? null;
  const showBackgroundQueryNotice = Boolean(
    isSending && pendingQueryProject && pendingQuerySession && !isCurrentSessionSending,
  );
  const activeProjectFileTab =
    activeProjectPanelTab?.view === "files" ? activeProjectPanelTab : null;
  const selectedProjectAttachments = selectedProject?.files ?? EMPTY_PROJECT_ATTACHMENTS;
  const selectedProjectFileImport = selectedProject
    ? projectFileImportsByProjectId[selectedProject.id] ?? null
    : null;
  const sortedSelectedProjectAttachments = useMemo(
    () => sortProjectSourcesByUploadedAt(selectedProjectAttachments),
    [selectedProjectAttachments],
  );
  const selectedProjectFileCount = useMemo(
    () => countProjectFileEntries(selectedProjectAttachments),
    [selectedProjectAttachments],
  );
  const selectedProjectDocumentStatusSummary = useMemo(
    () => getProjectDocumentStatusSummary(selectedProjectAttachments),
    [selectedProjectAttachments],
  );
  const selectedProjectMemoryCounts =
    selectedProject ? projectMemoryCountsByProjectId[selectedProject.id] : undefined;
  const selectedProjectMemoryItems =
    selectedProject
      ? projectMemoryItemsByProjectId[selectedProject.id] ?? EMPTY_PROJECT_MEMORY_ITEMS
      : EMPTY_PROJECT_MEMORY_ITEMS;
  const selectedProjectMemorySlotCounts =
    selectedProjectMemoryCounts ?? EMPTY_PROJECT_MEMORY_COUNTS;
  const selectedProjectSetupStatusCounts = useMemo(
    () =>
      collectFileAttachments(selectedProjectAttachments).reduce(
        (counts, attachment) => {
          if (attachment.documentStatus === "indexed") {
            counts.ready += 1;
          } else if (attachment.documentStatus === "failed" || attachment.documentStatus === "delayed") {
            counts.failed += 1;
          } else if (
            attachment.documentStatus === "uploading" ||
            attachment.documentStatus === "uploaded" ||
            attachment.documentStatus === "processing"
          ) {
            counts.processing += 1;
          }

          return counts;
        },
        { failed: 0, processing: 0, ready: 0 },
      ),
    [selectedProjectAttachments],
  );
  const selectedProjectHasDocumentInProgress =
    selectedProjectDocumentStatusSummary.inProgressCount > 0;
  const areSelectedProjectSourcesExpanded =
    selectedProject !== null && expandedProjectSourcesId === selectedProject.id;
  const selectedProjectSetupVisibleSources = useMemo(
    () =>
      areSelectedProjectSourcesExpanded
        ? sortedSelectedProjectAttachments
        : sortedSelectedProjectAttachments.slice(0, 5),
    [areSelectedProjectSourcesExpanded, sortedSelectedProjectAttachments],
  );
  const selectedProjectSetupHiddenSourceCount = Math.max(
    0,
    sortedSelectedProjectAttachments.length - selectedProjectSetupVisibleSources.length,
  );
  const selectedProjectGithubEvents = useMemo(
    () => (selectedProject ? getProjectGithubEvents(selectedProject) : []),
    [selectedProject],
  );
  const selectedProjectGithubSession = selectedProject
    ? githubLoginSessions[selectedProject.id] ?? null
    : null;
  const selectedProjectGithubRepositories = selectedProject
    ? githubRepositories[selectedProject.id] ?? []
    : [];
  const githubRepositoryQuery = selectedProject
    ? githubRepositoryQueries[selectedProject.id] ?? ""
    : "";
  const selectedGithubOperation = selectedProject
    ? githubOperationsByProjectId[selectedProject.id] ?? null
    : null;
  const isGithubAuthStarting = selectedGithubOperation?.kind === "auth-start";
  const isGithubAuthChecking = selectedGithubOperation?.kind === "auth-check";
  const isGithubRepoLoading = selectedGithubOperation?.kind === "repo-load";
  const isGithubConnecting = selectedGithubOperation?.kind === "connect";
  const isGithubSyncing = selectedGithubOperation?.kind === "sync";
  const githubConnectingRepositoryUrl = isGithubConnecting
    ? selectedGithubOperation.repositoryUrl ?? null
    : null;
  const isSelectedProjectGithubReauthPending =
    selectedProject?.githubRepository?.remoteCheckError === "session_expired" &&
    selectedProjectGithubSession?.status === "pending";
  const selectedProjectGithubPanelState: GithubPanelState =
    isSelectedProjectGithubReauthPending
      ? "authing"
      : selectedProject?.githubRepository
        ? "connected"
        : selectedProjectGithubSession?.status === "connected"
          ? "repos"
          : selectedProjectGithubSession?.status === "pending"
            ? "authing"
            : "signedout";
  const selectedProjectDelta =
    isPrimaryProjectContext &&
    selectedProject &&
    projectDeltaBanner?.projectId === selectedProject.id
      ? projectDeltaBanner
      : null;
  const selectedProjectDescription = selectedProject?.description?.trim() ?? "";
  const isSelectedProjectDefaultName = /^New Project(?: \d+)?$/.test(selectedProject?.name ?? "");
  const canOpenProjectMemory =
    serverStatus === "online" &&
    typeof selectedProject?.apiProjectId === "number" &&
    !selectedProject.serverMissing;
  const hasProjectSetupContext =
    selectedProjectFileCount > 0 ||
    selectedProjectGithubPanelState === "connected" ||
    selectedProjectDescription.length > 0;
  const isProjectBriefingDisabled =
    !canMutateSelectedProject ||
    !hasProjectSetupContext ||
    selectedProjectHasDocumentInProgress ||
    isSending;
  const shouldInertBackgroundForProjectPanel =
    showProjectPanel &&
    !isProjectPanelCollapsed &&
    !audioUploadDraft &&
    (isProjectPanelMaximized || isProjectPanelOverlay);
  useEffect(() => {
    if (!shouldInertBackgroundForProjectPanel) {
      return;
    }

    const projectPanel = document.querySelector<HTMLElement>(".project-panel");
    if (!projectPanel) {
      return;
    }
    const modalProjectPanel = projectPanel;

    function getFocusablePanelElements() {
      return Array.from(
        modalProjectPanel.querySelectorAll<HTMLElement>(FOCUSABLE_ELEMENT_SELECTOR),
      ).filter(
        (element) =>
          element.getClientRects().length > 0 &&
          element.tabIndex >= 0 &&
          !element.closest("[inert]") &&
          element.getAttribute("aria-hidden") !== "true",
      );
    }

    function focusPanelStart() {
      const firstFocusableElement = getFocusablePanelElements()[0];
      (firstFocusableElement ?? modalProjectPanel).focus();
    }

    const focusFrame = window.requestAnimationFrame(() => {
      if (document.activeElement?.closest(".project-panel")) {
        return;
      }
      focusPanelStart();
    });

    function handleModalKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key !== "Tab") {
        return;
      }

      const focusableElements = getFocusablePanelElements();
      if (focusableElements.length === 0) {
        event.preventDefault();
        modalProjectPanel.focus();
        return;
      }

      const firstFocusableElement = focusableElements[0];
      const lastFocusableElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement;

      if (
        event.shiftKey &&
        (activeElement === firstFocusableElement || !modalProjectPanel.contains(activeElement))
      ) {
        event.preventDefault();
        lastFocusableElement.focus();
        return;
      }

      if (
        !event.shiftKey &&
        (activeElement === lastFocusableElement || !modalProjectPanel.contains(activeElement))
      ) {
        event.preventDefault();
        firstFocusableElement.focus();
      }
    }

    function handleModalFocus(event: globalThis.FocusEvent) {
      if (event.target instanceof Node && !modalProjectPanel.contains(event.target)) {
        focusPanelStart();
      }
    }

    document.addEventListener("keydown", handleModalKeyDown, true);
    document.addEventListener("focusin", handleModalFocus, true);

    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", handleModalKeyDown, true);
      document.removeEventListener("focusin", handleModalFocus, true);
    };
  }, [shouldInertBackgroundForProjectPanel]);

  useEffect(() => {
    if (!openActionMenu) {
      return;
    }

    const focusFrame = window.requestAnimationFrame(() => {
      document
        .querySelector<HTMLElement>(
          '.item-action-menu [role="menuitem"]:not([aria-disabled="true"]):not(:disabled)',
        )
        ?.focus();
    });

    return () => window.cancelAnimationFrame(focusFrame);
  }, [openActionMenu]);

  useDestructiveConfirmationTimeout(pendingDeleteProjectId, () =>
    setPendingDeleteProjectId(null),
  );
  useDestructiveConfirmationTimeout(pendingDeleteSession, () =>
    setPendingDeleteSession(null),
  );
  useDestructiveConfirmationTimeout(pendingGithubDisconnectProjectId, () =>
    setPendingGithubDisconnectProjectId(null),
  );
  useDestructiveConfirmationTimeout(pendingSetupDeleteProjectFileId, () =>
    setPendingSetupDeleteProjectFileId(null),
  );

  useEffect(() => {
    if (mainView !== "settings" && mainView !== "profile" && mainView !== "members") {
      return;
    }

    const frame = window.requestAnimationFrame(() => mainViewHeadingRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [mainView]);

  useEffect(() => {
    const selector = mainViewReturnFocusSelectorRef.current;
    const selectorMatchesView =
      (mainView === "project-detail" &&
        selector?.startsWith(".project-detail")) ||
      (mainView === "project-management" &&
        selector?.startsWith(".project-management"));
    if (!selector || !selectorMatchesView) {
      return;
    }

    let isCancelled = false;
    let timeoutId: number | null = null;
    let attempts = 0;
    const focusReturningControl = () => {
      if (isCancelled) return;

      const target = document.querySelector<HTMLElement>(selector);
      if (target) {
        target.focus({ preventScroll: true });
        mainViewReturnFocusSelectorRef.current = null;
        return;
      }

      attempts += 1;
      if (attempts < 20) {
        timeoutId = window.setTimeout(focusReturningControl, 50);
      } else {
        mainViewReturnFocusSelectorRef.current = null;
      }
    };

    timeoutId = window.setTimeout(focusReturningControl, 0);
    return () => {
      isCancelled = true;
      if (timeoutId !== null) window.clearTimeout(timeoutId);
    };
  }, [mainView, selectedProjectId]);

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) {
      return;
    }

    let unlisten: (() => void) | undefined;
    let isDisposed = false;

    void listen("paim://open-settings", () => {
      const activeElement = document.activeElement;
      mainViewReturnFocusRef.current =
        activeElement instanceof HTMLElement &&
        activeElement !== document.body &&
        activeElement !== document.documentElement
          ? activeElement
          : accountMenuTriggerRef.current ?? promptTextareaRef.current;
      setIsAccountMenuOpen(false);
      setOpenActionMenu(null);
      navigateTo("settings");
    })
      .then((stopListening) => {
        if (isDisposed) {
          stopListening();
          return;
        }
        unlisten = stopListening;
      })
      .catch(() => undefined);

    return () => {
      isDisposed = true;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    const handleEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }

      if (openActionMenu) {
        setOpenActionMenu(null);
        window.requestAnimationFrame(() => actionMenuTriggerRef.current?.focus());
        return;
      }
      if (projectPanelMode === "maximized") {
        event.preventDefault();
        setProjectPanelMode("open");
        window.requestAnimationFrame(() => {
          document
            .querySelector<HTMLElement>(".project-panel-maximize-toggle")
            ?.focus({ preventScroll: true });
        });
        return;
      }
      if (isProjectPanelOverlay && projectPanelMode === "open") {
        closeProjectPanel();
        return;
      }
    };

    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [
    isProjectPanelOverlay,
    openActionMenu,
    projectPanelMode,
  ]);

  useEffect(() => {
    if (!openActionMenu) {
      return;
    }

    const closeDetachedMenu = () => setOpenActionMenu(null);
    window.addEventListener("resize", closeDetachedMenu);
    window.addEventListener("scroll", closeDetachedMenu, true);
    return () => {
      window.removeEventListener("resize", closeDetachedMenu);
      window.removeEventListener("scroll", closeDetachedMenu, true);
    };
  }, [openActionMenu]);

  useEffect(() => {
    if (isSidebarResizing && openActionMenu) {
      setOpenActionMenu(null);
    }
  }, [isSidebarResizing, openActionMenu]);

  useEffect(() => {
    if ((isSidebarResizing || shouldInertBackgroundForProjectPanel) && isAccountMenuOpen) {
      setIsAccountMenuOpen(false);
    }
  }, [isAccountMenuOpen, isSidebarResizing, shouldInertBackgroundForProjectPanel]);

  const visibleDemoStatus =
    demoStatus?.projectId &&
    (!isPrimaryProjectContext || demoStatus.projectId !== selectedProjectId)
      ? null
      : demoStatus;
  const rawMainDemoStatus = visibleDemoStatus?.scope === "github" ? null : visibleDemoStatus;
  const mainDemoStatus =
    serverStatus === "offline" &&
    rawMainDemoStatus?.message === "PaiM 서버에 연결할 수 없습니다 — 마지막 저장 상태를 표시 중"
      ? null
      : rawMainDemoStatus;
  const mainDemoStatusKind = mainDemoStatus?.kind ?? (mainDemoStatus?.ok ? "success" : "error");
  const noticeCount =
    Number(serverStatus === "offline") +
    Number(showBackgroundQueryNotice) +
    Number(selectedProjectDelta !== null) +
    Number(Boolean(isPrimaryProjectContext && selectedProject?.serverMissing)) +
    Number(mainDemoStatus !== null);
  const showNoticeStack = noticeCount > 0;

  useLayoutEffect(() => {
    const noticeStack = noticeStackRef.current;

    if (!showNoticeStack || !noticeStack) {
      setNoticeStackHeight(0);
      return;
    }

    const measureNoticeStack = () => {
      const nextHeight = Math.ceil(noticeStack.getBoundingClientRect().height);
      setNoticeStackHeight((currentHeight) =>
        currentHeight === nextHeight ? currentHeight : nextHeight,
      );
    };

    measureNoticeStack();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measureNoticeStack);
      return () => window.removeEventListener("resize", measureNoticeStack);
    }

    const resizeObserver = new ResizeObserver(measureNoticeStack);
    resizeObserver.observe(noticeStack);
    return () => resizeObserver.disconnect();
  }, [showNoticeStack]);

  function clearDemoStatusTimeout() {
    if (demoStatusTimeoutRef.current === null) {
      return;
    }

    window.clearTimeout(demoStatusTimeoutRef.current);
    demoStatusTimeoutRef.current = null;
  }

  function queueDemoStatusClear(delay = 3200) {
    demoStatusTimeoutRef.current = window.setTimeout(() => {
      setDemoStatusState(null);
      demoStatusTimeoutRef.current = null;
    }, delay);
  }

  function setDemoStatus(nextStatus: DemoStatus | null) {
    clearDemoStatusTimeout();
    setDemoStatusState(nextStatus);

    if (nextStatus) {
      const kind = nextStatus.kind ?? (nextStatus.ok ? "success" : "error");

      queueDemoStatusClear(
        kind === "error"
          ? 12000
          : kind === "warning"
            ? DESTRUCTIVE_CONFIRMATION_TIMEOUT_MS
            : 3200,
      );
    }
  }

  function reportLocalPersistenceResult(
    storage: "conversation" | "draft",
    didSave: boolean,
  ) {
    if (didSave) {
      localPersistenceFailureLatchRef.current[storage] = false;
      return;
    }

    if (localPersistenceFailureLatchRef.current[storage]) {
      return;
    }

    localPersistenceFailureLatchRef.current[storage] = true;
    setDemoStatus({
      kind: "warning",
      ok: false,
      message:
        storage === "conversation"
          ? "로컬 저장 공간이 부족해 최신 대화를 저장하지 못했습니다"
          : "로컬 저장 공간이 부족해 최신 초안을 저장하지 못했습니다",
      scope: "overview",
    });
  }

  function setGithubRepositoryQueryForProject(projectId: string, query: string) {
    setGithubRepositoryQueries((currentQueries) => ({
      ...currentQueries,
      [projectId]: query,
    }));
  }

  function restoreCancelledGithubRepositoryActivity(projectId: string) {
    updateGithubRepository(projectId, (repository) =>
      repository.remoteCheckStatus === "checking"
        ? {
            ...repository,
            remoteCheckAttemptedAt: repository.remoteCheckedAt ?? null,
            remoteCheckStatus: "unknown",
            remoteCheckError: null,
          }
        : repository,
    );
  }

  function cancelGithubRepositoryActivity(projectId: string) {
    cancelLatestProjectOperation(githubRepositoryActivityRegistryRef.current, projectId);
    restoreCancelledGithubRepositoryActivity(projectId);
  }

  function cancelGithubRepositoryReads(projectId: string) {
    cancelGithubRepositoryActivity(projectId);
    cancelLatestProjectOperation(githubRepositoryReconcileRegistryRef.current, projectId);
  }

  function beginGithubOperation(
    projectId: string,
    kind: GithubOperationKind,
    repositoryUrl?: string,
  ): LatestProjectOperationToken | null {
    const token = beginLatestProjectOperation(githubOperationRegistryRef.current, projectId);
    if (!token) {
      return null;
    }

    cancelGithubRepositoryReads(projectId);
    setGithubOperationsByProjectId((currentOperations) => ({
      ...currentOperations,
      [projectId]: { kind, repositoryUrl },
    }));
    return token;
  }

  function isGithubOperationCurrent(token: LatestProjectOperationToken) {
    return isLatestProjectOperationCurrent(githubOperationRegistryRef.current, token);
  }

  function finishGithubOperation(token: LatestProjectOperationToken) {
    if (!finishLatestProjectOperation(githubOperationRegistryRef.current, token)) {
      return false;
    }

    setGithubOperationsByProjectId((currentOperations) => {
      const nextOperations = { ...currentOperations };
      delete nextOperations[token.projectId];
      return nextOperations;
    });
    return true;
  }

  function cancelGithubOperation(projectId: string) {
    cancelLatestProjectOperation(githubOperationRegistryRef.current, projectId);
    cancelGithubRepositoryReads(projectId);
    setGithubOperationsByProjectId((currentOperations) => {
      if (!currentOperations[projectId]) {
        return currentOperations;
      }

      const nextOperations = { ...currentOperations };
      delete nextOperations[projectId];
      return nextOperations;
    });
  }

  function beginProjectFileImport(
    projectId: string,
    kind: ProjectFileImportState["kind"],
  ): LatestProjectOperationToken | null {
    const token = beginLatestProjectOperation(projectFileImportRegistryRef.current, projectId);
    if (!token) {
      return null;
    }

    setProjectFileImportsByProjectId((currentImports) => ({
      ...currentImports,
      [projectId]: { kind },
    }));
    return token;
  }

  function isProjectFileImportCurrent(token: LatestProjectOperationToken) {
    return isLatestProjectOperationCurrent(projectFileImportRegistryRef.current, token);
  }

  function finishProjectFileImport(token: LatestProjectOperationToken) {
    if (!finishLatestProjectOperation(projectFileImportRegistryRef.current, token)) {
      return;
    }

    setProjectFileImportsByProjectId((currentImports) => {
      const nextImports = { ...currentImports };
      delete nextImports[token.projectId];
      return nextImports;
    });
  }

  function cancelProjectFileImport(projectId: string) {
    cancelLatestProjectOperation(projectFileImportRegistryRef.current, projectId);
    setProjectFileImportsByProjectId((currentImports) => {
      if (!currentImports[projectId]) {
        return currentImports;
      }

      const nextImports = { ...currentImports };
      delete nextImports[projectId];
      return nextImports;
    });
    setDemoStatus({
      kind: "info",
      ok: true,
      message: "폴더 가져오기를 중지했습니다",
      projectId,
      scope: "overview",
    });
  }

  function updateSettings(patch: Partial<PaiMSettings>) {
    setSettingsState((currentSettings) => {
      const nextSettings = normalizePaimSettings({ ...currentSettings, ...patch });
      savePaimSettings(nextSettings);
      return nextSettings;
    });
    setIsSettingsResetConfirming(false);
  }

  function handleThemeChange(theme: ThemeSetting) {
    updateSettings({ theme });
  }

  function handleLanguageChange(language: LanguageSetting) {
    updateSettings({ language });
  }

  function handleResetAppSettings() {
    if (!isSettingsResetConfirming) {
      setIsSettingsResetConfirming(true);
      return;
    }

    // 프로젝트·대화·초안·계정·서버 범위는 사용자 데이터이므로 절대 초기화하지 않는다.
    savePaimSettings(
      normalizePaimSettings({
        serverUrl: settings.serverUrl,
      }),
    );
    [
      SIDEBAR_STORAGE_KEY,
      SIDEBAR_WIDTH_STORAGE_KEY,
      PROJECT_PANEL_COLLAPSED_STORAGE_KEY,
      PROJECT_PANEL_WIDTH_STORAGE_KEY,
      ZOOM_STORAGE_KEY,
    ].forEach((storageKey) => window.localStorage.removeItem(storageKey));
    window.location.reload();
  }

  function handleOpenReleasePage() {
    void openUrl("https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-4th-1Team/releases");
  }

  function applyProjectState(nextState: ProjectState) {
    projectsRef.current = nextState.projects;
    selectedProjectIdRef.current = nextState.selectedProjectId;
    selectedSessionIdRef.current = nextState.selectedSessionId;
    setProjects(nextState.projects);
    setSelectedProjectId(nextState.selectedProjectId);
    setSelectedSessionId(nextState.selectedSessionId);
  }

  async function fetchServerProjects() {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), SERVER_SYNC_TIMEOUT_MS);

    try {
      const health = await fetchPaimRootJson<ApiHealthResponse>("/health", {
        signal: controller.signal,
      });

      if (health.status !== "ok") {
        throw new Error("PaiM 서버 상태를 확인할 수 없습니다");
      }

      const serverProjects = await fetchPaimJson<ApiProjectResponse[]>("/projects", {
        signal: controller.signal,
      });
      return fillMissingProjectRoles(
        serverProjects,
        authUser,
        (projectId) =>
          fetchProjectMembers(projectId, {
            signal: controller.signal,
          }),
      );
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  async function completeServerProjectSetup(
    apiProjectId: number,
    mode: "chat_only",
  ) {
    return fetchPaimJson<ApiProjectSetupResponse>(
      `/projects/${apiProjectId}/setup/complete`,
      {
        method: "POST",
        body: JSON.stringify({ mode }),
      },
    );
  }

  async function reconcileLocalProjectSetup(
    serverProjects: ApiProjectResponse[],
  ) {
    return Promise.all(
      serverProjects.map(async (serverProject) => {
        const localProject = projectsRef.current.find(
          (project) => project.apiProjectId === serverProject.id,
        );
        if (
          serverProject.setup_status !== "draft" ||
          !localProject?.setupCompletedAt ||
          localProject.setupMode !== "chat_only"
        ) {
          return serverProject;
        }

        try {
          const completed = await completeServerProjectSetup(
            serverProject.id,
            "chat_only",
          );
          return {
            ...serverProject,
            ...completed,
          };
        } catch {
          // 서버 상태를 정본으로 유지한다. 실패한 로컬 완료 표시는 아래 병합에서 제거된다.
          return serverProject;
        }
      }),
    );
  }

  async function syncProjectsWithServer(showResult = false) {
    try {
      const serverProjects = await reconcileLocalProjectSetup(await fetchServerProjects());
      const nextState = createProjectState(
        mergeServerProjects(projectsRef.current, serverProjects),
        selectedProjectIdRef.current,
        selectedSessionIdRef.current,
      );

      applyProjectState(nextState);
      setServerStatus("online");

      if (showResult) {
        setDemoStatus({
          ok: true,
          message: "PaiM 서버와 다시 연결했습니다",
          scope: "overview",
        });
      }
    } catch {
      setServerStatus("offline");

      if (showResult) {
        setDemoStatus({
          ok: false,
          message: "PaiM 서버에 연결할 수 없습니다",
          scope: "overview",
        });
      }
    }
  }

  function applyZoomScale(scale: number) {
    const nextScale = clampZoomScale(scale);
    zoomScaleRef.current = nextScale;
    setZoomScaleState(nextScale);
    window.localStorage.setItem(ZOOM_STORAGE_KEY, String(nextScale));
    applyPageZoomLayoutScale(nextScale);
    if ("__TAURI_INTERNALS__" in window) {
      void getCurrentWebview().setZoom(nextScale).catch(() => undefined);
    }
  }

  function projectHasRole(project: ProjectWorkspace, minimumRole: ProjectRole) {
    if (!authUser) {
      return true;
    }
    if (typeof project.apiProjectId !== "number") {
      return true;
    }

    const latestProject =
      projectsRef.current.find((candidate) => candidate.id === project.id) ?? project;
    return canRole(latestProject.currentUserRole, minimumRole);
  }

  function shouldSkipProjectPermission(
    project: ProjectWorkspace,
    scope: DemoStatus["scope"] = "overview",
    minimumRole: ProjectRole = "member",
  ) {
    if (projectHasRole(project, minimumRole)) {
      return false;
    }

    setDemoStatus({
      ok: false,
      message:
        minimumRole === "owner"
          ? "이 작업은 프로젝트 Owner만 할 수 있습니다"
          : "이 작업은 프로젝트 Member 이상만 할 수 있습니다",
      scope,
    });
    return true;
  }

  function shouldSkipProjectMutation(
    project: ProjectWorkspace,
    scope: DemoStatus["scope"] = "overview",
    minimumRole: ProjectRole = "member",
  ) {
    if (shouldSkipProjectPermission(project, scope, minimumRole)) {
      return true;
    }

    return serverStatus !== "online";
  }

  function isGithubSessionExpiredError(error: unknown) {
    return (
      isPaimApiError(error) &&
      (error.code === "SESSION_EXPIRED" || error.status === 401 || error.status === 410)
    );
  }

  function handleGithubRemoteSessionExpired(projectId: string) {
    setGithubLoginSessions((currentSessions) => {
      const nextSessions = { ...currentSessions };
      delete nextSessions[projectId];
      return nextSessions;
    });
    setGithubRepositories((currentRepositories) => {
      const nextRepositories = { ...currentRepositories };
      delete nextRepositories[projectId];
      return nextRepositories;
    });
    setPendingGithubDisconnectProjectId((currentProjectId) =>
      currentProjectId === projectId ? null : currentProjectId,
    );
    setGithubRepositoryQueryForProject(projectId, "");
  }

  // GitHub App state가 만료되어도 이미 연결된 repo와 검색 인덱스는 유지한다.
  function handleGithubSessionExpired(projectId: string) {
    const repository = projectsRef.current.find(
      (project) => project.id === projectId,
    )?.githubRepository;
    cancelGithubOperation(projectId);
    if (repository?.authProvider === "github_app") {
      updateGithubRepository(projectId, (currentRepository) => ({
        ...currentRepository,
        remoteCheckStatus: "error",
        remoteCheckError: "session_expired",
        remoteCheckAttemptedAt: Date.now(),
      }));
      handleGithubRemoteSessionExpired(projectId);
      setDemoStatus({
        ok: false,
        message: "GitHub 연결이 만료되었습니다. 다시 인증해 주세요",
        projectId,
        scope: "github",
      });
      return;
    }

    setGithubLoginSessions((currentSessions) => {
      const nextSessions = { ...currentSessions };
      delete nextSessions[projectId];
      return nextSessions;
    });
    setGithubRepositories((currentRepositories) => {
      const nextRepositories = { ...currentRepositories };
      delete nextRepositories[projectId];
      return nextRepositories;
    });
    updateProject(projectId, (project) =>
      project.githubRepository?.authProvider === "github_app"
        ? {
            ...project,
            githubConnected: false,
            githubEvents: undefined,
            githubRepository: undefined,
          }
        : project,
    );
    setPendingGithubDisconnectProjectId((currentProjectId) =>
      currentProjectId === projectId ? null : currentProjectId,
    );
    setGithubRepositoryQueryForProject(projectId, "");
    setDemoStatus({
      ok: false,
      message: "GitHub 연결이 만료되었습니다. 다시 연결해 주세요",
      projectId,
      scope: "github",
    });
  }

  const filteredSelectedProjectGithubRepositories = useMemo(() => {
    const query = githubRepositoryQuery.trim().toLowerCase();

    if (!query) {
      return selectedProjectGithubRepositories;
    }

    return selectedProjectGithubRepositories.filter((repository) =>
      `${repository.fullName} ${repository.name}`.toLowerCase().includes(query),
    );
  }, [githubRepositoryQuery, selectedProjectGithubRepositories]);
  const actionMenuProject = openActionMenu
    ? projects.find((project) => project.id === openActionMenu.projectId) ?? null
    : null;
  const actionMenuSession = openActionMenu
    ? actionMenuProject?.sessions.find((session) => session.id === openActionMenu.sessionId) ??
      null
    : null;
  const canMutateActionMenuProject = actionMenuProject
    ? !authUser || typeof actionMenuProject.apiProjectId !== "number"
      ? true
      : projectHasRole(actionMenuProject, "member")
    : false;
  const isActionMenuProjectQueryPending =
    isSending && pendingProjectId === actionMenuProject?.id;
  const isActionMenuSessionQueryPending =
    isActionMenuProjectQueryPending && pendingSessionId === actionMenuSession?.id;
  const accountDisplayName = getAccountDisplayName(authUser);
  const accountEmail = authUser?.email?.trim() || t("오프라인 작업공간");
  const appShellStyle = {
    "--sidebar-width": `${
      isSidebarCollapsedForLayout ? COLLAPSED_SIDEBAR_WIDTH : sidebarWidth
    }px`,
    "--project-panel-width": `${projectPanelWidth}px`,
    "--project-panel-column-width": `${
      visibleProjectPanelMode === "open" && !isProjectPanelOverlay ? projectPanelWidth : 0
    }px`,
    "--project-panel-header-offset": `${
      visibleProjectPanelMode === "closed" ? PANEL_RAIL_WIDTH : projectPanelWidth
    }px`,
    "--project-file-tree-width": `${
      isProjectFileTreeCollapsed ? PANEL_RAIL_WIDTH : projectFileTreeWidth
    }px`,
  } as CSSProperties;

  useEffect(() => {
    const tabStrip = projectPanelTabsRef.current;

    if (!tabStrip || projectPanelView === "menu" || isProjectPanelCollapsed) {
      setProjectPanelTabScrollState({
        canScrollEnd: false,
        canScrollStart: false,
      });
      return;
    }

    const tabStripElement = tabStrip;

    function syncTabScrollState() {
      const maxScrollLeft = tabStripElement.scrollWidth - tabStripElement.clientWidth;
      const nextState = {
        canScrollEnd: maxScrollLeft - tabStripElement.scrollLeft > 1,
        canScrollStart: tabStripElement.scrollLeft > 1,
      };

      setProjectPanelTabScrollState((currentState) =>
        currentState.canScrollEnd === nextState.canScrollEnd &&
        currentState.canScrollStart === nextState.canScrollStart
          ? currentState
          : nextState,
      );
    }

    syncTabScrollState();

    const resizeObserver = new ResizeObserver(syncTabScrollState);
    resizeObserver.observe(tabStripElement);
    tabStripElement.addEventListener("scroll", syncTabScrollState, { passive: true });
    window.addEventListener("resize", syncTabScrollState);

    return () => {
      resizeObserver.disconnect();
      tabStripElement.removeEventListener("scroll", syncTabScrollState);
      window.removeEventListener("resize", syncTabScrollState);
    };
  }, [
    activeProjectPanelTabId,
    isProjectPanelCollapsed,
    isProjectPanelMaximized,
    projectPanelTabs.length,
    projectPanelView,
    projectPanelWidth,
  ]);

  useEffect(() => {
    setCapabilities(null);
    setCapabilitiesError("");

    if (serverStatus !== "online") {
      setCapabilitiesError("서버 연결 후 지원 파일 정보를 불러올 수 있습니다");
      return;
    }

    const controller = new AbortController();
    void fetchPaimCapabilities(controller.signal)
      .then((response) => {
        if (
          response.schema_version !== 1 ||
          response.project_documents.extensions.length === 0 ||
          response.query_attachments.extensions.length === 0
        ) {
          throw new Error("지원 파일 정보 응답이 올바르지 않습니다");
        }
        setCapabilities(response);
        setCapabilitiesError("");
      })
      .catch((error) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setCapabilitiesError(getErrorMessage(error, "지원 파일 정보를 불러올 수 없습니다"));
        }
      });

    return () => controller.abort();
  }, [authUser?.id, capabilitiesRevision, serverStatus, settings.serverUrl]);

  useEffect(() => {
    void getVersion()
      .then((version) => setAppVersion(version))
      .catch(() => setAppVersion(`개발 모드 ${packageJson.version}`));

    const controller = new AbortController();
    void fetch("https://api.github.com/repos/SKNETWORKS-FAMILY-AICAMP/SKN30-4th-1Team/releases/latest", {
      signal: controller.signal,
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: { tag_name?: unknown } | null) => {
        if (typeof payload?.tag_name === "string") {
          setLatestReleaseTag(payload.tag_name);
        }
      })
      .catch(() => {});

    return () => controller.abort();
  }, []);

  useLayoutEffect(() => {
    githubLoginSessionsRef.current = githubLoginSessions;
  }, [githubLoginSessions]);

  useLayoutEffect(() => {
    mainViewRef.current = mainView;
  }, [mainView]);

  useEffect(() => {
    if (
      mainView !== "project-management" ||
      !selectedProject ||
      isSelectedProjectOwner
    ) {
      return;
    }

    closeProjectPanel();
    openProjectDetail();
  }, [isSelectedProjectOwner, mainView, selectedProject]);

  useEffect(() => {
    const apiProjectId = selectedProject?.apiProjectId;
    if (
      (!isPrimaryProjectContext && mainView !== "members") ||
      !didSyncProjectsRef.current ||
      !authUser ||
      !selectedProject ||
      typeof apiProjectId !== "number" ||
      serverStatus !== "online"
    ) {
      return;
    }

    const currentAuthUser = authUser;
    const selectedApiProjectId = apiProjectId;
    const selectedLocalProjectId: string = selectedProject.id;
    let disposed = false;
    let retryTimeoutId: number | null = null;

    async function loadProjectRole(attempt: number) {
      try {
        const members = await fetchProjectMembers(selectedApiProjectId);
        if (!disposed) {
          const role = getCurrentProjectMember(members, currentAuthUser)?.role ?? null;
          updateProject(selectedLocalProjectId, (project) => ({
            ...project,
            currentUserRole: role,
          }));
        }
      } catch {
        if (disposed) {
          return;
        }

        const retryDelay = PROJECT_ROLE_RETRY_DELAYS_MS[attempt];
        if (retryDelay !== undefined) {
          retryTimeoutId = window.setTimeout(
            () => void loadProjectRole(attempt + 1),
            retryDelay,
          );
          return;
        }

        // A transient members request must not erase the role already supplied by
        // the canonical project response. Backend authorization remains the final
        // authority for every mutation.
      }
    }

    void loadProjectRole(0);

    return () => {
      disposed = true;
      if (retryTimeoutId !== null) {
        window.clearTimeout(retryTimeoutId);
      }
    };
  }, [
    authUser,
    isPrimaryProjectContext,
    mainView,
    selectedProject?.apiProjectId,
    selectedProject?.currentUserRole,
    selectedProject?.id,
    serverStatus,
  ]);

  useEffect(() => {
    if (didSyncProjectsRef.current) {
      return;
    }

    didSyncProjectsRef.current = true;
    void syncProjectsWithServer();
  }, []);

  useEffect(() => {
    if (
      !isPrimaryProjectContext ||
      serverStatus !== "online" ||
      !selectedProject ||
      selectedProject.serverMissing ||
      typeof selectedProject.apiProjectId !== "number"
    ) {
      return;
    }

    void syncProjectDocuments(selectedProject.id, selectedProject.apiProjectId);
  }, [
    selectedProject?.apiProjectId,
    selectedProject?.id,
    selectedProject?.serverMissing,
    isPrimaryProjectContext,
    serverStatus,
  ]);

  useEffect(() => {
    if (
      !isPrimaryProjectContext ||
      serverStatus !== "online" ||
      !selectedProject ||
      selectedProject.serverMissing ||
      typeof selectedProject.apiProjectId !== "number"
    ) {
      return;
    }

    void refreshProjectMemoryCounts(selectedProject.id, selectedProject.apiProjectId);
  }, [
    postSyncRefreshRevision,
    isPrimaryProjectContext,
    selectedProject?.apiProjectId,
    selectedProject?.id,
    selectedProject?.serverMissing,
    selectedProjectDocumentStatusSummary.incompleteCount,
    selectedProjectDocumentStatusSummary.terminalCount,
    selectedProjectDocumentStatusSummary.totalCount,
    serverStatus,
  ]);

  useEffect(() => {
    if (
      !isPrimaryProjectContext ||
      serverStatus !== "online" ||
      !selectedProject ||
      selectedProject.serverMissing ||
      typeof selectedProject.apiProjectId !== "number"
    ) {
      return;
    }

    void syncProjectRepositories(selectedProject.id, selectedProject.apiProjectId);
  }, [
    isPrimaryProjectContext,
    selectedProject?.apiProjectId,
    selectedProject?.id,
    selectedProject?.serverMissing,
    serverStatus,
  ]);

  useEffect(() => {
    if (
      !isPrimaryProjectContext ||
      !selectedProject ||
      selectedProject.serverMissing ||
      typeof selectedProject.apiProjectId !== "number"
    ) {
      setProjectDeltaBanner(null);
      return;
    }

    if (serverStatus !== "online") {
      return;
    }

    if (!selectedProject.lastSeenAt) {
      markProjectSeen(selectedProject.id);
      setProjectDeltaBanner(null);
      return;
    }

    let isDisposed = false;
    const projectId = selectedProject.id;
    const apiProjectId = selectedProject.apiProjectId;
    const since = selectedProject.lastSeenAt;

    if (ignoredProjectDeltaRef.current[projectId] === since) {
      setProjectDeltaBanner(null);
      return;
    }

    void fetchProjectDelta(apiProjectId, since, settings.dueSoonDays)
      .then((delta) => {
        if (
          isDisposed ||
          selectedProjectIdRef.current !== projectId ||
          ignoredProjectDeltaRef.current[projectId] === since
        ) {
          return;
        }
        setProjectDeltaBanner(
          shouldShowProjectDelta(delta) ? { projectId, since, delta } : null,
        );
      })
      .catch(() => {
        if (!isDisposed) {
          setProjectDeltaBanner(null);
        }
      });

    return () => {
      isDisposed = true;
    };
  }, [
    isPrimaryProjectContext,
    selectedProject?.apiProjectId,
    selectedProject?.id,
    selectedProject?.lastSeenAt,
    selectedProject?.serverMissing,
    postSyncRefreshRevision,
    settings.dueSoonDays,
    serverStatus,
  ]);

  useEffect(() => {
    let didSave = false;
    try {
      window.localStorage.setItem(
        projectStorageKey,
        JSON.stringify(createStoredProjectState(projects, selectedProjectId, selectedSessionId)),
      );
      didSave = true;
    } catch {
      // Keep the in-memory conversation intact and let the user copy it elsewhere.
    }
    reportLocalPersistenceResult("conversation", didSave);
  }, [projectStorageKey, projects, selectedProjectId, selectedSessionId]);

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(isSidebarCollapsed));
  }, [isSidebarCollapsed]);

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    window.localStorage.setItem(
      PROJECT_PANEL_COLLAPSED_STORAGE_KEY,
      String(isProjectPanelCollapsed),
    );
  }, [isProjectPanelCollapsed]);

  useEffect(() => {
    window.localStorage.setItem(PROJECT_PANEL_WIDTH_STORAGE_KEY, String(projectPanelWidth));
  }, [projectPanelWidth]);

  useEffect(() => {
    applyZoomScale(zoomScaleRef.current);

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      const direction = getZoomShortcutDirection(event, isWindows);

      if (!direction) {
        return;
      }

      event.preventDefault();

      if (direction === "reset") {
        applyZoomScale(DEFAULT_ZOOM_SCALE);
        return;
      }

      applyZoomScale(
        zoomScaleRef.current + (direction === "in" ? ZOOM_STEP : -ZOOM_STEP),
      );
    }

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isWindows]);

  useEffect(() => {
    if (!isSidebarResizing) {
      return;
    }

    const originalCursor = document.body.style.cursor;
    const originalUserSelect = document.body.style.userSelect;

    function handlePointerMove(event: globalThis.PointerEvent) {
      if (event.pointerId !== sidebarResizeRef.current.pointerId) {
        return;
      }

      const deltaX = event.clientX - sidebarResizeRef.current.startX;
      setSidebarWidth(clampSidebarWidth(sidebarResizeRef.current.startWidth + deltaX));
    }

    function handlePointerEnd(event: globalThis.PointerEvent) {
      if (event.pointerId !== sidebarResizeRef.current.pointerId) {
        return;
      }

      const { pointerId, target } = sidebarResizeRef.current;
      if (pointerId !== null && target?.hasPointerCapture(pointerId)) {
        target.releasePointerCapture(pointerId);
      }
      sidebarResizeRef.current.pointerId = null;
      sidebarResizeRef.current.target = null;
      setIsSidebarResizing(false);
    }

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("pointermove", handlePointerMove);
    document.addEventListener("pointerup", handlePointerEnd);
    document.addEventListener("pointercancel", handlePointerEnd);

    return () => {
      const { pointerId, target } = sidebarResizeRef.current;
      if (pointerId !== null && target?.hasPointerCapture(pointerId)) {
        target.releasePointerCapture(pointerId);
      }
      sidebarResizeRef.current.pointerId = null;
      sidebarResizeRef.current.target = null;
      document.body.style.cursor = originalCursor;
      document.body.style.userSelect = originalUserSelect;
      document.removeEventListener("pointermove", handlePointerMove);
      document.removeEventListener("pointerup", handlePointerEnd);
      document.removeEventListener("pointercancel", handlePointerEnd);
    };
  }, [isSidebarResizing]);

  useEffect(() => {
    if (!isProjectFileTreeResizing) {
      return;
    }

    const originalCursor = document.body.style.cursor;
    const originalUserSelect = document.body.style.userSelect;

    function handlePointerMove(event: globalThis.PointerEvent) {
      if (event.pointerId !== projectFileTreeResizeRef.current.pointerId) {
        return;
      }

      const deltaX = projectFileTreeResizeRef.current.startX - event.clientX;
      setProjectFileTreeWidth(
        clampProjectFileTreeWidth(projectFileTreeResizeRef.current.startWidth + deltaX),
      );
    }

    function handlePointerEnd(event: globalThis.PointerEvent) {
      if (event.pointerId !== projectFileTreeResizeRef.current.pointerId) {
        return;
      }

      const { pointerId, target } = projectFileTreeResizeRef.current;
      if (pointerId !== null && target?.hasPointerCapture(pointerId)) {
        target.releasePointerCapture(pointerId);
      }
      projectFileTreeResizeRef.current.pointerId = null;
      projectFileTreeResizeRef.current.target = null;
      setIsProjectFileTreeResizing(false);
    }

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("pointermove", handlePointerMove);
    document.addEventListener("pointerup", handlePointerEnd);
    document.addEventListener("pointercancel", handlePointerEnd);

    return () => {
      const { pointerId, target } = projectFileTreeResizeRef.current;
      if (pointerId !== null && target?.hasPointerCapture(pointerId)) {
        target.releasePointerCapture(pointerId);
      }
      projectFileTreeResizeRef.current.pointerId = null;
      projectFileTreeResizeRef.current.target = null;
      document.body.style.cursor = originalCursor;
      document.body.style.userSelect = originalUserSelect;
      document.removeEventListener("pointermove", handlePointerMove);
      document.removeEventListener("pointerup", handlePointerEnd);
      document.removeEventListener("pointercancel", handlePointerEnd);
    };
  }, [isProjectFileTreeResizing]);

  useEffect(() => {
    if (thinkingStartedAt === null) {
      setThinkingElapsedSeconds(0);
      return;
    }

    const startedAt = thinkingStartedAt;

    function updateThinkingElapsedSeconds() {
      setThinkingElapsedSeconds(
        Math.max(0, Math.floor((Date.now() - startedAt) / 1000)),
      );
    }

    updateThinkingElapsedSeconds();
    const intervalId = window.setInterval(updateThinkingElapsedSeconds, 1000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [thinkingStartedAt]);


  useEffect(() => {
    if (!demoStatus) {
      return;
    }

    setStatusRevision((currentRevision) => currentRevision + 1);
  }, [demoStatus]);

  useEffect(() => () => clearDemoStatusTimeout(), []);

  useEffect(
    () => () => {
      for (const timeoutId of documentPollTimeoutsRef.current.values()) {
        window.clearTimeout(timeoutId);
      }
      documentPollTimeoutsRef.current.clear();
      for (const timeoutId of documentStatusHydrationTimeoutsRef.current.values()) {
        window.clearTimeout(timeoutId);
      }
      documentStatusHydrationTimeoutsRef.current.clear();
      documentStatusHydrationsRef.current.clear();
      for (const timeoutId of postDocumentProcessingSyncTimeoutsRef.current) {
        window.clearTimeout(timeoutId);
      }
      postDocumentProcessingSyncTimeoutsRef.current.clear();
      documentUploadControllersRef.current.forEach((controller) => controller.abort());
      documentUploadControllersRef.current.clear();
      if (pendingDocumentDeleteRetryTimeoutRef.current !== null) {
        window.clearTimeout(pendingDocumentDeleteRetryTimeoutRef.current);
        pendingDocumentDeleteRetryTimeoutRef.current = null;
      }
      for (const timeoutId of githubRepositoryPollTimeoutsRef.current.values()) {
        window.clearTimeout(timeoutId);
      }
      githubRepositoryPollTimeoutsRef.current.clear();
      abortLatestProjectOperations(githubOperationRegistryRef.current);
      abortLatestProjectOperations(githubRepositoryActivityRegistryRef.current);
      abortLatestProjectOperations(githubRepositoryPollRegistryRef.current);
      abortLatestProjectOperations(githubRepositoryReconcileRegistryRef.current);
      abortLatestProjectOperations(projectFileImportRegistryRef.current);
      postGithubSyncRefreshTimeoutsRef.current.forEach((timeoutId) => window.clearTimeout(timeoutId));
      postGithubSyncRefreshTimeoutsRef.current = [];
    },
    [],
  );

  useEffect(() => {
    setPendingGithubDisconnectProjectId(null);
  }, [selectedProjectId]);

  useEffect(() => {
    if (
      projectPanelView !== "github" ||
      !selectedProjectId ||
      !showProjectPanel ||
      isProjectPanelCollapsed
    ) {
      return;
    }
    if (selectedProject?.serverMissing) {
      restoreCancelledGithubRepositoryActivity(selectedProjectId);
      return;
    }

    const projectId = selectedProjectId;
    const ownedActivityControllers = new Set<AbortController>();
    const runOwnedRepositoryRefresh = (refresh: () => Promise<void>) => {
      const previousController =
        githubRepositoryActivityRegistryRef.current.controllers[projectId] ?? null;
      void refresh();
      const nextController =
        githubRepositoryActivityRegistryRef.current.controllers[projectId] ?? null;
      if (nextController && nextController !== previousController) {
        ownedActivityControllers.add(nextController);
      }
    };

    runOwnedRepositoryRefresh(() =>
      refreshGithubRepositoryActivity(projectId, { onlyIfRemoteStale: true }),
    );

    const handleWindowFocus = () => {
      runOwnedRepositoryRefresh(() => refreshGithubRepositoryHead(projectId));
    };
    window.addEventListener("focus", handleWindowFocus);

    return () => {
      window.removeEventListener("focus", handleWindowFocus);
      const currentController =
        githubRepositoryActivityRegistryRef.current.controllers[projectId] ?? null;
      if (currentController && ownedActivityControllers.has(currentController)) {
        cancelGithubRepositoryActivity(projectId);
      }
    };
  }, [
    isProjectPanelCollapsed,
    projectPanelView,
    selectedProject?.apiProjectId,
    showProjectPanel,
    selectedProject?.serverMissing,
    selectedProject?.githubRepository?.branch,
    selectedProject?.githubRepository?.commitSha,
    selectedProject?.githubRepository?.path,
    selectedProject?.githubRepository?.repoId,
    selectedProjectId,
  ]);

  useEffect(() => {
    if (audioUploadDraft && audioUploadDraft.projectId !== selectedProjectId) {
      setAudioUploadDraft(null);
      setIsAudioUploadStarting(false);
    }
  }, [audioUploadDraft, selectedProjectId]);

  useEffect(() => {
    if (serverStatus === "online" && pendingDocumentDeleteQueue.size() > 0) {
      void flushPendingDocumentDeletes(true);
    }
  }, [pendingDocumentDeleteQueue, serverStatus]);

  useEffect(() => {
    if (didHydrateAttachmentPreviewsRef.current) {
      return;
    }

    didHydrateAttachmentPreviewsRef.current = true;
    void hydrateStoredAttachmentPreviews();
  }, []);

  // 드롭 리스너는 마운트 시 1회 등록이라, 최신 첨부 핸들러를 ref로 전달해
  // 선택 프로젝트/세션이 초기 null 스냅샷에 갇히는 stale closure를 막는다.
  const appendAttachmentPathsRef = useRef<((paths: string[]) => Promise<void>) | undefined>(undefined);
  const addDroppedPathsToProjectRef = useRef<
    ((projectId: string, paths: string[]) => Promise<void>) | undefined
  >(undefined);
  appendAttachmentPathsRef.current = appendAttachmentPaths;
  addDroppedPathsToProjectRef.current = addDroppedPathsToProject;

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) {
      return;
    }

    let isDisposed = false;
    let unlistenDragDrop: (() => void) | undefined;

    // 네이티브 파일 드롭 이벤트를 기존 첨부 생성 흐름으로 연결한다.
    void getCurrentWebview()
      .onDragDropEvent((event) => {
        if (event.payload.type === "enter" || event.payload.type === "over") {
          const { x, y } = event.payload.position;
          const scale = window.devicePixelRatio || 1;
          const element = document.elementFromPoint(x / scale, y / scale);
          const dropZone = element?.closest<HTMLElement>("[data-drop-zone]")?.dataset.dropZone;
          const validDropZone =
            canMutateSelectedProjectRef.current &&
            selectedProjectIdRef.current &&
            (dropZone === "project-files" ||
              (dropZone === "prompt" &&
                (selectedSessionIdRef.current ||
                  mainViewRef.current === "project-detail")))
              ? dropZone
              : null;
          setActiveDropZone(validDropZone);
          setIsDragActive(Boolean(validDropZone));
          return;
        }

        if (event.payload.type === "leave") {
          setIsDragActive(false);
          setActiveDropZone(null);
          return;
        }

        setIsDragActive(false);
        setActiveDropZone(null);

        const { x, y } = event.payload.position;
        const scale = window.devicePixelRatio || 1;
        const element = document.elementFromPoint(x / scale, y / scale);
        const dropZone = element?.closest<HTMLElement>("[data-drop-zone]")?.dataset.dropZone;
        const selectedProjectId = selectedProjectIdRef.current;

        if (!canMutateSelectedProjectRef.current || !selectedProjectId) {
          return;
        }

        if (dropZone === "project-files") {
          void addDroppedPathsToProjectRef.current?.(selectedProjectId, event.payload.paths);
        } else if (
          dropZone === "prompt" &&
          (selectedSessionIdRef.current || mainViewRef.current === "project-detail")
        ) {
          void appendAttachmentPathsRef.current?.(event.payload.paths);
        }
      })
      .then((unlisten) => {
        if (isDisposed) {
          unlisten();
          return;
        }

        unlistenDragDrop = unlisten;
      })
      .catch(() => undefined);

    return () => {
      isDisposed = true;
      unlistenDragDrop?.();
    };
  }, []);

  useEffect(() => {
    shouldStickToChatBottomRef.current = true;
    setShowLatestMessageButton(false);
    const frame = window.requestAnimationFrame(() => {
      const scrollContainer = chatScrollRef.current;
      if (scrollContainer) {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
      }
    });

    return () => window.cancelAnimationFrame(frame);
  }, [selectedSessionId]);

  useEffect(() => {
    if (!shouldStickToChatBottomRef.current) {
      setShowLatestMessageButton(true);
      return;
    }

    const scrollContainer = chatScrollRef.current;
    if (scrollContainer) {
      scrollContainer.scrollTop = scrollContainer.scrollHeight;
    }
  }, [isCurrentSessionSending, selectedSession?.messages.length]);

  useEffect(() => {
    if (mainView === "chat" && selectedSessionId && canMutateSelectedProject) {
      focusPrompt();
    }
    // Permission hydration must not steal focus after the user has moved elsewhere.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mainView, selectedSessionId]);

  useEffect(() => {
    if (
      mainView !== "chat" ||
      !selectedSessionId ||
      !canMutateSelectedProject ||
      (document.activeElement && document.activeElement !== document.body)
    ) {
      return;
    }

    focusPrompt();
  }, [canMutateSelectedProject, mainView, selectedSessionId]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => resizePromptTextarea(promptTextareaRef.current));
    return () => window.cancelAnimationFrame(frame);
  }, [mainView, prompt, selectedSessionId]);

  useEffect(() => {
    const textarea = promptTextareaRef.current;
    const promptElement = textarea?.closest(".prompt") as HTMLElement | null;
    if (!textarea || !promptElement || typeof ResizeObserver === "undefined") {
      return;
    }

    let previousWidth = promptElement.getBoundingClientRect().width;
    const observer = new ResizeObserver(([entry]) => {
      const nextWidth = entry.contentRect.width;
      if (Math.abs(nextWidth - previousWidth) < 0.5) {
        return;
      }
      previousWidth = nextWidth;
      resizePromptTextarea(textarea);
    });
    observer.observe(promptElement);
    return () => observer.disconnect();
  }, [mainView, selectedSessionId]);

  function handleChatScroll(event: ReactUIEvent<HTMLDivElement>) {
    const scrollContainer = event.currentTarget;
    const distanceFromBottom =
      scrollContainer.scrollHeight - scrollContainer.scrollTop - scrollContainer.clientHeight;

    if (isScrollingToChatBottomRef.current) {
      if (distanceFromBottom < 2) {
        isScrollingToChatBottomRef.current = false;
      }
      shouldStickToChatBottomRef.current = true;
      setShowLatestMessageButton(false);
      return;
    }

    const isAtLatest = distanceFromBottom < 88;
    shouldStickToChatBottomRef.current = isAtLatest;
    setShowLatestMessageButton(!isAtLatest);
  }

  function interruptChatAutoScroll() {
    if (!isScrollingToChatBottomRef.current) {
      return;
    }

    isScrollingToChatBottomRef.current = false;
    const scrollContainer = chatScrollRef.current;
    if (!scrollContainer) {
      return;
    }
    const distanceFromBottom =
      scrollContainer.scrollHeight - scrollContainer.scrollTop - scrollContainer.clientHeight;
    const isAtLatest = distanceFromBottom < 88;
    shouldStickToChatBottomRef.current = isAtLatest;
    setShowLatestMessageButton(!isAtLatest);
  }

  function handleChatKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (["ArrowUp", "End", "Home", "PageDown", "PageUp", " "].includes(event.key)) {
      interruptChatAutoScroll();
    }
  }

  function handleScrollToLatest() {
    const scrollContainer = chatScrollRef.current;
    if (!scrollContainer) {
      return;
    }

    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    isScrollingToChatBottomRef.current = !prefersReducedMotion;
    scrollContainer.scrollTo({
      behavior: prefersReducedMotion ? "auto" : "smooth",
      top: scrollContainer.scrollHeight,
    });
    shouldStickToChatBottomRef.current = true;
    setShowLatestMessageButton(false);
  }

  useEffect(() => {
    setProjectPanelTabs([]);
    setActiveProjectPanelTabId(null);
    setPendingSetupDeleteProjectFileId(null);
  }, [selectedProjectId]);

  useEffect(() => {
    if (canOpenProjectMemory) {
      return;
    }

    setProjectPanelTabs((currentTabs) => {
      if (!currentTabs.some((tab) => tab.view === "memory")) {
        return currentTabs;
      }

      setActiveProjectPanelTabId((currentTabId) => {
        const currentTab = currentTabs.find((tab) => tab.id === currentTabId);

        return currentTab?.view === "memory" ? null : currentTabId;
      });

      return currentTabs.filter((tab) => tab.view !== "memory");
    });
  }, [canOpenProjectMemory]);

  function updateProjectPanelTab(
    tabId: string,
    updater: (tab: ProjectPanelTab) => ProjectPanelTab,
  ) {
    setProjectPanelTabs((currentTabs) =>
      currentTabs.map((tab) => (tab.id === tabId ? updater(tab) : tab)),
    );
  }

  function updateActiveProjectFileTab(updater: (tab: ProjectPanelTab) => ProjectPanelTab) {
    if (!activeProjectFileTab) {
      return;
    }

    updateProjectPanelTab(activeProjectFileTab.id, updater);
  }

  function setProjectFileQuery(action: SetStateAction<string>) {
    updateActiveProjectFileTab((tab) => ({
      ...tab,
      fileQuery: resolveStateAction(action, tab.fileQuery),
    }));
  }

  function setProjectFilePreviewForTab(
    tabId: string,
    action: SetStateAction<ProjectFilePreview | null>,
  ) {
    updateProjectPanelTab(tabId, (tab) => ({
      ...tab,
      filePreview: resolveStateAction(action, tab.filePreview),
    }));
  }

  function setProjectFilePreview(action: SetStateAction<ProjectFilePreview | null>) {
    updateActiveProjectFileTab((tab) => ({
      ...tab,
      filePreview: resolveStateAction(action, tab.filePreview),
    }));
  }

  function setProjectSourcesMode(action: SetStateAction<ProjectSourcesMode>) {
    updateActiveProjectFileTab((tab) => ({
      ...tab,
      projectSourcesMode: resolveStateAction(action, tab.projectSourcesMode),
    }));
  }

  function setSelectedProjectSourceId(action: SetStateAction<string | null>) {
    updateActiveProjectFileTab((tab) => ({
      ...tab,
      selectedProjectSourceId: resolveStateAction(action, tab.selectedProjectSourceId),
    }));
  }

  function updateProject(projectId: string, updater: (project: ProjectWorkspace) => ProjectWorkspace) {
    setProjects((currentProjects) => {
      const nextProjects = currentProjects.map((project) =>
        project.id === projectId ? updater(project) : project,
      );
      projectsRef.current = nextProjects;
      return nextProjects;
    });
  }

  function markProjectSeen(projectId: string) {
    const seenAt = new Date().toISOString();
    updateProject(projectId, (project) => ({
      ...project,
      lastSeenAt: seenAt,
    }));
    return seenAt;
  }

  function updateProjectAttachment(
    projectId: string,
    attachmentId: string,
    updater: (attachment: Attachment) => Attachment,
  ) {
    updateProject(projectId, (project) => ({
      ...project,
      files: updateProjectFileEntry(project.files ?? [], attachmentId, updater),
    }));
  }

  function schedulePendingDocumentDeleteFlush() {
    if (pendingDocumentDeleteRetryTimeoutRef.current !== null) {
      window.clearTimeout(pendingDocumentDeleteRetryTimeoutRef.current);
      pendingDocumentDeleteRetryTimeoutRef.current = null;
    }
    if (serverStatus === "offline") {
      return;
    }

    const nextRetryAt = pendingDocumentDeleteQueue.nextRetryAt();
    if (nextRetryAt === null) {
      return;
    }

    pendingDocumentDeleteRetryTimeoutRef.current = window.setTimeout(() => {
      pendingDocumentDeleteRetryTimeoutRef.current = null;
      void flushPendingDocumentDeletes();
    }, Math.min(Math.max(0, nextRetryAt - Date.now()), 300000));
  }

  function syncPendingDocumentDeleteResults(
    results: PendingDocumentDeleteAttemptResult[],
  ) {
    schedulePendingDocumentDeleteFlush();
    return results;
  }

  async function flushPendingDocumentDeletes(force = false) {
    if (serverStatus === "offline") {
      return [];
    }

    const results = await pendingDocumentDeleteQueue.flush({ force });
    return syncPendingDocumentDeleteResults(results);
  }

  async function enqueuePendingDocumentDelete(
    target: PendingDocumentDeleteTarget,
  ) {
    const result = await pendingDocumentDeleteQueue.enqueue(target);
    syncPendingDocumentDeleteResults([result]);
    return result.outcome === "completed";
  }

  function clearDocumentPoll(projectId: string, docId: number) {
    const pollKey = `${projectId}:${docId}`;
    const timeoutId = documentPollTimeoutsRef.current.get(pollKey);

    if (typeof timeoutId === "number") {
      window.clearTimeout(timeoutId);
    }

    documentPollTimeoutsRef.current.delete(pollKey);
  }

  function getDocumentUploadKey(projectId: string, attachmentId: string) {
    return `${projectId}:${attachmentId}`;
  }

  function hasProjectAttachment(projectId: string, attachmentId: string) {
    const project = projectsRef.current.find((currentProject) => currentProject.id === projectId);
    return Boolean(
      project &&
        collectFileAttachments(project.files ?? []).some(
          (attachment) => attachment.id === attachmentId,
        ),
    );
  }

  function cancelProjectDocumentUploads(projectId: string, attachment: Attachment) {
    collectFileAttachments([attachment]).forEach((file) => {
      documentUploadControllersRef.current
        .get(getDocumentUploadKey(projectId, file.id))
        ?.abort();
    });
  }

  function applyDocumentStatusResponse(
    projectId: string,
    attachmentId: string,
    expectedDocId: number,
    status: ApiDocumentStatusResponse,
    documentType?: string | null,
  ) {
    const documentStatus = toProjectDocumentStatus(status.status);
    const isAudioDocument = isMeetingDocument(documentType);

    updateProjectAttachment(projectId, attachmentId, (attachment) => {
      if (attachment.docId !== expectedDocId) {
        return attachment;
      }

      return {
        ...attachment,
        docId: status.doc_id,
        documentStatus,
        extracted: status.extracted ?? attachment.extracted,
        lastError: status.last_error
          ? isAudioDocument
            ? getSttFailureMessage(status.last_error)
            : status.last_error
          : documentStatus === "failed" && isAudioDocument
            ? getSttFailureMessage()
            : null,
        processingProgressDone: status.progress_done ?? null,
        processingProgressTotal: status.progress_total ?? null,
      };
    });

    return documentStatus;
  }

  function getDocumentStatusHydrationKey(projectId: string, docId: number) {
    return `${projectId}:${docId}`;
  }

  function fetchDocumentStatusOnce(apiProjectId: number, docId: number) {
    const requestKey = `${apiProjectId}:${docId}`;
    const existingRequest = documentStatusRequestsRef.current.get(requestKey);
    if (existingRequest) {
      return existingRequest;
    }

    const request = fetchPaimJson<ApiDocumentStatusResponse>(
      `/projects/${apiProjectId}/documents/${docId}/status`,
    ).finally(() => {
      if (documentStatusRequestsRef.current.get(requestKey) === request) {
        documentStatusRequestsRef.current.delete(requestKey);
      }
    });
    documentStatusRequestsRef.current.set(requestKey, request);
    return request;
  }

  function clearDocumentStatusHydration(projectId: string, docId: number) {
    const hydrationKey = getDocumentStatusHydrationKey(projectId, docId);
    const timeoutId = documentStatusHydrationTimeoutsRef.current.get(hydrationKey);
    if (typeof timeoutId === "number") {
      window.clearTimeout(timeoutId);
    }
    documentStatusHydrationTimeoutsRef.current.delete(hydrationKey);
    documentStatusHydrationsRef.current.delete(hydrationKey);
  }

  function scheduleProjectDocumentsSyncAfterProcessing(
    projectId: string,
    apiProjectId: number,
    delay: number,
  ) {
    const timeoutId = window.setTimeout(() => {
      postDocumentProcessingSyncTimeoutsRef.current.delete(timeoutId);
      void syncProjectDocuments(projectId, apiProjectId);
    }, delay);
    postDocumentProcessingSyncTimeoutsRef.current.add(timeoutId);
  }

  function scheduleProjectDocumentStatusHydration(
    projectId: string,
    apiProjectId: number,
    attachmentId: string,
    docId: number,
    documentType?: string | null,
    attempt = 0,
    delay = 0,
  ) {
    const hydrationKey = getDocumentStatusHydrationKey(projectId, docId);
    if (
      documentStatusHydrationTimeoutsRef.current.has(hydrationKey) ||
      documentStatusHydrationsRef.current.has(hydrationKey)
    ) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      documentStatusHydrationTimeoutsRef.current.delete(hydrationKey);
      void hydrateProjectDocumentStatus(
        projectId,
        apiProjectId,
        attachmentId,
        docId,
        documentType,
        attempt,
      );
    }, delay);
    documentStatusHydrationTimeoutsRef.current.set(hydrationKey, timeoutId);
  }

  async function hydrateProjectDocumentStatus(
    projectId: string,
    apiProjectId: number,
    attachmentId: string,
    docId: number,
    documentType?: string | null,
    attempt = 0,
  ) {
    const hydrationKey = getDocumentStatusHydrationKey(projectId, docId);
    if (documentStatusHydrationsRef.current.has(hydrationKey)) {
      return;
    }

    documentStatusHydrationsRef.current.add(hydrationKey);
    let retryDelay: number | null = null;

    try {
      if (!hasProjectAttachment(projectId, attachmentId)) {
        return;
      }
      const status = await fetchDocumentStatusOnce(apiProjectId, docId);
      const documentStatus = applyDocumentStatusResponse(
        projectId,
        attachmentId,
        docId,
        status,
        documentType,
      );

      if (!isProjectDocumentTerminal(documentStatus)) {
        scheduleDocumentStatusPoll(
          projectId,
          apiProjectId,
          attachmentId,
          docId,
          documentType,
        );
      }
    } catch (error) {
      if (isPaimApiError(error) && error.status === 404) {
        void syncProjectDocuments(projectId, apiProjectId);
      } else if (
        attempt < 5 &&
        (!isPaimApiError(error) ||
          error.status === 408 ||
          error.status === 425 ||
          error.status === 429 ||
          error.status >= 500)
      ) {
        retryDelay = Math.min(5000 * 2 ** attempt, 30000);
      }
    } finally {
      documentStatusHydrationsRef.current.delete(hydrationKey);
    }

    if (retryDelay !== null) {
      scheduleProjectDocumentStatusHydration(
        projectId,
        apiProjectId,
        attachmentId,
        docId,
        documentType,
        attempt + 1,
        retryDelay,
      );
    }
  }

  function scheduleDocumentStatusPoll(
    projectId: string,
    apiProjectId: number,
    attachmentId: string,
    docId: number,
    documentType?: string | null,
    startedAt = Date.now(),
    transientFailureCount = 0,
  ) {
    clearDocumentStatusHydration(projectId, docId);
    clearDocumentPoll(projectId, docId);

    const isAudioDocument = isMeetingDocument(documentType);
    const pollInterval = isAudioDocument
      ? Math.min(
          AUDIO_STATUS_POLL_INTERVAL_MS * 2 ** Math.min(transientFailureCount, 3),
          30000,
        )
      : DOCUMENT_STATUS_POLL_INTERVAL_MS;
    const pollTimeout = isAudioDocument
      ? AUDIO_STATUS_POLL_TIMEOUT_MS
      : DOCUMENT_STATUS_POLL_TIMEOUT_MS;
    const pollKey = `${projectId}:${docId}`;
    const timeoutId = window.setTimeout(async () => {
      if (!hasProjectAttachment(projectId, attachmentId)) {
        documentPollTimeoutsRef.current.delete(pollKey);
        return;
      }

      try {
        const status = await fetchDocumentStatusOnce(apiProjectId, docId);
        const documentStatus = applyDocumentStatusResponse(
          projectId,
          attachmentId,
          docId,
          status,
          documentType,
        );
        const lastError =
          isAudioDocument && status.last_error
            ? getSttFailureMessage(status.last_error)
            : status.last_error ?? null;

        if (isProjectDocumentTerminal(documentStatus)) {
          const currentAttachment = collectFileAttachments(
            projectsRef.current.find((project) => project.id === projectId)?.files ?? [],
          ).find((attachment) => attachment.id === attachmentId);
          const completedAttachment = currentAttachment
            ? {
                ...currentAttachment,
                docId: status.doc_id,
                documentStatus,
              }
            : undefined;

          if (
            isAudioDocument &&
            documentStatus === "indexed" &&
            completedAttachment
          ) {
            updateProject(projectId, (project) => ({
              ...project,
              files: removeOlderMeetingDocumentGenerations(
                project.files ?? [],
                completedAttachment,
              ),
            }));
          }

          void refreshProjectMemoryCounts(projectId, apiProjectId);
          setPostSyncRefreshRevision((currentRevision) => currentRevision + 1);
          documentPollTimeoutsRef.current.delete(pollKey);
          if (isAudioDocument && documentStatus === "indexed") {
            scheduleProjectDocumentsSyncAfterProcessing(projectId, apiProjectId, 750);
          } else {
            void syncProjectDocuments(projectId, apiProjectId);
          }

          if (isAudioDocument) {
            const extractedCount = getExtractionTotal(status.extracted);
            setDemoStatus({
              kind: documentStatus === "indexed" ? "success" : "error",
              ok: documentStatus === "indexed",
              message:
                documentStatus === "indexed"
                  ? extractedCount > 0
                    ? t("회의 음성 분석 완료 · 프로젝트 메모리 {count}개 추출", {
                        count: extractedCount,
                      })
                    : t("회의 음성 분석을 완료했습니다")
                  : t(lastError || "회의 음성을 처리하지 못했습니다"),
              projectId,
              scope: "overview",
            });
          }
          return;
        }

        if (Date.now() - startedAt >= pollTimeout) {
          updateProjectAttachment(projectId, attachmentId, (attachment) => ({
            ...attachment,
            documentStatus: "delayed",
            lastError: isAudioDocument
              ? "회의 음성 처리 지연 — 앱을 다시 열면 상태를 이어서 확인합니다"
              : "처리 지연 — 나중에 다시 확인",
          }));
          void refreshProjectMemoryCounts(projectId, apiProjectId);
          documentPollTimeoutsRef.current.delete(pollKey);
          return;
        }

        scheduleDocumentStatusPoll(
          projectId,
          apiProjectId,
          attachmentId,
          docId,
          documentType,
          startedAt,
        );
      } catch (error) {
        const hasAudioPollTimedOut =
          isAudioDocument && Date.now() - startedAt >= pollTimeout;
        if (hasAudioPollTimedOut) {
          updateProjectAttachment(projectId, attachmentId, (attachment) => ({
            ...attachment,
            documentStatus: "delayed",
            lastError: "회의 음성 처리 지연 — 상태 새로고침으로 다시 확인할 수 있습니다",
          }));
          void refreshProjectMemoryCounts(projectId, apiProjectId);
          documentPollTimeoutsRef.current.delete(pollKey);
          return;
        }

        const shouldRetryAudioPoll =
          isAudioDocument &&
          (!isPaimApiError(error) ||
            error.status === 408 ||
            error.status === 425 ||
            error.status === 429 ||
            error.status >= 500) &&
          Date.now() - startedAt < pollTimeout;

        if (shouldRetryAudioPoll) {
          updateProjectAttachment(projectId, attachmentId, (attachment) => ({
            ...attachment,
            documentStatus: "processing",
            lastError: "서버 연결을 기다린 뒤 회의 음성 상태를 다시 확인합니다",
          }));
          scheduleDocumentStatusPoll(
            projectId,
            apiProjectId,
            attachmentId,
            docId,
            documentType,
            startedAt,
            transientFailureCount + 1,
          );
          return;
        }

        updateProjectAttachment(projectId, attachmentId, (attachment) => ({
          ...attachment,
          documentStatus: "failed",
          lastError: getErrorMessage(
            error,
            isAudioDocument
              ? "회의 음성 처리 상태를 확인할 수 없습니다"
              : "문서 처리 상태를 확인할 수 없습니다",
          ),
        }));
        void refreshProjectMemoryCounts(projectId, apiProjectId);
        documentPollTimeoutsRef.current.delete(pollKey);
      }
    }, pollInterval);

    documentPollTimeoutsRef.current.set(pollKey, timeoutId);
  }

  async function handleRefreshProjectDocumentStatus(
    projectId: string,
    attachment: Attachment,
  ) {
    if (
      !isMeetingDocument(attachment.documentType) ||
      (attachment.documentStatus !== "processing" &&
        attachment.documentStatus !== "delayed") ||
      typeof attachment.docId !== "number"
    ) {
      return;
    }

    const targetProject = projectsRef.current.find((project) => project.id === projectId);
    if (!targetProject || shouldSkipProjectPermission(targetProject)) {
      return;
    }

    const refreshKey = `${projectId}:${attachment.docId}`;
    if (manualDocumentStatusRefreshesRef.current.has(refreshKey)) {
      return;
    }
    manualDocumentStatusRefreshesRef.current.add(refreshKey);
    clearDocumentStatusHydration(projectId, attachment.docId);
    clearDocumentPoll(projectId, attachment.docId);

    try {
      const apiProject = await ensureApiProject(targetProject);
      if (typeof apiProject.apiProjectId !== "number") {
        throw new Error("서버 프로젝트를 준비할 수 없습니다");
      }

      const status = await fetchDocumentStatusOnce(
        apiProject.apiProjectId,
        attachment.docId,
      );
      const documentStatus = applyDocumentStatusResponse(
        projectId,
        attachment.id,
        attachment.docId,
        status,
        attachment.documentType,
      );

      if (documentStatus === "indexed") {
        const currentAttachment = collectFileAttachments(
          projectsRef.current.find((project) => project.id === projectId)?.files ?? [],
        ).find((candidate) => candidate.id === attachment.id);
        if (currentAttachment) {
          updateProject(projectId, (project) => ({
            ...project,
            files: removeOlderMeetingDocumentGenerations(
              project.files ?? [],
              currentAttachment,
            ),
          }));
        }
        await Promise.all([
          syncProjectDocuments(projectId, apiProject.apiProjectId),
          refreshProjectMemoryCounts(projectId, apiProject.apiProjectId),
        ]);
        setPostSyncRefreshRevision((currentRevision) => currentRevision + 1);
        setDemoStatus({
          kind: "success",
          message: "회의 음성 상태와 프로젝트 메모리를 새로고침했습니다",
          ok: true,
          projectId,
          scope: "overview",
        });
      } else if (documentStatus === "failed") {
        await syncProjectDocuments(projectId, apiProject.apiProjectId);
        void refreshProjectMemoryCounts(projectId, apiProject.apiProjectId);
        setDemoStatus({
          kind: "error",
          message: getSttFailureMessage(status.last_error),
          ok: false,
          projectId,
          scope: "overview",
        });
      } else {
        scheduleDocumentStatusPoll(
          projectId,
          apiProject.apiProjectId,
          attachment.id,
          attachment.docId,
          attachment.documentType,
        );
        setDemoStatus({
          kind: "info",
          message: "회의 음성을 계속 처리하고 있습니다",
          ok: true,
          projectId,
          scope: "overview",
        });
      }
    } catch (error) {
      setDemoStatus({
        kind: "warning",
        message: getErrorMessage(error, "회의 음성 상태를 새로고침할 수 없습니다"),
        ok: false,
        projectId,
        scope: "overview",
      });
    } finally {
      manualDocumentStatusRefreshesRef.current.delete(refreshKey);
    }
  }

  async function syncProjectDocuments(projectId: string, apiProjectId: number) {
    if (serverStatus === "offline") {
      return;
    }

    await flushPendingDocumentDeletes(true);

    try {
      const documents = await fetchPaimJson<ApiDocumentListItem[]>(
        `/projects/${apiProjectId}/documents`,
      );
      const tombstonedDocumentIds = new Set(
        pendingDocumentDeleteQueue
          .list()
          .filter((entry) => entry.apiProjectId === apiProjectId)
          .map((entry) => entry.docId),
      );
      const mergedFiles = mergeServerDocumentsIntoAttachments(
        projectsRef.current.find((project) => project.id === projectId)?.files ?? [],
        documents,
        tombstonedDocumentIds,
      );

      updateProject(projectId, (project) => ({
        ...project,
        files: mergedFiles,
      }));

      collectFileAttachments(mergedFiles)
        .forEach((attachment) => {
          if (typeof attachment.docId !== "number") {
            return;
          }
          if (needsProjectDocumentStatusHydration(attachment)) {
            scheduleProjectDocumentStatusHydration(
              projectId,
              apiProjectId,
              attachment.id,
              attachment.docId,
              attachment.documentType,
            );
            return;
          }
          if (!isProjectDocumentTerminal(attachment.documentStatus)) {
            scheduleDocumentStatusPoll(
              projectId,
              apiProjectId,
              attachment.id,
              attachment.docId,
              attachment.documentType,
            );
          }
        });
    } catch (error) {
      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "서버 문서 목록을 불러올 수 없습니다"),
        scope: "overview",
      });
    }
  }

  function updateGithubRepository(
    projectId: string,
    updater: (repository: GitRepositoryInfo) => GitRepositoryInfo,
  ) {
    updateProject(projectId, (project) =>
      project.githubRepository
        ? { ...project, githubRepository: updater(project.githubRepository) }
        : project,
    );
  }

  function clearGithubRepositoryPollKey(pollKey: string) {
    const timeoutId = githubRepositoryPollTimeoutsRef.current.get(pollKey);

    if (typeof timeoutId === "number") {
      window.clearTimeout(timeoutId);
    }

    githubRepositoryPollTimeoutsRef.current.delete(pollKey);
    cancelLatestProjectOperation(githubRepositoryPollRegistryRef.current, pollKey);
  }

  function clearGithubRepositoryPoll(projectId: string, repoId: number) {
    clearGithubRepositoryPollKey(`${projectId}:${repoId}`);
  }

  function clearGithubRepositoryPollsForProject(
    projectId: string,
    preservedRepoId?: number,
  ) {
    const preservedPollKey =
      typeof preservedRepoId === "number" ? `${projectId}:${preservedRepoId}` : null;
    const pollKeys = new Set([
      ...githubRepositoryPollTimeoutsRef.current.keys(),
      ...Object.keys(githubRepositoryPollRegistryRef.current.controllers),
    ]);

    for (const pollKey of pollKeys) {
      if (
        pollKey.startsWith(`${projectId}:`) &&
        pollKey !== preservedPollKey
      ) {
        clearGithubRepositoryPollKey(pollKey);
      }
    }
  }

  function refreshAfterGithubSync(projectId: string) {
    delete ignoredProjectDeltaRef.current[projectId];
    setPostSyncRefreshRevision((currentRevision) => currentRevision + 1);

    const timeoutId = window.setTimeout(() => {
      setPostSyncRefreshRevision((currentRevision) => currentRevision + 1);
      postGithubSyncRefreshTimeoutsRef.current = postGithubSyncRefreshTimeoutsRef.current.filter(
        (currentTimeoutId) => currentTimeoutId !== timeoutId,
      );
    }, 10000);

    postGithubSyncRefreshTimeoutsRef.current.push(timeoutId);
  }

  function handleGithubSyncSettled(projectId: string, status: ApiRepositoryStatus) {
    if (status === "indexed") {
      setDemoStatus({
        ok: true,
        message: "GitHub 동기화 완료",
        projectId,
        scope: "overview",
      });
      refreshAfterGithubSync(projectId);
      void refreshGithubRepositoryActivity(projectId, { force: true });
      return;
    }

    if (status === "failed") {
      setDemoStatus({
        ok: false,
        message: "GitHub 동기화 실패",
        projectId,
        scope: "overview",
      });
    }
  }

  function scheduleGithubRepositoryStatusPoll(
    projectId: string,
    apiProjectId: number,
    repoId: number,
    startedAt = Date.now(),
  ) {
    clearGithubRepositoryPoll(projectId, repoId);

    const pollKey = `${projectId}:${repoId}`;
    const project = projectsRef.current.find((candidate) => candidate.id === projectId);
    const repository = project?.githubRepository;
    if (
      !project ||
      project.serverMissing ||
      project.apiProjectId !== apiProjectId ||
      !repository ||
      repository.repoId !== repoId
    ) {
      return;
    }

    const repositoryUrl = getGithubRepositoryUrl(repository);
    const branch = repository.branch;
    const runId = repository.syncRunId ?? null;
    const serverUrl = getPaimApiRootUrl();
    const isPollIdentityCurrent = (operation: LatestProjectOperationToken) => {
      const currentProject = projectsRef.current.find(
        (candidate) => candidate.id === projectId,
      );
      const currentRepository = currentProject?.githubRepository;

      return Boolean(
        isLatestProjectOperationCurrent(
          githubRepositoryPollRegistryRef.current,
          operation,
        ) &&
          getPaimApiRootUrl() === serverUrl &&
          currentProject &&
          !currentProject.serverMissing &&
          currentProject.apiProjectId === apiProjectId &&
          currentRepository &&
          currentRepository.repoId === repoId &&
          getGithubRepositoryUrl(currentRepository) === repositoryUrl &&
          currentRepository.branch === branch &&
          (currentRepository.syncRunId ?? null) === runId,
      );
    };

    const timeoutId = window.setTimeout(async () => {
      if (githubRepositoryPollTimeoutsRef.current.get(pollKey) !== timeoutId) {
        return;
      }
      githubRepositoryPollTimeoutsRef.current.delete(pollKey);
      const operation = replaceLatestProjectOperation(
        githubRepositoryPollRegistryRef.current,
        pollKey,
      );
      let shouldScheduleNext = false;

      try {
        if (!isPollIdentityCurrent(operation)) {
          return;
        }
        const status = await fetchPaimJson<ApiRepositoryStatusResponse>(
          `/projects/${apiProjectId}/repositories/${repoId}/status`,
          { signal: operation.controller.signal },
        );
        if (!isPollIdentityCurrent(operation)) {
          return;
        }

        updateGithubRepository(projectId, (repository) =>
          applyGithubRepositoryStatus(repository, status),
        );

        if (status.status === "indexed" || status.status === "failed") {
          handleGithubSyncSettled(projectId, status.status);
          return;
        }

        if (Date.now() - startedAt >= GITHUB_REPOSITORY_SYNC_TIMEOUT_MS) {
          updateGithubRepository(projectId, (repository) => ({
            ...repository,
            syncStatus: "delayed",
            syncStartedAt: undefined,
            lastError: "처리 지연 — 나중에 다시 확인",
          }));
          return;
        }

        shouldScheduleNext = true;
      } catch (error) {
        if (!isPollIdentityCurrent(operation)) {
          return;
        }
        if (isGithubSessionExpiredError(error)) {
          handleGithubSessionExpired(projectId);
          return;
        }

        updateGithubRepository(projectId, (repository) => ({
          ...repository,
          syncStatus: "failed",
          syncStartedAt: undefined,
          lastError: getErrorMessage(error, "GitHub repo 동기화 상태를 확인할 수 없습니다"),
        }));
        handleGithubSyncSettled(projectId, "failed");
      } finally {
        const didFinish = finishLatestProjectOperation(
          githubRepositoryPollRegistryRef.current,
          operation,
        );
        if (shouldScheduleNext && didFinish) {
          scheduleGithubRepositoryStatusPoll(projectId, apiProjectId, repoId, startedAt);
        }
      }
    }, GITHUB_REPOSITORY_SYNC_POLL_INTERVAL_MS);

    githubRepositoryPollTimeoutsRef.current.set(pollKey, timeoutId);
  }

  function resumeGithubRepositoryPollIfNeeded(projectId: string) {
    const project = projectsRef.current.find((candidate) => candidate.id === projectId);
    const repository = project?.githubRepository;
    if (
      !project ||
      project.serverMissing ||
      typeof project.apiProjectId !== "number" ||
      !repository ||
      typeof repository.repoId !== "number" ||
      repository.syncStatus !== "syncing"
    ) {
      return;
    }

    scheduleGithubRepositoryStatusPoll(
      projectId,
      project.apiProjectId,
      repository.repoId,
      repository.syncStartedAt ?? Date.now(),
    );
  }

  function isGithubRepositoryReconcileCurrent(
    operation: LatestProjectOperationToken,
    apiProjectId: number,
    serverUrl: string,
  ) {
    const project = projectsRef.current.find(
      (candidate) => candidate.id === operation.projectId,
    );

    return (
      isLatestProjectOperationCurrent(
        githubRepositoryReconcileRegistryRef.current,
        operation,
      ) &&
      getPaimApiRootUrl() === serverUrl &&
      project?.apiProjectId === apiProjectId &&
      !project.serverMissing
    );
  }

  async function syncProjectRepositories(
    projectId: string,
    apiProjectId: number,
    retryStatusNotFound = true,
  ) {
    if (serverStatus === "offline") {
      return;
    }

    const operation = replaceLatestProjectOperation(
      githubRepositoryReconcileRegistryRef.current,
      projectId,
    );
    const serverUrl = getPaimApiRootUrl();

    try {
      const repositories = await fetchPaimJson<ApiRepositoryListItem[]>(
        `/projects/${apiProjectId}/repositories`,
        { signal: operation.controller.signal },
      );
      if (!isGithubRepositoryReconcileCurrent(operation, apiProjectId, serverUrl)) {
        return;
      }
      const serverRepository = repositories[0];
      const previousRepository = projectsRef.current.find(
        (project) => project.id === projectId,
      )?.githubRepository;
      const hasSameRepositoryIdentity = Boolean(
        serverRepository &&
          previousRepository &&
          previousRepository.repoId === serverRepository.id &&
          getGithubRepositoryUrl(previousRepository) === serverRepository.repository_url &&
          previousRepository.branch === serverRepository.branch,
      );

      if (!hasSameRepositoryIdentity) {
        cancelLatestProjectOperation(
          githubRepositoryActivityRegistryRef.current,
          projectId,
        );
        clearGithubRepositoryPollsForProject(projectId);
      }

      updateProject(projectId, (project) => {
        if (project.apiProjectId !== apiProjectId || project.serverMissing) {
          return project;
        }
        if (!serverRepository) {
          return project.githubRepository?.repoId
            ? {
                ...project,
                githubConnected: false,
                githubEvents: undefined,
                githubRepository: undefined,
              }
            : project;
        }

        return {
          ...project,
          githubConnected: true,
          githubRepository: mergeGithubRepositoryInfo(project.githubRepository, serverRepository),
        };
      });

      if (!serverRepository) {
        return;
      }

      let status: ApiRepositoryStatusResponse;
      try {
        status = await fetchPaimJson<ApiRepositoryStatusResponse>(
          `/projects/${apiProjectId}/repositories/${serverRepository.id}/status`,
          { signal: operation.controller.signal },
        );
      } catch (error) {
        if (!isGithubRepositoryReconcileCurrent(operation, apiProjectId, serverUrl)) {
          return;
        }
        if (
          retryStatusNotFound &&
          isPaimApiError(error) &&
          error.status === 404
        ) {
          queueMicrotask(() => {
            void syncProjectRepositories(projectId, apiProjectId, false);
          });
          return;
        }
        throw error;
      }
      if (!isGithubRepositoryReconcileCurrent(operation, apiProjectId, serverUrl)) {
        return;
      }
      const currentRepository = projectsRef.current.find(
        (project) => project.id === projectId,
      )?.githubRepository;
      if (
        !currentRepository ||
        currentRepository.repoId !== status.repo_id ||
        getGithubRepositoryUrl(currentRepository) !== status.repository_url ||
        currentRepository.branch !== status.branch
      ) {
        return;
      }
      updateGithubRepository(projectId, (repository) =>
        applyGithubRepositoryStatus(repository, status),
      );

      if (status.status === "syncing") {
        scheduleGithubRepositoryStatusPoll(projectId, apiProjectId, serverRepository.id);
      }
    } catch (error) {
      if (!isGithubRepositoryReconcileCurrent(operation, apiProjectId, serverUrl)) {
        return;
      }
      if (isGithubSessionExpiredError(error)) {
        handleGithubSessionExpired(projectId);
        return;
      }

      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "GitHub repo 연결 정보를 불러올 수 없습니다"),
        projectId,
        scope: "github",
      });
    } finally {
      finishLatestProjectOperation(
        githubRepositoryReconcileRegistryRef.current,
        operation,
      );
    }
  }

  async function startGithubRepositorySync(
    projectId: string,
    apiProjectId: number,
    repoId: number,
    state?: string,
    expectedRepositoryUrl?: string,
  ) {
    const path = `/projects/${apiProjectId}/repositories/${repoId}/sync`;
    const init = {
      method: "POST",
      body: JSON.stringify(state ? { state } : {}),
    };
    const response = state
      ? await fetchPaimJsonPreservingSession<ApiRepositoryConnectResponse>(path, init)
      : await fetchPaimJson<ApiRepositoryConnectResponse>(path, init);

    const currentRepository = projectsRef.current.find((project) => project.id === projectId)
      ?.githubRepository;
    if (
      !currentRepository ||
      (expectedRepositoryUrl &&
        getGithubRepositoryUrl(currentRepository) !== expectedRepositoryUrl) ||
      (typeof currentRepository.repoId === "number" &&
        currentRepository.repoId !== response.repo_id)
    ) {
      return response;
    }

    updateGithubRepository(projectId, (repository) => ({
      ...repository,
      repoId: response.repo_id,
      syncStatus: response.status,
      syncRunId:
        response.status === "syncing"
          ? response.run_id ?? repository.syncRunId ?? null
          : null,
      syncStartedAt:
        response.status === "syncing"
          ? (
              !response.run_id || repository.syncRunId === response.run_id
                ? repository.syncStartedAt
                : undefined
            ) ?? Date.now()
          : undefined,
      lastError: null,
      syncWarnings: undefined,
    }));
    scheduleGithubRepositoryStatusPoll(projectId, apiProjectId, response.repo_id);

    return response;
  }

  function createQueryHistory(messages: Message[]): ApiQueryHistoryMessage[] {
    return messages
      .filter((message): message is Message & ApiQueryHistoryMessage =>
        message.role === "assistant" || message.role === "user",
      )
      .map((message) => ({
        role: message.role,
        content: message.content,
      }));
  }

  async function fetchProjectQuery(
    apiProjectId: number,
    question: string,
    {
      attachments: queryAttachments = [],
      history = [],
      intent,
      setupMode,
      signal,
      since,
    }: ProjectQueryOptions = {},
  ) {
    const body = {
      question,
      history,
      ...(queryAttachments.length > 0 ? { attachments: queryAttachments } : {}),
      ...(setupMode ? { setup_mode: setupMode } : {}),
      ...(intent ? { intent } : {}),
      ...(since ? { since } : {}),
    };

    return fetchPaimJson<ApiQueryResponse>(`/projects/${apiProjectId}/query`, {
      method: "POST",
      signal,
      body: JSON.stringify(body),
    });
  }

  async function fetchProjectDelta(apiProjectId: number, since: string, dueSoonDays: number) {
    return fetchPaimJson<ApiProjectDeltaResponse>(
      `/projects/${apiProjectId}/delta?since=${encodeURIComponent(since)}&due_within_days=${dueSoonDays}`,
    );
  }

  async function fetchProjectMemorySnapshot(apiProjectId: number) {
    const items = await fetchPaimJson<ProjectMemoryItem[]>(`/projects/${apiProjectId}/memory`);
    const counts = createEmptyProjectMemoryCounts();

    items.forEach((item) => {
      if (PROJECT_MEMORY_CATEGORIES.includes(item.category)) {
        counts[item.category] += 1;
      }
    });

    return { counts, items };
  }

  async function refreshProjectMemoryCounts(projectId: string, apiProjectId: number) {
    try {
      const { counts, items } = await fetchProjectMemorySnapshot(apiProjectId);

      setProjectMemoryCountsByProjectId((current) => ({
        ...current,
        [projectId]: counts,
      }));
      setProjectMemoryItemsByProjectId((current) => ({
        ...current,
        [projectId]: items,
      }));
    } catch {
      setProjectMemoryCountsByProjectId((current) => {
        if (current[projectId]) {
          return current;
        }

        return {
          ...current,
          [projectId]: createEmptyProjectMemoryCounts(),
        };
      });
      setProjectMemoryItemsByProjectId((current) => {
        if (current[projectId]) {
          return current;
        }

        return {
          ...current,
          [projectId]: [],
        };
      });
    }
  }

  function beginActiveQuery() {
    const previousController = activeQueryControllerRef.current;
    if (previousController) {
      userCancelledQueryControllersRef.current.add(previousController);
      previousController.abort();
    }

    const controller = new AbortController();
    activeQueryControllerRef.current = controller;
    const timeoutId = window.setTimeout(() => controller.abort(), QUERY_TIMEOUT_MS);

    return { controller, timeoutId };
  }

  function finishActiveQuery(controller: AbortController, timeoutId: number) {
    window.clearTimeout(timeoutId);
    if (activeQueryControllerRef.current === controller) {
      activeQueryControllerRef.current = null;
      return true;
    }

    return false;
  }

  function handleCancelQuery() {
    const controller = activeQueryControllerRef.current;
    if (!controller) {
      return;
    }

    userCancelledQueryControllersRef.current.add(controller);
    controller.abort();
    if (activeQueryControllerRef.current === controller) {
      activeQueryControllerRef.current = null;
      setIsSending(false);
      setPendingProjectId(null);
      setPendingSessionId(null);
      setThinkingStartedAt(null);
    }
    setDemoStatus({
      kind: "info",
      message: "응답 생성을 중지했습니다",
      ok: true,
      scope: "overview",
    });
  }

  function isUserCancelledQuery(error: unknown, controller: AbortController) {
    return (
      controller.signal.aborted &&
      userCancelledQueryControllersRef.current.has(controller) &&
      (error instanceof DOMException ? error.name === "AbortError" : true)
    );
  }

  function cancelActiveQueryForProject(projectId: string) {
    if (pendingProjectId !== projectId) {
      return;
    }

    const controller = activeQueryControllerRef.current;
    if (controller) {
      userCancelledQueryControllersRef.current.add(controller);
      controller.abort();
      activeQueryControllerRef.current = null;
    }

    setIsSending(false);
    setPendingProjectId(null);
    setPendingSessionId(null);
    setThinkingStartedAt(null);
  }

  function getQueryErrorMessage(error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return "Q&A 응답 시간이 초과되었습니다. 다시 시도해 주세요";
    }

    return getErrorMessage(error, "Q&A 응답을 가져올 수 없습니다");
  }

  async function readAudioUploadFile(draft: AudioUploadDraft) {
    if (!supportsExtension(draft.name, [...STT_SAFE_EXTENSIONS])) {
      throw new Error(
        t("지원하지 않는 회의 음성 형식입니다 · {formats}", {
          formats: formatExtensions([...STT_SAFE_EXTENSIONS]),
        }),
      );
    }

    try {
      const encoded = await invoke<string>("read_file_base64", {
        maxBytes: STT_SAFE_MAX_FILE_BYTES,
        path: draft.path,
      });
      const bytes = base64ToBytes(encoded);

      if (bytes.byteLength === 0) {
        throw new Error(t("회의 음성 파일이 비어 있습니다"));
      }
      if (bytes.byteLength > STT_SAFE_MAX_FILE_BYTES) {
        throw new Error(
          t("{name}은 {limit}를 초과해 전사할 수 없습니다", {
            limit: formatBytesAsMiB(STT_SAFE_MAX_FILE_BYTES),
            name: draft.name,
          }),
        );
      }

      return new File([bytes], draft.name, { type: "application/octet-stream" });
    } catch (error) {
      if (String(error).includes("FILE_TOO_LARGE")) {
        throw new Error(
          t("{name}은 {limit}를 초과해 전사할 수 없습니다", {
            limit: formatBytesAsMiB(STT_SAFE_MAX_FILE_BYTES),
            name: draft.name,
          }),
        );
      }
      throw error;
    }
  }

  function prepareProjectAudioUpload(projectId: string, path: string) {
    const targetProject = projectsRef.current.find((project) => project.id === projectId);
    if (!targetProject || shouldSkipProjectPermission(targetProject)) {
      return false;
    }

    const name = getFileName(path);
    if (!isSupportedAudioFileName(name)) {
      throw new Error(
        t("지원하지 않는 회의 음성 형식입니다 · {formats}", {
          formats: formatExtensions([...STT_SAFE_EXTENSIONS]),
        }),
      );
    }

    setAudioUploadDraft({
      date: getLocalISODate(),
      name,
      path,
      projectId,
    });
    return true;
  }

  async function handleOpenProjectAudio(projectId: string) {
    const targetProject = projectsRef.current.find((project) => project.id === projectId);

    if (!targetProject || shouldSkipProjectPermission(targetProject)) {
      return;
    }
    if (!canUseTauriDialog()) {
      setDemoStatus({
        ok: false,
        message: "데스크톱 앱에서 회의 음성을 업로드할 수 있습니다",
        scope: "overview",
      });
      return;
    }

    try {
      const selectedPath = await open({
        directory: false,
        filters: [{ name: t("지원 오디오"), extensions: [...STT_SAFE_EXTENSIONS] }],
        multiple: false,
        title: t("전사할 회의 음성 선택"),
      });
      const [path] = normalizeDialogPaths(selectedPath);

      if (!path) {
        return;
      }

      prepareProjectAudioUpload(projectId, path);
    } catch (error) {
      setDemoStatus({
        kind: "error",
        ok: false,
        message: getErrorMessage(error, "회의 음성 파일을 선택할 수 없습니다"),
        projectId,
        scope: "overview",
      });
    }
  }

  function closeAudioUploadDialog() {
    if (!isAudioUploadStarting) {
      setAudioUploadDraft(null);
    }
  }

  async function handleConfirmAudioUpload() {
    const draft = audioUploadDraft;
    if (!draft || (draft.date && !isISODate(draft.date))) {
      return;
    }

    const targetProject = projectsRef.current.find(
      (project) => project.id === draft.projectId,
    );
    if (!targetProject || shouldSkipProjectPermission(targetProject)) {
      return;
    }
    if (serverStatus !== "online") {
      setDemoStatus({
        kind: "warning",
        message: "서버에 다시 연결한 뒤 전사를 시작할 수 있습니다",
        ok: false,
        projectId: draft.projectId,
        scope: "overview",
      });
      return;
    }

    setIsAudioUploadStarting(true);

    try {
      const [apiProject, file] = await Promise.all([
        ensureApiProject(targetProject),
        readAudioUploadFile(draft),
      ]);
      if (typeof apiProject.apiProjectId !== "number") {
        throw new Error("서버 프로젝트를 준비할 수 없습니다");
      }

      const entry: Attachment = {
        id: createId("project-audio"),
        name: draft.name,
        path: draft.path,
        kind: "file",
        documentStatus: "uploading",
        documentType: STT_DOCUMENT_TYPE,
        uploadedAt: Date.now(),
      };
      const uploadKey = getDocumentUploadKey(draft.projectId, entry.id);
      const controller = new AbortController();
      documentUploadControllersRef.current.set(uploadKey, controller);

      flushSync(() => {
        updateProject(draft.projectId, (project) => ({
          ...project,
          files: [entry, ...(project.files ?? [])],
        }));
      });
      if (selectedProjectIdRef.current === draft.projectId) {
        setProjectSourcesMode("library");
      }
      setAudioUploadDraft(null);
      setDemoStatus({
        kind: "info",
        ok: true,
        message: "회의 음성을 서버에 업로드하는 중입니다",
        projectId: draft.projectId,
        scope: "overview",
      });

      try {
        const formData = new FormData();
        formData.append("file", file, draft.name);
        if (draft.date) {
          formData.append("date", draft.date);
        }

        const response = await fetchPaimFormData<AudioUploadResponse>(
          `/projects/${apiProject.apiProjectId}/audio`,
          formData,
        );

        if (
          controller.signal.aborted ||
          !hasProjectAttachment(draft.projectId, entry.id)
        ) {
          const cleaned = await enqueuePendingDocumentDelete({
            apiProjectId: apiProject.apiProjectId,
            docId: response.doc_id,
          });
          if (!cleaned) {
            setDemoStatus({
              kind: "warning",
              ok: false,
              message: "취소한 회의 음성의 서버 정리를 계속 재시도합니다",
              projectId: draft.projectId,
              scope: "overview",
            });
          }
          return;
        }

        updateProjectAttachment(draft.projectId, entry.id, (attachment) => ({
          ...attachment,
          diarization: response.diarization,
          docId: response.doc_id,
          documentStatus: toProjectDocumentStatus(response.status),
          documentType: STT_DOCUMENT_TYPE,
          lastError: null,
          serverOnly: true,
          transcriptionProvider: response.provider,
        }));
        scheduleDocumentStatusPoll(
          draft.projectId,
          apiProject.apiProjectId,
          entry.id,
          response.doc_id,
          STT_DOCUMENT_TYPE,
        );
        setDemoStatus({
          kind: "success",
          ok: true,
          message: response.diarization
            ? t("회의 음성 전사를 시작했습니다 · {provider} · 화자 분리 지원", {
                provider: response.provider,
              })
            : t("회의 음성 전사를 시작했습니다 · {provider}", {
                provider: response.provider,
              }),
          projectId: draft.projectId,
          scope: "overview",
        });
      } catch (error) {
        if (!controller.signal.aborted) {
          updateProjectAttachment(draft.projectId, entry.id, (attachment) => ({
            ...attachment,
            documentStatus: "failed",
            lastError: getErrorMessage(error, "회의 음성을 업로드할 수 없습니다"),
          }));
          setDemoStatus({
            kind: "error",
            ok: false,
            message: getErrorMessage(error, "회의 음성을 업로드할 수 없습니다"),
            projectId: draft.projectId,
            scope: "overview",
          });
        }
      } finally {
        if (documentUploadControllersRef.current.get(uploadKey) === controller) {
          documentUploadControllersRef.current.delete(uploadKey);
        }
      }
    } catch (error) {
      setDemoStatus({
        kind: "error",
        ok: false,
        message: getErrorMessage(error, "회의 음성 업로드를 시작할 수 없습니다"),
        projectId: draft.projectId,
        scope: "overview",
      });
    } finally {
      setIsAudioUploadStarting(false);
    }
  }

  // 서버 업로드는 로컬 파일을 base64로 읽어 브라우저 FormData 파일로 감싼다.
  async function readUploadFile(entry: Attachment) {
    if (!capabilities) {
      throw new Error(capabilitiesError || "지원 파일 정보를 먼저 불러와야 합니다");
    }
    const encoded = await invoke<string>("read_file_base64", { path: entry.path });
    const bytes = base64ToBytes(encoded);
    if (bytes.byteLength > capabilities.project_documents.max_file_bytes) {
      throw new Error(
        t("{name}은 {limit}를 초과해 업로드할 수 없습니다", {
          name: entry.name,
          limit: formatBytesAsMiB(capabilities.project_documents.max_file_bytes),
        }),
      );
    }

    return new File([bytes], entry.name, { type: "application/octet-stream" });
  }

  async function readQueryAttachment(entry: Attachment): Promise<ApiQueryAttachment> {
    if (!capabilities) {
      throw new Error(capabilitiesError || "지원 파일 정보를 먼저 불러와야 합니다");
    }
    const encoded = await invoke<string>("read_file_base64", { path: entry.path });
    if (getBase64ByteLength(encoded) > capabilities.query_attachments.max_file_bytes) {
      throw new Error(
        t("{name}은 {limit}를 초과해 첨부할 수 없습니다", {
          name: entry.name,
          limit: formatBytesAsMiB(capabilities.query_attachments.max_file_bytes),
        }),
      );
    }
    return { filename: entry.name, content_base64: encoded };
  }

  async function uploadProjectDocument(
    projectId: string,
    apiProjectId: number,
    entry: Attachment,
  ) {
    if (!hasProjectAttachment(projectId, entry.id)) {
      return "cancelled" as const;
    }

    const uploadKey = getDocumentUploadKey(projectId, entry.id);
    const controller = new AbortController();
    documentUploadControllersRef.current.get(uploadKey)?.abort();
    documentUploadControllersRef.current.set(uploadKey, controller);
    updateProjectAttachment(projectId, entry.id, (attachment) => ({
      ...attachment,
      documentStatus: "uploading",
      lastError: null,
    }));

    try {
      const file = await readUploadFile(entry);
      if (controller.signal.aborted) {
        return "cancelled" as const;
      }
      const formData = new FormData();
      formData.append("file", file, entry.uploadName ?? entry.name);

      // Keep the HTTP request alive after a local cancel so we can receive doc_id and
      // issue the compensating DELETE. Aborting the fetch after a server commit would
      // lose the only cleanup handle and allow the document to reappear on next launch.
      const response = await fetchPaimFormData<ApiDocumentUploadResponse>(
        `/projects/${apiProjectId}/documents`,
        formData,
      );

      if (controller.signal.aborted) {
        const cleaned = await enqueuePendingDocumentDelete({
          apiProjectId,
          docId: response.doc_id,
        });
        if (!cleaned) {
          setDemoStatus({
            kind: "warning",
            ok: false,
            message: "취소한 업로드의 서버 정리를 계속 재시도합니다",
            projectId,
            scope: "overview",
          });
        }
        return "cancelled" as const;
      }

      const documentStatus = toProjectDocumentStatus(response.status);

      updateProjectAttachment(projectId, entry.id, (attachment) => ({
        ...attachment,
        docId: response.doc_id,
        documentStatus,
        lastError: null,
      }));

      if (!isProjectDocumentTerminal(documentStatus)) {
        scheduleDocumentStatusPoll(projectId, apiProjectId, entry.id, response.doc_id);
      } else {
        void refreshProjectMemoryCounts(projectId, apiProjectId);
        setPostSyncRefreshRevision((currentRevision) => currentRevision + 1);
      }
      return "uploaded" as const;
    } catch (error) {
      if (controller.signal.aborted) {
        return "cancelled" as const;
      }
      updateProjectAttachment(projectId, entry.id, (attachment) => ({
        ...attachment,
        documentStatus: "failed",
        lastError: getErrorMessage(error, "문서를 업로드할 수 없습니다"),
      }));
      return "failed" as const;
    } finally {
      if (documentUploadControllersRef.current.get(uploadKey) === controller) {
        documentUploadControllersRef.current.delete(uploadKey);
      }
    }
  }

  // 지원 문서만 서버로 보내고, 그 외 파일은 기존처럼 로컬 참조로 남긴다.
  async function uploadProjectDocuments(
    projectId: string,
    project: ProjectWorkspace,
    entries: Attachment[],
  ) {
    const supportedFiles = collectFileAttachments(entries).filter(
      (entry) =>
        !entry.serverOnly &&
        typeof entry.docId !== "number" &&
        supportsExtension(entry.name, projectDocumentExtensions),
    );

    if (supportedFiles.length === 0) {
      return;
    }

    if (project.serverMissing) {
      setDemoStatus({
        ok: false,
        message: "서버에서 찾을 수 없는 프로젝트에는 문서를 업로드할 수 없습니다",
        scope: "overview",
      });
      return;
    }

    if (shouldSkipProjectMutation(project, "overview")) {
      return;
    }

    try {
      const apiProject = await ensureApiProject(project);

      if (typeof apiProject.apiProjectId !== "number") {
        throw new Error("서버 프로젝트를 준비할 수 없습니다");
      }

      setDemoStatus({
        kind: "info",
        ok: true,
        message: t("지원 문서 {count}개 서버 업로드 중...", {
          count: supportedFiles.length,
        }),
        projectId,
        scope: "overview",
      });

      const uploadResults: Array<"cancelled" | "failed" | "uploaded"> = [];
      for (const entry of supportedFiles) {
        uploadResults.push(
          await uploadProjectDocument(projectId, apiProject.apiProjectId, entry),
        );
      }

      const uploadedCount = uploadResults.filter((result) => result === "uploaded").length;
      const failedCount = uploadResults.filter((result) => result === "failed").length;
      const cancelledCount = uploadResults.filter((result) => result === "cancelled").length;
      if (uploadResults.length > 0) {
        setDemoStatus({
          kind: failedCount > 0 ? "warning" : cancelledCount > 0 ? "info" : "success",
          ok: failedCount === 0,
          message: t("업로드 결과 · {done}개 완료 · {failed}개 실패 · {cancelled}개 취소", {
            cancelled: cancelledCount,
            done: uploadedCount,
            failed: failedCount,
          }),
          projectId,
          scope: "overview",
        });
      }
      void syncProjectDocuments(projectId, apiProject.apiProjectId);
    } catch (error) {
      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "문서를 서버로 업로드할 수 없습니다"),
        projectId,
        scope: "overview",
      });
    }
  }

  // FastAPI의 정수 project_id가 있어야 서버 메모리 API를 조회할 수 있다.
  async function ensureApiProject(project: ProjectWorkspace) {
    const latestProject =
      projectsRef.current.find((currentProject) => currentProject.id === project.id) ?? project;
    if (typeof latestProject.apiProjectId === "number") {
      return latestProject;
    }

    if (serverStatus === "offline") {
      throw new Error("PaiM 서버에 연결할 수 없습니다 — 마지막 저장 상태를 표시 중");
    }

    const existingPromise = apiProjectEnsurePromisesRef.current.get(project.id);
    if (existingPromise) {
      return existingPromise;
    }

    const creationPromise = (async () => {
      const createdProject = await fetchPaimJson<ApiProjectCreateResponse>("/projects", {
        method: "POST",
        body: JSON.stringify({
          description: latestProject.description?.trim() || null,
          name: latestProject.name || "New Project",
        }),
      });
      const currentProject = projectsRef.current.find(
        (candidate) => candidate.id === project.id,
      );

      if (!currentProject) {
        try {
          await fetchPaimJson<void>(`/projects/${createdProject.id}`, { method: "DELETE" });
        } catch {
          // The project may already have been removed by another request/cascade.
        }
        throw new Error("로컬에서 제거된 프로젝트의 서버 생성을 취소했습니다");
      }

      const nextProject = {
        ...currentProject,
        apiProjectId: createdProject.id,
        currentUserRole: createdProject.current_user_role ?? "owner",
        description:
          createdProject.description === undefined
            ? currentProject.description
            : createdProject.description ?? undefined,
      };

      updateProject(project.id, (candidate) => ({
        ...candidate,
        apiProjectId: createdProject.id,
        currentUserRole: createdProject.current_user_role ?? "owner",
        description:
          createdProject.description === undefined
            ? candidate.description
            : createdProject.description ?? undefined,
      }));

      return nextProject;
    })();

    apiProjectEnsurePromisesRef.current.set(project.id, creationPromise);
    try {
      return await creationPromise;
    } catch (error) {
      if (apiProjectEnsurePromisesRef.current.get(project.id) === creationPromise) {
        apiProjectEnsurePromisesRef.current.delete(project.id);
      }
      throw error;
    }
  }

  function updateSessionInProject(
    projectId: string,
    sessionId: string,
    updater: (session: ChatSession) => ChatSession,
  ) {
    updateProject(projectId, (project) => ({
      ...project,
      sessions: project.sessions.map((session) =>
        session.id === sessionId ? updater(session) : session,
      ),
    }));
  }

  // 서버 프로젝트가 있으면 이름 변경을 저장하고, 실패 시 로컬 이름을 되돌린다.
  async function syncProjectName(projectId: string, title: string, previousTitle: string) {
    if (serverStatus === "offline") {
      return;
    }

    const project = projectsRef.current.find((currentProject) => currentProject.id === projectId);

    if (
      !project ||
      project.serverMissing ||
      typeof project.apiProjectId !== "number" ||
      shouldSkipProjectPermission(project, "overview", "owner")
    ) {
      return;
    }

    try {
      await fetchPaimJson<ApiProjectResponse>(`/projects/${project.apiProjectId}`, {
        method: "PATCH",
        body: JSON.stringify({ name: title }),
      });
    } catch (error) {
      updateProject(projectId, (currentProject) => ({
        ...currentProject,
        name: currentProject.name === title ? previousTitle : currentProject.name,
        serverMissing:
          isPaimApiError(error) && error.status === 404 ? true : currentProject.serverMissing,
      }));
      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "프로젝트 이름을 서버에 저장할 수 없습니다"),
        scope: "overview",
      });
    }
  }

  async function syncProjectDescription(
    projectId: string,
    description: string,
    previousDescription: string,
  ) {
    if (serverStatus === "offline") {
      return;
    }

    const project = projectsRef.current.find((currentProject) => currentProject.id === projectId);
    if (
      !project ||
      project.serverMissing ||
      typeof project.apiProjectId !== "number" ||
      shouldSkipProjectPermission(project, "overview", "owner")
    ) {
      return;
    }

    const nextDescription = description.trim();
    try {
      const updated = await fetchPaimJson<ApiProjectResponse>(
        `/projects/${project.apiProjectId}`,
        {
          method: "PATCH",
          body: JSON.stringify({ description: nextDescription }),
        },
      );
      updateProject(projectId, (currentProject) => ({
        ...currentProject,
        description: updated.description?.trim() || undefined,
      }));
    } catch (error) {
      if (isPaimApiError(error) && error.status === 422) {
        // PR18 이전 프로젝트 API는 description PATCH를 지원하지 않는다.
        // 워크스페이스를 막지 않고 계정·서버 범위 로컬 상태로 보존한다.
        setDemoStatus({
          kind: "info",
          ok: true,
          message: "현재 서버에서는 프로젝트 설명을 이 기기에 저장합니다",
          projectId,
          scope: "overview",
        });
        return;
      }
      updateProject(projectId, (currentProject) => ({
        ...currentProject,
        description:
          currentProject.description?.trim() === nextDescription
            ? previousDescription.trim() || undefined
            : currentProject.description,
        serverMissing:
          isPaimApiError(error) && error.status === 404 ? true : currentProject.serverMissing,
      }));
      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "프로젝트 설명을 서버에 저장할 수 없습니다"),
        scope: "overview",
      });
    }
  }

  // 서버 프로젝트가 있으면 먼저 DELETE하고, 404는 이미 삭제된 상태로 본다.
  async function deleteServerProject(project: ProjectWorkspace) {
    if (typeof project.apiProjectId !== "number") {
      return true;
    }

    if (serverStatus === "offline") {
      setDemoStatus({
        ok: false,
        message: "서버에 연결되지 않아 프로젝트를 삭제할 수 없습니다",
        scope: "overview",
      });
      return false;
    }

    if (project.serverMissing) {
      return true;
    }

    try {
      await fetchPaimJson<void>(`/projects/${project.apiProjectId}`, { method: "DELETE" });
      return true;
    } catch (error) {
      if (isPaimApiError(error) && error.status === 404) {
        return true;
      }

      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "프로젝트를 서버에서 삭제할 수 없습니다"),
        scope: "overview",
      });
      return false;
    }
  }

  function handleOpenProjectPortfolio() {
    rememberCurrentDraft();
    selectedProjectIdRef.current = null;
    selectedSessionIdRef.current = null;
    setSelectedProjectId(null);
    setSelectedSessionId(null);
    navigateTo("projects");
    setOpenActionMenu(null);
    closeProjectPanel();
    resetVisibleDraft();
  }

  function handleOpenProjectDetail(projectId: string) {
    const nextProject = projects.find((project) => project.id === projectId);

    if (!nextProject) {
      return;
    }

    const nextView: MainView = isProjectSetupComplete(nextProject)
      ? "project-detail"
      : "project-setup";
    rememberCurrentDraft();
    setSelectedProjectId(nextProject.id);
    setSelectedSessionId(null);
    if (nextView === "project-detail") {
      openProjectDetail("overview");
    } else {
      navigateTo(nextView);
    }
    setOpenActionMenu(null);
    if (nextView === "project-detail") {
      showSessionDraft(nextProject.id, null);
    } else {
      resetVisibleDraft();
    }
  }

  function handleOpenProjectManagement(projectId: string, trigger?: HTMLElement) {
    const targetProject = projectsRef.current.find(
      (project) => project.id === projectId,
    );
    if (
      !targetProject ||
      shouldSkipProjectPermission(targetProject, "overview", "owner")
    ) {
      return;
    }

    mainViewReturnFocusRef.current =
      trigger ??
      (document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null);
    mainViewReturnFocusSelectorRef.current = ".project-detail-open-management";
    rememberCurrentDraft();
    setSelectedProjectId(projectId);
    setSelectedSessionId(null);
    openProjectManagement("general");
    setOpenActionMenu(null);
    closeProjectPanel();
    showSessionDraft(projectId, null);
  }

  function returnToProjectDetailFromManagement() {
    setSelectedSessionId(null);
    openProjectDetail();
    mainViewReturnFocusRef.current = null;
  }

  // 새 프로젝트는 먼저 홈에서 자료를 받기 위해 채팅 세션 없이 만든다.
  function createProjectFromName(baseName: string) {
    const nextProject = createProject(createUniqueProjectName(projects, baseName));

    rememberCurrentDraft();
    setProjects((currentProjects) => [nextProject, ...currentProjects]);
    setIsSidebarCollapsed(false);
    setIsSidebarResizing(false);
    navigateTo("project-setup");
    setSelectedProjectId(nextProject.id);
    setSelectedSessionId(null);
    setProjectPanelTabs([]);
    setActiveProjectPanelTabId(null);
    closeProjectPanel();
    resetVisibleDraft();
  }

  function closeProjectPanel() {
    setProjectPanelMode((currentMode) => {
      if (currentMode !== "closed") {
        projectPanelReopenModeRef.current = currentMode;
      }

      return "closed";
    });
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>(".project-panel-rail-toggle")?.focus();
    });
  }

  function openProjectPanel() {
    setProjectPanelMode(projectPanelReopenModeRef.current);
    window.requestAnimationFrame(() => {
      document
        .querySelector<HTMLElement>(".project-panel-inline-controls button")
        ?.focus();
    });
  }

  function handleToggleProjectPanel() {
    if (projectPanelMode === "closed") {
      openProjectPanel();
    } else {
      closeProjectPanel();
    }

    setIsProjectFileTreeResizing(false);
  }

  function handleToggleProjectPanelMaximized() {
    setProjectPanelMode((currentMode) => {
      if (currentMode === "closed") {
        return currentMode;
      }

      return currentMode === "maximized" ? "open" : "maximized";
    });
  }

  function handleToggleSidebar() {
    setIsSidebarCollapsed((current) => !current);
    setIsSidebarResizing(false);
  }

  function handleSidebarResizeStart(event: ReactPointerEvent<HTMLDivElement>) {
    if (isSidebarCollapsed || event.button !== 0) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    sidebarResizeRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: sidebarWidth,
      target: event.currentTarget,
    };
    setIsSidebarResizing(true);
  }

  function handleSidebarResizeKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.shiftKey ? 40 : 8;
    let nextWidth: number;

    switch (event.key) {
      case "ArrowLeft":
      case "ArrowDown":
        nextWidth = sidebarWidth - step;
        break;
      case "ArrowRight":
      case "ArrowUp":
        nextWidth = sidebarWidth + step;
        break;
      case "Home":
        nextWidth = MIN_SIDEBAR_WIDTH;
        break;
      case "End":
        nextWidth = MAX_SIDEBAR_WIDTH;
        break;
      default:
        return;
    }

    event.preventDefault();
    event.stopPropagation();
    setSidebarWidth(Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, nextWidth)));
  }

  function handleProjectPanelResizeKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (isProjectPanelMaximized) {
      return;
    }

    const step = event.shiftKey ? 50 : 10;
    let nextWidth: number;

    switch (event.key) {
      case "ArrowLeft":
      case "ArrowUp":
        nextWidth = projectPanelWidth + step;
        break;
      case "ArrowRight":
      case "ArrowDown":
        nextWidth = projectPanelWidth - step;
        break;
      case "Home":
        nextWidth = MIN_PROJECT_PANEL_WIDTH;
        break;
      case "End":
        nextWidth = MAX_PROJECT_PANEL_WIDTH;
        break;
      default:
        return;
    }

    event.preventDefault();
    event.stopPropagation();
    projectPanelResizable.resize(nextWidth);
  }

  function handleProjectPanelTabKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    tabIndex: number,
  ) {
    const lastIndex = projectPanelTabs.length - 1;
    let nextIndex: number;

    switch (event.key) {
      case "ArrowLeft":
      case "ArrowUp":
        nextIndex = tabIndex === 0 ? lastIndex : tabIndex - 1;
        break;
      case "ArrowRight":
      case "ArrowDown":
        nextIndex = tabIndex === lastIndex ? 0 : tabIndex + 1;
        break;
      case "Home":
        nextIndex = 0;
        break;
      case "End":
        nextIndex = lastIndex;
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        setActiveProjectPanelTabId(projectPanelTabs[tabIndex]?.id ?? null);
        return;
      default:
        return;
    }

    const nextTab = projectPanelTabs[nextIndex];
    if (!nextTab) {
      return;
    }

    event.preventDefault();
    setActiveProjectPanelTabId(nextTab.id);
    window.requestAnimationFrame(() => {
      projectPanelTabsRef.current
        ?.querySelector<HTMLElement>(`[data-tab-id="${nextTab.id}"]`)
        ?.focus();
    });
  }

  function handleProjectFileTreeResizeStart(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    projectFileTreeResizeRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: isProjectFileTreeCollapsed
        ? MIN_PROJECT_FILE_TREE_WIDTH
        : projectFileTreeWidth,
      target: event.currentTarget,
    };
    setIsProjectFileTreeCollapsed(false);
    setIsProjectFileTreeResizing(true);
  }

  async function handleCompleteSetupWithoutAnalysis(projectId: string) {
    const targetProject = projectsRef.current.find((project) => project.id === projectId);

    if (!targetProject || shouldSkipProjectPermission(targetProject)) {
      return;
    }

    let completedAt = Date.now();
    let completedMode: ProjectWorkspace["setupMode"] = "chat_only";
    if (serverStatus === "online") {
      try {
        const apiProject = await ensureApiProject(targetProject);
        if (typeof apiProject.apiProjectId !== "number") {
          throw new Error("서버 프로젝트를 준비할 수 없습니다");
        }
        const completed = await completeServerProjectSetup(
          apiProject.apiProjectId,
          "chat_only",
        );
        const parsedCompletedAt = parsePaimTimestamp(
          completed.setup_completed_at,
        );
        completedAt = Number.isFinite(parsedCompletedAt) ? parsedCompletedAt : Date.now();
        completedMode = completed.setup_mode;
      } catch (error) {
        if (!isPaimApiError(error) || error.status !== 404) {
          setDemoStatus({
            ok: false,
            message: getErrorMessage(error, "프로젝트 설정을 완료할 수 없습니다"),
            projectId,
            scope: "overview",
          });
          return;
        }
        // 구 서버는 완료 API와 setup 필드가 없으므로 로컬 완료 상태를
        // 레거시 existing 프로젝트로 유지한다.
      }
    }

    rememberCurrentDraft();
    updateProject(projectId, (project) => ({
      ...project,
      setupCompletedAt: completedAt,
      setupMode: completedMode,
    }));
    openProjectDetail("overview");
    setSelectedProjectId(projectId);
    setSelectedSessionId(null);
    closeProjectPanel();
    resetVisibleDraft();
  }

	  // 자료·GitHub 탭은 필요하면 여러 개 열 수 있지만, 메모리 편집 상태는 서버 항목과
	  // 일대일로 유지해야 하므로 기존 메모리 탭을 재사용한다.
	  function openProjectPanelTool(view: ProjectPanelToolView) {
	    if (view === "memory" && serverStatus !== "online") {
	      return;
	    }

	    if (view === "memory" && !canOpenProjectMemory) {
	      return;
	    }

	    if (view === "memory") {
	      const existingMemoryTab = projectPanelTabs.find((tab) => tab.view === "memory");
	      if (existingMemoryTab) {
	        setActiveProjectPanelTabId(existingMemoryTab.id);
	        return;
	      }
	    }

	    const nextTab = createProjectPanelTab(view);

	    setProjectPanelTabs((currentTabs) => [...currentTabs, nextTab]);
	    setActiveProjectPanelTabId(nextTab.id);
	  }

  // 탭을 닫으면 바로 왼쪽 탭을 우선 활성화하고, 남은 탭이 없으면 도구 메뉴로 포커스를 옮긴다.
  function handleCloseProjectPanelTab(tabId: string) {
    const closingIndex = projectPanelTabs.findIndex((tab) => tab.id === tabId);
    if (closingIndex < 0) {
      return;
    }

    const nextTabs = projectPanelTabs.filter((tab) => tab.id !== tabId);
    const nextActiveTab =
      activeProjectPanelTabId === tabId
        ? nextTabs[Math.max(0, closingIndex - 1)] ?? nextTabs[0] ?? null
        : nextTabs.find((tab) => tab.id === activeProjectPanelTabId) ?? nextTabs[0] ?? null;

    setProjectPanelTabs(nextTabs);
    setActiveProjectPanelTabId(nextActiveTab?.id ?? null);
    window.requestAnimationFrame(() => {
      const nextFocusTarget = nextActiveTab
        ? projectPanelTabsRef.current?.querySelector<HTMLElement>(
            `[data-tab-id="${nextActiveTab.id}"]`,
          )
        : document.querySelector<HTMLElement>(".project-panel-menu-item");
      nextFocusTarget?.focus();
    });
  }

	  // 열린 파일이 있으면 자료 탭 라벨을 파일명으로 압축해서 보여준다.
	  function getProjectPanelTabLabel(tab: ProjectPanelTab) {
	    return tab.view === "files" && tab.filePreview
	      ? tab.filePreview.name
	      : getProjectPanelTitle(tab.view);
	  }

  async function readDirectoryChildren(path: string) {
    const children = await invoke<DirectoryChildEntry[]>("read_directory_children", { path });

    return children.map(createProjectFileEntry);
  }

  async function createProjectDirectoryEntry(
    path: string,
    uploadedAt: number,
    rootPath = path,
    signal?: AbortSignal,
  ): Promise<Attachment> {
    if (signal?.aborted) {
      throw new DOMException("Project file import cancelled", "AbortError");
    }
    const children = await invoke<DirectoryChildEntry[]>("read_directory_children", { path });
    if (signal?.aborted) {
      throw new DOMException("Project file import cancelled", "AbortError");
    }
    const nextChildren = await Promise.all(
      children.map((entry) =>
        entry.kind === "directory"
          ? createProjectDirectoryEntry(entry.path, uploadedAt, rootPath, signal)
          : { ...createProjectFileEntry(entry), uploadName: getUploadName(rootPath, entry.path), uploadedAt },
      ),
    );

    return {
      id: createId("project-file"),
      name: getFileName(path),
      path,
      kind: "directory",
      children: nextChildren,
      childrenLoaded: true,
      isExpanded: true,
      uploadedAt,
    };
  }

  // 프로젝트 자료함에 단일 파일을 트리의 루트 항목으로 추가한다.
  function createProjectFileRootEntry(path: string, uploadedAt: number): Attachment {
    return {
      id: createId("project-file"),
      name: getFileName(path),
      path,
      kind: "file",
      uploadedAt,
    };
  }

  function registerProjectEntries(projectId: string, entries: Attachment[]) {
    const targetProject = projectsRef.current.find((project) => project.id === projectId);

    if (
      !targetProject ||
      entries.length === 0 ||
      shouldSkipProjectPermission(targetProject)
    ) {
      return;
    }

    // 네이티브 드롭 콜백에서는 React 상태 반영보다 업로드 비동기 흐름이 먼저 진행될 수 있다.
    // 기존에 예약된 프로젝트 갱신까지 보존하면서, 업로드 전에 새 파일 등록을 확정한다.
    flushSync(() => {
      updateProject(projectId, (project) => ({
        ...project,
        files: [...entries, ...(project.files ?? [])],
      }));
    });
    const registeredProject =
      projectsRef.current.find((project) => project.id === projectId) ?? targetProject;
    if (selectedProjectIdRef.current === projectId) {
      setProjectSourcesMode("library");
    }
    void uploadProjectDocuments(projectId, registeredProject, entries);
  }

  async function addDroppedPathsToProject(projectId: string, paths: string[]) {
    if (paths.length === 0) {
      return;
    }

    const topLevelPaths = (
      await Promise.all(
        paths.map(async (path) => {
          try {
            return {
              kind: await invoke<"directory" | "file">("path_kind", { path }),
              path,
            };
          } catch {
            return null;
          }
        }),
      )
    ).filter(
      (entry): entry is { kind: "directory" | "file"; path: string } => entry !== null,
    );
    const audioPaths = topLevelPaths
      .filter(
        (entry) =>
          entry.kind === "file" &&
          isSupportedAudioFileName(getFileName(entry.path)),
      )
      .map((entry) => entry.path);

    if (audioPaths.length > 1) {
      setDemoStatus({
        kind: "warning",
        ok: false,
        message: "회의 음성은 한 번에 하나씩 올려 주세요",
        projectId,
        scope: "overview",
      });
      return;
    }

    const generalPaths = topLevelPaths
      .filter((entry) => entry.path !== audioPaths[0])
      .map((entry) => entry.path);
    if (audioPaths.length === 1) {
      try {
        prepareProjectAudioUpload(projectId, audioPaths[0]);
      } catch (error) {
        setDemoStatus({
          kind: "error",
          ok: false,
          message: getErrorMessage(error, "회의 음성 파일을 선택할 수 없습니다"),
          projectId,
          scope: "overview",
        });
        return;
      }
    }
    if (generalPaths.length === 0) {
      return;
    }

    const operation = beginProjectFileImport(projectId, "drop");
    if (!operation) {
      return;
    }

    setDemoStatus({
      kind: "info",
      ok: true,
      message: "자료 구조를 읽는 중...",
      projectId,
      scope: "overview",
    });

    try {
      const uploadedAt = Date.now();
      const entries = (
        await Promise.all(
          generalPaths.map(async (path) => {
            try {
              const kind = await invoke<"directory" | "file">("path_kind", { path });
              if (operation.controller.signal.aborted) {
                throw new DOMException("Project file import cancelled", "AbortError");
              }

              return kind === "directory"
                ? createProjectDirectoryEntry(
                    path,
                    uploadedAt,
                    path,
                    operation.controller.signal,
                  )
                : createProjectFileRootEntry(path, uploadedAt);
            } catch {
              return null;
            }
          }),
        )
      ).filter((entry): entry is Attachment => entry !== null);

      if (!isProjectFileImportCurrent(operation)) {
        return;
      }
      if (entries.length === 0) {
        setDemoStatus({
          ok: false,
          message: "드롭한 파일이나 폴더를 등록할 수 없습니다",
          projectId,
          scope: "overview",
        });
        return;
      }

      registerProjectEntries(projectId, entries);
      const failedCount =
        paths.length - audioPaths.length - entries.length;
      if (failedCount > 0) {
        setDemoStatus({
          kind: "warning",
          ok: false,
          message: t("자료 {added}개 추가 · {failed}개 읽기 실패", {
            added: entries.length,
            failed: failedCount,
          }),
          projectId,
          scope: "overview",
        });
      }
    } finally {
      finishProjectFileImport(operation);
    }
  }

  // 프로젝트 자료함에 개별 파일을 루트 자료로 추가한다.
  async function handleOpenProjectFiles(projectId: string) {
    const targetProject = projectsRef.current.find((project) => project.id === projectId);

    if (!targetProject || shouldSkipProjectPermission(targetProject)) {
      return;
    }
    if (!capabilities) {
      setDemoStatus({
        ok: false,
        message: capabilitiesError || "지원 파일 정보를 불러오는 중입니다",
        scope: "overview",
      });
      return;
    }

    if (!canUseTauriDialog()) {
      setDemoStatus({
        ok: false,
        message: "데스크톱 앱에서 파일을 업로드할 수 있습니다",
        scope: "overview",
      });
      return;
    }

    try {
      const selectedPaths = await open({
        directory: false,
        filters: [{ name: t("지원 문서"), extensions: projectDocumentExtensions }],
        multiple: true,
        title: t("프로젝트 자료 추가"),
      });
      const paths = normalizeDialogPaths(selectedPaths);

      if (paths.length === 0) {
        return;
      }

      const uploadedAt = Date.now();
      const nextEntries = paths.map((path) => createProjectFileRootEntry(path, uploadedAt));
      registerProjectEntries(projectId, nextEntries);
    } catch {
      setDemoStatus({
        ok: false,
        message: "프로젝트 파일을 업로드할 수 없습니다",
        scope: "overview",
      });
    }
  }

  // 프로젝트 자료함은 폴더를 루트로 받아 트리로 보여준다.
  async function handleOpenProjectDirectory(projectId: string) {
    const targetProject = projectsRef.current.find((project) => project.id === projectId);

    if (!targetProject || shouldSkipProjectPermission(targetProject)) {
      return;
    }

    if (!canUseTauriDialog()) {
      setDemoStatus({
        ok: false,
        message: "데스크톱 앱에서 폴더를 업로드할 수 있습니다",
        scope: "overview",
      });
      return;
    }

    try {
      const selectedPaths = await open({
        directory: true,
        multiple: true,
        title: t("프로젝트 폴더 추가"),
      });
      const paths = normalizeDialogPaths(selectedPaths);

      if (paths.length === 0) {
        return;
      }

      const uploadedAt = Date.now();
      const operation = beginProjectFileImport(projectId, "folder");
      if (!operation) {
        return;
      }
      setDemoStatus({
        kind: "info",
        ok: true,
        message: "폴더 구조를 읽는 중...",
        projectId,
        scope: "overview",
      });

      try {
        const nextEntries = await Promise.all(
          paths.map((path) =>
            createProjectDirectoryEntry(
              path,
              uploadedAt,
              path,
              operation.controller.signal,
            ),
          ),
        );
        if (!isProjectFileImportCurrent(operation)) {
          return;
        }
        registerProjectEntries(projectId, nextEntries);
      } catch (error) {
        if (!isProjectFileImportCurrent(operation)) {
          return;
        }
        throw error;
      } finally {
        finishProjectFileImport(operation);
      }
    } catch {
      setDemoStatus({
        ok: false,
        message: "프로젝트 폴더를 업로드할 수 없습니다",
        projectId,
        scope: "overview",
      });
    }
  }

  async function handleToggleProjectFileEntry(projectId: string, entry: Attachment) {
    if (entry.kind !== "directory") {
      return;
    }

    if (entry.childrenLoaded) {
      updateProject(projectId, (project) => ({
        ...project,
        files: updateProjectFileEntry(project.files ?? [], entry.id, (currentEntry) => ({
          ...currentEntry,
          isExpanded: !currentEntry.isExpanded,
        })),
      }));
      return;
    }

    const loadingKey = `${projectId}:${entry.id}`;
    if (loadingProjectFileEntryKeys.has(loadingKey)) {
      return;
    }
    setLoadingProjectFileEntryKeys((currentKeys) => {
      const nextKeys = new Set(currentKeys);
      nextKeys.add(loadingKey);
      return nextKeys;
    });

    try {
      const children = await readDirectoryChildren(entry.path);

      updateProject(projectId, (project) => ({
        ...project,
        files: updateProjectFileEntry(project.files ?? [], entry.id, (currentEntry) => ({
          ...currentEntry,
          children,
          childrenLoaded: true,
          isExpanded: true,
        })),
      }));
    } catch {
      setDemoStatus({
        ok: false,
        message: "하위 폴더를 읽을 수 없습니다",
        projectId,
        scope: "overview",
      });
    } finally {
      setLoadingProjectFileEntryKeys((currentKeys) => {
        const nextKeys = new Set(currentKeys);
        nextKeys.delete(loadingKey);
        return nextKeys;
      });
    }
  }

  // 파일 트리에서 선택한 텍스트 파일을 왼쪽 프리뷰 영역에 읽기 전용으로 표시한다.
  async function handleSelectProjectFile(entry: Attachment) {
    if (entry.kind === "directory") {
      return;
    }
    const targetTabId = activeProjectFileTab?.id;

    if (!targetTabId) {
      return;
    }

    const nextPreview = {
      id: entry.id,
      name: entry.name,
      path: entry.path,
      content: "",
      isLoading: true,
    };

    setProjectFilePreviewForTab(targetTabId, nextPreview);

    if (entry.serverOnly) {
      setProjectFilePreviewForTab(targetTabId, {
        ...nextPreview,
        isLoading: false,
        error: t("서버 문서는 로컬 경로가 없어 미리볼 수 없습니다"),
      });
      return;
    }

    try {
      const content = await invoke<string>("read_text_file", { path: entry.path });

      setProjectFilePreviewForTab(targetTabId, (currentPreview) =>
        currentPreview?.id === entry.id
          ? { ...nextPreview, content, isLoading: false }
          : currentPreview,
      );
    } catch (error) {
      setProjectFilePreviewForTab(targetTabId, (currentPreview) =>
        currentPreview?.id === entry.id
          ? {
              ...nextPreview,
              isLoading: false,
              error: error instanceof Error ? error.message : String(error),
            }
          : currentPreview,
      );
    }
  }

  // 파일 패널에서 선택한 항목을 트리에서 제거한다.
  async function handleDeleteProjectFile(projectId: string, attachment: Attachment) {
    const targetProject = projects.find((project) => project.id === projectId);
    const linkedDocIds = Array.from(getAttachmentDocIds([attachment]));

    if (!targetProject || shouldSkipProjectPermission(targetProject)) {
      return false;
    }

    cancelProjectDocumentUploads(projectId, attachment);

    if (linkedDocIds.length > 0) {
      if (shouldSkipProjectMutation(targetProject, "overview")) {
        return false;
      }

      if (targetProject.serverMissing || typeof targetProject.apiProjectId !== "number") {
        setDemoStatus({
          ok: false,
          message: "서버 문서 삭제에 필요한 프로젝트 정보를 찾을 수 없습니다",
          scope: "overview",
        });
        return false;
      }

      for (const docId of linkedDocIds) {
        try {
          await fetchPaimJson<void>(
            `/projects/${targetProject.apiProjectId}/documents/${docId}`,
            { method: "DELETE" },
          );
        } catch (error) {
          const message = getErrorMessage(error, "서버 문서를 삭제할 수 없습니다");

          if (!/document not found/i.test(message)) {
            setDemoStatus({
              ok: false,
              message,
              scope: "overview",
            });
            return false;
          }
        }

        clearDocumentPoll(projectId, docId);
        clearDocumentStatusHydration(projectId, docId);
      }
    }

    setProjectPanelTabs((currentTabs) =>
      currentTabs.map((tab) => {
        if (tab.view !== "files") {
          return tab;
        }

        const isSelectedSource = tab.selectedProjectSourceId === attachment.id;

        return {
          ...tab,
          filePreview: tab.filePreview?.id === attachment.id ? null : tab.filePreview,
          projectSourcesMode: isSelectedSource ? "library" : tab.projectSourcesMode,
          selectedProjectSourceId: isSelectedSource ? null : tab.selectedProjectSourceId,
        };
      }),
    );

    updateProject(projectId, (project) => ({
      ...project,
      files: deleteProjectFileEntry(project.files ?? [], attachment.id),
    }));
    setPendingSetupDeleteProjectFileId(null);

    if (!targetProject.serverMissing && typeof targetProject.apiProjectId === "number") {
      void syncProjectDocuments(projectId, targetProject.apiProjectId);
      void refreshProjectMemoryCounts(projectId, targetProject.apiProjectId);
      setPostSyncRefreshRevision((currentRevision) => currentRevision + 1);
    }

    return true;
  }

  function handleRequestDeleteProjectSetupSource(projectId: string, attachment: Attachment) {
    if (pendingSetupDeleteProjectFileId !== attachment.id) {
      setPendingSetupDeleteProjectFileId(attachment.id);
      return;
    }

    void handleDeleteProjectFile(projectId, attachment);
  }

  // 자료 카드 선택은 해당 자료 하나만 트리 루트로 보여주고, 파일이면 바로 미리보기를 연다.
  function handleOpenProjectSource(source: Attachment) {
    setProjectFileQuery("");
    setSelectedProjectSourceId(source.id);
    setProjectSourcesMode("tree");

    if (source.kind === "file") {
      void handleSelectProjectFile(source);
      return;
    }

    setProjectFilePreview(null);
  }

  // 상세 페이지의 자료 행은 우측 자료 도구를 실제로 열고 선택한 항목까지 이어서 보여준다.
  function openProjectFileFromDetail(source: Attachment) {
    const baseTab = activeProjectFileTab ?? createProjectPanelTab("files");
    const nextPreview: ProjectFilePreview | null =
      source.kind === "file"
        ? {
            id: source.id,
            name: source.name,
            path: source.path,
            content: "",
            isLoading: !source.serverOnly,
            error: source.serverOnly
              ? t("서버 문서는 로컬 경로가 없어 미리볼 수 없습니다")
              : undefined,
          }
        : null;
    const preparedTab: ProjectPanelTab = {
      ...baseTab,
      fileQuery: "",
      filePreview: nextPreview,
      projectSourcesMode: "tree",
      selectedProjectSourceId: source.id,
      view: "files",
    };

    setProjectPanelTabs((currentTabs) =>
      currentTabs.some((tab) => tab.id === preparedTab.id)
        ? currentTabs.map((tab) =>
            tab.id === preparedTab.id ? preparedTab : tab,
          )
        : [...currentTabs, preparedTab],
    );
    setActiveProjectPanelTabId(preparedTab.id);
    openProjectPanel();

    if (
      source.kind !== "file" ||
      source.serverOnly ||
      !source.path
    ) {
      return;
    }

    void invoke<string>("read_text_file", { path: source.path })
      .then((content) => {
        setProjectFilePreviewForTab(preparedTab.id, {
          ...nextPreview!,
          content,
          isLoading: false,
        });
      })
      .catch((error) => {
        setProjectFilePreviewForTab(preparedTab.id, {
          ...nextPreview!,
          isLoading: false,
          error: error instanceof Error ? error.message : String(error),
        });
      });
  }

  function isGithubRemoteAttemptFresh(repository: GitRepositoryInfo, now = Date.now()) {
    const attemptedAt = repository.remoteCheckAttemptedAt ?? repository.remoteCheckedAt;
    return (
      typeof attemptedAt === "number" &&
      Number.isFinite(attemptedAt) &&
      now >= attemptedAt &&
      now - attemptedAt < GITHUB_REMOTE_HEAD_TTL_MS
    );
  }

  function isGithubRepositoryIdentityCurrent(
    projectId: string,
    apiProjectId: number | null,
    repoId: number | null,
    repositoryUrl: string,
    branch: string,
    commitSha: string | null,
  ) {
    const currentProject = projectsRef.current.find(
      (candidate) => candidate.id === projectId,
    );
    const currentRepository = currentProject?.githubRepository;
    return Boolean(
      currentProject &&
        !currentProject.serverMissing &&
        (currentProject.apiProjectId ?? null) === apiProjectId &&
        currentRepository &&
        (currentRepository.repoId ?? null) === repoId &&
        getGithubRepositoryUrl(currentRepository) === repositoryUrl &&
        currentRepository.branch === branch &&
        (currentRepository.commitSha ?? null) === commitSha,
    );
  }

  async function refreshGithubRepositoryActivity(
    projectId: string,
    options: GithubRepositoryRefreshOptions = {},
  ) {
    const project = projectsRef.current.find((candidate) => candidate.id === projectId);
    const repository = project?.githubRepository;
    const repositoryUrl = repository ? getGithubRepositoryUrl(repository) : "";
    const session =
      options.session === undefined
        ? githubLoginSessionsRef.current[projectId] ?? null
        : options.session;

    if (!project || !repository || !repositoryUrl) {
      return;
    }
    if (project.serverMissing) {
      restoreCancelledGithubRepositoryActivity(projectId);
      return;
    }
    if (repository.authProvider === "github_app" && !session?.state) {
      updateGithubRepository(projectId, (currentRepository) => ({
        ...currentRepository,
        remoteCheckAttemptedAt: Date.now(),
        remoteCheckStatus: "error",
        remoteCheckError: "session_expired",
      }));
      handleGithubRemoteSessionExpired(projectId);
      return;
    }
    if (
      options.onlyIfRemoteStale &&
      isGithubRemoteAttemptFresh(repository)
    ) {
      return;
    }

    const operation = options.force
      ? replaceLatestProjectOperation(
          githubRepositoryActivityRegistryRef.current,
          projectId,
        )
      : beginLatestProjectOperation(
          githubRepositoryActivityRegistryRef.current,
          projectId,
        );
    if (!operation) {
      return;
    }

    const apiProjectId = project.apiProjectId ?? null;
    const repoId = repository.repoId ?? null;
    const branch = repository.branch;
    const commitSha = repository.commitSha ?? null;
    const serverUrl = getPaimApiRootUrl();
    const attemptedAt = Date.now();

    updateGithubRepository(projectId, (currentRepository) =>
      (currentRepository.repoId ?? null) === repoId &&
      currentRepository.branch === branch &&
      getGithubRepositoryUrl(currentRepository) === repositoryUrl
        ? {
            ...currentRepository,
            remoteCheckAttemptedAt: attemptedAt,
            remoteCheckStatus: "checking",
            remoteCheckError: null,
          }
        : currentRepository,
    );

    try {
      const preview = session?.state
        ? await fetchGithubAppRepositoryPreview(
            repositoryUrl,
            session.state,
            operation.controller.signal,
            branch,
          )
        : await fetchGithubRepository(
            repositoryUrl,
            session?.accessToken ?? null,
            operation.controller.signal,
            branch,
          );

      if (
        !isLatestProjectOperationCurrent(
          githubRepositoryActivityRegistryRef.current,
          operation,
        ) ||
        getPaimApiRootUrl() !== serverUrl ||
        !isGithubRepositoryIdentityCurrent(
          projectId,
          apiProjectId,
          repoId,
          repositoryUrl,
          branch,
          commitSha,
        )
      ) {
        return;
      }

      updateProject(projectId, (currentProject) => {
        const currentRepository = currentProject.githubRepository;
        if (
          !currentRepository ||
          (currentRepository.repoId ?? null) !== repoId ||
          getGithubRepositoryUrl(currentRepository) !== repositoryUrl ||
          currentRepository.branch !== branch ||
          (currentRepository.commitSha ?? null) !== commitSha
        ) {
          return currentProject;
        }

        const remoteHeadSha = preview.repository.remoteHeadSha ?? null;
        const checkedAt = Date.now();
        return {
          ...currentProject,
          githubEvents: preview.events,
          githubRepository: {
            ...currentRepository,
            name: preview.repository.name,
            remoteRepo: preview.repository.remoteRepo,
            issuePrStatus: preview.repository.issuePrStatus,
            visibility: preview.repository.visibility,
            authProvider: preview.repository.authProvider,
            remoteHeadSha,
            remoteCheckedAt: checkedAt,
            remoteCheckAttemptedAt: checkedAt,
            remoteCheckStatus:
              currentRepository.commitSha && remoteHeadSha
                ? githubCommitShasMatch(currentRepository.commitSha, remoteHeadSha)
                  ? "current"
                  : "needs_sync"
                : "unknown",
            remoteCheckError: null,
          },
        };
      });
    } catch (error) {
      if (
        !isLatestProjectOperationCurrent(
          githubRepositoryActivityRegistryRef.current,
          operation,
        ) ||
        getPaimApiRootUrl() !== serverUrl ||
        !isGithubRepositoryIdentityCurrent(
          projectId,
          apiProjectId,
          repoId,
          repositoryUrl,
          branch,
          commitSha,
        )
      ) {
        return;
      }
      const sessionExpired = isGithubSessionExpiredError(error);
      const failedAt = Date.now();
      updateProject(projectId, (currentProject) => {
        const currentRepository = currentProject.githubRepository;
        if (
          !currentRepository ||
          (currentRepository.repoId ?? null) !== repoId ||
          getGithubRepositoryUrl(currentRepository) !== repositoryUrl ||
          currentRepository.branch !== branch ||
          (currentRepository.commitSha ?? null) !== commitSha
        ) {
          return currentProject;
        }

        return {
          ...currentProject,
          githubRepository: {
            ...currentRepository,
            remoteCheckAttemptedAt: failedAt,
            remoteCheckStatus: "error",
            remoteCheckError: sessionExpired ? "session_expired" : "unavailable",
          },
        };
      });
      if (sessionExpired) {
        handleGithubRemoteSessionExpired(projectId);
      }
    } finally {
      finishLatestProjectOperation(
        githubRepositoryActivityRegistryRef.current,
        operation,
      );
    }
  }

  async function refreshGithubRepositoryHead(
    projectId: string,
    options: GithubRepositoryRefreshOptions = {},
  ) {
    const project = projectsRef.current.find((candidate) => candidate.id === projectId);
    const repository = project?.githubRepository;
    const repositoryUrl = repository ? getGithubRepositoryUrl(repository) : "";
    const session =
      options.session === undefined
        ? githubLoginSessionsRef.current[projectId] ?? null
        : options.session;

    if (!project || !repository || !repositoryUrl) {
      return;
    }
    if (project.serverMissing) {
      restoreCancelledGithubRepositoryActivity(projectId);
      return;
    }
    if (repository.authProvider === "github_app" && !session?.state) {
      updateGithubRepository(projectId, (currentRepository) => ({
        ...currentRepository,
        remoteCheckAttemptedAt: Date.now(),
        remoteCheckStatus: "error",
        remoteCheckError: "session_expired",
      }));
      handleGithubRemoteSessionExpired(projectId);
      return;
    }
    if (!options.force && isGithubRemoteAttemptFresh(repository)) {
      return;
    }

    const operation = options.force
      ? replaceLatestProjectOperation(
          githubRepositoryActivityRegistryRef.current,
          projectId,
        )
      : beginLatestProjectOperation(
          githubRepositoryActivityRegistryRef.current,
          projectId,
        );
    if (!operation) {
      return;
    }

    const apiProjectId = project.apiProjectId ?? null;
    const repoId = repository.repoId ?? null;
    const branch = repository.branch;
    const commitSha = repository.commitSha ?? null;
    const serverUrl = getPaimApiRootUrl();
    const attemptedAt = Date.now();

    updateGithubRepository(projectId, (currentRepository) =>
      (currentRepository.repoId ?? null) === repoId &&
      currentRepository.branch === branch &&
      getGithubRepositoryUrl(currentRepository) === repositoryUrl
        ? {
            ...currentRepository,
            remoteCheckAttemptedAt: attemptedAt,
            remoteCheckStatus: "checking",
            remoteCheckError: null,
          }
        : currentRepository,
    );

    try {
      const head = session?.state
        ? await fetchGithubAppRepositoryHead(
            repositoryUrl,
            branch,
            session.state,
            operation.controller.signal,
          )
        : await fetchGithubRepositoryHead(
            repositoryUrl,
            branch,
            session?.accessToken ?? null,
            operation.controller.signal,
          );

      if (
        !isLatestProjectOperationCurrent(
          githubRepositoryActivityRegistryRef.current,
          operation,
        ) ||
        getPaimApiRootUrl() !== serverUrl ||
        !isGithubRepositoryIdentityCurrent(
          projectId,
          apiProjectId,
          repoId,
          repositoryUrl,
          branch,
          commitSha,
        )
      ) {
        return;
      }

      updateProject(projectId, (currentProject) => {
        const currentRepository = currentProject.githubRepository;
        if (
          !currentRepository ||
          (currentRepository.repoId ?? null) !== repoId ||
          getGithubRepositoryUrl(currentRepository) !== repositoryUrl ||
          currentRepository.branch !== branch ||
          head.branch !== branch ||
          (currentRepository.commitSha ?? null) !== commitSha
        ) {
          return currentProject;
        }

        const checkedAt = Date.now();
        return {
          ...currentProject,
          githubRepository: {
            ...currentRepository,
            remoteHeadSha: head.remoteHeadSha,
            remoteCheckedAt: checkedAt,
            remoteCheckAttemptedAt: checkedAt,
            remoteCheckStatus:
              currentRepository.commitSha && head.remoteHeadSha
                ? githubCommitShasMatch(currentRepository.commitSha, head.remoteHeadSha)
                  ? "current"
                  : "needs_sync"
                : "unknown",
            remoteCheckError: null,
          },
        };
      });
    } catch (error) {
      if (
        !isLatestProjectOperationCurrent(
          githubRepositoryActivityRegistryRef.current,
          operation,
        ) ||
        getPaimApiRootUrl() !== serverUrl ||
        !isGithubRepositoryIdentityCurrent(
          projectId,
          apiProjectId,
          repoId,
          repositoryUrl,
          branch,
          commitSha,
        )
      ) {
        return;
      }
      const sessionExpired = isGithubSessionExpiredError(error);
      const failedAt = Date.now();
      updateProject(projectId, (currentProject) => {
        const currentRepository = currentProject.githubRepository;
        if (
          !currentRepository ||
          (currentRepository.repoId ?? null) !== repoId ||
          getGithubRepositoryUrl(currentRepository) !== repositoryUrl ||
          currentRepository.branch !== branch ||
          (currentRepository.commitSha ?? null) !== commitSha
        ) {
          return currentProject;
        }

        return {
          ...currentProject,
          githubRepository: {
            ...currentRepository,
            remoteCheckAttemptedAt: failedAt,
            remoteCheckStatus: "error",
            remoteCheckError: sessionExpired ? "session_expired" : "unavailable",
          },
        };
      });
      if (sessionExpired) {
        handleGithubRemoteSessionExpired(projectId);
      }
    } finally {
      finishLatestProjectOperation(
        githubRepositoryActivityRegistryRef.current,
        operation,
      );
    }
  }

  async function handleStartGithubLogin(projectId: string) {
    const targetProject = projects.find((project) => project.id === projectId);

    if (!targetProject || shouldSkipProjectPermission(targetProject, "github", "owner")) {
      return;
    }
    const operation = beginGithubOperation(projectId, "auth-start");
    if (!operation) {
      return;
    }

    setSelectedProjectId(projectId);
    setGithubRepositoryQueryForProject(projectId, "");
    setDemoStatus({
      kind: "info",
      ok: true,
      message: "GitHub 로그인 준비 중...",
      projectId,
      scope: "github",
    });

    try {
      const deviceCode = await createGithubDeviceCode(operation.controller.signal);
      if (!isGithubOperationCurrent(operation)) {
        return;
      }

      if (
        deviceCode.error ||
        !deviceCode.device_code ||
        !deviceCode.user_code ||
        !deviceCode.verification_uri
      ) {
        throw new Error(
          getGithubOAuthErrorMessage(
            deviceCode.error,
            deviceCode.error_description,
            "GitHub 로그인을 시작할 수 없습니다",
          ),
        );
      }

      const session: GithubLoginSessionState = {
        deviceCode: deviceCode.device_code,
        userCode: deviceCode.user_code,
        verificationUri: deviceCode.verification_uri,
        interval: deviceCode.interval ?? 5,
        status: "pending",
      };

      setGithubLoginSessions((currentSessions) => ({
        ...currentSessions,
        [projectId]: session,
      }));
      await openExternalUrl(session.verificationUri);
      if (!isGithubOperationCurrent(operation)) {
        return;
      }
      setDemoStatus({
        ok: true,
        message: t("GitHub 인증 화면을 열었습니다. 코드: {code}", {
          code: session.userCode ?? "",
        }),
        projectId,
        scope: "github",
      });
    } catch (error) {
      if (!isGithubOperationCurrent(operation)) {
        return;
      }
      setDemoStatus({
        ok: false,
        message: getGithubLoginErrorMessage(error),
        projectId,
        scope: "github",
      });
    } finally {
      finishGithubOperation(operation);
    }
  }

  async function handleStartGithubPrivateLogin(projectId: string) {
    const targetProject = projects.find((project) => project.id === projectId);

    if (!targetProject || shouldSkipProjectMutation(targetProject, "github", "owner")) {
      return;
    }
    const operation = beginGithubOperation(projectId, "auth-start");
    if (!operation) {
      return;
    }

    setSelectedProjectId(projectId);
    setGithubRepositoryQueryForProject(projectId, "");
    setDemoStatus({
      kind: "info",
      ok: true,
      message: "Private repo 연결 준비 중...",
      projectId,
      scope: "github",
    });

    try {
      const appSession = await createGithubAppSession(operation.controller.signal);
      if (!isGithubOperationCurrent(operation)) {
        return;
      }

      if (!appSession.state || !appSession.installUrl) {
        throw new Error("GitHub App 설치를 시작할 수 없습니다");
      }

      const session: GithubLoginSessionState = {
        state: appSession.state,
        verificationUri: appSession.installUrl,
        interval: 5,
        status: "pending",
      };

      setGithubLoginSessions((currentSessions) => ({
        ...currentSessions,
        [projectId]: session,
      }));
      await openExternalUrl(session.verificationUri);
      if (!isGithubOperationCurrent(operation)) {
        return;
      }
      setDemoStatus({
        ok: true,
        message: "GitHub App 설치 화면을 열었습니다",
        projectId,
        scope: "github",
      });
    } catch (error) {
      if (!isGithubOperationCurrent(operation)) {
        return;
      }
      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "Private repo 연결은 PaiM backend가 켜져 있어야 합니다"),
        projectId,
        scope: "github",
      });
    } finally {
      finishGithubOperation(operation);
    }
  }

  async function handleCheckGithubLogin(projectId: string) {
    const session = githubLoginSessions[projectId];
    const targetProject = projects.find((project) => project.id === projectId);

    if (!session) {
      return;
    }
    if (!targetProject || shouldSkipProjectPermission(targetProject, "github", "owner")) {
      return;
    }

    if (session.state && shouldSkipProjectMutation(targetProject, "github", "owner")) {
      return;
    }
    const operation = beginGithubOperation(projectId, "auth-check");
    if (!operation) {
      return;
    }

    try {
      if (session.state) {
        const appSession = await fetchGithubAppSession(
          session.state,
          operation.controller.signal,
        );
        if (!isGithubOperationCurrent(operation)) {
          return;
        }

        if (appSession.status !== "connected") {
          setDemoStatus({
            ok: false,
            message: "아직 GitHub App 설치가 완료되지 않았습니다",
            projectId,
            scope: "github",
          });
          return;
        }

        const response = await fetchGithubAppRepositories(
          session.state,
          operation.controller.signal,
        );
        if (!isGithubOperationCurrent(operation)) {
          return;
        }
        const nextSession: GithubLoginSessionState = {
          ...session,
          status: "connected",
          user: response.user ?? getGithubRepositoryOwner(response.repositories) ?? session.user,
        };

        setGithubLoginSessions((currentSessions) => ({
          ...currentSessions,
          [projectId]: nextSession,
        }));
        setGithubRepositories((currentRepositories) => ({
          ...currentRepositories,
          [projectId]: response.repositories,
        }));
        setDemoStatus({
          ok: true,
          message: getGithubRepositoryLoadMessage(response.repositories, settings.language),
          projectId,
          scope: "github",
        });
        if (targetProject.githubRepository) {
          void refreshGithubRepositoryActivity(projectId, {
            force: true,
            session: nextSession,
          });
        }
        return;
      }

      if (!session.deviceCode) {
        throw new Error("GitHub 인증 세션을 찾을 수 없습니다");
      }

      const tokenResponse = await fetchGithubAccessToken(
        session.deviceCode,
        operation.controller.signal,
      );
      if (!isGithubOperationCurrent(operation)) {
        return;
      }

      if (!tokenResponse.access_token) {
        const isPending = tokenResponse.error === "authorization_pending";

        setDemoStatus({
          ok: false,
          message: isPending
            ? "아직 GitHub 인증이 완료되지 않았습니다"
            : getGithubOAuthErrorMessage(
                tokenResponse.error,
                tokenResponse.error_description,
                "GitHub 인증을 완료할 수 없습니다",
              ),
          projectId,
          scope: "github",
        });
        return;
      }

      const [repositories, user] = await Promise.all([
        fetchGithubRepositories(tokenResponse.access_token, operation.controller.signal),
        fetchGithubUserProfile(tokenResponse.access_token, operation.controller.signal),
      ]);
      if (!isGithubOperationCurrent(operation)) {
        return;
      }
      const nextSession: GithubLoginSessionState = {
        ...session,
        accessToken: tokenResponse.access_token,
        scope: tokenResponse.scope,
        tokenType: tokenResponse.token_type,
        status: "connected",
        user,
      };

      setGithubLoginSessions((currentSessions) => ({
        ...currentSessions,
        [projectId]: nextSession,
      }));
      setGithubRepositories((currentRepositories) => ({
        ...currentRepositories,
        [projectId]: repositories.repositories,
      }));
      setDemoStatus({
        ok: true,
        message: getGithubRepositoryLoadMessage(repositories.repositories, settings.language),
        projectId,
        scope: "github",
      });
      if (targetProject.githubRepository) {
        void refreshGithubRepositoryActivity(projectId, {
          force: true,
          session: nextSession,
        });
      }
    } catch (error) {
      if (!isGithubOperationCurrent(operation)) {
        return;
      }
      if (isGithubSessionExpiredError(error)) {
        handleGithubSessionExpired(projectId);
        return;
      }

      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "GitHub 로그인 상태를 확인할 수 없습니다"),
        projectId,
        scope: "github",
      });
    } finally {
      finishGithubOperation(operation);
    }
  }

  async function handleOpenGithubVerification(projectId: string) {
    const session = githubLoginSessions[projectId];

    if (!session) {
      return;
    }

    try {
      await openExternalUrl(session.verificationUri);
    } catch {
      setDemoStatus({
        ok: false,
        message: "GitHub 인증 페이지를 열 수 없습니다",
        projectId,
        scope: "github",
      });
    }
  }

  function handleResetGithubLogin(projectId: string) {
    const targetProject = projects.find((project) => project.id === projectId);

    if (!targetProject || shouldSkipProjectPermission(targetProject, "github", "owner")) {
      return;
    }

    cancelGithubOperation(projectId);
    setGithubLoginSessions((currentSessions) => {
      const nextSessions = { ...currentSessions };
      delete nextSessions[projectId];
      return nextSessions;
    });
    setGithubRepositories((currentRepositories) => {
      const nextRepositories = { ...currentRepositories };
      delete nextRepositories[projectId];
      return nextRepositories;
    });
    setGithubRepositoryQueryForProject(projectId, "");
    setDemoStatus({
      ok: true,
      message: "GitHub 로그인을 해제했습니다",
      projectId,
      scope: "github",
    });
  }

  async function handleLoadGithubRepositories(projectId: string) {
    const session = githubLoginSessions[projectId];
    const targetProject = projects.find((project) => project.id === projectId);

    if (!session?.accessToken && !session?.state) {
      return;
    }
    if (!targetProject || shouldSkipProjectPermission(targetProject, "github", "owner")) {
      return;
    }

    if (session.state && shouldSkipProjectMutation(targetProject, "github", "owner")) {
      return;
    }
    const operation = beginGithubOperation(projectId, "repo-load");
    if (!operation) {
      return;
    }

    try {
      if (session.state) {
        const response = await fetchGithubAppRepositories(
          session.state,
          operation.controller.signal,
        );
        if (!isGithubOperationCurrent(operation)) {
          return;
        }
        const appUser = response.user ?? getGithubRepositoryOwner(response.repositories);

        setGithubRepositories((currentRepositories) => ({
          ...currentRepositories,
          [projectId]: response.repositories,
        }));
        if (appUser && !session.user) {
          setGithubLoginSessions((currentSessions) => ({
            ...currentSessions,
            [projectId]: {
              ...session,
              user: appUser,
            },
          }));
        }
        setDemoStatus({
          ok: true,
          message: getGithubRepositoryLoadMessage(response.repositories, settings.language),
          projectId,
          scope: "github",
        });
        return;
      }

      if (!session.accessToken) {
        throw new Error("GitHub 인증 세션을 찾을 수 없습니다");
      }

      const response = await fetchGithubRepositories(
        session.accessToken,
        operation.controller.signal,
      );
      if (!isGithubOperationCurrent(operation)) {
        return;
      }

      setGithubRepositories((currentRepositories) => ({
        ...currentRepositories,
        [projectId]: response.repositories,
      }));
      setDemoStatus({
        ok: true,
        message: getGithubRepositoryLoadMessage(response.repositories, settings.language),
        projectId,
        scope: "github",
      });
    } catch (error) {
      if (!isGithubOperationCurrent(operation)) {
        return;
      }
      if (isGithubSessionExpiredError(error)) {
        handleGithubSessionExpired(projectId);
        return;
      }

      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "GitHub repo 목록을 불러올 수 없습니다"),
        projectId,
        scope: "github",
      });
    } finally {
      finishGithubOperation(operation);
    }
  }

  async function connectGithubRepository(projectId: string, repositoryUrl: string) {
    const trimmedRepositoryUrl = repositoryUrl.trim();
    const session = githubLoginSessions[projectId] ?? null;
    const targetProject = projects.find((project) => project.id === projectId);

    if (!trimmedRepositoryUrl) {
      return;
    }
    if (!targetProject || shouldSkipProjectPermission(targetProject, "github", "owner")) {
      return;
    }

    if (session?.state && shouldSkipProjectMutation(targetProject, "github", "owner")) {
      return;
    }
    const operation = beginGithubOperation(
      projectId,
      "connect",
      trimmedRepositoryUrl,
    );
    if (!operation) {
      return;
    }

    setSelectedProjectId(projectId);
    setDemoStatus({
      kind: "info",
      ok: true,
      message: "GitHub repo 연결 중...",
      projectId,
      scope: "github",
    });

    try {
      const { events, repository } = session?.state
        ? await fetchGithubAppRepositoryPreview(
            trimmedRepositoryUrl,
            session.state,
            operation.controller.signal,
          )
        : await fetchGithubRepository(
            trimmedRepositoryUrl,
            session?.accessToken ?? null,
            operation.controller.signal,
          );
      if (!isGithubOperationCurrent(operation)) {
        return;
      }

      updateProject(projectId, (project) => ({
        ...project,
        githubConnected: true,
        githubEvents: events,
        githubRepository: repository,
      }));
      setPendingGithubDisconnectProjectId(null);
      setDemoStatus({
        ok: true,
        message: t("{name} repo 연결됨", {
          name: repository.remoteRepo ?? repository.name,
        }),
        projectId,
        scope: "github",
      });
      setGithubRepositoryQueryForProject(projectId, "");
    } catch (error) {
      if (!isGithubOperationCurrent(operation)) {
        return;
      }
      if (isGithubSessionExpiredError(error)) {
        handleGithubSessionExpired(projectId);
        return;
      }

      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "GitHub repo를 연결할 수 없습니다"),
        projectId,
        scope: "github",
      });
    } finally {
      finishGithubOperation(operation);
    }
  }

  async function handleSyncGithubRepository(projectId: string) {
    const project = projects.find((currentProject) => currentProject.id === projectId);
    const session = githubLoginSessions[projectId] ?? null;

    if (!project?.githubRepository) {
      return;
    }

    if (shouldSkipProjectMutation(project, "github", "owner")) {
      return;
    }
    const operation = beginGithubOperation(projectId, "sync");
    if (!operation) {
      return;
    }

    updateGithubRepository(projectId, (repository) => ({
      ...repository,
      syncStatus: "syncing",
      syncStartedAt: Date.now(),
      lastError: null,
      syncWarnings: undefined,
    }));
    setDemoStatus({
      kind: "info",
      ok: true,
      message: "GitHub repo 서버 동기화 중...",
      projectId,
      scope: "github",
    });

    try {
      if (project.serverMissing) {
        throw new Error("서버에서 찾을 수 없는 프로젝트에는 GitHub repo를 동기화할 수 없습니다");
      }

      // Project creation is non-idempotent, so always collect its id before
      // honoring a cancelled GitHub operation.
      const apiProject = await ensureApiProject(project);
      if (!isGithubOperationCurrent(operation)) {
        return;
      }

      if (typeof apiProject.apiProjectId !== "number") {
        throw new Error("서버 프로젝트를 준비할 수 없습니다");
      }

      let repoId = project.githubRepository.repoId;

      if (typeof repoId !== "number") {
        const repositoryUrl = getGithubRepositoryUrl(project.githubRepository);

        if (!repositoryUrl) {
          throw new Error("GitHub repository URL을 확인할 수 없습니다");
        }

        const path = `/projects/${apiProject.apiProjectId}/repositories`;
        const init = {
          method: "POST",
          body: JSON.stringify({
            provider: "github",
            repository_url: repositoryUrl,
            branch: project.githubRepository.branch,
            ...(session?.state ? { state: session.state } : {}),
          }),
        };
        const connected = session?.state
          ? await fetchPaimJsonPreservingSession<ApiRepositoryConnectResponse>(path, init)
          : await fetchPaimJson<ApiRepositoryConnectResponse>(path, init);
        repoId = connected.repo_id;

        const latestRepository = projectsRef.current.find(
          (currentProject) => currentProject.id === projectId,
        )?.githubRepository;
        if (!latestRepository || getGithubRepositoryUrl(latestRepository) !== repositoryUrl) {
          // A disconnect can win while the non-idempotent POST is in flight. Keep
          // the response long enough to remove the exact server row it created.
          try {
            await fetchPaimJson<void>(
              `/projects/${apiProject.apiProjectId}/repositories/${connected.repo_id}`,
              { method: "DELETE" },
            );
          } catch (cleanupError) {
            const detail = getErrorMessage(cleanupError, "취소한 GitHub 연결을 정리할 수 없습니다");
            if (!/repository not found/i.test(detail)) {
              setDemoStatus({
                ok: false,
                message: detail,
                projectId,
                scope: "github",
              });
            }
          }
          return;
        }

        updateGithubRepository(projectId, (repository) => ({
          ...repository,
          repoId: connected.repo_id,
          branch: connected.branch ?? repository.branch,
          syncStatus: connected.status,
          syncRunId:
            connected.status === "syncing"
              ? connected.run_id ?? repository.syncRunId ?? null
              : null,
          syncStartedAt:
            connected.status === "syncing"
              ? (
                  !connected.run_id || repository.syncRunId === connected.run_id
                    ? repository.syncStartedAt
                    : undefined
                ) ?? Date.now()
              : undefined,
          lastError: null,
          syncWarnings: undefined,
        }));

        if (!isGithubOperationCurrent(operation)) {
          return;
        }

        if (connected.status === "syncing") {
          scheduleGithubRepositoryStatusPoll(projectId, apiProject.apiProjectId, connected.repo_id);
        } else {
          await startGithubRepositorySync(
            projectId,
            apiProject.apiProjectId,
            connected.repo_id,
            session?.state,
            repositoryUrl,
          );
        }
      } else {
        await startGithubRepositorySync(
          projectId,
          apiProject.apiProjectId,
          repoId,
          session?.state,
          getGithubRepositoryUrl(project.githubRepository),
        );
      }

      if (!isGithubOperationCurrent(operation)) {
        return;
      }
      setDemoStatus({
        ok: true,
        message: "GitHub repo 서버 동기화를 시작했습니다",
        projectId,
        scope: "github",
      });
    } catch (error) {
      if (!isGithubOperationCurrent(operation)) {
        return;
      }
      if (isGithubSessionExpiredError(error)) {
        handleGithubSessionExpired(projectId);
        return;
      }

      const message = getErrorMessage(error, "GitHub repo 서버 동기화를 시작할 수 없습니다");
      updateGithubRepository(projectId, (repository) => ({
        ...repository,
        syncStatus: "failed",
        syncStartedAt: undefined,
        lastError: message,
      }));
      setDemoStatus({
        ok: false,
        message,
        projectId,
        scope: "overview",
      });
    } finally {
      finishGithubOperation(operation);
    }
  }

  async function handleDisconnectGithub(projectId: string) {
    const project = projects.find((currentProject) => currentProject.id === projectId);
    const repoId = project?.githubRepository?.repoId;

    if (!project?.githubRepository) {
      return;
    }
    const repositoryName =
      project.githubRepository.remoteRepo ?? project.githubRepository.name;
    if (shouldSkipProjectPermission(project, "github", "owner")) {
      return;
    }

    if (typeof repoId === "number" && pendingGithubDisconnectProjectId !== projectId) {
      setPendingGithubDisconnectProjectId(projectId);
      setDemoStatus({
        kind: "warning",
        ok: false,
        message: t("{name} 연결을 해제하면 이 저장소에서 만든 서버 메모리 연결도 해제됩니다. 한 번 더 눌러 확인하세요.", {
          name: repositoryName,
        }),
        projectId,
        scope: "github",
      });
      return;
    }

    if (typeof repoId === "number") {
      if (shouldSkipProjectMutation(project, "github", "owner")) {
        return;
      }

      if (typeof project.apiProjectId !== "number") {
        setDemoStatus({
          ok: false,
          message: "서버 GitHub 연결 해제에 필요한 프로젝트 정보를 찾을 수 없습니다",
          projectId,
          scope: "github",
        });
        return;
      }

      clearGithubRepositoryPollsForProject(projectId);
      cancelGithubOperation(projectId);
      try {
        await fetchPaimJson<void>(
          `/projects/${project.apiProjectId}/repositories/${repoId}`,
          { method: "DELETE" },
        );
      } catch (error) {
        if (isGithubSessionExpiredError(error)) {
          resumeGithubRepositoryPollIfNeeded(projectId);
          handleGithubSessionExpired(projectId);
          return;
        }

        const detail = getErrorMessage(error, "GitHub repo 연결을 해제할 수 없습니다");

        if (!/repository not found/i.test(detail)) {
          resumeGithubRepositoryPollIfNeeded(projectId);
          setDemoStatus({
            ok: false,
            message: detail,
            projectId,
            scope: "github",
          });
          return;
        }
      }
    } else {
      clearGithubRepositoryPollsForProject(projectId);
      cancelGithubOperation(projectId);
    }

    updateProject(projectId, (project) => ({
      ...project,
      githubConnected: false,
      githubEvents: undefined,
      githubRepository: undefined,
    }));
    setPendingGithubDisconnectProjectId(null);
    setDemoStatus({
      ok: true,
      message: t("{name} 저장소 연결을 해제했습니다", { name: repositoryName }),
      projectId,
      scope: "github",
    });
  }

  function toggleSessionActionMenu(
    projectId: string,
    sessionId: string,
    event: MouseEvent<HTMLButtonElement>,
  ) {
    event.stopPropagation();
    setIsAccountMenuOpen(false);
    actionMenuTriggerRef.current = event.currentTarget;
    const position = getActionMenuPosition(event.currentTarget, ACTION_MENU_SESSION_HEIGHT);

    setOpenActionMenu((current) =>
      current?.type === "session" &&
      current.projectId === projectId &&
      current.sessionId === sessionId
        ? null
        : { type: "session", projectId, sessionId, ...position },
    );
  }

  function handleSessionContextMenu(
    projectId: string,
    sessionId: string,
    event: MouseEvent<HTMLElement>,
  ) {
    event.preventDefault();
    event.stopPropagation();
    setIsAccountMenuOpen(false);
    actionMenuTriggerRef.current = event.currentTarget.matches("button")
      ? event.currentTarget
      : event.currentTarget.querySelector<HTMLElement>("button");
    setOpenActionMenu({
      type: "session",
      projectId,
      sessionId,
      ...getActionMenuPositionAtPoint(
        event.clientX,
        event.clientY,
        ACTION_MENU_SESSION_HEIGHT,
      ),
    });
  }

  function handleActionMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const items = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(
        '[role="menuitem"]:not([aria-disabled="true"]):not(:disabled)',
      ),
    );

    if (items.length === 0) {
      return;
    }

    const currentIndex = Math.max(0, items.indexOf(document.activeElement as HTMLElement));
    let nextIndex = currentIndex;

    if (event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1) % items.length;
    } else if (event.key === "ArrowUp") {
      nextIndex = (currentIndex - 1 + items.length) % items.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = items.length - 1;
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      setOpenActionMenu(null);
      window.requestAnimationFrame(() => actionMenuTriggerRef.current?.focus());
      return;
    } else if (event.key === "Tab") {
      setOpenActionMenu(null);
      return;
    } else {
      return;
    }

    event.preventDefault();
    items[nextIndex]?.focus();
  }

  function openAccountView(view: Extract<MainView, "profile" | "settings">) {
    mainViewReturnFocusRef.current = accountMenuTriggerRef.current;
    navigateTo(view);
    setIsAccountMenuOpen(false);
    setOpenActionMenu(null);
  }

  function handleAccountMenuOpenChange(isOpen: boolean) {
    setIsAccountMenuOpen(isOpen);

    if (!isOpen) {
      window.requestAnimationFrame(() => {
        if (!document.activeElement || document.activeElement === document.body) {
          accountMenuTriggerRef.current?.focus();
        }
      });
    }
  }

  function handleAccountLogout() {
    setIsAccountMenuOpen(false);
    onLogout();
  }

  // 상세 화면에서 로컬 프로젝트의 서버 ID까지 준비한 뒤 멤버 관리로 이동한다.
  async function openProjectMembers(projectId: string, trigger?: HTMLElement) {
    const targetProject = projectsRef.current.find((project) => project.id === projectId);
    if (!targetProject) {
      return;
    }

    if (!authUser) {
      setDemoStatus({
        ok: false,
        message: "팀원 관리는 로그인된 서버 프로젝트에서 사용할 수 있습니다",
        projectId,
        scope: "overview",
      });
      return;
    }

    if (serverStatus !== "online") {
      setDemoStatus({
        ok: false,
        message: "서버에 연결한 뒤 팀원을 관리할 수 있습니다",
        projectId,
        scope: "overview",
      });
      return;
    }

    try {
      const apiProject = await ensureApiProject(targetProject);
      if (typeof apiProject.apiProjectId !== "number") {
        throw new Error("서버 프로젝트를 준비할 수 없습니다");
      }
    } catch (error) {
      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "팀원 관리 화면을 열 수 없습니다"),
        projectId,
        scope: "overview",
      });
      return;
    }

    const nextMembersReturnView =
      mainViewRef.current === "project-management"
        ? "project-management"
        : "project-detail";
    mainViewReturnFocusRef.current =
      trigger ??
      (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    mainViewReturnFocusSelectorRef.current = trigger?.closest(
      ".project-management-page",
    )
      ? ".project-management-tab[data-section='members']"
      : ".project-detail-rail-manage-members";
    rememberCurrentDraft();
    setSelectedProjectId(projectId);
    setSelectedSessionId(null);
    openMembers(nextMembersReturnView);
    setOpenActionMenu(null);
    showSessionDraft(projectId, null);
  }

  async function renameProjectFromDetail(projectId: string, rawName: string) {
    const targetProject = projectsRef.current.find((project) => project.id === projectId);
    const nextName = rawName.trim();

    if (
      !targetProject ||
      !nextName ||
      nextName === targetProject.name ||
      shouldSkipProjectPermission(targetProject, "overview", "owner")
    ) {
      return;
    }

    const previousName = targetProject.name;
    updateProject(projectId, (project) => ({ ...project, name: nextName }));
    await syncProjectName(projectId, nextName, previousName);
  }

  async function updateProjectDescriptionFromDetail(
    projectId: string,
    rawDescription: string,
  ) {
    const targetProject = projectsRef.current.find((project) => project.id === projectId);
    const nextDescription = rawDescription.trim();

    if (
      !targetProject ||
      nextDescription === (targetProject.description ?? "").trim() ||
      shouldSkipProjectPermission(targetProject, "overview", "owner")
    ) {
      return;
    }

    const previousDescription = targetProject.description ?? "";
    updateProject(projectId, (project) => ({
      ...project,
      description: nextDescription || undefined,
    }));
    await syncProjectDescription(projectId, nextDescription, previousDescription);
  }

  // 행 안에서 바로 수정하도록 채팅명 입력을 연다.
  function beginRenameSession(projectId: string, sessionId: string, trigger?: HTMLElement) {
    const targetProject = projectsRef.current.find((project) => project.id === projectId);
    const targetSession = targetProject?.sessions.find((session) => session.id === sessionId);

    if (
      !targetProject ||
      !targetSession ||
      shouldSkipProjectPermission(targetProject)
    ) {
      return;
    }

    if (trigger) {
      actionMenuTriggerRef.current = trigger;
    }

    setRenameDraft({ type: "session", projectId, sessionId, value: targetSession.title });
    setOpenActionMenu(null);
  }

  // 빈 값은 저장하지 않고 편집만 닫는다.
  function restoreRenameTriggerFocus(force = false) {
    window.requestAnimationFrame(() => {
      const activeElement = document.activeElement;
      if (force || !activeElement || activeElement === document.body) {
        actionMenuTriggerRef.current?.focus();
      }
    });
  }

  function commitRenameDraft(rawValue: string, restoreFocus = false) {
    if (!renameDraft) {
      return;
    }

    const targetProject = projectsRef.current.find(
      (project) => project.id === renameDraft.projectId,
    );
    const nextValue = rawValue.trim();

    if (
      !targetProject ||
      !nextValue ||
      shouldSkipProjectPermission(targetProject)
    ) {
      setRenameDraft(null);
      restoreRenameTriggerFocus(restoreFocus);
      return;
    }

    updateSessionInProject(renameDraft.projectId, renameDraft.sessionId, (session) => ({
      ...session,
      title: nextValue,
    }));

    setRenameDraft(null);
    restoreRenameTriggerFocus(restoreFocus);
  }

  function updateRenameDraftValue(value: string) {
    setRenameDraft((currentDraft) =>
      currentDraft ? { ...currentDraft, value } : currentDraft,
    );
  }

  function handleRenameKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      commitRenameDraft(event.currentTarget.value, true);
    }

    if (event.key === "Escape") {
      event.preventDefault();
      setRenameDraft(null);
      restoreRenameTriggerFocus(true);
    }
  }

  function returnToPrimaryView() {
    const returnView = mainView;
    setSelectedSessionId(null);
    navigateTo(
      returnView === "members" && selectedProject
        ? membersReturnView
        : "projects",
    );
    window.requestAnimationFrame(() => {
      const returnTarget = mainViewReturnFocusRef.current;
      if (returnTarget?.isConnected) {
        returnTarget.focus();
      } else if (returnView === "members" && mainViewReturnFocusSelectorRef.current) {
        // 상세 데이터가 다시 붙으면 위 effect가 원래 관리 버튼으로 포커스를 복원한다.
      } else if (
        (returnView === "profile" || returnView === "settings") &&
        accountMenuTriggerRef.current?.isConnected
      ) {
        accountMenuTriggerRef.current.focus();
      } else {
        mainViewHeadingRef.current?.focus();
      }
      mainViewReturnFocusRef.current = null;
    });
  }

  // 채팅 삭제 뒤에는 빈 채팅을 만들지 않고 프로젝트 상세로 돌아간다.
  async function handleDeleteSession(
    projectId: string,
    sessionId: string,
    event: MouseEvent<HTMLButtonElement>,
  ) {
    const targetProject = projectsRef.current.find((project) => project.id === projectId);

    event.stopPropagation();

    if (!targetProject || shouldSkipProjectPermission(targetProject)) {
      return;
    }

    if (
      pendingDeleteSession?.projectId !== projectId ||
      pendingDeleteSession.sessionId !== sessionId
    ) {
      setPendingDeleteSession({ projectId, sessionId });
      setDemoStatus({
        kind: "warning",
        ok: false,
        message: "한 번 더 누르면 이 기기에 저장된 채팅과 대화 기록을 삭제합니다",
        scope: "overview",
      });
      return;
    }

    const targetSession = targetProject.sessions.find((session) => session.id === sessionId);

    if (!targetSession) {
      return;
    }
    const latestProject = projectsRef.current.find((project) => project.id === projectId);
    if (!latestProject) {
      return;
    }

    const remainingSessions = latestProject.sessions.filter((session) => session.id !== sessionId);
    const wasSelected =
      selectedProjectIdRef.current === projectId &&
      sessionId === selectedSessionIdRef.current;

    updateProject(projectId, (project) => ({
      ...project,
      sessions: remainingSessions,
    }));

    if (wasSelected) {
      setSelectedSessionId(null);
      openProjectDetail("overview");
      if (pendingProjectId === projectId && pendingSessionId === sessionId) {
        cancelActiveQueryForProject(projectId);
      }
      forgetSessionDraft(projectId, sessionId);
      showSessionDraft(projectId, null);
    } else {
      forgetSessionDraft(projectId, sessionId);
    }

    setOpenActionMenu(null);
    setPendingDeleteSession(null);

    focusPrompt();
  }

  async function handleStartProjectBriefing(project: ProjectWorkspace, projectFiles: Attachment[]) {
    const description = project.description?.trim();
    const githubName = project.githubRepository?.remoteRepo ?? project.githubRepository?.name;

    if (projectFiles.length === 0 && !description && !githubName) {
      setDemoStatus({
        ok: false,
        message: "프로젝트 설명, 파일, 폴더, GitHub 중 하나를 먼저 추가해 주세요",
        scope: "overview",
      });
      return;
    }

    if (project.serverMissing) {
      setDemoStatus({
        ok: false,
        message: "서버에서 찾을 수 없는 프로젝트에는 브리핑을 만들 수 없습니다",
        scope: "overview",
      });
      return;
    }

    if (shouldSkipProjectMutation(project, "overview")) {
      return;
    }

    const requestStartedAt = Date.now();
    const { controller, timeoutId } = beginActiveQuery();

    setSelectedProjectId(project.id);
    setSelectedSessionId(null);
    closeProjectPanel();
    setIsSending(true);
    setPendingProjectId(project.id);
    setPendingSessionId(null);
    setThinkingStartedAt(requestStartedAt);
    rememberCurrentDraft();
    resetVisibleDraft();

    try {
      // Project creation is a mutation: always receive and persist its server id,
      // then honor cancellation before starting the abortable query.
      const apiProject = await ensureApiProject(project);
      if (typeof apiProject.apiProjectId !== "number") {
        throw new Error("서버 프로젝트를 준비할 수 없습니다");
      }
      if (controller.signal.aborted) {
        throw new DOMException("Query cancelled", "AbortError");
      }

      await fetchProjectQuery(
        apiProject.apiProjectId,
        PROJECT_BRIEFING_QUESTION,
        {
          setupMode: "analyzed",
          signal: controller.signal,
        },
      );

      updateProject(project.id, (currentProject) => ({
        ...currentProject,
        setupCompletedAt: Date.now(),
        setupMode: "analyzed",
      }));
      setSelectedProjectId(project.id);
      setSelectedSessionId(null);
      openProjectDetail("overview");
      resetVisibleDraft();
    } catch (error) {
      if (!isUserCancelledQuery(error, controller)) {
        setDemoStatus({
          ok: false,
          message: getQueryErrorMessage(error),
          projectId: project.id,
          scope: "overview",
        });
      }
      setSelectedSessionId(null);
      navigateTo("project-setup");
      resetVisibleDraft();
    } finally {
      if (finishActiveQuery(controller, timeoutId)) {
        setIsSending(false);
        setPendingProjectId(null);
        setPendingSessionId(null);
        setThinkingStartedAt(null);
      }
    }
  }

  function handleDismissProjectDelta() {
    if (!selectedProjectDelta) {
      return;
    }

    ignoredProjectDeltaRef.current[selectedProjectDelta.projectId] = selectedProjectDelta.since;
    markProjectSeen(selectedProjectDelta.projectId);
    setProjectDeltaBanner(null);
  }

  function handleRequestProjectDeltaBriefing() {
    if (
      !selectedProject ||
      !selectedProjectDelta ||
      selectedProject.serverMissing ||
      typeof selectedProject.apiProjectId !== "number" ||
      isSending
    ) {
      return;
    }

    if (shouldSkipProjectMutation(selectedProject, "overview")) {
      return;
    }

    const targetProjectId = selectedProject.id;
    const since = selectedProjectDelta.since;
    const question =
      settings.language === "ko"
        ? `지난 확인 시점(${since}) 이후 프로젝트에서 달라진 점을 진행, 신규, 긴급 순서로 브리핑해줘.`
        : `Brief me on what changed in this project since ${since}, ordered by progress, new items, and urgency.`;

    void handleSubmit(undefined, {
      forceNewSession: true,
      intent: "delta_briefing",
      preserveCurrentDraft: true,
      question,
      sessionTitle: settings.language === "ko" ? "변경사항 브리핑" : "Change briefing",
      since,
      onSuccess: () => {
        ignoredProjectDeltaRef.current[targetProjectId] = since;
        markProjectSeen(targetProjectId);
        setProjectDeltaBanner(null);
      },
    });
  }

  // 프로젝트 삭제 후에는 남은 프로젝트로 선택을 옮기고, 마지막이면 빈 상태로 둔다.
  async function handleDeleteProject(projectId: string, event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();

    const targetProject = projects.find((project) => project.id === projectId);

    if (!targetProject) {
      return;
    }

    if (shouldSkipProjectPermission(targetProject, "overview", "owner")) {
      return;
    }

    if (pendingDeleteProjectId !== projectId) {
      setPendingDeleteProjectId(projectId);
      setDemoStatus({
        kind: "warning",
        ok: false,
        message:
          typeof targetProject.apiProjectId === "number"
            ? "한 번 더 누르면 서버 프로젝트 자료와 이 기기의 채팅을 삭제합니다"
            : "한 번 더 누르면 로컬 프로젝트를 삭제합니다",
        scope: "overview",
      });
      return;
    }

    clearGithubRepositoryPollsForProject(projectId);
    if (!(await deleteServerProject(targetProject))) {
      resumeGithubRepositoryPollIfNeeded(projectId);
      return;
    }

    cancelGithubOperation(projectId);
    cancelProjectFileImport(projectId);
    (targetProject.files ?? []).forEach((attachment) =>
      cancelProjectDocumentUploads(projectId, attachment),
    );

    const currentProjects = projectsRef.current;
    const remainingProjects = currentProjects.filter((project) => project.id !== projectId);

    if (remainingProjects.length === currentProjects.length) {
      return;
    }

    const wasSelected = projectId === selectedProjectIdRef.current;
    const nextState = createProjectState(
      remainingProjects,
      selectedProjectIdRef.current,
      selectedSessionIdRef.current,
    );

    applyProjectState(nextState);
    forgetProjectDrafts(projectId);
    setPendingDeleteProjectId(null);
    if (pendingProjectId === projectId) {
      cancelActiveQueryForProject(projectId);
    }
    setOpenActionMenu(null);

    if (wasSelected) {
      setSelectedSessionId(null);
      navigateTo("projects");
      showSessionDraft(nextState.selectedProjectId ?? "", null);
    }
  }

  // 렌더링이 끝난 뒤 채팅 입력창으로 포커스를 복원한다.
  function focusPrompt() {
    window.requestAnimationFrame(() => {
      promptTextareaRef.current?.focus();
    });
  }

  function getSessionDraftKey(projectId: string, sessionId: string | null) {
    return `${projectId}\u0000${sessionId ?? "__project_detail__"}`;
  }

  function persistSessionDrafts() {
    const didSave = saveSessionDrafts(
      sessionDraftStorageKey,
      sessionDraftsRef.current,
    );
    reportLocalPersistenceResult("draft", didSave);
    return didSave;
  }

  function persistDraft(
    projectId: string,
    sessionId: string | null,
    nextPrompt: string,
    nextAttachments: Attachment[],
    allowProjectDetail: boolean,
  ) {
    if (!projectId || (!sessionId && !allowProjectDetail)) {
      return;
    }

    const key = getSessionDraftKey(projectId, sessionId);
    if (!nextPrompt.trim() && nextAttachments.length === 0) {
      sessionDraftsRef.current.delete(key);
    } else {
      sessionDraftsRef.current.set(key, {
        attachments: [...nextAttachments],
        prompt: nextPrompt,
      });
    }
    persistSessionDrafts();
  }

  function handlePromptChange(nextPrompt: string) {
    setPrompt(nextPrompt);

    const projectId = selectedProjectIdRef.current;
    const sessionId = selectedSessionIdRef.current;
    persistDraft(
      projectId ?? "",
      sessionId,
      nextPrompt,
      attachmentsRef.current,
      mainViewRef.current === "project-detail",
    );
  }

  // 상세 composer와 각 채팅을 떠나도 작성 중인 텍스트·첨부가 남도록
  // 프로젝트/세션별 초안을 메모리에 보관한다.
  function rememberCurrentDraft() {
    const isVisibleChatDraft =
      mainViewRef.current === "chat" && Boolean(selectedSessionId);
    const isVisibleProjectDetailDraft =
      mainViewRef.current === "project-detail" && !selectedSessionId;
    if (
      !selectedProjectId ||
      (!isVisibleChatDraft && !isVisibleProjectDetailDraft)
    ) {
      return;
    }

    // 세션 전환 클릭은 React state commit보다 먼저 들어올 수 있으므로 현재 DOM 값을 우선한다.
    const currentPrompt = promptTextareaRef.current?.value ?? prompt;
    persistDraft(
      selectedProjectId,
      selectedSessionId,
      currentPrompt,
      attachmentsRef.current,
      mainViewRef.current === "project-detail",
    );
  }

  function showSessionDraft(projectId: string, sessionId: string | null) {
    const draft = projectId
      ? sessionDraftsRef.current.get(getSessionDraftKey(projectId, sessionId))
      : undefined;

    const nextAttachments = draft ? [...draft.attachments] : [];
    attachmentsRef.current = nextAttachments;
    setPrompt(draft?.prompt ?? "");
    setAttachments(nextAttachments);
  }

  function forgetSessionDraft(projectId: string, sessionId: string | null) {
    sessionDraftsRef.current.delete(getSessionDraftKey(projectId, sessionId));
    persistSessionDrafts();
  }

  function forgetProjectDrafts(projectId: string) {
    const prefix = `${projectId}\u0000`;
    let didChange = false;
    Array.from(sessionDraftsRef.current.keys()).forEach((key) => {
      if (key.startsWith(prefix)) {
        sessionDraftsRef.current.delete(key);
        didChange = true;
      }
    });
    if (didChange) {
      persistSessionDrafts();
    }
  }

  function resetVisibleDraft() {
    attachmentsRef.current = [];
    setPrompt("");
    setAttachments([]);
  }

  function handleSelectSession(projectId: string, sessionId: string) {
    rememberCurrentDraft();
    navigateTo("chat");
    setSelectedProjectId(projectId);
    setSelectedSessionId(sessionId);
    showSessionDraft(projectId, sessionId);
    focusPrompt();
  }

  async function handleCopy(message: Message) {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedMessageId(message.id);
      window.setTimeout(() => setCopiedMessageId(null), 1200);
    } catch {
      setDemoStatus({
        kind: "error",
        message: "응답을 복사할 수 없습니다",
        ok: false,
        scope: "overview",
      });
    }
  }

  async function handlePickFiles() {
    if (
      !selectedProject ||
      (!selectedSession && mainView !== "project-detail")
    ) {
      return;
    }
    if (!capabilities) {
      setDemoStatus({
        ok: false,
        message: capabilitiesError || "지원 파일 정보를 불러오는 중입니다",
        scope: "overview",
      });
      return;
    }

    const selectedPaths = await open({
      multiple: true,
      directory: false,
      filters: [{ name: t("지원 문서"), extensions: queryAttachmentExtensions }],
      title: t("PaiM에 첨부할 파일 선택"),
    });

    if (!selectedPaths) {
      return;
    }

    const paths = Array.isArray(selectedPaths) ? selectedPaths : [selectedPaths];
    await appendAttachmentPaths(paths);
  }

  // 여러 파일 경로를 현재 초안 첨부 목록에 추가한다.
  async function appendAttachmentPaths(paths: string[]) {
    if (
      !selectedProject ||
      (!selectedSession && mainView !== "project-detail") ||
      paths.length === 0
    ) {
      return;
    }

    if (!capabilities) {
      setDemoStatus({
        ok: false,
        message: capabilitiesError || "지원 파일 정보를 불러오는 중입니다",
        scope: "overview",
      });
      return;
    }
    if (paths.some((path) => isKnownAudioFileName(getFileName(path)))) {
      setDemoStatus({
        kind: "warning",
        ok: false,
        message:
          "음성 파일은 프로젝트 자료함의 회의 녹음 업로드를 이용해 주세요.",
        scope: "overview",
      });
      return;
    }
    const supportedPaths = paths.filter((path) =>
      supportsExtension(getFileName(path), queryAttachmentExtensions),
    );
    const skippedCount = paths.length - supportedPaths.length;
    if (supportedPaths.length !== paths.length) {
      setDemoStatus({
        kind: "warning",
        ok: false,
        message: t("{added}개 추가 · {skipped}개 제외 — 지원 형식: {formats}", {
          added: supportedPaths.length,
          skipped: skippedCount,
          formats: formatExtensions(queryAttachmentExtensions),
        }),
        scope: "overview",
      });
    }
    if (supportedPaths.length === 0) {
      return;
    }

    const targetProjectId = selectedProject.id;
    const targetSessionId = selectedSession?.id ?? null;
    const targetView = mainView === "project-detail" ? "project-detail" : "chat";
    const targetDraftKey = getSessionDraftKey(targetProjectId, targetSessionId);
    const targetDraftWasPresent = sessionDraftsRef.current.has(targetDraftKey);
    const targetDraftSnapshot: SessionDraft = {
      attachments: [...attachmentsRef.current],
      prompt: promptTextareaRef.current?.value ?? prompt,
    };
    const nextAttachments = await Promise.all(supportedPaths.map(createAttachment));

    const targetProject = projectsRef.current.find(
      (project) => project.id === targetProjectId,
    );
    if (
      !targetProject ||
      (targetSessionId !== null &&
        !targetProject.sessions.some((session) => session.id === targetSessionId))
    ) {
      return;
    }

    const isTargetContextVisible =
      selectedProjectIdRef.current === targetProjectId &&
      selectedSessionIdRef.current === targetSessionId &&
      mainViewRef.current === targetView;

    if (isTargetContextVisible) {
      const updatedAttachments = [...attachmentsRef.current, ...nextAttachments];
      attachmentsRef.current = updatedAttachments;
      setAttachments(updatedAttachments);
      persistDraft(
        targetProjectId,
        targetSessionId,
        promptTextareaRef.current?.value ?? prompt,
        updatedAttachments,
        targetView === "project-detail",
      );
      return;
    }

    const latestTargetDraft = sessionDraftsRef.current.get(targetDraftKey);
    const targetDraftBase =
      latestTargetDraft ??
      (targetDraftWasPresent
        ? { attachments: [], prompt: "" }
        : targetDraftSnapshot);
    persistDraft(
      targetProjectId,
      targetSessionId,
      targetDraftBase.prompt,
      [...targetDraftBase.attachments, ...nextAttachments],
      targetView === "project-detail",
    );
  }

  // 로컬 이미지 파일이면 프론트 표시용 미리보기 URL을 만든다.
  async function createAttachmentPreviewUrl(path: string) {
    try {
      const previewUrl = await invoke<string | null>("create_attachment_preview", { path });
      return previewUrl;
    } catch {
      return null;
    }
  }

  // 선택한 파일의 기본 정보와 이미지 미리보기 URL을 만든다.
  async function createAttachment(path: string): Promise<Attachment> {
    const attachment: Attachment = {
      id: createId("attachment"),
      name: getFileName(path),
      path,
    };
    const previewUrl = await createAttachmentPreviewUrl(path);

    if (previewUrl) {
      attachment.previewUrl = previewUrl;
    }

    return attachment;
  }

  // 저장된 세션을 다시 열 때 파일 경로로 이미지 미리보기를 복원한다.
  async function hydrateStoredAttachmentPreviews() {
    let didChange = false;
    const hydratedProjects = await Promise.all(
      projects.map(async (project) => ({
        ...project,
        sessions: await Promise.all(
          project.sessions.map(async (session) => ({
            ...session,
            messages: await Promise.all(
              session.messages.map(async (message) => {
                if (!message.attachments || message.attachments.length === 0) {
                  return message;
                }

                const attachments = await Promise.all(
                  message.attachments.map(async (attachment) => {
                    if (attachment.previewUrl) {
                      return attachment;
                    }

                    const previewUrl = await createAttachmentPreviewUrl(attachment.path);

                    if (!previewUrl) {
                      return attachment;
                    }

                    didChange = true;
                    return { ...attachment, previewUrl };
                  }),
                );

                return { ...message, attachments };
              }),
            ),
          })),
        ),
      })),
    );

    if (!didChange) {
      return;
    }

    setProjects((currentProjects) =>
      currentProjects.map(
        (currentProject) =>
          hydratedProjects.find((project) => project.id === currentProject.id) ?? currentProject,
      ),
    );
  }

  function removeAttachment(attachmentId: string) {
    const updatedAttachments = attachmentsRef.current.filter(
      (attachment) => attachment.id !== attachmentId,
    );
    attachmentsRef.current = updatedAttachments;
    setAttachments(updatedAttachments);
    persistDraft(
      selectedProjectIdRef.current ?? "",
      selectedSessionIdRef.current,
      promptTextareaRef.current?.value ?? prompt,
      updatedAttachments,
      mainViewRef.current === "project-detail",
    );
  }

  async function handleSubmit(
    event?: FormEvent<HTMLFormElement>,
    options: SubmitQuestionOptions = {},
  ) {
    event?.preventDefault();
    const hasQuestionOverride = typeof options.question === "string";
    const trimmedPrompt = (options.question ?? prompt).trim();
    const messageAttachments = hasQuestionOverride ? [] : attachments;

    if (!selectedProject || (!trimmedPrompt && messageAttachments.length === 0) || isSending) {
      return;
    }

    if (selectedProject.serverMissing) {
      setDemoStatus({
        ok: false,
        message: "서버에서 찾을 수 없는 프로젝트에는 질문을 보낼 수 없습니다",
        scope: "overview",
      });
      return;
    }

    if (shouldSkipProjectMutation(selectedProject, "overview")) {
      return;
    }

    const sourceSessionId = selectedSession?.id ?? null;
    if (options.preserveCurrentDraft) {
      rememberCurrentDraft();
    }

    let targetSession = options.forceNewSession ? null : selectedSession;
    if (!targetSession) {
      if (
        (!options.forceNewSession && mainView !== "project-detail") ||
        !isProjectSetupComplete(selectedProject)
      ) {
        return;
      }

      const initialSessionTitle = (
        options.sessionTitle ||
        trimmedPrompt ||
        messageAttachments[0]?.name ||
        (settings.language === "ko" ? "새 채팅" : "New chat")
      ).slice(0, 32);
      targetSession = createEmptySession(initialSessionTitle);
      const nextSession = targetSession;
      flushSync(() => {
        updateProject(selectedProject.id, (project) => ({
          ...project,
          sessions: [nextSession, ...project.sessions],
        }));
        navigateTo("chat");
        setSelectedProjectId(selectedProject.id);
        setSelectedSessionId(nextSession.id);
      });
    }

    const targetProjectId = selectedProject.id;
    const targetSessionId = targetSession.id;
    const question = trimmedPrompt || "첨부 파일을 확인해줘";
    const nextSessionTitle =
      options.sessionTitle ||
      (targetSession.title === "New Chat"
        ? (trimmedPrompt || messageAttachments[0]?.name || "File attachment").slice(0, 32)
        : targetSession.title);
    const previousMessage =
      targetSession.messages[targetSession.messages.length - 2];
    const previousError =
      targetSession.messages[targetSession.messages.length - 1];
    const latestMessage =
      targetSession.messages[targetSession.messages.length - 1];
    const isRetryingPendingMessageAfterError =
      previousMessage?.role === "user" &&
      previousMessage.content === question &&
      previousError?.role === "error";
    const isRetryingPendingMessageAfterCancellation =
      latestMessage?.role === "user" &&
      latestMessage.content === question;
    const queryMessageAttachments = isRetryingPendingMessageAfterError
      ? previousMessage.attachments ?? []
      : isRetryingPendingMessageAfterCancellation
        ? latestMessage.attachments ?? []
        : messageAttachments;
    const history = createQueryHistory(
      isRetryingPendingMessageAfterError
        ? targetSession.messages.slice(0, -2)
        : isRetryingPendingMessageAfterCancellation
          ? targetSession.messages.slice(0, -1)
        : targetSession.messages,
    );
    const userMessage: Message = {
      id: createId("user"),
      role: "user",
      content: question,
      attachments: messageAttachments,
    };
    const requestStartedAt = Date.now();
    const { controller, timeoutId } = beginActiveQuery();

    setIsSending(true);
    setPendingProjectId(targetProjectId);
    setPendingSessionId(targetSessionId);
    setThinkingStartedAt(requestStartedAt);
    shouldStickToChatBottomRef.current = true;
    setShowLatestMessageButton(false);
    updateSessionInProject(targetProjectId, targetSessionId, (session) => ({
      ...session,
      title: nextSessionTitle,
      messages: isRetryingPendingMessageAfterError
        ? session.messages.slice(0, -1)
        : isRetryingPendingMessageAfterCancellation
          ? session.messages
          : [...session.messages, userMessage],
    }));
    forgetSessionDraft(targetProjectId, targetSessionId);
    if (!options.preserveCurrentDraft) {
      forgetSessionDraft(targetProjectId, sourceSessionId);
    }
    resetVisibleDraft();

    try {
      let queryAttachments: ApiQueryAttachment[] = [];
      if (queryMessageAttachments.length > 0) {
        if (canUseTauriDialog()) {
          queryAttachments = await Promise.all(
            queryMessageAttachments.map(readQueryAttachment),
          );
          const totalBytes = queryAttachments.reduce(
            (total, attachment) => total + getBase64ByteLength(attachment.content_base64),
            0,
          );
          if (
            capabilities &&
            totalBytes > capabilities.query_attachments.max_total_bytes
          ) {
            throw new Error(
              `전체 첨부 파일은 ${formatBytesAsMiB(
                capabilities.query_attachments.max_total_bytes,
              )}를 초과할 수 없습니다`,
            );
          }
          if (controller.signal.aborted) {
            throw new DOMException("Query cancelled", "AbortError");
          }
        } else {
          setDemoStatus({
            ok: true,
            message: "브라우저 모드에서는 채팅 첨부를 LLM에 전달하지 않습니다",
            scope: "overview",
          });
        }
      }

      // 프로젝트 생성은 서버 mutation이지만 개인 채팅과 history는 로컬에만 둔다.
      const apiProject = await ensureApiProject(selectedProject);

      if (typeof apiProject.apiProjectId !== "number") {
        throw new Error("서버 프로젝트를 준비할 수 없습니다");
      }
      if (controller.signal.aborted) {
        throw new DOMException("Query cancelled", "AbortError");
      }

      const response = await fetchProjectQuery(
        apiProject.apiProjectId,
        question,
        {
          attachments: queryAttachments,
          history,
          intent: options.intent,
          signal: controller.signal,
          since: options.since,
        },
      );
      const thinkingSeconds = Math.max(1, Math.ceil((Date.now() - requestStartedAt) / 1000));

      updateSessionInProject(targetProjectId, targetSessionId, (session) => ({
        ...session,
        messages: [
          ...session.messages,
          {
            id: createId("assistant"),
            role: "assistant",
            content: response.answer,
            sources: response.sources?.filter(Boolean),
            thinkingSeconds,
          },
        ],
      }));
      options.onSuccess?.();
    } catch (error) {
      if (!isUserCancelledQuery(error, controller)) {
        updateSessionInProject(targetProjectId, targetSessionId, (session) => ({
          ...session,
          messages: [
            ...session.messages,
            {
              id: createId("error"),
              role: "error",
              content: t(getQueryErrorMessage(error)),
            },
          ],
        }));
      }
    } finally {
      if (finishActiveQuery(controller, timeoutId)) {
        setIsSending(false);
        setPendingProjectId(null);
        setPendingSessionId(null);
        setThinkingStartedAt(null);
      }
    }
  }

  // 채팅 앱의 기본 키보드 동작으로 Enter 전송, Shift+Enter 줄바꿈을 처리한다.
  function handlePromptKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }

    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  function handleChromeDragStart(event: ReactPointerEvent<HTMLDivElement>) {
    if (isWindows || event.button !== 0 || isWindowControlTarget(event.target)) {
      return;
    }

    void getCurrentWindow().startDragging();
  }

  function handleChromeToggleMaximize(event: MouseEvent<HTMLDivElement>) {
    if (isWindows || isWindowControlTarget(event.target)) {
      return;
    }

    void getCurrentWindow().toggleMaximize();
  }

  function handleProjectMembersChange(
    _members: ProjectMember[],
    currentRole: ProjectRole | null,
  ) {
    const localProjectId = selectedProject?.id;
    const apiProjectId = selectedProject?.apiProjectId;
    if (!localProjectId || typeof apiProjectId !== "number") {
      return;
    }

    updateProject(localProjectId, (project) => ({
      ...project,
      currentUserRole: currentRole,
    }));
  }

  function handleLeaveSelectedProject() {
    if (!selectedProject) {
      return;
    }

    const remainingProjects = projectsRef.current.filter(
      (project) => project.id !== selectedProject.id,
    );
    cancelActiveQueryForProject(selectedProject.id);
    const nextState = createProjectState(remainingProjects, null, null);
    applyProjectState(nextState);
    forgetProjectDrafts(selectedProject.id);
    navigateTo("projects");
    setOpenActionMenu(null);
    showSessionDraft(nextState.selectedProjectId ?? "", null);
    mainViewReturnFocusRef.current = null;
    mainViewReturnFocusSelectorRef.current = null;
    window.requestAnimationFrame(() => {
      const focusTarget =
        promptTextareaRef.current ??
        mainViewHeadingRef.current ??
        document.querySelector<HTMLElement>(".project-create-trigger, .portfolio-create-button");
      focusTarget?.focus({ preventScroll: true });
    });
  }

  function renderMembersPage() {
    return (
      <WorkspacePageLayout
        ariaLabel={t("프로젝트 멤버 관리")}
        className="members-page"
        contentClassName="members-page-content"
      >
          <header className="settings-header members-page-header">
            <Button
              className="settings-back-button"
              icon={<ArrowLeft size={15} />}
              isIconOnly
              label={t("멤버 관리에서 돌아가기")}
              onClick={returnToPrimaryView}
              tooltip={t("돌아가기")}
              variant="ghost"
            />
            <div className="settings-header-copy">
              <h1 ref={mainViewHeadingRef} tabIndex={-1}>{t("멤버 관리")}</h1>
              {selectedProject ? <p>{selectedProject.name}</p> : null}
            </div>
          </header>

          {authUser && typeof selectedProject?.apiProjectId === "number" ? (
            <Suspense fallback={<PanelLoadingState label={t("멤버를 불러오는 중")} />}>
              <LazyProjectMembersPanel
                currentUser={authUser}
                onLeaveProject={handleLeaveSelectedProject}
                onMembersChange={handleProjectMembersChange}
                projectId={selectedProject.apiProjectId}
              />
            </Suspense>
          ) : (
            <Banner
              container="card"
              status="warning"
              title={t("로그인된 서버 프로젝트에서만 멤버를 관리할 수 있습니다.")}
            />
          )}
      </WorkspacePageLayout>
    );
  }

  function renderProjectPortfolio() {
    return (
      <ProjectPortfolioPage
        language={settings.language}
        localProjects={projects}
        onCreateProject={() => createProjectFromName(createNextProjectName(projects))}
        onOpenProject={handleOpenProjectDetail}
      />
    );
  }

  function renderProfilePage() {
    return (
      <WorkspacePageLayout
        ariaLabel={t("프로필")}
        className="profile-page"
        contentClassName="profile-content"
      >
          <header className="settings-header">
            <Button
              className="settings-back-button"
              icon={<ArrowLeft size={15} />}
              isIconOnly
              label={t("프로필에서 돌아가기")}
              onClick={returnToPrimaryView}
              tooltip={t("돌아가기")}
              variant="ghost"
            />
            <div className="settings-header-copy">
              <h1 ref={mainViewHeadingRef} tabIndex={-1}>{t("프로필")}</h1>
            </div>
          </header>

          <section className="profile-identity-card" aria-label={t("계정 정보")}>
            <AccountAvatar className="profile-avatar" user={authUser} />
            <div className="profile-identity-copy">
              <h2>{accountDisplayName}</h2>
              <p>{accountEmail}</p>
            </div>
          </section>

          <dl className="profile-details" aria-label={t("프로필 세부 정보")}>
            <div>
              <dt>{t("가입일")}</dt>
              <dd>{formatAccountCreatedAt(authUser?.created_at, settings.language)}</dd>
            </div>
            <div>
              <dt>{t("서비스 상태")}</dt>
              <dd>
                <span className="profile-connection" data-status={serverStatus}>
                  <span aria-hidden="true" className="profile-connection-dot" />
                  {serverStatus === "online" ? t("연결됨") : t("오프라인")}
                </span>
              </dd>
            </div>
          </dl>

          {authUser ? (
            <p className="profile-note">
              {t("계정 정보는 PaiM에서 안전하게 관리됩니다.")}
            </p>
          ) : (
            <Banner
              container="card"
              status="warning"
              title={t("오프라인 또는 인증이 없는 개발 서버를 사용 중입니다.")}
            />
          )}
      </WorkspacePageLayout>
    );
  }

  function renderSettingsPage() {
    return (
      <WorkspacePageLayout
        ariaLabel={t("설정")}
        className="settings-page"
        contentClassName="settings-content"
      >
          <header className="settings-header">
            <Button
              className="settings-back-button"
              icon={<ArrowLeft size={15} />}
              isIconOnly
              label={t("설정에서 돌아가기")}
              onClick={returnToPrimaryView}
              tooltip={t("돌아가기")}
              variant="ghost"
            />
            <div className="settings-header-copy">
              <h1 ref={mainViewHeadingRef} tabIndex={-1}>{t("설정")}</h1>
            </div>
          </header>

          <section className="settings-group" aria-label={t("테마")}>
            <div className="settings-copy">
              <h2>{t("테마")}</h2>
              <p>{t("시스템 설정을 따르거나 PaiM 화면만 고정합니다.")}</p>
            </div>
            <SegmentedControl
              label={t("테마 선택")}
              layout="fill"
              onChange={(value) => handleThemeChange(value as ThemeSetting)}
              size="sm"
              value={settings.theme}
            >
              <SegmentedControlItem label={t("시스템")} value="system" />
              <SegmentedControlItem label={t("다크")} value="dark" />
              <SegmentedControlItem label={t("라이트")} value="light" />
            </SegmentedControl>
          </section>

          <section className="settings-group" aria-label={t("화면 확대")}>
            <div className="settings-copy">
              <h2>{t("화면 확대")}</h2>
              <p>{t("텍스트와 인터페이스를 50%에서 200%까지 5% 단위로 조절합니다.")}</p>
            </div>
            <div className="settings-range">
              <Suspense fallback={<div className="settings-control-skeleton" aria-hidden="true" />}>
                <LazySlider
                  formatValue={(value: number) => `${Math.round(value * 100)}%`}
                  isLabelHidden
                  label={t("화면 확대")}
                  max={MAX_ZOOM_SCALE}
                  min={MIN_ZOOM_SCALE}
                  onChange={applyZoomScale}
                  step={ZOOM_STEP}
                  value={zoomScale}
                  valueDisplay="none"
                  width="100%"
                />
              </Suspense>
              <strong>{Math.round(zoomScale * 100)}%</strong>
            </div>
          </section>

          <section className="settings-group" aria-label={t("언어")}>
            <div className="settings-copy">
              <h2>{t("언어")}</h2>
              <p>{t("PaiM 전체 표시 언어를 선택합니다.")}</p>
            </div>
            <SegmentedControl
              label={t("언어 선택")}
              layout="fill"
              onChange={(value) => handleLanguageChange(value as LanguageSetting)}
              size="sm"
              value={settings.language}
            >
              <SegmentedControlItem label={t("한국어")} value="ko" />
              <SegmentedControlItem label="English" value="en" />
            </SegmentedControl>
          </section>

          <section className="settings-group" aria-label={t("완료 제안 민감도")}>
            <div className="settings-copy">
              <h2>{t("완료 제안 민감도")}</h2>
              <p>{t("서버 제안은 유지하고 인박스 표시만 조절합니다.")}</p>
            </div>
            <SegmentedControl
              label={t("완료 제안 민감도 선택")}
              layout="fill"
              onChange={(value) =>
                updateSettings({ suggestionMin: value as SuggestionMinConfidence })
              }
              size="sm"
              value={settings.suggestionMin}
            >
              <SegmentedControlItem label={t("확실할 때만")} value="high" />
              <SegmentedControlItem label={t("추정 포함")} value="medium" />
            </SegmentedControl>
          </section>

          <section className="settings-group" aria-label={t("마감 임박 기준")}>
            <div className="settings-copy">
              <h2>{t("마감 임박 기준")}</h2>
              <p>{t("델타 배너의 마감 임박 범위를 1일부터 7일까지 조절합니다.")}</p>
            </div>
            <div className="settings-range">
              <Suspense fallback={<div className="settings-control-skeleton" aria-hidden="true" />}>
                <LazySlider
                  formatValue={(value: number) => t("{count}일", { count: value })}
                  isLabelHidden
                  label={t("마감 임박 기준")}
                  max={7}
                  min={1}
                  onChange={(value: number) => updateSettings({ dueSoonDays: value })}
                  value={settings.dueSoonDays}
                  valueDisplay="none"
                  width="100%"
                />
              </Suspense>
              <strong>{t("{count}일", { count: settings.dueSoonDays })}</strong>
            </div>
          </section>

          <section className="settings-group settings-danger-group" aria-label={t("앱 설정 초기화")}>
            <div className="settings-copy">
              <h2>{t("앱 설정 초기화")}</h2>
              <p aria-live="polite">
                {isSettingsResetConfirming
                  ? t("계속하려면 초기화를 확인하세요. 화면·언어·분석 표시와 패널 배치만 기본값으로 되돌립니다.")
                  : t("프로젝트·대화·계정은 유지하고 앱 설정만 기본값으로 되돌립니다.")}
              </p>
            </div>
            <div className="settings-confirm-actions">
              {isSettingsResetConfirming ? (
                <Button
                  label={t("취소")}
                  onClick={() => setIsSettingsResetConfirming(false)}
                  variant="secondary"
                />
              ) : null}
              <Button
                label={isSettingsResetConfirming ? t("설정 초기화") : t("앱 설정 초기화")}
                onClick={handleResetAppSettings}
                variant={isSettingsResetConfirming ? "destructive" : "secondary"}
              />
            </div>
          </section>

          <section className="settings-group" aria-label={t("버전")}>
            <div className="settings-copy">
              <h2>{t("버전")}</h2>
              <p>
                {t("현재 {version}{latest}", {
                  latest: latestReleaseTag ? t(" · 최신 {tag}", { tag: latestReleaseTag }) : "",
                  version: appVersion,
                })}
              </p>
            </div>
            <Button
              label={t("릴리즈 페이지 열기")}
              onClick={handleOpenReleasePage}
              variant="secondary"
            />
          </section>
      </WorkspacePageLayout>
    );
  }

  function renderProjectSetupMemorySummary() {
    if (!selectedProject) {
      return null;
    }

    return (
      <>
        <div>
          <p className="project-setup-slots-title">{t("추출될 항목")}</p>
          <p className="project-setup-slots-hint">
            {canOpenProjectMemory
              ? t("서버 프로젝트 메모리 개수를 표시합니다")
              : t("자료 업로드 후 서버 메모리 개수를 표시합니다")}
          </p>
        </div>
        <div className="project-setup-slot-list">
          <div
            className="project-setup-slot"
            data-kind="action"
            data-state={getProjectMemorySlotState(
              canOpenProjectMemory,
              selectedProjectMemorySlotCounts.action,
            )}
          >
            <Zap size={13} />
            <span>{t("액션")}</span>
            <strong>
              {canOpenProjectMemory ? selectedProjectMemorySlotCounts.action : "—"}
            </strong>
          </div>
          <div
            className="project-setup-slot"
            data-kind="decision"
            data-state={getProjectMemorySlotState(
              canOpenProjectMemory,
              selectedProjectMemorySlotCounts.decision,
            )}
          >
            <Check size={13} />
            <span>{t("결정")}</span>
            <strong>
              {canOpenProjectMemory ? selectedProjectMemorySlotCounts.decision : "—"}
            </strong>
          </div>
          <div
            className="project-setup-slot"
            data-kind="issue"
            data-state={getProjectMemorySlotState(
              canOpenProjectMemory,
              selectedProjectMemorySlotCounts.issue,
            )}
          >
            <AlertTriangle size={13} />
            <span>{t("이슈")}</span>
            <strong>
              {canOpenProjectMemory ? selectedProjectMemorySlotCounts.issue : "—"}
            </strong>
          </div>
          <div
            className="project-setup-slot"
            data-kind="risk"
            data-state={getProjectMemorySlotState(
              canOpenProjectMemory,
              selectedProjectMemorySlotCounts.risk,
            )}
          >
            <Flag size={13} />
            <span>{t("리스크")}</span>
            <strong>
              {canOpenProjectMemory ? selectedProjectMemorySlotCounts.risk : "—"}
            </strong>
          </div>
        </div>
        <p className="project-setup-slots-foot">
          {t("업로드와 분석 결과가 서버에 반영되면 자동으로 갱신됩니다.")}
        </p>
      </>
    );
  }

  const sidebarToggleLabel = isHighZoomViewport
    ? t("사이드바를 펼치려면 창을 넓혀주세요")
    : t(isSidebarCollapsed ? "사이드바 펼치기" : "사이드바 접기");
  const sidebarToggleControl = hasProjects ? (
    <Tooltip
      alignment="center"
      content={sidebarToggleLabel}
      delay={650}
      hasHoverIndication={false}
      placement="below"
    >
      <IconButton
        className="sidebar-collapse-button"
        icon={<PanelLeft size={16} />}
        isDisabled={isHighZoomViewport}
        label={sidebarToggleLabel}
        onClick={handleToggleSidebar}
        variant="ghost"
      />
    </Tooltip>
  ) : null;

  return (
    <I18nProvider language={settings.language}>
      <Theme theme={neutralTheme} mode={settings.theme}>
        <AppShell
          className="paim-app-shell"
          contentPadding={0}
          height="fill"
          variant="wash"
        >
          <div
            className="app-shell"
            data-drag-active={isDragActive}
            data-drag-zone={activeDropZone ?? undefined}
            data-language={settings.language}
            data-high-zoom-layout={isHighZoomViewport}
            data-main-view={mainView}
            data-platform={isWindows ? "windows" : isMac ? "macos" : "native"}
            data-project-panel={showProjectPanel ? "true" : "false"}
            data-project-panel-overlay={isProjectPanelOverlay ? "true" : "false"}
            data-project-panel-state={visibleProjectPanelMode}
            data-project-file-tree-resizing={isProjectFileTreeResizing}
            data-sidebar-collapsed={isSidebarCollapsedForLayout}
            data-sidebar-empty={!hasProjects}
            data-sidebar-resizing={isSidebarResizing}
            onClick={() => setOpenActionMenu(null)}
            style={appShellStyle}
          >
        {isWindows ? <WindowsTitlebar inert={shouldInertBackgroundForProjectPanel} /> : null}
        {showProjectPanel && selectedProject ? (
          <>
            <div className="project-panel-header-meta" aria-label={t("프로젝트 상태")}>
              <span
                className="project-panel-header-meta-item"
                aria-label={t("자료 {count}개", { count: selectedProjectFileCount })}
              >
                <Files aria-hidden="true" size={13} />
                <span>{t("{count}개", { count: selectedProjectFileCount })}</span>
              </span>
              <span
                aria-label={t("GitHub {status}", {
                  status: t(getGithubPanelStateLabel(selectedProjectGithubPanelState)),
                })}
                className="project-panel-header-meta-item"
                title={t("GitHub {status}", {
                  status: t(getGithubPanelStateLabel(selectedProjectGithubPanelState)),
                })}
              >
                <GitBranch aria-hidden="true" size={13} />
                <span>GitHub</span>
                <span aria-hidden="true" className="project-panel-header-status-label">
                  · {t(getGithubPanelStateLabel(selectedProjectGithubPanelState))}
                </span>
                <span
                  aria-hidden="true"
                  className="project-panel-header-status-dot"
                  data-state={selectedProjectGithubPanelState}
                />
              </span>
            </div>
            {isProjectPanelCollapsed ? (
              <div className="project-panel-control-cluster" aria-label={t("프로젝트 패널 도구")}>
                <IconButton
                  className="project-panel-rail-toggle"
                  icon={<PanelRight size={17} />}
                  label={t("프로젝트 패널 펼치기")}
                  onClick={handleToggleProjectPanel}
                  tooltip={t("프로젝트 패널 펼치기")}
                  variant="ghost"
                />
              </div>
            ) : null}
          </>
        ) : null}
        <div
          className="app-chrome"
          aria-label={t("앱 상단 도구")}
          inert={shouldInertBackgroundForProjectPanel}
          onDoubleClick={handleChromeToggleMaximize}
          onPointerDown={handleChromeDragStart}
        >
          {isMac && sidebarToggleControl ? (
            <div className="app-chrome-sidebar-control">{sidebarToggleControl}</div>
          ) : null}
          {mainView === "chat" && selectedSession ? (
            <div className="chat-context-bar" aria-label={t("현재 채팅 정보")}>
              <div className="chat-context-primary">
                <h1
                  aria-label={`${selectedProject?.name ?? "PaiM"} ${t(selectedSession.title)}`}
                  className="chat-context-item chat-context-title"
                  id="chat-context-heading"
                  title={`${selectedProject?.name ?? "PaiM"} / ${t(selectedSession.title)}`}
                >
                  <MessageSquare aria-hidden="true" size={14} />
                  <span className="chat-context-project">{selectedProject?.name}</span>
                  <ChevronRight aria-hidden="true" className="chat-context-separator" size={12} />
                  <span>{t(selectedSession.title)}</span>
                </h1>
              </div>
            </div>
          ) : null}
        </div>
        <aside className="sidebar" inert={shouldInertBackgroundForProjectPanel}>
          <div aria-hidden="true" className="sidebar-drag-region" />
          {!isMac && sidebarToggleControl ? (
            <div className="sidebar-header">{sidebarToggleControl}</div>
          ) : null}

          <SideNav aria-label={t("프로젝트와 대화")} className="sidebar-panel">
            {hasProjects ? (
              <nav className="sidebar-nav" aria-label={t("프로젝트 작업")}>
                <Button
                  className="project-create-trigger"
                  icon={<FolderPlus size={15} />}
                  label={t("새 프로젝트")}
                  onClick={() => createProjectFromName(createNextProjectName(projects))}
                  size="sm"
                  variant="ghost"
                />
                <Button
                  aria-current={mainView === "projects" ? "page" : undefined}
                  className="project-portfolio-trigger"
                  icon={<FolderOpen size={15} />}
                  label={t("전체 프로젝트")}
                  onClick={handleOpenProjectPortfolio}
                  size="sm"
                  variant="ghost"
                />
              </nav>
            ) : null}
            {hasProjects ? (
              <section className="projects project-tree" aria-label={t("프로젝트")}>
              <h2>{t("프로젝트")}</h2>
              <div className="project-tree-list" role="list">
                {projects.map((project) => {
                  // Home에서는 전역 "전체 프로젝트"만 선택 상태로 둔다.
                  // 프로젝트/채팅 선택 표시는 실제 프로젝트 맥락 화면에서만 노출한다.
                  const isActiveProject =
                    (isPrimaryProjectContext || mainView === "members") &&
                    project.id === selectedProjectId;
                  const isProjectReady = isProjectSetupComplete(project);
                  const isOwnerProject = projectHasRole(project, "owner");

                  return (
                    <div
                      className="project-group"
                      data-active={isActiveProject ? "true" : undefined}
                      data-project-id={project.id}
                      key={project.id}
                      role="listitem"
                    >
                      <div className="project-row">
                        <div className="project-title">
                          <Button
                            aria-current={isActiveProject ? "page" : undefined}
                            className="project-item"
                            data-active={isActiveProject ? "true" : undefined}
                            data-project-id={project.id}
                            data-project-name={project.name}
                            endContent={
                              isOwnerProject ? (
                                <span className="project-owner-badge" data-role="owner">
                                  Owner
                                </span>
                              ) : undefined
                            }
                            icon={<FolderOpen size={14} />}
                            label={isOwnerProject ? `${project.name}, Owner` : project.name}
                            onClick={() => handleOpenProjectDetail(project.id)}
                            tooltip={project.name}
                            variant="ghost"
                          >
                            <span className="project-name">{project.name}</span>
                          </Button>
                        </div>
                      </div>

                      {isActiveProject && isProjectReady ? (
                        <div className="project-sessions" role="list">
                          {project.sessions.map((session) => (
                            <div
                              className="history-row"
                              data-active={
                                session.id === selectedSessionId ? "true" : undefined
                              }
                              key={session.id}
                              onContextMenu={(event) =>
                                handleSessionContextMenu(project.id, session.id, event)
                              }
                              role="listitem"
                            >
                              {renameDraft?.type === "session" &&
                              renameDraft.projectId === project.id &&
                              renameDraft.sessionId === session.id ? (
                                <div className="history-item history-rename-editor">
                                  <TextInput
                                    className="rename-input"
                                    hasAutoFocus
                                    isLabelHidden
                                    label={t("채팅 이름 변경")}
                                    onBlur={(event) =>
                                      commitRenameDraft((event.target as HTMLInputElement).value)
                                    }
                                    onChange={updateRenameDraftValue}
                                    onClick={(event) => event.stopPropagation()}
                                    onFocus={(event) =>
                                      (event.target as HTMLInputElement).select()
                                    }
                                    onKeyDown={handleRenameKeyDown}
                                    size="sm"
                                    value={renameDraft.value}
                                    width="100%"
                                  />
                                </div>
                              ) : (
                                <Button
                                  aria-current={
                                    session.id === selectedSessionId ? "page" : undefined
                                  }
                                  className="history-item"
                                  data-active={
                                    session.id === selectedSessionId ? "true" : undefined
                                  }
                                  endContent={
                                    <small className="history-age">
                                      {formatRelativeAge(session.createdAt, settings.language)}
                                    </small>
                                  }
                                  label={t(session.title)}
                                  onClick={() =>
                                    handleSelectSession(project.id, session.id)
                                  }
                                  onContextMenu={(event) =>
                                    handleSessionContextMenu(project.id, session.id, event)
                                  }
                                  variant="ghost"
                                >
                                  <span className="history-title">{t(session.title)}</span>
                                </Button>
                              )}
                              <IconButton
                                aria-expanded={
                                  openActionMenu?.type === "session" &&
                                  openActionMenu.projectId === project.id &&
                                  openActionMenu.sessionId === session.id
                                }
                                aria-haspopup="menu"
                                className="history-action-menu-button"
                                icon={<Ellipsis size={14} />}
                                label={t("{name} 메뉴", { name: session.title })}
                                onClick={(event) =>
                                  toggleSessionActionMenu(project.id, session.id, event)
                                }
                                tooltip={t("{name} 메뉴", { name: session.title })}
                                variant="ghost"
                              />
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
              </section>
            ) : null}
          </SideNav>

          <div className="sidebar-footer">
            <DropdownMenu
              button={{
                children: <span className="sidebar-account-name">{accountDisplayName}</span>,
                className: "sidebar-account-button",
                icon: (
                  <AccountAvatar className="sidebar-account-avatar" user={authUser} />
                ),
                isIconOnly: isSidebarCollapsedForLayout,
                label: t("{name} 계정 메뉴", { name: accountDisplayName }),
                ref: accountMenuTriggerRef,
                size: "sm",
                tooltip: t("{name} 계정 메뉴", { name: accountDisplayName }),
                variant: "ghost",
              }}
              className="account-menu"
              hasChevron={false}
              isMenuOpen={isAccountMenuOpen}
              menuWidth={isSidebarCollapsedForLayout ? 232 : Math.max(212, sidebarWidth - 20)}
              onClick={() => setOpenActionMenu(null)}
              onOpenChange={handleAccountMenuOpenChange}
              placement="above"
            >
              <div className="account-menu-identity" role="presentation">
                <AccountAvatar className="account-menu-avatar" user={authUser} />
                <span className="account-menu-identity-copy">
                  <strong>{accountDisplayName}</strong>
                  <small>{accountEmail}</small>
                </span>
              </div>
              <div aria-hidden="true" className="account-menu-divider" role="separator" />
              <DropdownMenuItem
                className="account-menu-profile"
                icon={<UserRound size={15} />}
                label={t("프로필")}
                onClick={() => openAccountView("profile")}
              />
              <DropdownMenuItem
                className="account-menu-settings"
                icon={<SettingsIcon size={15} />}
                label={t("설정")}
                onClick={() => openAccountView("settings")}
              />
              {canLogout ? (
                <>
                  <div aria-hidden="true" className="account-menu-divider" role="separator" />
                  <DropdownMenuItem
                    className="account-menu-logout"
                    icon={<LogOut size={15} />}
                    label={t("로그아웃")}
                    onClick={handleAccountLogout}
                  />
                </>
              ) : null}
            </DropdownMenu>
          </div>

        <div
          aria-keyshortcuts="ArrowLeft ArrowRight Home End"
          aria-label={t("사이드바 크기 조절")}
          aria-orientation="vertical"
          aria-valuemax={MAX_SIDEBAR_WIDTH}
          aria-valuemin={MIN_SIDEBAR_WIDTH}
          aria-valuenow={sidebarWidth}
          className="sidebar-resize-handle"
          onKeyDown={handleSidebarResizeKeyDown}
          onPointerDown={handleSidebarResizeStart}
          role="separator"
          tabIndex={0}
        />

        {openActionMenu && actionMenuProject ? (
          <div
            className="item-action-menu"
            data-origin={openActionMenu.origin}
            onClick={(event) => event.stopPropagation()}
            onKeyDown={handleActionMenuKeyDown}
            role="menu"
            style={{ top: openActionMenu.top, left: openActionMenu.left }}
          >
            {actionMenuSession ? (
              <>
                <Button
                  data-action="rename-session"
                  isDisabled={!canMutateActionMenuProject}
                  label={t("Name change")}
                  onClick={() => beginRenameSession(actionMenuProject.id, actionMenuSession.id)}
                  role="menuitem"
                  size="sm"
                  variant="ghost"
                />
                <Button
                  className="danger"
                  data-action="delete-session"
                  isDisabled={!canMutateActionMenuProject || isActionMenuSessionQueryPending}
                  label={
                    pendingDeleteSession?.projectId === actionMenuProject.id &&
                    pendingDeleteSession.sessionId === actionMenuSession.id
                      ? t("Delete again")
                      : t("Delete")
                  }
                  onClick={(event) =>
                    void handleDeleteSession(actionMenuProject.id, actionMenuSession.id, event)
                  }
                  role="menuitem"
                  size="sm"
                  variant="destructive"
                />
              </>
            ) : null}
          </div>
        ) : null}
      </aside>

      <LayoutContent
        className="chat"
        data-notice-count={noticeCount > 0 ? String(noticeCount) : undefined}
        data-empty-chat={
          mainView === "chat" && selectedSession?.messages.length === 0 ? "true" : undefined
        }
        isScrollable={false}
        inert={shouldInertBackgroundForProjectPanel}
        padding={0}
        style={
          showNoticeStack
            ? ({ "--notice-stack-height": `${noticeStackHeight}px` } as CSSProperties)
            : undefined
        }
      >
        {showNoticeStack ? (
          <div className="notice-stack" ref={noticeStackRef}>
            {serverStatus === "offline" ? (
              <div
                aria-live="polite"
                className="app-connection-status notice"
                data-state="offline"
                role="status"
              >
                <span className="app-connection-status-copy">
                  <span aria-hidden="true" className="app-connection-status-dot" />
                  <span>{t("오프라인 · 저장된 프로젝트 사용 중")}</span>
                </span>
                <Button
                  label={t("다시 연결")}
                  onClick={() => void syncProjectsWithServer(true)}
                  size="sm"
                  variant="ghost"
                />
              </div>
            ) : null}
            {showBackgroundQueryNotice && pendingQueryProject && pendingQuerySession ? (
              <Banner
                className="notice pending-query-notice"
                container="card"
                endContent={
                  <div className="notice-actions">
                    <Button
                      label={t("채팅으로 이동")}
                      onClick={() =>
                        handleSelectSession(pendingQueryProject.id, pendingQuerySession.id)
                      }
                      size="sm"
                      variant="primary"
                    />
                    <Button
                      label={t("응답 중지")}
                      onClick={handleCancelQuery}
                      size="sm"
                      variant="ghost"
                    />
                  </div>
                }
                status="info"
                title={t("{project} · {chat}에서 응답을 생성 중입니다", {
                  chat: t(pendingQuerySession.title),
                  project: pendingQueryProject.name,
                })}
              />
            ) : null}
            {selectedProjectDelta ? (
              <Banner
                className="notice"
                container="card"
                endContent={
                  <div className="notice-actions">
                  {canBriefProjectDelta(selectedProjectDelta.delta) ? (
                    <Button
                      isDisabled={isSending || !canMutateSelectedProject}
                      label={t("브리핑 받기")}
                      onClick={() => void handleRequestProjectDeltaBriefing()}
                      size="sm"
                      variant="primary"
                    />
                  ) : null}
                  <Button
                    label={t("닫기")}
                    onClick={handleDismissProjectDelta}
                    size="sm"
                    variant="ghost"
                  />
                  </div>
                }
                status="info"
                title={t("지난 확인 이후 — {summary}", {
                  summary: formatProjectDeltaSummary(selectedProjectDelta.delta, t),
                })}
              />
            ) : null}
            {isPrimaryProjectContext && selectedProject?.serverMissing ? (
              <Banner
                className="notice"
                container="card"
                status="error"
                title={t("서버에서 찾을 수 없어 로컬 캐시를 표시 중")}
              />
            ) : null}
            {mainDemoStatus ? (
              <Banner
                className="notice runtime-status"
                container="card"
                endContent={
                  mainDemoStatusKind === "error" ? (
                    <Button
                      label={t("닫기")}
                      onClick={() => setDemoStatus(null)}
                      size="sm"
                      variant="ghost"
                    />
                  ) : undefined
                }
                key={statusRevision}
                status={mainDemoStatusKind}
                title={t(mainDemoStatus.message)}
              />
            ) : null}
          </div>
        ) : null}
        {mainView === "settings" ? (
          renderSettingsPage()
        ) : mainView === "profile" ? (
          renderProfilePage()
        ) : mainView === "members" ? (
          renderMembersPage()
        ) : mainView === "projects" ? (
          renderProjectPortfolio()
        ) : mainView === "project-management" &&
          selectedProject &&
          isSelectedProjectOwner ? (
          <Suspense fallback={<PanelLoadingState label={t("프로젝트 관리 불러오는 중")} />}>
            <LazyProjectManagementPage
              activeSection={projectManagementSection}
              isProjectDeleteConfirming={
                pendingDeleteProjectId === selectedProject.id
              }
              language={settings.language}
              onBack={returnToProjectDetailFromManagement}
              onDeleteProject={
                canDeleteSelectedProject
                  ? (event) =>
                      handleDeleteProject(selectedProject.id, event)
                  : undefined
              }
              onManageMembers={(trigger) =>
                void openProjectMembers(selectedProject.id, trigger)
              }
              onOpenProjectGithub={() => {
                if (
                  !shouldSkipProjectPermission(
                    selectedProject,
                    "overview",
                    "owner",
                  )
                ) {
                  openProjectPanelTool("github");
                  openProjectPanel();
                }
              }}
              onRenameProject={(name) =>
                renameProjectFromDetail(selectedProject.id, name)
              }
              onSectionChange={setProjectManagementSection}
              onUpdateProjectDescription={(description) =>
                updateProjectDescriptionFromDetail(
                  selectedProject.id,
                  description,
                )
              }
              project={selectedProject}
            />
          </Suspense>
        ) : mainView === "project-detail" && selectedProject ? (
          <Suspense fallback={<PanelLoadingState label={t("프로젝트 상세 불러오는 중")} />}>
            <LazyProjectDetailPage
              activeTab={projectDetailTab}
              composerAttachments={attachments}
              composerDisabledMessage={selectedProjectReadOnlyReason}
              composerPrompt={prompt}
              currentUserId={authUser?.id ?? null}
              isComposerSending={isSending}
              key={selectedProject.id}
              language={settings.language}
              onAddProjectAudio={
                canMutateSelectedProject
                  ? () => void handleOpenProjectAudio(selectedProject.id)
                  : undefined
              }
              onAddProjectFiles={
                canMutateSelectedProject
                  ? () => void handleOpenProjectFiles(selectedProject.id)
                  : undefined
              }
              onAddProjectFolder={
                canMutateSelectedProject
                  ? () => void handleOpenProjectDirectory(selectedProject.id)
                  : undefined
              }
              onBack={handleOpenProjectPortfolio}
              onComposerPickFiles={
                canMutateSelectedProject && capabilities
                  ? () => void handlePickFiles()
                  : undefined
              }
              onComposerPromptChange={handlePromptChange}
              onComposerRemoveAttachment={removeAttachment}
              onComposerSubmit={() => handleSubmit()}
              onDeleteProjectFile={
                canMutateSelectedProject
                  ? (file) => handleDeleteProjectFile(selectedProject.id, file)
                  : undefined
              }
              onOpenGithub={() => {
                openProjectPanelTool("github");
                openProjectPanel();
              }}
              onManageMembers={(trigger) =>
                void openProjectMembers(selectedProject.id, trigger)
              }
              onOpenManagement={
                isSelectedProjectOwner
                  ? (trigger) =>
                      handleOpenProjectManagement(selectedProject.id, trigger)
                  : undefined
              }
              onOpenProjectFile={openProjectFileFromDetail}
              onOpenProjectFilesManager={() => {
                openProjectPanelTool("files");
                openProjectPanel();
              }}
              onRefreshProjectFileStatus={(file) =>
                void handleRefreshProjectDocumentStatus(selectedProject.id, file)
              }
              onTabChange={setProjectDetailTab}
              memoryItems={selectedProjectMemoryItems}
              project={selectedProject}
              projectRole={
                isSelectedProjectOwner ? "owner" : selectedProjectRole
              }
              refreshRevision={postSyncRefreshRevision}
            />
          </Suspense>
        ) : mainView === "chat" && selectedSession ? (
          <>
            {selectedSession.messages.length === 0 ? (
              <div className="chat-empty">
                <h1>
                  {t("{name}에서 무엇을 도와드릴까요?", {
                    name: selectedProject?.name ?? "PaiM",
                  })}
                </h1>
              </div>
            ) : (
              <>
                <div
                  className="chat-scroll"
                  onKeyDownCapture={handleChatKeyDown}
                  onPointerDown={interruptChatAutoScroll}
                  onScroll={handleChatScroll}
                  onWheel={interruptChatAutoScroll}
                  ref={chatScrollRef}
                >
                  <div
                    aria-labelledby="chat-context-heading"
                    aria-live="polite"
                    aria-relevant="additions text"
                    className="conversation"
                    role="log"
                  >
                  {selectedSession.messages.map((message) => (
                    <article
                      className="message"
                      data-role={message.role}
                      key={message.id}
                      role={message.role === "error" ? "alert" : undefined}
                    >
                      <span className="message-author">
                        {t(
                          message.role === "assistant"
                            ? "PaiM 응답"
                            : message.role === "error"
                              ? "오류 메시지"
                              : "내 메시지",
                        )}
                      </span>
                      <div className="message-content">
                        {message.role === "assistant" ? (
                          <div className="paim-assistant-content">
                            {typeof message.thinkingSeconds === "number" ? (
                              <div className="thought-for">
                                {t("{seconds}초 동안 생각함", {
                                  seconds: message.thinkingSeconds,
                                })}
                              </div>
                            ) : null}
                            <Suspense
                              fallback={
                                <div
                                  aria-label={t("응답 표시 준비 중")}
                                  className="message-content-skeleton"
                                />
                              }
                            >
                              <LazyMarkdown
                                className="paim-message-markdown"
                                density="compact"
                                headingLevelStart={3}
                              >
                                {message.content}
                              </LazyMarkdown>
                            </Suspense>
                            {message.sources && message.sources.length > 0 ? (
                              <div className="sources" aria-label={t("출처")}>
                                <span className="paim-sources-label">{t("출처")}</span>
                                {message.sources.map((source, sourceIndex) => (
                                  <Badge
                                    className="source-chip"
                                    icon={<Files aria-hidden="true" size={11} />}
                                    key={`${message.id}-${sourceIndex}`}
                                    label={<span className="source-chip-label">{source}</span>}
                                    variant="neutral"
                                  />
                                ))}
                              </div>
                            ) : null}
                          </div>
                        ) : (
                          <>
                            {message.content.split("\n").map((line, lineIndex) => (
                              <p key={`${message.id}-${lineIndex}`}>{line}</p>
                            ))}
                          </>
                        )}
                        {message.attachments && message.attachments.length > 0 ? (
                          <>
                            <AttachmentList attachments={message.attachments} label={t("첨부 파일")} />
                            {message.role === "user" ? (
                              <span className="attachment-scope-note">{t("이번 질문 참고용")}</span>
                            ) : null}
                          </>
                        ) : null}
                      </div>
                      {message.role === "assistant" ? (
                        <IconButton
                          className="copy-button"
                          data-copied={copiedMessageId === message.id ? "true" : undefined}
                          icon={copiedMessageId === message.id ? <Check size={16} /> : <Copy size={16} />}
                          label={copiedMessageId === message.id ? t("복사됨") : t("응답 복사")}
                          onClick={() => void handleCopy(message)}
                          size="sm"
                          tooltip={copiedMessageId === message.id ? t("복사됨") : t("응답 복사")}
                          variant="ghost"
                        />
                      ) : null}
                    </article>
                  ))}

                  {isCurrentSessionSending ? (
                    <article className="message" data-role="assistant">
                      <div className="thinking">
                        <Spinner aria-label={t("응답 생성 중")} shade="subtle" size="sm" />
                        <span aria-hidden="true">
                          <span className="paim-thinking-dots">{t("생각 중")}</span> · {t("{seconds}초", {
                            seconds: thinkingElapsedSeconds,
                          })}
                        </span>
                      </div>
                    </article>
                  ) : null}
                  </div>
                </div>
                {showLatestMessageButton ? (
                  <Button
                    className="chat-latest-button"
                    icon={<ArrowDown size={15} />}
                    label={t("최신 메시지")}
                    onClick={handleScrollToLatest}
                    size="sm"
                    variant="secondary"
                  />
                ) : null}
              </>
            )}

            <form className="prompt" data-drop-zone="prompt" onSubmit={handleSubmit}>
              {selectedProjectReadOnlyReason ? (
                <p className="prompt-readonly-note">{selectedProjectReadOnlyReason}</p>
              ) : null}
              <TextArea
                className="prompt-textarea"
                disabledMessage={selectedProjectReadOnlyReason}
                isDisabled={!canMutateSelectedProject}
                isLabelHidden
                label={t("메시지 입력")}
                onChange={handlePromptChange}
                onKeyDown={handlePromptKeyDown}
                placeholder={t("Send a message")}
                ref={promptTextareaRef}
                rows={1}
                size="sm"
                value={prompt}
                width="100%"
              />
              {attachments.length > 0 ? (
                <div className="draft-attachments">
                  <AttachmentList
                    attachments={attachments}
                    label={t("전송할 첨부 파일")}
                    onRemove={removeAttachment}
                  />
                </div>
              ) : null}
              <div className="attachment-scope-note">
                {capabilities ? (
                  <span>{t("지원 형식 및 제한: {details}", { details: queryAttachmentCapabilityLabel })}</span>
                ) : (
                  <>
                    <span>{capabilitiesError || t("지원 파일 정보를 불러오는 중입니다")}</span>
                    {capabilitiesError ? (
                      <Button
                        label={t("지원 파일 정보 다시 불러오기")}
                        onClick={retryCapabilities}
                        size="sm"
                        variant="secondary"
                      >
                        {t("다시 시도")}
                      </Button>
                    ) : null}
                  </>
                )}
              </div>
              <div className="prompt-actions">
                <IconButton
                  icon={<Plus size={17} />}
                  isDisabled={!canMutateSelectedProject || !capabilities}
                  label={t("파일 추가")}
                  onClick={() => void handlePickFiles()}
                  tooltip={
                    selectedProjectReadOnlyReason ??
                    (capabilities
                      ? t("파일 추가 · {details}", { details: queryAttachmentCapabilityLabel })
                      : capabilitiesError || t("지원 파일 정보를 불러오는 중입니다"))
                  }
                  variant="ghost"
                />
                {isCurrentSessionSending ? (
                  <IconButton
                    className="send-button stop-button"
                    icon={<Square fill="currentColor" size={12} />}
                    label={t("응답 중지")}
                    onClick={handleCancelQuery}
                    tooltip={t("응답 중지")}
                    type="button"
                    variant="secondary"
                  />
                ) : (
                  <IconButton
                    className="send-button"
                    icon={<ArrowUp size={16} />}
                    isDisabled={
                      !canMutateSelectedProject ||
                      (!prompt.trim() && attachments.length === 0) ||
                      isSending
                    }
                    label={t("메시지 보내기")}
                    tooltip={selectedProjectReadOnlyReason ?? t("메시지 보내기")}
                    type="submit"
                    variant="primary"
                  />
                )}
              </div>
            </form>
          </>
        ) : mainView === "project-setup" && selectedProject ? (
          <>
            <WorkspacePageLayout
              ariaLabel={t("프로젝트 시작 화면")}
              aside={renderProjectSetupMemorySummary()}
              asideAriaLabel={t("추출될 항목")}
              asideClassName="project-setup-slots"
              className="project-setup"
              contentClassName="project-setup-main-content"
              layoutClassName="project-setup-content"
              mainClassName="project-setup-main"
              sectionProps={{
                "data-context-ready": hasProjectSetupContext ? "true" : "false",
                "data-drop-zone": "project-files",
                "data-stage": "context",
              }}
            >
                  <div className="project-setup-name-row">
                    <TextInput
                      className="project-setup-name"
                      isDisabled={!isSelectedProjectOwner}
                      isLabelHidden
                      label={t("프로젝트 이름")}
                      onBlur={(event) => {
                        const currentValue = (event.target as HTMLInputElement).value;
                        const previousName =
                          projectSetupNameBeforeEditRef.current ?? selectedProject.name;
                        const nextName =
                          currentValue.trim() ||
                          createNextProjectName(
                            projects.filter((project) => project.id !== selectedProject.id),
                          );

                        updateProject(selectedProject.id, (project) => ({
                          ...project,
                          name: nextName,
                        }));
                        projectSetupNameBeforeEditRef.current = null;

                        if (nextName !== previousName) {
                          void syncProjectName(selectedProject.id, nextName, previousName);
                        }
                      }}
                      onChange={(nextName) => {
                        updateProject(selectedProject.id, (project) => ({
                          ...project,
                          name: nextName,
                        }));
                      }}
                      onFocus={() => {
                        projectSetupNameBeforeEditRef.current = selectedProject.name;
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          event.currentTarget.blur();
                          return;
                        }

                        if (event.key === "Escape") {
                          event.preventDefault();
                          const previousName =
                            projectSetupNameBeforeEditRef.current ?? selectedProject.name;
                          event.currentTarget.value = previousName;
                          updateProject(selectedProject.id, (project) => ({
                            ...project,
                            name: previousName,
                          }));
                          projectSetupNameBeforeEditRef.current = previousName;
                          event.currentTarget.blur();
                        }
                      }}
                      data-default-name={isSelectedProjectDefaultName ? "true" : undefined}
                      placeholder={t("New Project 1")}
                      value={selectedProject.name}
                      width="100%"
                    />
                    <Pencil aria-hidden="true" className="project-setup-name-edit" size={15} />
                  </div>
                  <ol className="project-setup-steps" aria-label={t("프로젝트 시작 단계")}>
                    <li aria-current="step" data-state="current">
                      <span className="project-setup-step-number">1</span>
                      <span className="project-setup-step-label">{t("맥락 추가")}</span>
                    </li>
                    <li data-state="upcoming">
                      <span className="project-setup-step-number">2</span>
                      <span className="project-setup-step-label">{t("분석")}</span>
                    </li>
                    <li data-state="upcoming">
                      <span className="project-setup-step-number">3</span>
                      <span className="project-setup-step-label">{t("첫 질문")}</span>
                    </li>
                  </ol>

                  <section className="project-setup-section">
                    <h2>{t("프로젝트 설명")}</h2>
                    <TextArea
                      className="project-setup-description"
                      isDisabled={!isSelectedProjectOwner}
                      isLabelHidden
                      label={t("프로젝트 설명")}
                      onBlur={(event) => {
                        const nextDescription = event.currentTarget.value;
                        const previousDescription =
                          projectSetupDescriptionBeforeEditRef.current ??
                          selectedProject.description ??
                          "";
                        projectSetupDescriptionBeforeEditRef.current = null;
                        if (nextDescription.trim() !== previousDescription.trim()) {
                          void syncProjectDescription(
                            selectedProject.id,
                            nextDescription,
                            previousDescription,
                          );
                        }
                      }}
                      onChange={(nextDescription) => {
                        updateProject(selectedProject.id, (project) => ({
                          ...project,
                          description: nextDescription,
                        }));
                      }}
                      onFocus={() => {
                        projectSetupDescriptionBeforeEditRef.current =
                          selectedProject.description ?? "";
                      }}
                      placeholder={t("프로젝트 설명을 적어두면 PaiM이 맥락을 잡는 데 도움이 됩니다.")}
                      rows={2}
                      value={selectedProject.description ?? ""}
                      width="100%"
                    />
                  </section>

                  <section className="project-setup-section project-setup-context-section">
                    <header className="project-setup-section-header">
                      <h2>{t("프로젝트 맥락 추가")}</h2>
                      <p>
                        {capabilities
                          ? t("지원 형식 및 제한: {details}", {
                              details: projectDocumentCapabilityLabel,
                            })
                          : capabilitiesError || t("지원 파일 정보를 불러오는 중입니다")}
                      </p>
                    </header>
                    <div
                      className="project-setup-canvas"
                      data-state={selectedProjectFileCount > 0 ? "filled" : "empty"}
                    >
                    {selectedProjectFileCount > 0 ? (
                      <div
                        aria-label={t("프로젝트 자료")}
                        className="project-setup-canvas-filled"
                        data-expanded={areSelectedProjectSourcesExpanded ? "true" : "false"}
                        role="group"
                      >
                        <div className="project-setup-upload-summary">
                          <span className="project-setup-summary-item" data-kind="ready">
                            {t("{count}개 완료", { count: selectedProjectSetupStatusCounts.ready })}
                          </span>
                          <span className="project-setup-summary-item" data-kind="processing">
                            {t("{count}개 처리 중", {
                              count: selectedProjectSetupStatusCounts.processing,
                            })}
                          </span>
                          <span className="project-setup-summary-item" data-kind="failed">
                            {t("{count}개 실패", { count: selectedProjectSetupStatusCounts.failed })}
                          </span>
                          <Button
                            className="project-setup-summary-action"
                            isDisabled={!canMutateSelectedProject}
                            label={t("자료 더 추가")}
                            onClick={() => void handleOpenProjectFiles(selectedProject.id)}
                            size="sm"
                            variant="ghost"
                          />
                          <Button
                            className="project-setup-summary-action"
                            icon={<AudioLines size={13} />}
                            isDisabled={!canMutateSelectedProject}
                            label={t("회의 음성")}
                            onClick={() => void handleOpenProjectAudio(selectedProject.id)}
                            size="sm"
                            variant="ghost"
                          />
                        </div>
                        <div className="project-setup-source-list">
                          {selectedProjectSetupVisibleSources.map((source) => {
                            const sourceMeta =
                              source.kind === "directory"
                                ? { Icon: FolderOpen, color: "var(--muted)" }
                                : getProjectFileVisualMeta(source.name);
                            const SourceIcon = sourceMeta.Icon;
                            const sourceStatus =
                              source.documentStatus ??
                              (source.kind === "directory" ? "folder" : "local");

                            return (
                              <div
                                className="project-setup-source-row"
                                data-delete={
                                  pendingSetupDeleteProjectFileId === source.id
                                    ? "confirm"
                                    : undefined
                                }
                                data-status={sourceStatus}
                                key={source.id}
                              >
                                <span
                                  className="project-setup-source-icon"
                                  style={{ color: sourceMeta.color }}
                                >
                                  <SourceIcon size={15} />
                                </span>
                                <span className="project-setup-source-name">{source.name}</span>
                                <span className="project-setup-source-status">
                                  {t(getProjectSetupSourceStatusLabel(source))}
                                </span>
                                <IconButton
                                  className="project-setup-source-delete"
                                  icon={<X size={12} />}
                                  isDisabled={!canMutateSelectedProject}
                                  label={
                                    pendingSetupDeleteProjectFileId === source.id
                                      ? t("자료 삭제 확인")
                                      : t("자료 삭제")
                                  }
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    handleRequestDeleteProjectSetupSource(selectedProject.id, source);
                                  }}
                                  size="sm"
                                  tooltip={
                                    pendingSetupDeleteProjectFileId === source.id
                                      ? t("한 번 더 누르면 삭제")
                                      : t("자료 삭제")
                                  }
                                  variant="ghost"
                                />
                              </div>
                            );
                          })}
                        </div>
                        {selectedProjectSetupHiddenSourceCount > 0 ? (
                          <Button
                            className="project-setup-source-more"
                            label={t("외 {count}개 자료 보기", {
                              count: selectedProjectSetupHiddenSourceCount,
                            })}
                            onClick={() => {
                              setExpandedProjectSourcesId(selectedProject.id);
                            }}
                            size="sm"
                            variant="ghost"
                          />
                        ) : null}
                      </div>
                    ) : (
                      <div className="project-setup-canvas-empty">
                        <FileText
                          aria-hidden="true"
                          className="project-setup-drop-icon"
                          size={30}
                          strokeWidth={1.6}
                        />
                        <h3>{t("자료를 추가해 프로젝트 맥락을 만드세요")}</h3>
                        <p>{t("파일을 드래그하거나 아래 버튼을 이용해 추가할 수 있습니다.")}</p>
                        <div className="project-setup-picker-row">
                          <Button
                            className="project-setup-picker"
                            icon={<FileText size={14} />}
                            isDisabled={!canMutateSelectedProject}
                            label={t("파일 선택")}
                            onClick={() => void handleOpenProjectFiles(selectedProject.id)}
                            size="sm"
                            variant="secondary"
                          />
                          <Button
                            className="project-setup-picker"
                            icon={<FolderOpen size={14} />}
                            isDisabled={!canMutateSelectedProject}
                            label={t("폴더 선택")}
                            onClick={() => void handleOpenProjectDirectory(selectedProject.id)}
                            size="sm"
                            variant="secondary"
                          />
                          <Button
                            className="project-setup-picker"
                            icon={<AudioLines size={14} />}
                            isDisabled={!canMutateSelectedProject}
                            label={t("회의 음성")}
                            onClick={() =>
                              void handleOpenProjectAudio(selectedProject.id)
                            }
                            size="sm"
                            variant="secondary"
                          />
                        </div>
                      </div>
                    )}
                    </div>
                  </section>

                  <div className="project-setup-footer">
                    <p
                      aria-live="polite"
                      className="project-setup-note"
                      id="project-setup-analysis-note"
                    >
                      {!canMutateSelectedProject
                        ? t("프로젝트 편집 권한이 있어야 분석할 수 있습니다")
                        : selectedProjectHasDocumentInProgress
                        ? t("자료 처리 중 — 완료 후 분석할 수 있습니다")
                        : !hasProjectSetupContext
                          ? t("설명이나 자료를 추가하면 분석할 수 있습니다")
                        : t("분석하면 설명과 자료를 읽고 프로젝트 상세 Home으로 이동합니다.")}
                    </p>
                    <div className="project-setup-actions">
                      <Button
                        className="project-setup-secondary"
                        isDisabled={!canMutateSelectedProject}
                        label={t("설정 완료")}
                        onClick={() =>
                          void handleCompleteSetupWithoutAnalysis(selectedProject.id)
                        }
                        size="sm"
                        variant="ghost"
                      />
                      <Button
                        aria-describedby="project-setup-analysis-note"
                        className="project-setup-primary"
                        isDisabled={isProjectBriefingDisabled}
                        label={isSending ? t("분석 중") : t("분석 시작")}
                        onClick={() =>
                          void handleStartProjectBriefing(selectedProject, selectedProjectAttachments)
                        }
                        size="sm"
                        variant="primary"
                      >
                        <span className="project-setup-primary-content">
                          <span>{isSending ? t("분석 중") : t("분석 시작")}</span>
                          <ChevronRight aria-hidden="true" size={15} />
                        </span>
                      </Button>
                    </div>
                  </div>
            </WorkspacePageLayout>
          </>
        ) : (
          renderProjectPortfolio()
        )}
      </LayoutContent>

      {showProjectPanel && !isProjectPanelCollapsed ? (
        <button
          aria-label={t("프로젝트 패널 닫기")}
          className="project-panel-backdrop"
          data-mode={projectPanelMode}
          onClick={closeProjectPanel}
          tabIndex={-1}
          type="button"
        />
      ) : null}

      {showProjectPanel && selectedProject ? (
        <LayoutPanel
          aria-hidden={isProjectPanelCollapsed || undefined}
          aria-modal={shouldInertBackgroundForProjectPanel || undefined}
          className="project-panel"
          data-state={projectPanelMode}
          data-view={projectPanelView}
          inert={isProjectPanelCollapsed}
          isScrollable={false}
          label={t("프로젝트 보조 패널")}
          padding={0}
          resizable={projectPanelMode === "open" ? projectPanelResizable.props : undefined}
          role={shouldInertBackgroundForProjectPanel ? "dialog" : "complementary"}
          tabIndex={isProjectPanelCollapsed ? undefined : -1}
        >
          {projectPanelMode === "open" ? (
            <ResizeHandle
              className="project-panel-resize-handle"
              direction="horizontal"
              isAlwaysVisible={false}
              isReversed
              label={t("프로젝트 패널 크기 조절")}
              onKeyDown={handleProjectPanelResizeKeyDown}
              pillPlacement="center"
              position="overlay"
              resizable={projectPanelResizable.props}
            />
          ) : null}
          <div className="project-panel-topbar">
            {projectPanelView === "menu" ? (
              <span className="project-panel-kicker">{t("도구 선택")}</span>
            ) : (
	              <div
	                className="project-panel-tabs"
	                data-scroll-end={projectPanelTabScrollState.canScrollEnd ? "true" : undefined}
	                data-scroll-start={projectPanelTabScrollState.canScrollStart ? "true" : undefined}
	                aria-label={t("열린 프로젝트 패널 탭")}
	                ref={projectPanelTabsRef}
	                role="tablist"
	              >
	                {projectPanelTabs.map((tab, tabIndex) => {
	                  const tabLabel = getProjectPanelTabLabel(tab);
	                  const { Icon, color } = getProjectPanelTabVisualMeta(
	                    tab.view,
	                    tab.view === "files" ? tab.filePreview : null,
	                  );

	                  return (
	                    <div className="project-panel-tab-shell" key={tab.id}>
	                      <button
	                        aria-controls={`project-panel-content-${tab.id}`}
	                        aria-label={t("{label} 탭", { label: tabLabel })}
	                        aria-selected={activeProjectPanelTabId === tab.id}
	                        className="project-panel-tab"
	                        data-active={activeProjectPanelTabId === tab.id ? "true" : undefined}
	                        data-tab-id={tab.id}
	                        id={`project-panel-tab-${tab.id}`}
	                        onClick={() => setActiveProjectPanelTabId(tab.id)}
	                        onKeyDown={(event) => handleProjectPanelTabKeyDown(event, tabIndex)}
	                        role="tab"
	                        tabIndex={activeProjectPanelTabId === tab.id ? 0 : -1}
	                        title={tabLabel}
	                        type="button"
	                      >
	                        <Icon aria-hidden="true" size={16} style={{ color }} />
	                        <span>{tabLabel}</span>
	                      </button>
	                      <IconButton
	                        className="project-panel-tab-close"
	                        icon={<X size={13} />}
	                        label={t("{label} 탭 닫기", { label: tabLabel })}
	                        onClick={() => handleCloseProjectPanelTab(tab.id)}
	                        size="sm"
	                        tooltip={t("{label} 탭 닫기", { label: tabLabel })}
	                        variant="ghost"
	                      />
	                    </div>
	                  );
	                })}
	                <DropdownMenu
	                  button={{
	                    className: "project-panel-tab-add",
	                    icon: <Plus size={18} />,
	                    isIconOnly: true,
	                    label: t("패널 탭 추가"),
	                    size: "sm",
	                    tooltip: t("패널 탭 추가"),
	                    variant: "ghost",
	                  }}
	                  items={PROJECT_PANEL_TOOL_VIEWS
	                    .filter((view) => view !== "memory" || canOpenProjectMemory)
	                    .map((view) => ({
                      label: t(getProjectPanelTitle(view)),
	                      onClick: () => openProjectPanelTool(view),
	                    }))}
	                  menuWidth={132}
	                />
              </div>
            )}
            <div className="project-panel-inline-controls" aria-label={t("프로젝트 패널 도구")}>
              <IconButton
                className="project-panel-toggle project-panel-maximize-toggle"
                icon={isProjectPanelMaximized ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
                label={t(isProjectPanelMaximized ? "{title} 패널 축소" : "{title} 패널 최대화", {
                  title: getProjectPanelTitle(projectPanelView),
                })}
                onClick={handleToggleProjectPanelMaximized}
                tooltip={t(isProjectPanelMaximized ? "{title} 패널 축소" : "{title} 패널 최대화", {
                  title: getProjectPanelTitle(projectPanelView),
                })}
                variant="ghost"
              />
              <IconButton
                className="project-panel-toggle project-panel-collapse-toggle"
                icon={<PanelRight size={16} />}
                label={t("프로젝트 패널 접기")}
                onClick={handleToggleProjectPanel}
                tooltip={t("프로젝트 패널 접기")}
                variant="ghost"
              />
            </div>
          </div>

          {projectPanelView === "menu" ? (
            <div
              aria-label={t("프로젝트 패널 도구")}
              className="project-panel-menu"
              role="group"
            >
              {canOpenProjectMemory ? (
                <Button
                  className="project-panel-menu-item"
                  label={t("메모리 열기")}
                  onClick={() => openProjectPanelTool("memory")}
                  variant="secondary"
                >
                  <span className="project-panel-menu-row">
                    <span className="project-panel-menu-leading">
                      <Brain className="project-panel-menu-icon" size={18} />
                      <span className="project-panel-menu-copy">
                        <strong>{t("메모리")}</strong>
                        <small>{t("결정·액션·이슈·리스크")}</small>
                      </span>
                    </span>
                    <ChevronRight className="project-panel-menu-chevron" size={16} />
                  </span>
                </Button>
              ) : null}
              <Button
                className="project-panel-menu-item"
                label={t("자료 열기")}
                onClick={() => openProjectPanelTool("files")}
                variant="secondary"
              >
                <span className="project-panel-menu-row">
                  <span className="project-panel-menu-leading">
                    <Files className="project-panel-menu-icon" size={18} />
                    <span className="project-panel-menu-copy">
                      <strong>{t("자료")}</strong>
                      <small>{t("{count}개 소스", { count: selectedProjectAttachments.length })}</small>
                    </span>
                  </span>
                  <ChevronRight className="project-panel-menu-chevron" size={16} />
                </span>
              </Button>
              <Button
                className="project-panel-menu-item"
                label={t("GitHub 열기")}
                onClick={() => openProjectPanelTool("github")}
                variant="secondary"
              >
                <span className="project-panel-menu-row">
                  <span className="project-panel-menu-leading">
                    <GitBranch className="project-panel-menu-icon" size={18} />
                    <span className="project-panel-menu-copy">
                      <strong>GitHub</strong>
                      <small>{t(getGithubPanelStateLabel(selectedProjectGithubPanelState))}</small>
                    </span>
                  </span>
                  <ChevronRight className="project-panel-menu-chevron" size={16} />
                </span>
              </Button>
            </div>
          ) : null}

          {projectPanelTabs.map((tab) => {
            const isActiveTab = activeProjectPanelTabId === tab.id;
            const tabSelectedSource =
              selectedProjectAttachments.find((source) => source.id === tab.selectedProjectSourceId) ??
              null;
            const tabTreeAttachments = tabSelectedSource
              ? [tabSelectedSource]
              : selectedProjectAttachments;
            const tabFilteredFiles = filterProjectFileEntries(
              sortedSelectedProjectAttachments,
              tab.fileQuery,
            );

            return (
              <div
                aria-labelledby={`project-panel-tab-${tab.id}`}
                className="project-panel-tabpanel"
                hidden={!isActiveTab}
                id={`project-panel-content-${tab.id}`}
                inert={!isActiveTab ? true : undefined}
                key={tab.id}
                role="tabpanel"
              >
                {tab.view === "memory" ? (
                  <Suspense fallback={<PanelLoadingState label={t("메모리 불러오는 중")} />}>
                    <LazyProjectMemoryPanel
                      canManage={canOpenProjectMemory && canMutateSelectedProject}
                      isMaximized={isProjectPanelMaximized}
                      project={selectedProject}
                      reloadRevision={postSyncRefreshRevision}
                      suggestionMin={settings.suggestionMin}
                    />
                  </Suspense>
                ) : null}

                {tab.view === "files" ? (
                  <Suspense fallback={<PanelLoadingState label={t("자료 불러오는 중")} />}>
                    <LazyProjectFilesPanel
                      attachments={selectedProjectAttachments}
                      canManage={canMutateSelectedProject}
                      demoStatus={visibleDemoStatus}
                      filteredTreeFiles={filterProjectFileEntries(
                        tabTreeAttachments,
                        tab.fileQuery,
                      )}
                      groupedFiles={groupProjectSourcesByUploadedDate(tabFilteredFiles)}
                      isMaximized={isProjectPanelMaximized}
                      isImporting={Boolean(selectedProjectFileImport)}
                      isSelectedSourceFile={tabSelectedSource?.kind === "file"}
                      isTreeCollapsed={isProjectFileTreeCollapsed}
                      loadingEntryIds={Array.from(loadingProjectFileEntryKeys)
                        .filter((key) => key.startsWith(`${selectedProject.id}:`))
                        .map((key) => key.slice(selectedProject.id.length + 1))}
                      mode={tab.projectSourcesMode}
                      onBackToLibrary={() =>
                        updateProjectPanelTab(tab.id, (currentTab) => ({
                          ...currentTab,
                          filePreview: null,
                          projectSourcesMode: "library",
                          selectedProjectSourceId: null,
                        }))
                      }
                      onClosePreview={() =>
                        setProjectFilePreviewForTab(tab.id, null)
                      }
                      onCancelImport={() => cancelProjectFileImport(selectedProject.id)}
                      onOpenAudio={() => void handleOpenProjectAudio(selectedProject.id)}
                      onOpenDirectory={() => void handleOpenProjectDirectory(selectedProject.id)}
                      onOpenFiles={() => void handleOpenProjectFiles(selectedProject.id)}
                      onOpenSource={handleOpenProjectSource}
                      onRefreshDocumentStatus={(source) =>
                        void handleRefreshProjectDocumentStatus(
                          selectedProject.id,
                          source,
                        )
                      }
                      onQueryChange={(query) =>
                        updateProjectPanelTab(tab.id, (currentTab) => ({
                          ...currentTab,
                          fileQuery: query,
                        }))
                      }
                      onConfirmDelete={(entry) =>
                        handleDeleteProjectFile(selectedProject.id, entry)
                      }
                      onSelectFile={(entry) => void handleSelectProjectFile(entry)}
                      onToggleFile={(entry) =>
                        void handleToggleProjectFileEntry(selectedProject.id, entry)
                      }
                      onToggleTreeCollapsed={() =>
                        setIsProjectFileTreeCollapsed((current) => !current)
                      }
                      onTreeResizeStart={handleProjectFileTreeResizeStart}
                      onTreeWidthChange={setProjectFileTreeWidth}
                      preview={tab.filePreview}
                      query={tab.fileQuery}
                      statusRevision={statusRevision}
                      treeAttachments={tabTreeAttachments}
                      treeFileCount={countProjectFileEntries(tabTreeAttachments)}
                      treeWidth={projectFileTreeWidth}
                    />
                  </Suspense>
                ) : null}

                {tab.view === "github" ? (
                  <Suspense fallback={<PanelLoadingState label={t("GitHub 불러오는 중")} />}>
                    <LazyGithubPanel
                      canManage={isSelectedProjectOwner}
                      demoStatus={visibleDemoStatus}
                      events={selectedProjectGithubEvents}
                      filteredRepositories={filteredSelectedProjectGithubRepositories}
                      githubConnected={selectedProject.githubConnected}
                      isAuthChecking={isGithubAuthChecking}
                      isAuthStarting={isGithubAuthStarting}
                      isConnecting={isGithubConnecting}
                      connectingRepositoryUrl={githubConnectingRepositoryUrl}
                      isDisconnectConfirming={
                        pendingGithubDisconnectProjectId === selectedProject.id
                      }
                      isRepoLoading={isGithubRepoLoading}
                      isSyncing={isGithubSyncing}
                      onCheckLogin={() => void handleCheckGithubLogin(selectedProject.id)}
                      onConnectRepository={(repositoryUrl) =>
                        void connectGithubRepository(selectedProject.id, repositoryUrl)
                      }
                      onDisconnect={() => void handleDisconnectGithub(selectedProject.id)}
                      onLoadRepositories={() =>
                        void handleLoadGithubRepositories(selectedProject.id)
                      }
                      onOpenVerification={() =>
                        void handleOpenGithubVerification(selectedProject.id)
                      }
                      onQueryChange={(query) =>
                        setGithubRepositoryQueryForProject(selectedProject.id, query)
                      }
                      onRefreshRepository={() =>
                        void refreshGithubRepositoryHead(selectedProject.id, { force: true })
                      }
                      onResetLogin={() => handleResetGithubLogin(selectedProject.id)}
                      onStartLogin={() => void handleStartGithubLogin(selectedProject.id)}
                      onStartPrivateLogin={() =>
                        void handleStartGithubPrivateLogin(selectedProject.id)
                      }
                      onSyncRepository={() =>
                        void handleSyncGithubRepository(selectedProject.id)
                      }
                      panelState={selectedProjectGithubPanelState}
                      memoryItems={selectedProjectMemoryItems}
                      repositories={selectedProjectGithubRepositories}
                      repository={selectedProject.githubRepository}
                      repositoryQuery={githubRepositoryQuery}
                      session={selectedProjectGithubSession}
                      statusRevision={statusRevision}
                    />
                  </Suspense>
                ) : null}
              </div>
            );
          })}
        </LayoutPanel>
      ) : null}
          <AudioUploadDialog
            draft={audioUploadDraft}
            isServerOnline={serverStatus === "online"}
            isSubmitting={isAudioUploadStarting}
            onCancel={closeAudioUploadDialog}
            onConfirm={() => void handleConfirmAudioUpload()}
            onDateChange={(date) =>
              setAudioUploadDraft((currentDraft) =>
                currentDraft ? { ...currentDraft, date } : currentDraft,
              )
            }
          />
          </div>
        </AppShell>
      </Theme>
    </I18nProvider>
  );
}
