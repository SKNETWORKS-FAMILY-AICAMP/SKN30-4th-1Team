import {
  AlertTriangle,
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
  Users,
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
import { StatusDot } from "@astryxdesign/core/StatusDot";
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
import { formatRelativeAge } from "./format";
import {
  canRole,
  fetchProjectMembers,
  getCurrentProjectMember,
  type ProjectMember,
  type ProjectRole,
} from "./members";
import {
  createGithubDeviceCode,
  createGithubAppSession,
  fetchGithubAccessToken,
  fetchGithubAppRepositories,
  fetchGithubAppRepositoryPreview,
  fetchGithubAppSession,
  fetchGithubRepositories,
  fetchGithubRepository,
  fetchGithubUserProfile,
  getGithubOAuthErrorMessage,
  getGithubPanelStateLabel,
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
  DEFAULT_PAIM_API_ROOT_URL,
  getPaimApiRootUrl,
  loadPaimSettings,
  normalizePaimServerUrl,
  normalizePaimSettings,
  resolvePaimApiRootUrl,
  savePaimSettings,
  type LanguageSetting,
  type PaiMSettings,
  type SuggestionMinConfidence,
  type ThemeSetting,
} from "./settings";
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
  extracted?: Record<string, number>;
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

type ApiChatSessionResponse = {
  id: string;
  project_id: number;
  title: string;
  created_at?: string;
  updated_at?: string;
};

type ApiChatMessageResponse = {
  id: number;
  role: string;
  text: string;
  token_count?: number;
  created_at?: string;
};

type ApiChatSessionWithMessages = {
  session: ApiChatSessionResponse;
  messages: Message[];
};

type ApiRepositoryStatus = "connected" | "syncing" | "indexed" | "failed";

type ApiRepositoryConnectResponse = {
  repo_id: number;
  status: ApiRepositoryStatus;
  branch?: string;
};

type ApiRepositoryListItem = {
  id: number;
  provider: string;
  repository_url: string;
  branch: string;
  status: ApiRepositoryStatus;
  connected_at?: string | null;
};

type ApiRepositoryStatusResponse = {
  repo_id: number;
  status: ApiRepositoryStatus;
  provider: string;
  repository_url: string;
  branch: string;
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

type ApiDeltaBriefingResponse = {
  answer: string;
  sources: string[];
};

type ProjectDeltaBannerState = {
  projectId: string;
  since: string;
  delta: ApiProjectDeltaResponse;
};

type ServerStatus = "online" | "offline";
type MainView = "workspace" | "settings" | "profile" | "members";
type ServerTestState = {
  message: string;
  status: "idle" | "testing" | "ok" | "error";
};

type ActionMenuOrigin = "bottom-left" | "bottom-right" | "top-left" | "top-right";

type ActionMenuState =
  | {
      type: "project";
      projectId: string;
      top: number;
      left: number;
      origin: ActionMenuOrigin;
    }
  | {
      type: "session";
      projectId: string;
      sessionId: string;
      top: number;
      left: number;
      origin: ActionMenuOrigin;
    };

type RenameDraft =
  | { type: "project"; projectId: string; value: string }
  | { type: "session"; projectId: string; sessionId: string; value: string };

const SERVER_SYNC_TIMEOUT_MS = 3000;
const DOCUMENT_STATUS_POLL_INTERVAL_MS = 3000;
const DOCUMENT_STATUS_POLL_TIMEOUT_MS = 180000;
const GITHUB_REPOSITORY_SYNC_POLL_INTERVAL_MS = 3000;
const GITHUB_REPOSITORY_SYNC_TIMEOUT_MS = 600000;
const QUERY_HISTORY_LIMIT = 20;
const QUERY_TIMEOUT_MS = 60000;
const ACTION_MENU_WIDTH = 132;
const ACTION_MENU_PROJECT_HEIGHT = 108;
const ACTION_MENU_SESSION_HEIGHT = 76;
const ACTION_MENU_GAP = 12;
const DESTRUCTIVE_CONFIRMATION_TIMEOUT_MS = 6000;
const PROJECT_STORAGE_KEY = "paim.projects.v8";
const PROJECT_ROLE_RETRY_DELAYS_MS = [400, 1200] as const;
const PROJECT_BRIEFING_QUESTION =
  "이 프로젝트의 목적, 현재 상태(완료된 것과 진행 중인 것), 그리고 다음에 해야 할 액션을 프로젝트 기록을 근거로 간결하게 브리핑해줘. 담당자와 마감일이 있는 액션은 함께 표기해줘.";
const PROJECT_ANALYSIS_PENDING_STEPS = [
  "프로젝트 설명을 읽는 중",
  "연결된 자료를 훑는 중",
  "핵심 결정과 액션을 정리하는 중",
  "브리핑을 작성하는 중",
];
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
const DEFAULT_SIDEBAR_WIDTH = 252;
const COLLAPSED_SIDEBAR_WIDTH = 52;
const MIN_SIDEBAR_WIDTH = 232;
const MAX_SIDEBAR_WIDTH = 332;
const DEFAULT_PROJECT_PANEL_WIDTH = 330;
const MIN_PROJECT_PANEL_WIDTH = 300;
const MAX_PROJECT_PANEL_WIDTH = 520;
const MIN_MAIN_CONTENT_WIDTH = 580;
const PANEL_RAIL_WIDTH = 44;
const DEFAULT_ZOOM_SCALE = 1;
const MIN_ZOOM_SCALE = 1;
const MAX_ZOOM_SCALE = 2;
const ZOOM_STEP = 0.1;
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

function createProject(name: string, sessions: ChatSession[], files: Attachment[] = []): ProjectWorkspace {
  return {
    id: createId("project"),
    name,
    files,
    createdAt: Date.now(),
    sessions,
  };
}

function createProjectFromApi(serverProject: ApiProjectResponse): ProjectWorkspace {
  const createdAt = Date.parse(serverProject.created_at ?? "");

  return {
    id: createId("project"),
    apiProjectId: serverProject.id,
    name: serverProject.name,
    files: [],
    createdAt: Number.isFinite(createdAt) ? createdAt : Date.now(),
    sessions: [],
  };
}

function createEmptySession(): ChatSession {
  return {
    id: createId("session"),
    title: "New Chat",
    createdAt: Date.now(),
    messages: [],
  };
}

// 서버 세션 row를 로컬 ChatSession 형태로 변환한다.
function createSessionFromApi(apiSession: ApiChatSessionResponse, messages: Message[]): ChatSession {
  const createdAt = Date.parse(apiSession.created_at ?? "");

  return {
    id: createId("session"),
    serverSessionId: apiSession.id,
    title: apiSession.title || "New Chat",
    createdAt: Number.isFinite(createdAt) ? createdAt : Date.now(),
    messages,
  };
}

// 서버 메시지의 text 필드를 기존 content 필드로 매핑한다.
function createMessageFromApi(apiMessage: ApiChatMessageResponse): Message | null {
  if (apiMessage.role !== "assistant" && apiMessage.role !== "user") {
    return null;
  }

  return {
    id: `server-message-${apiMessage.id}`,
    role: apiMessage.role,
    content: apiMessage.text,
  };
}

// 서버 세션 목록은 정렬 기준으로 삼고, 로컬 전용 세션은 아직 서버에 없으므로 뒤에 보존한다.
function mergeServerChatSessions(
  localSessions: ChatSession[],
  serverSessions: ApiChatSessionWithMessages[],
) {
  const localSessionsByServerId = new Map(
    localSessions
      .filter((session) => session.serverSessionId)
      .map((session) => [session.serverSessionId as string, session]),
  );
  const syncedSessions = serverSessions.map(({ session, messages }) => {
    const localSession = localSessionsByServerId.get(session.id);

    if (!localSession) {
      return createSessionFromApi(session, messages);
    }

    return {
      ...localSession,
      serverSessionId: session.id,
      title: session.title || localSession.title,
      messages: messages.length > 0 ? messages : localSession.messages,
    };
  });
  const localOnlySessions = localSessions.filter((session) => !session.serverSessionId);

  return [...syncedSessions, ...localOnlySessions];
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

function formatAccountCreatedAt(value: string | null | undefined, language: LanguageSetting) {
  if (!value) {
    return language === "ko" ? "확인할 수 없음" : "Unavailable";
  }

  const date = new Date(value);
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
      const sessions = (project.sessions ?? []).map((session) => ({
        ...session,
        messages: removeLegacyWelcomeMessages(session.messages),
      }));

      return {
        ...project,
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
    selectedSessionId === null
      ? null
      : selectedProject.sessions.find((session) => session.id === selectedSessionId) ??
        selectedProject.sessions[0] ??
        null;

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

    return {
      ...localProject,
      apiProjectId: serverProject.id,
      name: serverProject.name,
      serverMissing: undefined,
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
    const projects = savedState.projects ?? [];

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
  return Math.min(MAX_ZOOM_SCALE, Math.max(MIN_ZOOM_SCALE, scale));
}

function loadZoomScale() {
  const savedScale = Number(window.localStorage.getItem(ZOOM_STORAGE_KEY));

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

function getProjectAnalysisPendingStep(elapsedSeconds: number) {
  return PROJECT_ANALYSIS_PENDING_STEPS[
    Math.min(
      PROJECT_ANALYSIS_PENDING_STEPS.length - 1,
      Math.floor(elapsedSeconds / 4),
    )
  ];
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

function getFileExtension(name: string) {
  return name.includes(".") ? name.split(".").pop()?.toLowerCase() ?? "" : "";
}

function isSupportedProjectDocument(name: string) {
  return ["md", "txt", "pdf", "docx"].includes(getFileExtension(name));
}

function getBase64ByteLength(encoded: string) {
  const padding = encoded.endsWith("==") ? 2 : encoded.endsWith("=") ? 1 : 0;
  return Math.floor((encoded.length * 3) / 4) - padding;
}

function getUploadMimeType(name: string) {
  const extension = getFileExtension(name);

  if (extension === "pdf") {
    return "application/pdf";
  }

  if (extension === "docx") {
    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  }

  return "text/plain";
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

function createServerDocumentAttachment(document: ApiDocumentListItem): Attachment {
  const uploadedAt = Date.parse(document.uploaded_at ?? "");

  return {
    id: `project-document-${document.id}`,
    name: document.filename,
    path: `server-document://${document.id}/${document.filename}`,
    kind: "file",
    docId: document.id,
    documentStatus: toProjectDocumentStatus(document.status),
    serverOnly: true,
    uploadedAt: Number.isFinite(uploadedAt) ? uploadedAt : Date.now(),
  };
}

function mapAttachments(
  attachments: Attachment[],
  updater: (attachment: Attachment) => Attachment,
): Attachment[] {
  return attachments.map((attachment) => ({
    ...updater(attachment),
    children: attachment.children ? mapAttachments(attachment.children, updater) : undefined,
  }));
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
) {
  const documentsById = new Map(documents.map((document) => [document.id, document]));
  const updatedAttachments = mapAttachments(attachments, (attachment) => {
    if (typeof attachment.docId !== "number") {
      return attachment;
    }

    const document = documentsById.get(attachment.docId);

    if (!document) {
      return attachment;
    }

    return {
      ...attachment,
      uploadName: document.filename,
      documentStatus: toProjectDocumentStatus(document.status),
    };
  });
  const existingDocIds = getAttachmentDocIds(updatedAttachments);
  const serverOnlyAttachments = documents
    .filter((document) => !existingDocIds.has(document.id))
    .map(createServerDocumentAttachment);

  return [...serverOnlyAttachments, ...updatedAttachments];
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
  return {
    path: repository.repository_url,
    name: currentRepository?.name ?? getGithubRepositoryName(repository.repository_url),
    branch: repository.branch,
    isDirty: false,
    remoteRepo: currentRepository?.remoteRepo ?? getGithubRemoteRepo(repository.repository_url),
    issuePrStatus: currentRepository?.issuePrStatus ?? "서버 연결됨",
    visibility: currentRepository?.visibility ?? "public",
    authProvider: currentRepository?.authProvider ?? "public",
    repoId: repository.id,
    syncStatus: repository.status,
    syncStartedAt: repository.status === "syncing" ? currentRepository?.syncStartedAt ?? Date.now() : undefined,
    connectedAt: repository.connected_at ?? undefined,
    commitSha: currentRepository?.commitSha,
    indexedFiles: currentRepository?.indexedFiles,
    lastError: currentRepository?.lastError,
    syncWarnings: currentRepository?.syncWarnings,
  };
}

function applyGithubRepositoryStatus(
  repository: GitRepositoryInfo,
  status: ApiRepositoryStatusResponse,
): GitRepositoryInfo {
  return {
    ...repository,
    path: status.repository_url,
    name: repository.name || getGithubRepositoryName(status.repository_url),
    branch: status.branch,
    remoteRepo: repository.remoteRepo ?? getGithubRemoteRepo(status.repository_url),
    repoId: status.repo_id,
    syncStatus: status.status,
    syncStartedAt: status.status === "syncing" ? repository.syncStartedAt ?? Date.now() : undefined,
    commitSha: status.commit_sha ?? null,
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
	    children: attachment.children ? createStoredAttachments(attachment.children) : undefined,
	    childrenLoaded: attachment.childrenLoaded,
	    docId: attachment.docId,
	    documentStatus: attachment.documentStatus,
	    isExpanded: attachment.isExpanded,
	    lastError: attachment.lastError,
	    serverOnly: attachment.serverOnly,
	    uploadedAt: attachment.uploadedAt,
	  }));
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
                serverUrl={getPaimApiRootUrl()}
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

// 레퍼런스 앱의 단순한 채팅 경험을 유지하면서 세션 상태를 관리한다.
function WorkspaceApp({ authUser, canLogout, initialServerOffline, onLogout }: WorkspaceAppProps) {
  const isWindows = useMemo(isWindowsHost, []);
  const isMac = useMemo(isMacHost, []);
  const initialProjectApiRootUrl = useMemo(getPaimApiRootUrl, []);
  const projectStorageKey = useMemo(
    () => getProjectStorageKey(authUser, canLogout, initialProjectApiRootUrl),
    [authUser, canLogout, initialProjectApiRootUrl],
  );
  const allowLegacyProjectCacheFallback =
    !canLogout &&
    normalizePaimServerUrl(initialProjectApiRootUrl) === DEFAULT_PAIM_API_ROOT_URL;
  const [initialProjectState] = useState(() =>
    loadProjectState(projectStorageKey, allowLegacyProjectCacheFallback),
  );
  const [projects, setProjects] = useState<ProjectWorkspace[]>(initialProjectState.projects);
  const [selectedProjectId, setSelectedProjectId] = useState(
    initialProjectState.selectedProjectId,
  );
  const [selectedSessionId, setSelectedSessionId] = useState(
    initialProjectState.selectedSessionId,
  );
  const [zoomScale, setZoomScaleState] = useState(loadZoomScale);
  const [prompt, setPrompt] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [isSending, setIsSending] = useState(false);
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
  const [projectRolesByApiId, setProjectRolesByApiId] = useState<
    Record<number, ProjectRole | null>
  >({});
  const [pendingSetupDeleteProjectFileId, setPendingSetupDeleteProjectFileId] = useState<string | null>(
    null,
  );
  const [mainView, setMainView] = useState<MainView>("workspace");
  const [settings, setSettingsState] = useState(loadPaimSettings);
  const [serverUrlDraft, setServerUrlDraft] = useState(settings.serverUrl);
  const t = (key: string, vars?: Record<string, number | string>) =>
    translate(settings.language, key, vars);
  const [serverTestState, setServerTestState] = useState<ServerTestState>({
    message: "",
    status: "idle",
  });
  const [isSettingsResetConfirming, setIsSettingsResetConfirming] = useState(false);
  const [isServerApplyConfirming, setIsServerApplyConfirming] = useState(false);
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
  const serverUrlSyncRef = useRef(settings.serverUrl);
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
  const promptTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const activeQueryControllerRef = useRef<AbortController | null>(null);
  const userCancelledQueryControllersRef = useRef(new WeakSet<AbortController>());
  const apiProjectEnsurePromisesRef = useRef(
    new Map<string, Promise<ProjectWorkspace>>(),
  );
  const serverSessionEnsurePromisesRef = useRef(new Map<string, Promise<string>>());
  const isScrollingToChatBottomRef = useRef(false);
  const shouldStickToChatBottomRef = useRef(true);
  const actionMenuTriggerRef = useRef<HTMLElement | null>(null);
  const accountMenuTriggerRef = useRef<HTMLButtonElement | null>(null);
  const didHydrateAttachmentPreviewsRef = useRef(false);
  const didSyncProjectsRef = useRef(false);
  const documentPollTimeoutsRef = useRef(new Map<string, number>());
  const documentUploadControllersRef = useRef(new Map<string, AbortController>());
  const cancelledDocumentIdsRef = useRef(new Set<number>());
  const githubRepositoryPollTimeoutsRef = useRef(new Map<string, number>());
  const postGithubSyncRefreshTimeoutsRef = useRef<number[]>([]);
  const demoStatusTimeoutRef = useRef<number | null>(null);
  const githubOperationRegistryRef = useRef(createLatestProjectOperationRegistry());
  const projectFileImportRegistryRef = useRef(createLatestProjectOperationRegistry());
  const ignoredProjectDeltaRef = useRef<Record<string, string>>({});
  const projectsRef = useRef(initialProjectState.projects);
  const selectedProjectIdRef = useRef(initialProjectState.selectedProjectId);
  const selectedSessionIdRef = useRef(initialProjectState.selectedSessionId);
  const sessionDraftsRef = useRef(
    new Map<string, { attachments: Attachment[]; prompt: string }>(),
  );
  const projectHomeNameBeforeEditRef = useRef<string | null>(null);
  const zoomScaleRef = useRef(zoomScale);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );
  const selectedProjectRole =
    typeof selectedProject?.apiProjectId === "number"
      ? projectRolesByApiId[selectedProject.apiProjectId]
      : undefined;
  const canMutateSelectedProject = selectedProject
    ? !authUser || typeof selectedProject.apiProjectId !== "number"
      ? true
      : canRole(selectedProjectRole, "member")
    : false;
  const canMutateSelectedProjectRef = useRef(canMutateSelectedProject);
  canMutateSelectedProjectRef.current = canMutateSelectedProject;
  const selectedProjectReadOnlyReason = !canMutateSelectedProject
    ? t("조회 권한으로 열려 있어 메시지와 파일을 보낼 수 없습니다.")
    : undefined;
  const sessions = selectedProject?.sessions ?? [];
  const selectedSession = useMemo(
    () => sessions.find((session) => session.id === selectedSessionId) ?? null,
    [selectedSessionId, sessions],
  );
  const showProjectPanel =
    mainView === "workspace" && Boolean(selectedProject) && Boolean(selectedSession);
  const visibleProjectPanelMode = showProjectPanel ? projectPanelMode : "closed";
  const activeProjectPanelTab = useMemo(
    () => projectPanelTabs.find((tab) => tab.id === activeProjectPanelTabId) ?? null,
    [activeProjectPanelTabId, projectPanelTabs],
  );
  const projectPanelView: ProjectPanelView = activeProjectPanelTab?.view ?? "menu";
  const isProjectBriefingPending =
    selectedSession?.title === "Project Briefing" &&
    selectedSession.messages.length === 0 &&
    isSending &&
    pendingProjectId === selectedProject?.id &&
    pendingSessionId === selectedSession.id;
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
  const projectAnalysisPendingStep = getProjectAnalysisPendingStep(thinkingElapsedSeconds);
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
    selectedProject ? projectMemoryItemsByProjectId[selectedProject.id] ?? [] : [];
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
  const selectedProjectSetupVisibleSources = useMemo(
    () => sortedSelectedProjectAttachments.slice(0, 5),
    [sortedSelectedProjectAttachments],
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
  const selectedProjectGithubPanelState: GithubPanelState = selectedProject?.githubRepository
    ? "connected"
    : selectedProjectGithubSession?.status === "connected"
      ? "repos"
      : selectedProjectGithubSession?.status === "pending"
        ? "authing"
        : "signedout";
  const selectedProjectDelta =
    selectedProject && projectDeltaBanner?.projectId === selectedProject.id
      ? projectDeltaBanner
      : null;
  const selectedProjectDescription = selectedProject?.description?.trim() ?? "";
  const isSelectedProjectDefaultName = /^New Project(?: \d+)?$/.test(selectedProject?.name ?? "");
  const canOpenProjectMemory =
    serverStatus === "online" &&
    typeof selectedProject?.apiProjectId === "number" &&
    !selectedProject.serverMissing;
  const hasProjectHomeContext =
    selectedProjectFileCount > 0 ||
    selectedProjectGithubPanelState === "connected" ||
    selectedProjectDescription.length > 0;
  const isProjectBriefingDisabled =
    !canMutateSelectedProject ||
    !hasProjectHomeContext ||
    selectedProjectHasDocumentInProgress ||
    isSending;
  const shouldInertBackgroundForProjectPanel =
    showProjectPanel &&
    !isProjectPanelCollapsed &&
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
      setMainView("settings");
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
    demoStatus?.projectId && demoStatus.projectId !== selectedProjectId ? null : demoStatus;
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
    Number(Boolean(selectedProject?.serverMissing)) +
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

  function setGithubRepositoryQueryForProject(projectId: string, query: string) {
    setGithubRepositoryQueries((currentQueries) => ({
      ...currentQueries,
      [projectId]: query,
    }));
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

  async function handleTestServerConnection() {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 3000);
    const nextServerUrl = resolvePaimApiRootUrl(serverUrlDraft);

    setServerTestState({ message: "연결 확인 중", status: "testing" });

    try {
      const response = await fetch(`${nextServerUrl}/health`, {
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`서버가 ${response.status} 상태를 반환했습니다`);
      }
      const health = (await response.json()) as ApiHealthResponse;

      if (health.status !== "ok") {
        throw new Error("서버 상태가 ok가 아닙니다");
      }

      setServerTestState({ message: "새 주소에 연결할 수 있습니다", status: "ok" });
    } catch {
      setServerTestState({ message: "연결 실패", status: "error" });
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  function handleApplyServerUrl() {
    const nextSettings = normalizePaimSettings({ ...settings, serverUrl: serverUrlDraft });
    const nextServerUrl = resolvePaimApiRootUrl(nextSettings.serverUrl);
    const willChangeProjectScope =
      getProjectStorageKey(authUser, canLogout, nextServerUrl) !== projectStorageKey;

    if (willChangeProjectScope && !isServerApplyConfirming) {
      setIsServerApplyConfirming(true);
      return;
    }

    savePaimSettings(nextSettings);
    setSettingsState(nextSettings);
    setServerUrlDraft(nextSettings.serverUrl);
    setIsServerApplyConfirming(false);

    if (willChangeProjectScope) {
      // 새 서버의 프로젝트와 인증 범위를 섞지 않도록 저장 후 다시 마운트한다.
      window.location.reload();
      return;
    }

    if (serverTestState.status === "ok") {
      setServerStatus("online");
    }
    void syncProjectsWithServer(false);
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
    void openUrl("https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-3rd-1Team/releases");
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

      return fetchPaimJson<ApiProjectResponse[]>("/projects", {
        signal: controller.signal,
      });
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  async function syncProjectsWithServer(showResult = false) {
    try {
      const serverProjects = await fetchServerProjects();
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
    const nextScale = Math.round(clampZoomScale(scale) * 100) / 100;
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

    return canRole(projectRolesByApiId[project.apiProjectId], minimumRole);
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

  // GitHub App state가 만료되면 repo 선택부터 다시 시작할 수 있게 인증 상태를 비운다.
  function handleGithubSessionExpired(projectId: string) {
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
  const actionMenuSession =
    openActionMenu?.type === "session"
      ? actionMenuProject?.sessions.find((session) => session.id === openActionMenu.sessionId) ??
        null
      : null;
  const actionMenuProjectRole =
    typeof actionMenuProject?.apiProjectId === "number"
      ? projectRolesByApiId[actionMenuProject.apiProjectId]
      : undefined;
  const canMutateActionMenuProject = actionMenuProject
    ? !authUser || typeof actionMenuProject.apiProjectId !== "number"
      ? true
      : canRole(actionMenuProjectRole, "member")
    : false;
  const canDeleteActionMenuProject = actionMenuProject
    ? !authUser || typeof actionMenuProject.apiProjectId !== "number"
      ? true
      : actionMenuProjectRole === "owner"
    : false;
  const isActionMenuProjectQueryPending =
    isSending && pendingProjectId === actionMenuProject?.id;
  const isActionMenuSessionQueryPending =
    isActionMenuProjectQueryPending && pendingSessionId === actionMenuSession?.id;
  const accountDisplayName = getAccountDisplayName(authUser);
  const accountInitials = getAccountInitials(authUser);
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
    setServerTestState({ message: "", status: "idle" });

    if (serverUrlSyncRef.current === settings.serverUrl) {
      return;
    }

    serverUrlSyncRef.current = settings.serverUrl;
    const timeoutId = window.setTimeout(() => {
      void syncProjectsWithServer(false);
    }, 450);

    return () => window.clearTimeout(timeoutId);
  }, [settings.serverUrl]);

  useEffect(() => {
    void getVersion()
      .then((version) => setAppVersion(version))
      .catch(() => setAppVersion(`개발 모드 ${packageJson.version}`));

    const controller = new AbortController();
    void fetch("https://api.github.com/repos/SKNETWORKS-FAMILY-AICAMP/SKN30-3rd-1Team/releases/latest", {
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

  useEffect(() => {
    projectsRef.current = projects;
  }, [projects]);

  useEffect(() => {
    selectedProjectIdRef.current = selectedProjectId;
  }, [selectedProjectId]);

  useEffect(() => {
    selectedSessionIdRef.current = selectedSessionId;
  }, [selectedSessionId]);

  useEffect(() => {
    const apiProjectId = selectedProject?.apiProjectId;
    if (!authUser || typeof apiProjectId !== "number" || serverStatus !== "online") {
      return;
    }

    const currentAuthUser = authUser;
    const selectedApiProjectId = apiProjectId;
    let disposed = false;
    let retryTimeoutId: number | null = null;

    async function loadProjectRole(attempt: number) {
      try {
        const members = await fetchProjectMembers(selectedApiProjectId);
        if (!disposed) {
          const role = getCurrentProjectMember(members, currentAuthUser)?.role ?? null;
          setProjectRolesByApiId((current) => ({
            ...current,
            [selectedApiProjectId]: role,
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

        setProjectRolesByApiId((current) => ({
          ...current,
          [selectedApiProjectId]: null,
        }));
      }
    }

    void loadProjectRole(0);

    return () => {
      disposed = true;
      if (retryTimeoutId !== null) {
        window.clearTimeout(retryTimeoutId);
      }
    };
  }, [authUser, selectedProject?.apiProjectId, serverStatus]);

  useEffect(() => {
    if (didSyncProjectsRef.current) {
      return;
    }

    didSyncProjectsRef.current = true;
    void syncProjectsWithServer();
  }, []);

  useEffect(() => {
    if (
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
    serverStatus,
  ]);

  useEffect(() => {
    if (
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
      serverStatus !== "online" ||
      !selectedProject ||
      selectedProject.serverMissing ||
      typeof selectedProject.apiProjectId !== "number"
    ) {
      return;
    }

    void syncProjectRepositories(selectedProject.id, selectedProject.apiProjectId);
  }, [
    selectedProject?.apiProjectId,
    selectedProject?.id,
    selectedProject?.serverMissing,
    serverStatus,
  ]);

  useEffect(() => {
    if (
      serverStatus !== "online" ||
      !selectedProject ||
      selectedProject.serverMissing ||
      typeof selectedProject.apiProjectId !== "number"
    ) {
      return;
    }

    void syncProjectChatSessions(selectedProject.id, selectedProject.apiProjectId);
  }, [
    selectedProject?.apiProjectId,
    selectedProject?.id,
    selectedProject?.serverMissing,
    serverStatus,
  ]);

  useEffect(() => {
    if (
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
    selectedProject?.apiProjectId,
    selectedProject?.id,
    selectedProject?.lastSeenAt,
    selectedProject?.serverMissing,
    postSyncRefreshRevision,
    settings.dueSoonDays,
    serverStatus,
  ]);

  useEffect(() => {
    window.localStorage.setItem(
      projectStorageKey,
      JSON.stringify(createStoredProjectState(projects, selectedProjectId, selectedSessionId)),
    );
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
      documentUploadControllersRef.current.forEach((controller) => controller.abort());
      documentUploadControllersRef.current.clear();
      for (const timeoutId of githubRepositoryPollTimeoutsRef.current.values()) {
        window.clearTimeout(timeoutId);
      }
      githubRepositoryPollTimeoutsRef.current.clear();
      abortLatestProjectOperations(githubOperationRegistryRef.current);
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
              (dropZone === "prompt" && selectedSessionIdRef.current))
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
        } else if (dropZone === "prompt" && selectedSessionIdRef.current) {
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
    if (mainView === "workspace" && selectedSessionId && canMutateSelectedProject) {
      focusPrompt();
    }
    // Permission hydration must not steal focus after the user has moved elsewhere.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mainView, selectedSessionId]);

  useEffect(() => {
    if (
      mainView !== "workspace" ||
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

  function scheduleDocumentStatusPoll(
    projectId: string,
    apiProjectId: number,
    attachmentId: string,
    docId: number,
    startedAt = Date.now(),
  ) {
    clearDocumentPoll(projectId, docId);

    const pollKey = `${projectId}:${docId}`;
    const timeoutId = window.setTimeout(async () => {
      try {
        const status = await fetchPaimJson<ApiDocumentStatusResponse>(
          `/projects/${apiProjectId}/documents/${docId}/status`,
        );
        const documentStatus = toProjectDocumentStatus(status.status);

        updateProjectAttachment(projectId, attachmentId, (attachment) => ({
          ...attachment,
          docId: status.doc_id,
          documentStatus,
          lastError: status.last_error ?? null,
        }));

        if (isProjectDocumentTerminal(documentStatus)) {
          void refreshProjectMemoryCounts(projectId, apiProjectId);
          setPostSyncRefreshRevision((currentRevision) => currentRevision + 1);
          documentPollTimeoutsRef.current.delete(pollKey);
          return;
        }

        if (Date.now() - startedAt >= DOCUMENT_STATUS_POLL_TIMEOUT_MS) {
          updateProjectAttachment(projectId, attachmentId, (attachment) => ({
            ...attachment,
            documentStatus: "delayed",
            lastError: "처리 지연 — 나중에 다시 확인",
          }));
          void refreshProjectMemoryCounts(projectId, apiProjectId);
          documentPollTimeoutsRef.current.delete(pollKey);
          return;
        }

        scheduleDocumentStatusPoll(projectId, apiProjectId, attachmentId, docId, startedAt);
      } catch (error) {
        updateProjectAttachment(projectId, attachmentId, (attachment) => ({
          ...attachment,
          documentStatus: "failed",
          lastError: getErrorMessage(error, "문서 처리 상태를 확인할 수 없습니다"),
        }));
        void refreshProjectMemoryCounts(projectId, apiProjectId);
        documentPollTimeoutsRef.current.delete(pollKey);
      }
    }, DOCUMENT_STATUS_POLL_INTERVAL_MS);

    documentPollTimeoutsRef.current.set(pollKey, timeoutId);
  }

  async function syncProjectDocuments(projectId: string, apiProjectId: number) {
    if (serverStatus === "offline") {
      return;
    }

    try {
      const documents = await fetchPaimJson<ApiDocumentListItem[]>(
        `/projects/${apiProjectId}/documents`,
      );
      const visibleDocuments = documents.filter(
        (document) => !cancelledDocumentIdsRef.current.has(document.id),
      );

      updateProject(projectId, (project) => ({
        ...project,
        files: mergeServerDocumentsIntoAttachments(project.files ?? [], visibleDocuments),
      }));
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

  function clearGithubRepositoryPoll(projectId: string, repoId: number) {
    const pollKey = `${projectId}:${repoId}`;
    const timeoutId = githubRepositoryPollTimeoutsRef.current.get(pollKey);

    if (typeof timeoutId === "number") {
      window.clearTimeout(timeoutId);
    }

    githubRepositoryPollTimeoutsRef.current.delete(pollKey);
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
    const timeoutId = window.setTimeout(async () => {
      try {
        const status = await fetchPaimJson<ApiRepositoryStatusResponse>(
          `/projects/${apiProjectId}/repositories/${repoId}/status`,
        );

        updateGithubRepository(projectId, (repository) =>
          applyGithubRepositoryStatus(repository, status),
        );

        if (status.status === "indexed" || status.status === "failed") {
          githubRepositoryPollTimeoutsRef.current.delete(pollKey);
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
          githubRepositoryPollTimeoutsRef.current.delete(pollKey);
          return;
        }

        scheduleGithubRepositoryStatusPoll(projectId, apiProjectId, repoId, startedAt);
      } catch (error) {
        if (isGithubSessionExpiredError(error)) {
          handleGithubSessionExpired(projectId);
          githubRepositoryPollTimeoutsRef.current.delete(pollKey);
          return;
        }

        updateGithubRepository(projectId, (repository) => ({
          ...repository,
          syncStatus: "failed",
          syncStartedAt: undefined,
          lastError: getErrorMessage(error, "GitHub repo 동기화 상태를 확인할 수 없습니다"),
        }));
        githubRepositoryPollTimeoutsRef.current.delete(pollKey);
        handleGithubSyncSettled(projectId, "failed");
      }
    }, GITHUB_REPOSITORY_SYNC_POLL_INTERVAL_MS);

    githubRepositoryPollTimeoutsRef.current.set(pollKey, timeoutId);
  }

  async function syncProjectRepositories(projectId: string, apiProjectId: number) {
    if (serverStatus === "offline") {
      return;
    }

    try {
      const repositories = await fetchPaimJson<ApiRepositoryListItem[]>(
        `/projects/${apiProjectId}/repositories`,
      );
      const serverRepository = repositories[0];

      updateProject(projectId, (project) => {
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

      const status = await fetchPaimJson<ApiRepositoryStatusResponse>(
        `/projects/${apiProjectId}/repositories/${serverRepository.id}/status`,
      );
      updateGithubRepository(projectId, (repository) =>
        applyGithubRepositoryStatus(repository, status),
      );

      if (status.status === "syncing") {
        scheduleGithubRepositoryStatusPoll(projectId, apiProjectId, serverRepository.id);
      }
    } catch (error) {
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
    }
  }

  // 서버 세션 목록과 각 세션의 복호화 메시지를 함께 가져온다.
  async function fetchProjectChatSessions(apiProjectId: number) {
    const sessions = await fetchPaimJson<ApiChatSessionResponse[]>(
      `/projects/${apiProjectId}/sessions`,
    );

    return Promise.all(
      sessions.map(async (session) => {
        const messages = await fetchPaimJson<ApiChatMessageResponse[]>(
          `/projects/${apiProjectId}/sessions/${encodeURIComponent(session.id)}/messages`,
        );

        return {
          session,
          messages: messages
            .map(createMessageFromApi)
            .filter((message): message is Message => message !== null),
        };
      }),
    );
  }

  // 선택된 프로젝트의 서버 세션을 로컬 캐시에 병합한다.
  async function syncProjectChatSessions(projectId: string, apiProjectId: number) {
    if (serverStatus === "offline") {
      return;
    }

    try {
      const serverSessions = await fetchProjectChatSessions(apiProjectId);
      const currentProject = projectsRef.current.find((project) => project.id === projectId);

      if (!currentProject) {
        return;
      }

      const nextSessions = mergeServerChatSessions(currentProject.sessions, serverSessions);

      updateProject(projectId, (project) => ({
        ...project,
        sessions: nextSessions,
      }));

      if (
        selectedProjectIdRef.current === projectId &&
        !nextSessions.some((session) => session.id === selectedSessionIdRef.current)
      ) {
        setSelectedSessionId(nextSessions[0]?.id ?? null);
      }
    } catch (error) {
      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "서버 채팅 세션을 불러올 수 없습니다"),
        scope: "overview",
      });
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
      syncStartedAt: response.status === "syncing" ? repository.syncStartedAt ?? Date.now() : undefined,
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
      .slice(-QUERY_HISTORY_LIMIT)
      .map((message) => ({
        role: message.role,
        content: message.content,
      }));
  }

  async function fetchProjectQuery(
    apiProjectId: number,
    question: string,
    history: ApiQueryHistoryMessage[],
    queryAttachments: ApiQueryAttachment[] = [],
    signal?: AbortSignal,
  ) {
    const body =
      queryAttachments.length > 0
        ? { question, history, attachments: queryAttachments }
        : { question, history };

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

  async function fetchProjectDeltaBriefing(
    apiProjectId: number,
    since: string,
    signal?: AbortSignal,
  ) {
    return fetchPaimJson<ApiDeltaBriefingResponse>(
      `/projects/${apiProjectId}/briefing/delta`,
      {
        method: "POST",
        signal,
        body: JSON.stringify({ since }),
      },
    );
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

  // 서버 업로드는 로컬 파일을 base64로 읽어 브라우저 FormData 파일로 감싼다.
  async function readUploadFile(entry: Attachment) {
    const encoded = await invoke<string>("read_file_base64", { path: entry.path });
    const bytes = base64ToBytes(encoded);

    return new File([bytes], entry.name, { type: getUploadMimeType(entry.name) });
  }

  async function readQueryAttachment(entry: Attachment): Promise<ApiQueryAttachment> {
    const encoded = await invoke<string>("read_file_base64", { path: entry.path });
    if (getBase64ByteLength(encoded) > 10 * 1024 * 1024) {
      throw new Error(t("{name}은 10 MB를 초과해 첨부할 수 없습니다", { name: entry.name }));
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
        cancelledDocumentIdsRef.current.add(response.doc_id);
        try {
          await fetchPaimJson<void>(
            `/projects/${apiProjectId}/documents/${response.doc_id}`,
            { method: "DELETE" },
          );
          cancelledDocumentIdsRef.current.delete(response.doc_id);
        } catch {
          setDemoStatus({
            ok: false,
            message: "취소한 업로드의 서버 문서를 정리하지 못했습니다",
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
        isSupportedProjectDocument(entry.name),
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
        body: JSON.stringify({ name: latestProject.name || "New Project" }),
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
      };

      updateProject(project.id, (candidate) => ({
        ...candidate,
        apiProjectId: createdProject.id,
      }));
      if (authUser) {
        setProjectRolesByApiId((current) => ({ ...current, [createdProject.id]: "owner" }));
      }

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

  // 서버에 비어 있는 채팅 세션 row를 만든다.
  async function createServerChatSession(
    apiProjectId: number,
    title: string,
  ) {
    return fetchPaimJson<ApiChatSessionResponse>(`/projects/${apiProjectId}/sessions`, {
      method: "POST",
      body: JSON.stringify({ title: title || "New Chat" }),
    });
  }

  // 로컬 세션은 첫 질문 전까지 서버 세션을 만들지 않는다.
  async function ensureServerChatSession(
    projectId: string,
    session: ChatSession,
    apiProjectId: number,
    title: string,
  ) {
    const sessionKey = `${projectId}\u0000${session.id}`;
    const latestSession = projectsRef.current
      .find((project) => project.id === projectId)
      ?.sessions.find((candidate) => candidate.id === session.id);
    if (latestSession?.serverSessionId || session.serverSessionId) {
      return latestSession?.serverSessionId ?? session.serverSessionId!;
    }

    const existingPromise = serverSessionEnsurePromisesRef.current.get(sessionKey);
    if (existingPromise) {
      return existingPromise;
    }

    const creationPromise = (async () => {
      const createdSession = await createServerChatSession(apiProjectId, title);
      const currentSession = projectsRef.current
        .find((project) => project.id === projectId)
        ?.sessions.find((candidate) => candidate.id === session.id);

      if (!currentSession) {
        try {
          await fetchPaimJson<void>(
            `/projects/${apiProjectId}/sessions/${encodeURIComponent(createdSession.id)}`,
            { method: "DELETE" },
          );
        } catch {
          // The session may already have been removed with its parent project.
        }
        throw new Error("로컬에서 제거된 채팅의 서버 생성을 취소했습니다");
      }

      updateSessionInProject(projectId, session.id, (candidate) => ({
        ...candidate,
        serverSessionId: createdSession.id,
        title: createdSession.title || candidate.title,
      }));

      return createdSession.id;
    })();

    serverSessionEnsurePromisesRef.current.set(sessionKey, creationPromise);
    try {
      return await creationPromise;
    } catch (error) {
      if (serverSessionEnsurePromisesRef.current.get(sessionKey) === creationPromise) {
        serverSessionEnsurePromisesRef.current.delete(sessionKey);
      }
      throw error;
    }
  }

  // 서버에 이미 연결된 세션의 제목 변경만 동기화한다.
  async function syncChatSessionTitle(projectId: string, sessionId: string, title: string) {
    if (serverStatus === "offline") {
      return;
    }

    const project = projectsRef.current.find((currentProject) => currentProject.id === projectId);
    const session = project?.sessions.find((currentSession) => currentSession.id === sessionId);

    if (!project || !session?.serverSessionId || typeof project.apiProjectId !== "number") {
      return;
    }

    try {
      await fetchPaimJson<ApiChatSessionResponse>(
        `/projects/${project.apiProjectId}/sessions/${encodeURIComponent(session.serverSessionId)}`,
        {
          method: "PATCH",
          body: JSON.stringify({ title }),
        },
      );
    } catch (error) {
      if (isPaimApiError(error) && error.status === 404) {
        return;
      }

      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "채팅 세션 제목을 서버에 저장할 수 없습니다"),
        scope: "overview",
      });
    }
  }

  // 서버 프로젝트가 있으면 이름 변경을 저장하고, 실패 시 로컬 이름을 되돌린다.
  async function syncProjectName(projectId: string, title: string, previousTitle: string) {
    if (serverStatus === "offline") {
      return;
    }

    const project = projectsRef.current.find((currentProject) => currentProject.id === projectId);

    if (!project || project.serverMissing || typeof project.apiProjectId !== "number") {
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

  // 서버 세션이 있으면 삭제하고, 404는 이미 삭제된 상태로 본다.
  async function deleteServerChatSession(project: ProjectWorkspace, session: ChatSession) {
    if (!session.serverSessionId) {
      return true;
    }

    if (serverStatus === "offline") {
      setDemoStatus({
        ok: false,
        message: "서버에 연결되지 않아 로컬 채팅만 삭제했습니다",
        scope: "overview",
      });
      return true;
    }

    if (typeof project.apiProjectId !== "number") {
      return true;
    }

    try {
      await fetchPaimJson<void>(
        `/projects/${project.apiProjectId}/sessions/${encodeURIComponent(session.serverSessionId)}`,
        { method: "DELETE" },
      );
      return true;
    } catch (error) {
      if (isPaimApiError(error) && error.status === 404) {
        return true;
      }

      setDemoStatus({
        ok: false,
        message: getErrorMessage(error, "채팅 세션을 서버에서 삭제할 수 없습니다"),
        scope: "overview",
      });
      return false;
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

  function handleSelectProject(projectId: string) {
    const nextProject = projects.find((project) => project.id === projectId);

    if (!nextProject) {
      return;
    }

    const nextSessionId = nextProject.sessions[0]?.id ?? null;
    rememberCurrentDraft();
    setMainView("workspace");
    setSelectedProjectId(nextProject.id);
    setSelectedSessionId(nextSessionId);
    showSessionDraft(nextProject.id, nextSessionId);
  }

  // 새 프로젝트는 먼저 홈에서 자료를 받기 위해 채팅 세션 없이 만든다.
  function createProjectFromName(baseName: string, files: Attachment[] = []) {
    const nextProject = createProject(createUniqueProjectName(projects, baseName), [], files);

    rememberCurrentDraft();
    setProjects((currentProjects) => [nextProject, ...currentProjects]);
    setIsSidebarCollapsed(false);
    setIsSidebarResizing(false);
    setMainView("workspace");
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

  // 지정한 프로젝트 안에 새 채팅을 항상 추가하고 그 채팅을 선택한다.
  function handleCreateChatInProject(projectId: string) {
	  const targetProject = projects.find((project) => project.id === projectId);

    if (!targetProject || shouldSkipProjectPermission(targetProject)) {
      return;
    }

    const nextSession = createEmptySession();

    rememberCurrentDraft();
    updateProject(projectId, (project) => ({
      ...project,
      sessions: [nextSession, ...project.sessions],
    }));
    setMainView("workspace");
    setSelectedProjectId(projectId);
    setSelectedSessionId(nextSession.id);
    closeProjectPanel();
	  resetVisibleDraft();
	  focusPrompt();
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
          paths.map(async (path) => {
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
      const failedCount = paths.length - entries.length;
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
        filters: [{ name: t("지원 문서"), extensions: ["md", "txt", "pdf", "docx"] }],
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

  async function handleStartGithubLogin(projectId: string) {
    const targetProject = projects.find((project) => project.id === projectId);

    if (!targetProject || shouldSkipProjectPermission(targetProject, "github")) {
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

    if (!targetProject || shouldSkipProjectMutation(targetProject, "github")) {
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
    if (!targetProject || shouldSkipProjectPermission(targetProject, "github")) {
      return;
    }

    if (session.state && shouldSkipProjectMutation(targetProject, "github")) {
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

    if (!targetProject || shouldSkipProjectPermission(targetProject, "github")) {
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
    if (!targetProject || shouldSkipProjectPermission(targetProject, "github")) {
      return;
    }

    if (session.state && shouldSkipProjectMutation(targetProject, "github")) {
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
    if (!targetProject || shouldSkipProjectPermission(targetProject, "github")) {
      return;
    }

    if (session?.state && shouldSkipProjectMutation(targetProject, "github")) {
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

    if (shouldSkipProjectMutation(project, "github")) {
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
          syncStartedAt: connected.status === "syncing" ? repository.syncStartedAt ?? Date.now() : undefined,
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
    if (shouldSkipProjectPermission(project, "github")) {
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
      if (shouldSkipProjectMutation(project, "github")) {
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

      cancelGithubOperation(projectId);
      try {
        await fetchPaimJson<void>(
          `/projects/${project.apiProjectId}/repositories/${repoId}`,
          { method: "DELETE" },
        );
      } catch (error) {
        if (isGithubSessionExpiredError(error)) {
          handleGithubSessionExpired(projectId);
          return;
        }

        const detail = getErrorMessage(error, "GitHub repo 연결을 해제할 수 없습니다");

        if (!/repository not found/i.test(detail)) {
          setDemoStatus({
            ok: false,
            message: detail,
            projectId,
            scope: "github",
          });
          return;
        }
      }

      clearGithubRepositoryPoll(projectId, repoId);
    } else {
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

  function toggleProjectActionMenu(projectId: string, event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();
    setIsAccountMenuOpen(false);
    actionMenuTriggerRef.current = event.currentTarget;
    const position = getActionMenuPosition(event.currentTarget, ACTION_MENU_PROJECT_HEIGHT);

    setOpenActionMenu((current) =>
      current?.type === "project" && current.projectId === projectId
        ? null
        : { type: "project", projectId, ...position },
    );
  }

  function handleProjectContextMenu(projectId: string, event: MouseEvent<HTMLElement>) {
    event.preventDefault();
    event.stopPropagation();
    setIsAccountMenuOpen(false);
    actionMenuTriggerRef.current = event.currentTarget.matches("button")
      ? event.currentTarget
      : event.currentTarget.querySelector<HTMLElement>("button");
    setOpenActionMenu({
      type: "project",
      projectId,
      ...getActionMenuPositionAtPoint(
        event.clientX,
        event.clientY,
        ACTION_MENU_PROJECT_HEIGHT,
      ),
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
    setMainView(view);
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

  // 행 안에서 바로 수정하도록 프로젝트명 입력을 연다.
  function openProjectMembers(projectId: string) {
    const targetProject = projects.find((project) => project.id === projectId);
    if (!targetProject || !authUser || typeof targetProject.apiProjectId !== "number") {
      return;
    }

    const targetSessionId = targetProject.sessions[0]?.id ?? null;
    mainViewReturnFocusRef.current = actionMenuTriggerRef.current;
    rememberCurrentDraft();
    setSelectedProjectId(projectId);
    setSelectedSessionId(targetSessionId);
    setMainView("members");
    setOpenActionMenu(null);
    showSessionDraft(projectId, targetSessionId);
  }

  // 행 안에서 바로 수정하도록 프로젝트명 입력을 연다.
  function beginRenameProject(projectId: string, trigger?: HTMLElement) {
    const targetProject = projects.find((project) => project.id === projectId);

    if (!targetProject) {
      return;
    }

    if (trigger) {
      actionMenuTriggerRef.current = trigger;
    }

    setRenameDraft({ type: "project", projectId, value: targetProject.name });
    setPendingDeleteProjectId(null);
    setOpenActionMenu(null);
  }

  // 행 안에서 바로 수정하도록 채팅명 입력을 연다.
  function beginRenameSession(projectId: string, sessionId: string, trigger?: HTMLElement) {
    const targetSession = projects
      .find((project) => project.id === projectId)
      ?.sessions.find((session) => session.id === sessionId);

    if (!targetSession) {
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

    const nextValue = rawValue.trim();

    if (!nextValue) {
      setRenameDraft(null);
      restoreRenameTriggerFocus(restoreFocus);
      return;
    }

    if (renameDraft.type === "project") {
      const targetProject = projects.find((project) => project.id === renameDraft.projectId);
      const previousName = targetProject?.name ?? nextValue;

      updateProject(renameDraft.projectId, (project) => ({
        ...project,
        name: nextValue,
      }));
      void syncProjectName(renameDraft.projectId, nextValue, previousName);
    } else {
      updateSessionInProject(renameDraft.projectId, renameDraft.sessionId, (session) => ({
        ...session,
        title: nextValue,
      }));
      void syncChatSessionTitle(renameDraft.projectId, renameDraft.sessionId, nextValue);
    }

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

  function returnToWorkspace() {
    const returnView = mainView;
    setMainView("workspace");
    window.requestAnimationFrame(() => {
      const returnTarget = mainViewReturnFocusRef.current;
      if (returnTarget?.isConnected) {
        returnTarget.focus();
      } else if (
        (returnView === "profile" || returnView === "settings") &&
        accountMenuTriggerRef.current?.isConnected
      ) {
        accountMenuTriggerRef.current.focus();
      } else {
        promptTextareaRef.current?.focus();
      }
      mainViewReturnFocusRef.current = null;
    });
  }

  // 히스토리에서 채팅 세션을 제거하고 마지막 세션이면 빈 채팅으로 남긴다.
  async function handleDeleteSession(
    projectId: string,
    sessionId: string,
    event: MouseEvent<HTMLButtonElement>,
  ) {
    const targetProject = projects.find((project) => project.id === projectId);

    event.stopPropagation();

    if (!targetProject) {
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
        message: "한 번 더 누르면 이 채팅과 대화 기록을 삭제합니다",
        scope: "overview",
      });
      return;
    }

    const targetSession = targetProject.sessions.find((session) => session.id === sessionId);

    if (!targetSession || !(await deleteServerChatSession(targetProject, targetSession))) {
      return;
    }

    const latestProject = projectsRef.current.find((project) => project.id === projectId);
    if (!latestProject) {
      return;
    }

    const remainingSessions = latestProject.sessions.filter((session) => session.id !== sessionId);
    const nextSessions = remainingSessions.length > 0 ? remainingSessions : [createEmptySession()];
    const shouldMoveSelection =
      selectedProjectIdRef.current === projectId &&
      (sessionId === selectedSessionIdRef.current ||
        !nextSessions.some((session) => session.id === selectedSessionIdRef.current));

    updateProject(projectId, (project) => ({
      ...project,
      sessions: nextSessions,
    }));

    if (shouldMoveSelection) {
      setSelectedSessionId(nextSessions[0]?.id ?? null);
      if (pendingProjectId === projectId && pendingSessionId === sessionId) {
        cancelActiveQueryForProject(projectId);
      }
      forgetSessionDraft(projectId, sessionId);
      showSessionDraft(projectId, nextSessions[0]?.id ?? null);
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

    const nextSession: ChatSession = {
      ...createEmptySession(),
      title: "Project Briefing",
      messages: [],
    };
    const requestStartedAt = Date.now();
    const { controller, timeoutId } = beginActiveQuery();

    updateProject(project.id, (currentProject) => ({
      ...currentProject,
      sessions: [nextSession, ...currentProject.sessions],
    }));
    setSelectedProjectId(project.id);
    setSelectedSessionId(nextSession.id);
    closeProjectPanel();
    setIsSending(true);
    setPendingProjectId(project.id);
    setPendingSessionId(nextSession.id);
    setThinkingStartedAt(requestStartedAt);
    rememberCurrentDraft();
    resetVisibleDraft();
    focusPrompt();

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

      const response = await fetchProjectQuery(
        apiProject.apiProjectId,
        PROJECT_BRIEFING_QUESTION,
        [],
        [],
        controller.signal,
      );
      const thinkingSeconds = Math.max(1, Math.ceil((Date.now() - requestStartedAt) / 1000));

      updateSessionInProject(project.id, nextSession.id, (session) => ({
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
    } catch (error) {
      if (!isUserCancelledQuery(error, controller)) {
        updateSessionInProject(project.id, nextSession.id, (session) => ({
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

  function handleDismissProjectDelta() {
    if (!selectedProjectDelta) {
      return;
    }

    ignoredProjectDeltaRef.current[selectedProjectDelta.projectId] = selectedProjectDelta.since;
    markProjectSeen(selectedProjectDelta.projectId);
    setProjectDeltaBanner(null);
  }

  async function handleRequestProjectDeltaBriefing() {
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
    let targetSessionId = selectedSession?.id ?? null;

    if (!targetSessionId) {
      const nextSession = createEmptySession();
      targetSessionId = nextSession.id;
      updateProject(targetProjectId, (project) => ({
        ...project,
        sessions: [nextSession, ...project.sessions],
      }));
      setSelectedSessionId(nextSession.id);
    }

    const requestStartedAt = Date.now();
    const { controller, timeoutId } = beginActiveQuery();
    setIsSending(true);
    setPendingProjectId(targetProjectId);
    setPendingSessionId(targetSessionId);
    setThinkingStartedAt(requestStartedAt);
    focusPrompt();

    try {
      const response = await fetchProjectDeltaBriefing(
        selectedProject.apiProjectId,
        selectedProjectDelta.since,
        controller.signal,
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
      ignoredProjectDeltaRef.current[targetProjectId] = selectedProjectDelta.since;
      markProjectSeen(targetProjectId);
      setProjectDeltaBanner(null);
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

  // 프로젝트 삭제 후에는 남은 프로젝트로 선택을 옮기고, 마지막이면 빈 상태로 둔다.
  async function handleDeleteProject(projectId: string, event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();

    const targetProject = projects.find((project) => project.id === projectId);

    if (!targetProject) {
      return;
    }

    if (pendingDeleteProjectId !== projectId) {
      setPendingDeleteProjectId(projectId);
      setDemoStatus({
        kind: "warning",
        ok: false,
        message:
          typeof targetProject.apiProjectId === "number"
            ? "한 번 더 누르면 서버의 문서·메모리·채팅까지 삭제됩니다"
            : "한 번 더 누르면 로컬 프로젝트를 삭제합니다",
        scope: "overview",
      });
      return;
    }

    if (!(await deleteServerProject(targetProject))) {
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
      showSessionDraft(nextState.selectedProjectId ?? "", nextState.selectedSessionId);
    }
  }

  // 렌더링이 끝난 뒤 채팅 입력창으로 포커스를 복원한다.
  function focusPrompt() {
    window.requestAnimationFrame(() => {
      promptTextareaRef.current?.focus();
    });
  }

  function getSessionDraftKey(projectId: string, sessionId: string) {
    return `${projectId}\u0000${sessionId}`;
  }

  function handlePromptChange(nextPrompt: string) {
    setPrompt(nextPrompt);

    const projectId = selectedProjectIdRef.current;
    const sessionId = selectedSessionIdRef.current;
    if (!projectId || !sessionId) {
      return;
    }

    const key = getSessionDraftKey(projectId, sessionId);
    if (!nextPrompt.trim() && attachments.length === 0) {
      sessionDraftsRef.current.delete(key);
      return;
    }

    sessionDraftsRef.current.set(key, {
      attachments: [...attachments],
      prompt: nextPrompt,
    });
  }

  // 세션을 떠나도 작성 중인 텍스트와 첨부가 남도록 메모리 안에 세션별로 보관한다.
  function rememberCurrentDraft() {
    if (!selectedProjectId || !selectedSessionId) {
      return;
    }

    // 세션 전환 클릭은 React state commit보다 먼저 들어올 수 있으므로 현재 DOM 값을 우선한다.
    const currentPrompt = promptTextareaRef.current?.value ?? prompt;
    const key = getSessionDraftKey(selectedProjectId, selectedSessionId);
    if (!currentPrompt.trim() && attachments.length === 0) {
      sessionDraftsRef.current.delete(key);
      return;
    }

    sessionDraftsRef.current.set(key, { attachments: [...attachments], prompt: currentPrompt });
  }

  function showSessionDraft(projectId: string, sessionId: string | null) {
    const draft = sessionId
      ? sessionDraftsRef.current.get(getSessionDraftKey(projectId, sessionId))
      : undefined;

    setPrompt(draft?.prompt ?? "");
    setAttachments(draft ? [...draft.attachments] : []);
  }

  function forgetSessionDraft(projectId: string, sessionId: string) {
    sessionDraftsRef.current.delete(getSessionDraftKey(projectId, sessionId));
  }

  function forgetProjectDrafts(projectId: string) {
    const prefix = `${projectId}\u0000`;
    Array.from(sessionDraftsRef.current.keys()).forEach((key) => {
      if (key.startsWith(prefix)) {
        sessionDraftsRef.current.delete(key);
      }
    });
  }

  function resetVisibleDraft() {
    setPrompt("");
    setAttachments([]);
  }

  function handleSelectSession(projectId: string, sessionId: string) {
    rememberCurrentDraft();
    setMainView("workspace");
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
    if (!selectedProject || !selectedSession) {
      return;
    }

    const selectedPaths = await open({
      multiple: true,
      directory: false,
      filters: [{ name: t("지원 문서"), extensions: ["md", "txt", "pdf", "docx"] }],
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
    if (!selectedProject || !selectedSession || paths.length === 0) {
      return;
    }

    const supportedPaths = paths.filter((path) => isSupportedProjectDocument(getFileName(path)));
    const skippedCount = paths.length - supportedPaths.length;
    if (supportedPaths.length !== paths.length) {
      setDemoStatus({
        kind: "warning",
        ok: false,
        message: t("{added}개 추가 · {skipped}개 제외 — 채팅 첨부는 md/txt/pdf를 지원합니다", {
          added: supportedPaths.length,
          skipped: skippedCount,
        }),
        scope: "overview",
      });
    }
    if (supportedPaths.length === 0) {
      return;
    }

    const nextAttachments = await Promise.all(supportedPaths.map(createAttachment));

    setAttachments((currentAttachments) => [...currentAttachments, ...nextAttachments]);
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
    setAttachments((currentAttachments) =>
      currentAttachments.filter((attachment) => attachment.id !== attachmentId),
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedPrompt = prompt.trim();

    if (!selectedProject || !selectedSession || (!trimmedPrompt && attachments.length === 0) || isSending) {
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

    const targetProjectId = selectedProject.id;
    const targetSessionId = selectedSession.id;
    const messageAttachments = attachments;
    const question = trimmedPrompt || "첨부 파일을 확인해줘";
    const nextSessionTitle =
      selectedSession.title === "New Chat"
        ? (trimmedPrompt || messageAttachments[0]?.name || "File attachment").slice(0, 32)
        : selectedSession.title;
    const history = createQueryHistory(selectedSession.messages);
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
      messages: [...session.messages, userMessage],
    }));
    forgetSessionDraft(targetProjectId, targetSessionId);
    resetVisibleDraft();

    try {
      let queryAttachments: ApiQueryAttachment[] = [];
      if (messageAttachments.length > 0) {
        if (canUseTauriDialog()) {
          queryAttachments = await Promise.all(messageAttachments.map(readQueryAttachment));
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

      // Server ids created by a POST must be collected even when the user stops.
      // Only the final query request is abortable; otherwise a commit-after-abort
      // response could be lost and create duplicate projects or sessions later.
      const apiProject = await ensureApiProject(selectedProject);

      if (typeof apiProject.apiProjectId !== "number") {
        throw new Error("서버 프로젝트를 준비할 수 없습니다");
      }
      if (controller.signal.aborted) {
        throw new DOMException("Query cancelled", "AbortError");
      }

      const serverSessionId = await ensureServerChatSession(
        targetProjectId,
        selectedSession,
        apiProject.apiProjectId,
        nextSessionTitle,
      );

      if (selectedSession.serverSessionId && nextSessionTitle !== selectedSession.title) {
        void syncChatSessionTitle(targetProjectId, targetSessionId, nextSessionTitle);
      }

      updateSessionInProject(targetProjectId, targetSessionId, (session) => ({
        ...session,
        serverSessionId,
        title: nextSessionTitle,
      }));
      if (controller.signal.aborted) {
        throw new DOMException("Query cancelled", "AbortError");
      }

      const response = await fetchProjectQuery(
        apiProject.apiProjectId,
        question,
        history,
        queryAttachments,
        controller.signal,
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
    const apiProjectId = selectedProject?.apiProjectId;
    if (typeof apiProjectId !== "number") {
      return;
    }

    setProjectRolesByApiId((current) => ({ ...current, [apiProjectId]: currentRole }));
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
    setMainView("workspace");
    setOpenActionMenu(null);
    showSessionDraft(nextState.selectedProjectId ?? "", nextState.selectedSessionId);
    mainViewReturnFocusRef.current = null;
    window.requestAnimationFrame(() => {
      const focusTarget =
        promptTextareaRef.current ??
        mainViewHeadingRef.current ??
        document.querySelector<HTMLElement>(".project-start-button, .project-create-trigger");
      focusTarget?.focus({ preventScroll: true });
    });
  }

  function renderMembersPage() {
    return (
      <section className="members-page" aria-label={t("프로젝트 멤버 관리")}>
        <div className="members-page-content">
          <header className="settings-header members-page-header">
            <Button
              className="settings-back-button"
              icon={<ArrowLeft size={15} />}
              isIconOnly
              label={t("멤버 관리에서 돌아가기")}
              onClick={returnToWorkspace}
              tooltip={t("돌아가기")}
              variant="ghost"
            />
            <div>
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
        </div>
      </section>
    );
  }

  function renderProfilePage() {
    return (
      <section className="profile-page" aria-label={t("프로필")}>
        <div className="profile-content">
          <header className="settings-header">
            <Button
              className="settings-back-button"
              icon={<ArrowLeft size={15} />}
              isIconOnly
              label={t("프로필에서 돌아가기")}
              onClick={returnToWorkspace}
              tooltip={t("돌아가기")}
              variant="ghost"
            />
            <h1 ref={mainViewHeadingRef} tabIndex={-1}>{t("프로필")}</h1>
          </header>

          <section className="profile-identity-card" aria-label={t("계정 정보")}>
            <span aria-hidden="true" className="account-avatar profile-avatar">
              {accountInitials}
            </span>
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
              <dt>{t("서버 상태")}</dt>
              <dd>
                <span className="profile-connection" data-status={serverStatus}>
                  <span aria-hidden="true" className="profile-connection-dot" />
                  {serverStatus === "online" ? t("서버 연결됨") : t("서버 오프라인")}
                </span>
              </dd>
            </div>
          </dl>

          {authUser ? (
            <p className="profile-note">
              {t("계정 정보는 현재 연결된 PaiM 서버에서 관리됩니다.")}
            </p>
          ) : (
            <Banner
              container="card"
              status="warning"
              title={t("오프라인 또는 인증이 없는 개발 서버를 사용 중입니다.")}
            />
          )}
        </div>
      </section>
    );
  }

  function renderSettingsPage() {
    const effectiveServerUrl = settings.serverUrl || getPaimApiRootUrl() || DEFAULT_PAIM_API_ROOT_URL;
    const normalizedServerUrlDraft = normalizePaimServerUrl(serverUrlDraft);
    const isServerUrlDirty = normalizedServerUrlDraft !== normalizePaimServerUrl(settings.serverUrl);
    const draftServerUrl = resolvePaimApiRootUrl(normalizedServerUrlDraft);
    const willServerApplyReload =
      isServerUrlDirty &&
      getProjectStorageKey(authUser, canLogout, draftServerUrl) !== projectStorageKey;

    return (
      <section className="settings-page" aria-label={t("설정")}>
        <div className="settings-content">
          <header className="settings-header">
            <Button
              className="settings-back-button"
              icon={<ArrowLeft size={15} />}
              isIconOnly
              label={t("설정에서 돌아가기")}
              onClick={returnToWorkspace}
              tooltip={t("돌아가기")}
              variant="ghost"
            />
            <h1 ref={mainViewHeadingRef} tabIndex={-1}>{t("설정")}</h1>
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
              <p>{t("텍스트와 인터페이스를 100%에서 200%까지 확대합니다.")}</p>
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

          <section className="settings-group" aria-label={t("서버 주소")}>
            <div className="settings-copy">
              <h2>{t("서버 주소")}</h2>
              <p>{t("비우면 기본 주소 {url}로 돌아갑니다.", { url: DEFAULT_PAIM_API_ROOT_URL })}</p>
            </div>
            <div className="settings-control-stack">
              <div className="settings-inline-control">
                <TextInput
                  isLabelHidden
                  label={t("PaiM 서버 주소")}
                  onChange={(value) => {
                    setServerUrlDraft(value);
                    setServerTestState({ message: "", status: "idle" });
                    setIsServerApplyConfirming(false);
                  }}
                  placeholder={DEFAULT_PAIM_API_ROOT_URL}
                  value={serverUrlDraft}
                  width="100%"
                />
              </div>
              <div className="settings-server-actions">
                <Button
                  isLoading={serverTestState.status === "testing"}
                  label={t("연결 테스트")}
                  onClick={() => void handleTestServerConnection()}
                  variant="secondary"
                />
                {isServerApplyConfirming ? (
                  <Button
                    label={t("취소")}
                    onClick={() => setIsServerApplyConfirming(false)}
                    variant="secondary"
                  />
                ) : null}
                <Button
                  isDisabled={!isServerUrlDirty || serverTestState.status === "testing"}
                  label={
                    isServerApplyConfirming
                      ? t("전환하고 다시 시작")
                      : willServerApplyReload
                        ? t("서버 전환 적용")
                        : t("주소 적용")
                  }
                  onClick={handleApplyServerUrl}
                  variant={isServerApplyConfirming ? "primary" : "secondary"}
                />
              </div>
              <p
                className="settings-status"
                aria-atomic="true"
                role="status"
              >
                <StatusDot
                  label={serverStatus === "online" ? t("서버 연결됨") : t("서버 오프라인")}
                  variant={serverStatus === "online" ? "success" : "error"}
                />
                {t(serverStatus === "online" ? "현재 연결됨 · {url}{message}" : "현재 오프라인 · {url}{message}", {
                  message: "",
                  url: effectiveServerUrl,
                })}
              </p>
              {isServerUrlDirty ? (
                <p
                  aria-live="polite"
                  className="settings-draft-status"
                  data-status={isServerApplyConfirming ? "warning" : serverTestState.status}
                >
                  {isServerApplyConfirming
                    ? t("적용하면 앱이 다시 시작되고 새 서버의 프로젝트로 전환됩니다.")
                    : serverTestState.message
                      ? t(serverTestState.message)
                      : willServerApplyReload
                        ? t("새 서버 주소입니다. 연결을 확인한 뒤 적용하세요.")
                        : t("적용하지 않은 변경 사항이 있습니다.")}
                </p>
              ) : null}
            </div>
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
                  : t("프로젝트·대화·계정·서버 주소는 유지하고 앱 설정만 기본값으로 되돌립니다.")}
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
        </div>
      </section>
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
          {mainView === "workspace" && selectedSession ? (
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
              </nav>
            ) : null}
            {hasProjects ? (
              <section className="projects project-tree" aria-label={t("프로젝트")}>
              <h2>{t("프로젝트")}</h2>
              <div className="project-tree-list" role="list">
                {projects.map((project) => {
                  const isActiveProject = project.id === selectedProjectId;

                  return (
                    <div
                      className="project-group"
                      data-active={isActiveProject ? "true" : undefined}
                      data-project-id={project.id}
                      key={project.id}
                      role="listitem"
                    >
                      <div
                        className="project-row"
                        onContextMenu={(event) => handleProjectContextMenu(project.id, event)}
                      >
                        <div className="project-title">
                          {renameDraft?.type === "project" &&
                          renameDraft.projectId === project.id ? (
                            <div className="project-item project-rename-editor">
                              <FolderOpen aria-hidden="true" size={14} />
                              <TextInput
                                className="rename-input"
                                hasAutoFocus
                                isLabelHidden
                                label={t("프로젝트 이름 변경")}
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
                              aria-current={isActiveProject ? "page" : undefined}
                              className="project-item"
                              data-active={isActiveProject ? "true" : undefined}
                              data-project-id={project.id}
                              data-project-name={project.name}
                              icon={<FolderOpen size={14} />}
                              label={project.name}
                              onClick={() => handleSelectProject(project.id)}
                              onContextMenu={(event) =>
                                handleProjectContextMenu(project.id, event)
                              }
                              tooltip={project.name}
                              variant="ghost"
                            >
                              <span className="project-name">{project.name}</span>
                            </Button>
                          )}
                        </div>
                        {isActiveProject ? (
                          <div className="project-actions">
                            <IconButton
                              className="project-chat-create-button"
                              icon={<Plus size={13} />}
                              isDisabled={!canMutateSelectedProject}
                              label={t("{name}에 새 채팅 만들기", { name: project.name })}
                              onClick={(event) => {
                                event.stopPropagation();
                                handleCreateChatInProject(project.id);
                              }}
                              tooltip={t("{name}에 새 채팅 만들기", {
                                name: project.name,
                              })}
                              variant="ghost"
                            />
                            <IconButton
                              aria-expanded={
                                openActionMenu?.type === "project" &&
                                openActionMenu.projectId === project.id
                              }
                              aria-haspopup="menu"
                              className="project-action-menu-button"
                              icon={<Ellipsis size={14} />}
                              label={t("{name} 메뉴", { name: project.name })}
                              onClick={(event) =>
                                toggleProjectActionMenu(project.id, event)
                              }
                              tooltip={t("{name} 메뉴", { name: project.name })}
                              variant="ghost"
                            />
                          </div>
                        ) : null}
                      </div>

                      {isActiveProject ? (
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
                                  <MessageSquare size={13} />
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
                                  icon={<MessageSquare size={13} />}
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
                  <span aria-hidden="true" className="account-avatar sidebar-account-avatar">
                    {accountInitials}
                  </span>
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
                <span aria-hidden="true" className="account-avatar account-menu-avatar">
                  {accountInitials}
                </span>
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
            {openActionMenu.type === "project" ? (
              <>
                <Button
                  data-action="rename-project"
                  isDisabled={!canMutateActionMenuProject}
                  label={t("Name change")}
                  onClick={() => beginRenameProject(actionMenuProject.id)}
                  role="menuitem"
                  size="sm"
                  variant="ghost"
                />
                {authUser && typeof actionMenuProject.apiProjectId === "number" ? (
                  <Button
                    data-action="manage-project-members"
                    icon={<Users size={14} />}
                    label={t("멤버 관리")}
                    onClick={() => openProjectMembers(actionMenuProject.id)}
                    role="menuitem"
                    size="sm"
                    variant="ghost"
                  />
                ) : null}
                <Button
                  className="danger"
                  data-action="delete-project"
                  isDisabled={!canDeleteActionMenuProject || isActionMenuProjectQueryPending}
                  label={pendingDeleteProjectId === actionMenuProject.id ? t("Delete again") : t("Delete")}
                  onClick={(event) => void handleDeleteProject(actionMenuProject.id, event)}
                  role="menuitem"
                  size="sm"
                  variant="destructive"
                />
              </>
            ) : actionMenuSession ? (
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
          mainView === "workspace" && selectedSession?.messages.length === 0 ? "true" : undefined
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
              <Banner
                className="notice"
                container="card"
                endContent={
                  <Button
                    label={t("다시 연결")}
                    onClick={() => void syncProjectsWithServer(true)}
                    size="sm"
                    variant="primary"
                  />
                }
                status="error"
                title={t("PaiM 서버에 연결할 수 없습니다 — 마지막 저장 상태를 표시 중")}
              />
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
            {selectedProject?.serverMissing ? (
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
        ) : selectedSession ? (
          <>
            {selectedSession.messages.length === 0 ? (
              isProjectBriefingPending ? (
                <div className="chat-empty chat-analysis-pending">
                  <div className="analysis-progress">
                    <Spinner aria-label={t("프로젝트 분석 중")} shade="subtle" size="md" />
                    <h1>{t("프로젝트를 분석하고 있습니다")}</h1>
                    <p>
                      {t("{step} · {seconds}초", {
                        seconds: thinkingElapsedSeconds,
                        step: t(projectAnalysisPendingStep),
                      })}
                    </p>
                  </div>
                </div>
              ) : (
              <div className="chat-empty">
                <h1>
                  {t("{name}에서 무엇을 도와드릴까요?", {
                    name: selectedProject?.name ?? "PaiM",
                  })}
                </h1>
              </div>
              )
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
                  {selectedSession.messages.map((message, messageIndex) => (
                    <article
                      className="message"
                      data-briefing={
                        selectedSession.title === "Project Briefing" &&
                        message.role === "assistant" &&
                        messageIndex === 0
                          ? "true"
                          : undefined
                      }
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
                          <div className="assistant">
                            {selectedSession.title === "Project Briefing" && messageIndex === 0 ? (
                              <span className="message-briefing-label">{t("프로젝트 브리핑")}</span>
                            ) : null}
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
                                className="md"
                                density="compact"
                                headingLevelStart={3}
                              >
                                {message.content}
                              </LazyMarkdown>
                            </Suspense>
                            {message.sources && message.sources.length > 0 ? (
                              <div className="sources" aria-label={t("출처")}>
                                <span className="label">{t("출처")}</span>
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
                          <span className="dots">{t("생각 중")}</span> · {t("{seconds}초", {
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
              <div className="prompt-actions">
                <IconButton
                  icon={<Plus size={17} />}
                  isDisabled={!canMutateSelectedProject}
                  label={t("파일 추가")}
                  onClick={() => void handlePickFiles()}
                  tooltip={selectedProjectReadOnlyReason ?? t("파일 추가")}
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
        ) : selectedProject ? (
          <>
            <section
              className="project-home"
              data-drop-zone="project-files"
              aria-label={t("프로젝트 시작 화면")}
            >
              <div
                className="project-home-content"
                data-has-sources={selectedProjectFileCount > 0 ? "true" : "false"}
              >
                <div className="project-home-main">
                  <div className="project-home-name-row">
                    <TextInput
                      className="project-home-name"
                      isDisabled={!canMutateSelectedProject}
                      isLabelHidden
                      label={t("프로젝트 이름")}
                      onBlur={(event) => {
                        const currentValue = (event.target as HTMLInputElement).value;
                        const previousName =
                          projectHomeNameBeforeEditRef.current ?? selectedProject.name;
                        const nextName =
                          currentValue.trim() ||
                          createNextProjectName(
                            projects.filter((project) => project.id !== selectedProject.id),
                          );

                        updateProject(selectedProject.id, (project) => ({
                          ...project,
                          name: nextName,
                        }));
                        projectHomeNameBeforeEditRef.current = null;

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
                        projectHomeNameBeforeEditRef.current = selectedProject.name;
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
                            projectHomeNameBeforeEditRef.current ?? selectedProject.name;
                          event.currentTarget.value = previousName;
                          updateProject(selectedProject.id, (project) => ({
                            ...project,
                            name: previousName,
                          }));
                          projectHomeNameBeforeEditRef.current = previousName;
                          event.currentTarget.blur();
                        }
                      }}
                      data-default-name={isSelectedProjectDefaultName ? "true" : undefined}
                      placeholder={t("New Project 1")}
                      value={selectedProject.name}
                      width="100%"
                    />
                    <Pencil aria-hidden="true" className="project-home-name-edit" size={15} />
                  </div>
                  <p className="project-home-subtitle">
                    {selectedProjectFileCount > 0
                      ? t("{count}개 자료가 연결되었습니다", { count: selectedProjectFileCount })
                      : t("자료를 추가하거나 설명만으로 바로 대화를 시작하세요")}
                  </p>
                  <TextArea
                    className="project-home-description"
                    isDisabled={!canMutateSelectedProject}
                    isLabelHidden
                    label={t("프로젝트 설명")}
                    onChange={(nextDescription) => {
                      updateProject(selectedProject.id, (project) => ({
                        ...project,
                        description: nextDescription,
                      }));
                    }}
                    placeholder={t("프로젝트 설명을 적어두면 PaiM이 맥락을 잡는 데 도움이 됩니다.")}
                    rows={2}
                    value={selectedProject.description ?? ""}
                    width="100%"
                  />

                  <div
                    className="project-home-canvas"
                    data-state={selectedProjectFileCount > 0 ? "filled" : "empty"}
                  >
                    {selectedProjectFileCount > 0 ? (
                      <div
                        aria-label={t("프로젝트 자료")}
                        className="project-home-canvas-filled"
                        role="group"
                      >
                        <div className="project-home-upload-summary">
                          <span className="project-home-summary-item" data-kind="ready">
                            {t("{count}개 완료", { count: selectedProjectSetupStatusCounts.ready })}
                          </span>
                          <span className="project-home-summary-item" data-kind="processing">
                            {t("{count}개 처리 중", {
                              count: selectedProjectSetupStatusCounts.processing,
                            })}
                          </span>
                          <span className="project-home-summary-item" data-kind="failed">
                            {t("{count}개 실패", { count: selectedProjectSetupStatusCounts.failed })}
                          </span>
                          <Button
                            className="project-home-summary-action"
                            isDisabled={!canMutateSelectedProject}
                            label={t("자료 더 추가")}
                            onClick={() => void handleOpenProjectFiles(selectedProject.id)}
                            size="sm"
                            variant="ghost"
                          />
                        </div>
                        {selectedProjectSetupVisibleSources.map((source) => {
                          const sourceMeta =
                            source.kind === "directory"
                              ? { Icon: FolderOpen, color: "var(--muted)" }
                              : getProjectFileVisualMeta(source.name);
                          const SourceIcon = sourceMeta.Icon;
                          const sourceStatus =
                            source.documentStatus ?? (source.kind === "directory" ? "folder" : "local");

                          return (
                            <div
                              className="project-home-source-row"
                              data-delete={
                                pendingSetupDeleteProjectFileId === source.id ? "confirm" : undefined
                              }
                              data-status={sourceStatus}
                              key={source.id}
                            >
                              <span className="project-home-source-icon" style={{ color: sourceMeta.color }}>
                                <SourceIcon size={15} />
                              </span>
                              <span className="project-home-source-name">{source.name}</span>
                              <span className="project-home-source-status">
                                {t(getProjectSetupSourceStatusLabel(source))}
                              </span>
                              <IconButton
                                className="project-home-source-delete"
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
                        {selectedProjectSetupHiddenSourceCount > 0 ? (
                          <Button
                            className="project-home-source-more"
                            label={t("외 {count}개 자료 보기", {
                              count: selectedProjectSetupHiddenSourceCount,
                            })}
                            onClick={() => {
                              openProjectPanel();
                              openProjectPanelTool("files");
                            }}
                            size="sm"
                            variant="ghost"
                          />
                        ) : null}
                      </div>
                    ) : (
                      <div className="project-home-canvas-empty">
                        <div className="project-home-paper-stack" aria-hidden="true">
                          <span />
                          <span />
                          <span />
                        </div>
                        <h2>{t("자료를 여기에 끌어다 놓으세요")}</h2>
                        <p>{t("회의록, README, PDF, 스펙 문서를 읽고 프로젝트 맥락을 정리합니다")}</p>
                        <div className="project-home-picker-row">
                          <Button
                            className="project-home-picker"
                            icon={<FileText size={14} />}
                            isDisabled={!canMutateSelectedProject}
                            label={t("파일 선택")}
                            onClick={() => void handleOpenProjectFiles(selectedProject.id)}
                            size="sm"
                            variant="secondary"
                          />
                          <Button
                            className="project-home-picker"
                            icon={<FolderOpen size={14} />}
                            isDisabled={!canMutateSelectedProject}
                            label={t("폴더 선택")}
                            onClick={() => void handleOpenProjectDirectory(selectedProject.id)}
                            size="sm"
                            variant="secondary"
                          />
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="project-home-footer">
                    <p
                      aria-live="polite"
                      className="project-home-note"
                      id="project-home-analysis-note"
                    >
                      {!canMutateSelectedProject
                        ? t("프로젝트 편집 권한이 있어야 분석할 수 있습니다")
                        : selectedProjectHasDocumentInProgress
                        ? t("자료 처리 중 — 완료 후 분석할 수 있습니다")
                        : !hasProjectHomeContext
                          ? t("설명이나 자료를 추가하면 분석할 수 있습니다")
                        : t("분석하면 설명과 자료를 읽고 첫 브리핑을 만든 뒤 채팅으로 이어집니다.")}
                    </p>
                    <div className="project-home-actions">
                      <Button
                        className="project-home-secondary"
                        isDisabled={!canMutateSelectedProject}
                        label={t("분석 없이 채팅")}
                        onClick={() => handleCreateChatInProject(selectedProject.id)}
                        size="sm"
                        variant="ghost"
                      />
                      <Button
                        aria-describedby="project-home-analysis-note"
                        className="project-home-primary"
                        isDisabled={isProjectBriefingDisabled}
                        label={isSending ? t("분석 중") : t("분석 시작")}
                        onClick={() =>
                          void handleStartProjectBriefing(selectedProject, selectedProjectAttachments)
                        }
                        size="sm"
                        variant="primary"
                      />
                    </div>
                  </div>
                </div>

                <aside className="project-home-slots" aria-label={t("추출될 항목")}>
                  <div>
                    <p className="project-home-slots-title">{t("추출될 항목")}</p>
                    <p className="project-home-slots-hint">
                      {canOpenProjectMemory
                        ? t("서버 프로젝트 메모리 개수를 표시합니다")
                        : t("자료 업로드 후 서버 메모리 개수를 표시합니다")}
                    </p>
                  </div>
                  <div className="project-home-slot-list">
                    <div
                      className="project-home-slot"
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
                      className="project-home-slot"
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
                      className="project-home-slot"
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
                      className="project-home-slot"
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
                  <p className="project-home-slots-foot">
                    {t("업로드와 분석 결과가 서버에 반영되면 자동으로 갱신됩니다.")}
                  </p>
                </aside>
              </div>
            </section>
          </>
        ) : (
          <section className="project-start" aria-labelledby="project-start-title">
            <div className="project-start-content">
              <div className="project-start-mark" aria-hidden="true">PaiM</div>
              <div className="project-start-copy">
                <h1 id="project-start-title" ref={mainViewHeadingRef} tabIndex={-1}>
                  {t("프로젝트의 맥락을 놓치지 마세요")}
                </h1>
                <p>
                  {t("자료와 대화를 연결해 결정, 액션, 이슈와 리스크를 한곳에서 정리합니다.")}
                </p>
              </div>
              <Button
                className="project-start-button"
                icon={<FolderPlus size={16} />}
                label={t("새 프로젝트 시작하기")}
                onClick={() => createProjectFromName(createNextProjectName(projects))}
                tooltip={t("새 프로젝트 시작하기")}
                variant="primary"
              />
            </div>
          </section>
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
                      onOpenDirectory={() => void handleOpenProjectDirectory(selectedProject.id)}
                      onOpenFiles={() => void handleOpenProjectFiles(selectedProject.id)}
                      onOpenSource={handleOpenProjectSource}
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
                      canManage={canMutateSelectedProject}
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
          </div>
        </AppShell>
      </Theme>
    </I18nProvider>
  );
}
