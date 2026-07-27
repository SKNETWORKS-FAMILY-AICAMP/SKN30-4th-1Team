import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { createConnection } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";

const APP_PORT = Number(process.env.PAIM_LAYOUT_PORT ?? 7421);
const APP_URL = `http://127.0.0.1:${APP_PORT}/`;
const API_SERVER_A = "http://127.0.0.1:7272";
const API_SERVER_B = "http://127.0.0.1:7273";
const LEGACY_STORAGE_KEY = "paim.chatSessions.v2";
const LEGACY_AUTH_STORAGE_KEY = "paim.auth.v1";
const AUTH_STORAGE_KEY_PREFIX = "paim.auth.v2.server.";
const AUTH_STORAGE_KEY = `${AUTH_STORAGE_KEY_PREFIX}${encodeURIComponent(API_SERVER_A)}`;
const SERVER_B_AUTH_STORAGE_KEY = `${AUTH_STORAGE_KEY_PREFIX}${encodeURIComponent(API_SERVER_B)}`;
const AUTH_SCENARIO_STORAGE_KEY = "paim.smoke.authScenario.v1";
const SETTINGS_STORAGE_KEY = "paim.settings.v1";
const SMOKE_ACCESS_TOKEN = "paim-smoke-access-token";
const SMOKE_USER = {
  id: 1,
  email: "owner@paim.local",
  name: "Smoke Owner",
  created_at: "2026-01-01T00:00:00.000Z",
};
const AUTH_SESSION = {
  accessToken: SMOKE_ACCESS_TOKEN,
  user: SMOKE_USER,
};
const PROJECT_STORAGE_KEY = `paim.projects.v8.account.${encodeURIComponent(
  `${API_SERVER_A}|${SMOKE_USER.id}|${SMOKE_USER.email}`,
)}`;
const SIDEBAR_STORAGE_KEY = "paim.sidebarCollapsed.v1";
const SIDEBAR_WIDTH_STORAGE_KEY = "paim.sidebarWidth.v1";
const PROJECT_PANEL_COLLAPSED_STORAGE_KEY = "paim.projectPanelCollapsed.v2";
const PROJECT_PANEL_WIDTH_STORAGE_KEY = "paim.projectPanelWidth.v1";
const PROJECT_COLLAPSED_STORAGE_KEY = "paim.projectCollapsed.v1";
const ZOOM_STORAGE_KEY = "paim.zoomScale.v1";
const GITHUB_CLIENT_ID_STORAGE_KEY = "paim.githubClientId.v1";
const VITE_BIN = "node_modules/vite/bin/vite.js";
const DEBUG_PORT = Number(process.env.PAIM_LAYOUT_DEBUG_PORT ?? 7336);
const CDP_REQUEST_TIMEOUT_MS = 15_000;
const WEBSOCKET_OPEN_TIMEOUT_MS = 5_000;
const childSpawnErrors = new WeakMap();

const BROWSER_CANDIDATES = [
  process.env.PAIM_BROWSER_PATH,
  "/Applications/Whale.app/Contents/MacOS/Whale",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
].filter(Boolean);

const scenarios = [
  { width: 1280, height: 820, collapsed: false, dragActive: false },
  { width: 1280, height: 820, collapsed: true, dragActive: false },
  { width: 960, height: 680, collapsed: false, dragActive: false },
  { width: 960, height: 680, collapsed: true, dragActive: false },
  { width: 960, height: 680, collapsed: true, dragActive: true },
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let nextSmokeNavigationId = 1;

const PROJECT_PANEL_TAB_ADD_SELECTOR = 'button.project-panel-tab-add[aria-label="패널 탭 추가"]';
const PROJECT_PANEL_TAB_MENU_ITEM_SELECTOR = '[role="menuitem"]';
const DEBUG_LAYOUT = process.env.PAIM_LAYOUT_DEBUG === "1";

function debugLayout(label, value) {
  if (!DEBUG_LAYOUT) {
    return;
  }

  console.log(`DEBUG ${label} ${JSON.stringify(value, null, 2)}`);
}

function createPaimApiMockScript() {
  return `
    (() => {
      if (window.__paimLayoutApiMockInstalled) {
        return;
      }

      window.__paimLayoutApiMockInstalled = true;
      window.__paimLayoutApiCalls = [];
      window.__paimLayoutApiRequests = [];
      const originalFetch = window.fetch.bind(window);
      const serverDocumentsByProject = new Map();
      const serverSessionsByProject = new Map();
      let includeSupersedingDecision = false;
      let pendingMemorySuggestions = [];
      let nextSuggestionResolutionStatus = null;
      const queryControl = {
        aborted: 0,
        delayMs: 0,
        requested: 0,
        resolved: 0,
      };
      const creationControl = {
        projectDelayMs: 0,
        projectRequested: 0,
        projectResolved: 0,
        sessionDelayMs: 0,
        sessionRequested: 0,
        sessionResolved: 0,
      };
      const documentControl = {
        delayMs: 0,
        deleted: 0,
        lastFile: null,
        requested: 0,
        resolved: 0,
      };
      const smokeUser = ${JSON.stringify(SMOKE_USER)};
      const smokeAuthSession = ${JSON.stringify(AUTH_SESSION)};
      const smokeAccessToken = ${JSON.stringify(SMOKE_ACCESS_TOKEN)};
      const authScenario =
        localStorage.getItem(${JSON.stringify(AUTH_SCENARIO_STORAGE_KEY)}) || "owner";

      if (authScenario === "anonymous") {
        localStorage.removeItem(${JSON.stringify(AUTH_STORAGE_KEY)});
      } else {
        localStorage.setItem(
          ${JSON.stringify(AUTH_STORAGE_KEY)},
          JSON.stringify(smokeAuthSession),
        );
      }
      let nextDocumentId = 7000;
      let nextProjectId = 1000;
      let nextSessionId = 1000;

      window.__paimLayoutSeedSupersedeSuggestion = (suggestionId = 901) => {
        includeSupersedingDecision = true;
        pendingMemorySuggestions = [
          {
            id: suggestionId,
            memory_id: 1,
            kind: "supersede",
            rationale: "새 아키텍처 결정이 기존 결정을 대체합니다",
            confidence: "high",
            status: "pending",
            evidence: {
              type: "supersede",
              superseding_memory_id: 5,
            },
          },
        ];
      };
      window.__paimLayoutSetSuggestionResolutionStatus = (status) => {
        nextSuggestionResolutionStatus = Number(status);
      };
      window.__paimLayoutConfigureQuery = ({ delayMs = 0 } = {}) => {
        queryControl.aborted = 0;
        queryControl.delayMs = Math.max(0, Number(delayMs) || 0);
        queryControl.requested = 0;
        queryControl.resolved = 0;
      };
      window.__paimLayoutReadQueryControl = () => ({ ...queryControl });
      window.__paimLayoutConfigureCreation = ({ projectDelayMs = 0, sessionDelayMs = 0 } = {}) => {
        creationControl.projectDelayMs = Math.max(0, Number(projectDelayMs) || 0);
        creationControl.projectRequested = 0;
        creationControl.projectResolved = 0;
        creationControl.sessionDelayMs = Math.max(0, Number(sessionDelayMs) || 0);
        creationControl.sessionRequested = 0;
        creationControl.sessionResolved = 0;
      };
      window.__paimLayoutReadCreationControl = () => ({ ...creationControl });
      window.__paimLayoutConfigureDocument = ({ delayMs = 0 } = {}) => {
        documentControl.delayMs = Math.max(0, Number(delayMs) || 0);
        documentControl.deleted = 0;
        documentControl.lastFile = null;
        documentControl.requested = 0;
        documentControl.resolved = 0;
        nextDocumentId = 7000;
        serverDocumentsByProject.clear();
      };
      window.__paimLayoutReadDocumentControl = () => ({
        ...documentControl,
        lastFile: documentControl.lastFile ? { ...documentControl.lastFile } : null,
        serverDocumentCount: Array.from(serverDocumentsByProject.values()).reduce(
          (count, documents) => count + documents.length,
          0,
        ),
      });

      const json = (payload, status = 200) =>
        Promise.resolve(new Response(JSON.stringify(payload), {
          status,
          headers: { "Content-Type": "application/json" },
        }));
      const empty = () => Promise.resolve(new Response(null, { status: 204 }));
      const readJson = async (init) => {
        try {
          return JSON.parse(init?.body || "{}");
        } catch {
          return {};
        }
      };
      const readStoredServerProjects = () => {
        try {
          const savedState = JSON.parse(
            localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || "{}",
          );
          return (savedState.projects || [])
            .filter((project) => typeof project.apiProjectId === "number" && !project.serverMissing)
            .map((project) => ({
              id: project.apiProjectId,
              name: project.name || "Smoke Project",
              created_at: new Date(project.createdAt || Date.now()).toISOString(),
            }));
        } catch {
          return [];
        }
      };

      window.fetch = async (input, init = {}) => {
        const rawUrl = typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
        let url;

        try {
          url = new URL(rawUrl, window.location.origin);
        } catch {
          return originalFetch(input, init);
        }

        const method = String(
          init?.method || (typeof Request !== "undefined" && input instanceof Request ? input.method : "GET"),
        ).toUpperCase();
        const headers = new Headers(
          init?.headers ||
            (typeof Request !== "undefined" && input instanceof Request ? input.headers : undefined),
        );
        const authorization = headers.get("Authorization") || "";

        if (url.hostname !== "127.0.0.1" || !["7272", "7273"].includes(url.port)) {
          return originalFetch(input, init);
        }

        const apiCall = method + " " + url.pathname + url.search;
        window.__paimLayoutApiCalls.push(apiCall);
        window.__paimLayoutApiRequests.push({
          call: apiCall,
          authorization,
          serverOrigin: url.origin,
        });
        if (window.__paimLayoutApiCalls.length > 80) {
          window.__paimLayoutApiCalls.shift();
        }
        if (window.__paimLayoutApiRequests.length > 80) {
          window.__paimLayoutApiRequests.shift();
        }

        if (url.pathname === "/health") {
          return json({ status: "ok" });
        }

        if ((url.pathname === "/api/v1/auth/login" ||
             url.pathname === "/api/v1/auth/signup") && method === "POST") {
          return json({
            access_token: smokeAccessToken,
            token_type: "bearer",
            user: smokeUser,
          });
        }

        if (url.pathname.startsWith("/api/v1/") &&
            authorization !== "Bearer " + smokeAccessToken) {
          return json({ detail: "인증이 필요합니다." }, 401);
        }

        if (url.pathname === "/api/v1/auth/me" && method === "GET") {
          if (authScenario === "expired") {
            return json({ detail: "세션이 만료되었습니다." }, 401);
          }
          return json(smokeUser);
        }

        if (url.pathname === "/api/v1/projects") {
          if (method === "GET") {
            return json(readStoredServerProjects());
          }

          if (method === "POST") {
            creationControl.projectRequested += 1;
            const body = await readJson(init);
            const id = nextProjectId;
            nextProjectId += 1;
            if (creationControl.projectDelayMs > 0) {
              await new Promise((resolve) => window.setTimeout(resolve, creationControl.projectDelayMs));
            }
            creationControl.projectResolved += 1;
            return json({ id, name: body.name || "Smoke Project" });
          }
        }

        const projectMembersMatch = url.pathname.match(
          /^\\/api\\/v1\\/projects\\/(\\d+)\\/members$/,
        );
        if (projectMembersMatch && method === "GET") {
          const currentRole = authScenario === "viewer"
            ? "viewer"
            : authScenario === "member"
              ? "member"
              : "owner";
          return json([
            {
              user_id: smokeUser.id,
              email: smokeUser.email,
              name: smokeUser.name,
              role: currentRole,
              created_at: smokeUser.created_at,
              last_seen_at: smokeUser.created_at,
            },
            {
              user_id: 2,
              email: "teammate@paim.local",
              name: "Smoke Teammate",
              role: currentRole === "owner" ? "member" : "owner",
              created_at: smokeUser.created_at,
              last_seen_at: smokeUser.created_at,
            },
          ]);
        }

        const projectSessionMatch = url.pathname.match(/^\\/api\\/v1\\/projects\\/(\\d+)\\/sessions$/);
        if (projectSessionMatch && method === "GET") {
          return json(serverSessionsByProject.get(Number(projectSessionMatch[1])) || []);
        }

        if (projectSessionMatch && method === "POST") {
          creationControl.sessionRequested += 1;
          const body = await readJson(init);
          const projectId = Number(projectSessionMatch[1]);
          const id = "smoke-session-" + nextSessionId;
          nextSessionId += 1;
          const session = {
            id,
            project_id: projectId,
            title: body.title || "New Chat",
          };
          serverSessionsByProject.set(projectId, [
            ...(serverSessionsByProject.get(projectId) || []),
            session,
          ]);
          if (creationControl.sessionDelayMs > 0) {
            await new Promise((resolve) => window.setTimeout(resolve, creationControl.sessionDelayMs));
          }
          creationControl.sessionResolved += 1;
          return json(session);
        }

        const sessionPathMatch = url.pathname.match(
          /^\\/api\\/v1\\/projects\\/(\\d+)\\/sessions\\/([^/]+)$/,
        );
        if (sessionPathMatch && method === "PATCH") {
          const body = await readJson(init);
          return json({
            id: decodeURIComponent(sessionPathMatch[2]),
            project_id: Number(sessionPathMatch[1]),
            title: body.title || "New Chat",
          });
        }

        if (sessionPathMatch && method === "DELETE") {
          return empty();
        }

        if (/^\\/api\\/v1\\/projects\\/\\d+\\/sessions\\/[^/]+\\/messages$/.test(url.pathname)) {
          return json([]);
        }

        if (/^\\/api\\/v1\\/projects\\/\\d+\\/query$/.test(url.pathname) && method === "POST") {
          const body = await readJson(init);
          const question = body.question || "";
          const answer = question.includes("프로젝트의 목적")
            ? "프로젝트 설명: 분석 시작 테스트용 프로젝트 설명\\n다음 액션을 정리했습니다."
            : "좋아요. 이 내용을 프로젝트 메모로 정리할 수 있습니다.";

          queryControl.requested += 1;
          if (queryControl.delayMs > 0) {
            const signal = init?.signal ||
              (typeof Request !== "undefined" && input instanceof Request ? input.signal : undefined);
            await new Promise((resolve, reject) => {
              let settled = false;
              const finish = () => {
                if (settled) {
                  return;
                }
                settled = true;
                signal?.removeEventListener("abort", abort);
                resolve();
              };
              const abort = () => {
                if (settled) {
                  return;
                }
                settled = true;
                window.clearTimeout(timeoutId);
                queryControl.aborted += 1;
                reject(new DOMException("Smoke query aborted", "AbortError"));
              };
              const timeoutId = window.setTimeout(finish, queryControl.delayMs);

              if (signal?.aborted) {
                abort();
                return;
              }
              signal?.addEventListener("abort", abort, { once: true });
            });
          }

          queryControl.resolved += 1;
          return json({ answer, sources: [], route: "smoke" });
        }

        const memoryPathMatch = url.pathname.match(/^\\/api\\/v1\\/projects\\/(\\d+)\\/memory$/);
        if (memoryPathMatch && method === "GET") {
          const projectId = Number(memoryPathMatch[1]);
          return json([
            {
              id: 1,
              project_id: projectId,
              doc_id: 1,
              category: "decision",
              content: "프로젝트 메모리는 FastAPI에서 조회한다",
              topic: "아키텍처",
              owner: "PM",
              source: "meeting.md",
            },
            {
              id: 2,
              project_id: projectId,
              doc_id: 1,
              category: "action",
              content: "API 연결 상태를 확인한다",
              owner: "백엔드",
              source: "meeting.md",
            },
            {
              id: 3,
              project_id: projectId,
              doc_id: 1,
              category: "issue",
              content: "서버 미연결 상태에서는 메모리를 숨긴다",
              source: "meeting.md",
            },
            {
              id: 4,
              project_id: projectId,
              doc_id: 1,
              category: "risk",
              content: "프론트 임시 데이터가 실제 메모리처럼 보일 수 있다",
              source: "meeting.md",
            },
            ...(includeSupersedingDecision
              ? [
                  {
                    id: 5,
                    project_id: projectId,
                    doc_id: 2,
                    category: "decision",
                    content: "프로젝트 메모리는 GraphQL 게이트웨이를 통해 조회한다",
                    topic: "아키텍처",
                    owner: "PM",
                    source: "architecture-v2.md",
                  },
                ]
              : []),
          ]);
        }

        if (/^\\/api\\/v1\\/projects\\/\\d+\\/suggestions$/.test(url.pathname) && method === "GET") {
          const isPendingAll =
            url.searchParams.get("status") === "pending" &&
            url.searchParams.get("kind") === "all";
          return json(isPendingAll ? pendingMemorySuggestions : []);
        }

        const suggestionResolutionMatch = url.pathname.match(
          /^\\/api\\/v1\\/projects\\/\\d+\\/suggestions\\/(\\d+)\\/(accept|reject)$/,
        );
        if (suggestionResolutionMatch && method === "POST") {
          const suggestionId = Number(suggestionResolutionMatch[1]);
          pendingMemorySuggestions = pendingMemorySuggestions.filter(
            (suggestion) => suggestion.id !== suggestionId,
          );

          if ([400, 404, 409].includes(nextSuggestionResolutionStatus)) {
            const status = nextSuggestionResolutionStatus;
            nextSuggestionResolutionStatus = null;
            return json({ detail: "제안 상태가 변경되어 다시 조회합니다." }, status);
          }

          nextSuggestionResolutionStatus = null;
          return empty();
        }

        const projectPathMatch = url.pathname.match(/^\\/api\\/v1\\/projects\\/(\\d+)$/);
        if (projectPathMatch && method === "PATCH") {
          const body = await readJson(init);
          return json({
            id: Number(projectPathMatch[1]),
            name: body.name || "Smoke Project",
          });
        }

        if (projectPathMatch && method === "DELETE") {
          return empty();
        }

        const projectDocumentsMatch = url.pathname.match(
          /^\\/api\\/v1\\/projects\\/(\\d+)\\/documents$/,
        );
        if (projectDocumentsMatch && method === "GET") {
          return json(serverDocumentsByProject.get(Number(projectDocumentsMatch[1])) || []);
        }

        if (projectDocumentsMatch && method === "POST") {
          const projectId = Number(projectDocumentsMatch[1]);
          const file = init?.body instanceof FormData ? init.body.get("file") : null;
          const docId = nextDocumentId;
          nextDocumentId += 1;
          documentControl.requested += 1;
          documentControl.lastFile = file instanceof File
            ? { name: file.name, size: file.size, type: file.type }
            : null;

          if (documentControl.delayMs > 0) {
            await new Promise((resolve) => window.setTimeout(resolve, documentControl.delayMs));
          }

          const document = {
            id: docId,
            filename: file instanceof File ? file.name : "drop.pdf",
            doc_type: "pdf",
            status: "indexed",
            uploaded_at: "2026-01-01T00:00:00.000Z",
          };
          serverDocumentsByProject.set(projectId, [
            ...(serverDocumentsByProject.get(projectId) || []),
            document,
          ]);
          documentControl.resolved += 1;
          return json({
            doc_id: docId,
            status: "indexed",
            format: "pdf",
            blocks: 1,
            pages: 1,
            warnings: [],
          }, 201);
        }

        const projectDocumentStatusMatch = url.pathname.match(
          /^\\/api\\/v1\\/projects\\/(\\d+)\\/documents\\/(\\d+)\\/status$/,
        );
        if (projectDocumentStatusMatch && method === "GET") {
          return json({
            doc_id: Number(projectDocumentStatusMatch[2]),
            status: "indexed",
            blocks: 1,
            error_message: null,
          });
        }

        const projectDocumentMatch = url.pathname.match(
          /^\\/api\\/v1\\/projects\\/(\\d+)\\/documents\\/(\\d+)$/,
        );
        if (projectDocumentMatch && method === "DELETE") {
          const projectId = Number(projectDocumentMatch[1]);
          const docId = Number(projectDocumentMatch[2]);
          serverDocumentsByProject.set(
            projectId,
            (serverDocumentsByProject.get(projectId) || []).filter(
              (document) => document.id !== docId,
            ),
          );
          documentControl.deleted += 1;
          return empty();
        }

        if (/^\\/api\\/v1\\/projects\\/\\d+\\/repositories$/.test(url.pathname)) {
          return json([]);
        }

        if (/^\\/api\\/v1\\/projects\\/\\d+\\/delta/.test(url.pathname)) {
          return json({
            summary: "",
            decisions: [],
            actions: [],
            risks: [],
            due_soon: [],
            overdue: [],
          });
        }

        return originalFetch(input, init);
      };
    })();
  `;
}

async function installPaimApiMock(send) {
  await send("Page.addScriptToEvaluateOnNewDocument", {
    source: createPaimApiMockScript(),
  });
}

// 실제 Tauri 창 없이도 해당 문서에서만 native file-drop 이벤트와 파일 IPC를 재현한다.
function createPaimTauriMockScript() {
  return `
    (() => {
      if (window.__paimLayoutTauriMockInstalled) {
        return;
      }

      window.__paimLayoutTauriMockInstalled = true;
      const callbacks = new Map();
      const listeners = new Map();
      let nextCallbackId = 1;
      let nextEventId = 1;

      const unregisterCallback = (callbackId) => {
        callbacks.delete(callbackId);
      };
      const transformCallback = (callback, once = false) => {
        const callbackId = nextCallbackId;
        nextCallbackId += 1;
        callbacks.set(callbackId, (payload) => {
          if (once) {
            callbacks.delete(callbackId);
          }
          return callback?.(payload);
        });
        return callbackId;
      };
      const unregisterListener = (event, eventId) => {
        const eventListeners = listeners.get(event) || [];
        const listener = eventListeners.find((candidate) => candidate.eventId === eventId);
        if (listener) {
          unregisterCallback(listener.callbackId);
        }
        listeners.set(
          event,
          eventListeners.filter((candidate) => candidate.eventId !== eventId),
        );
      };

      window.__TAURI_INTERNALS__ = {
        callbacks,
        convertFileSrc: (path) => "asset://localhost/" + encodeURIComponent(path),
        metadata: {
          currentWindow: { label: "main" },
          currentWebview: { label: "main", windowLabel: "main" },
        },
        transformCallback,
        unregisterCallback,
        invoke: async (cmd, args = {}) => {
          if (cmd === "plugin:event|listen") {
            const eventId = nextEventId;
            nextEventId += 1;
            listeners.set(args.event, [
              ...(listeners.get(args.event) || []),
              { callbackId: args.handler, eventId },
            ]);
            return eventId;
          }
          if (cmd === "plugin:event|unlisten") {
            unregisterListener(args.event, args.eventId);
            return null;
          }
          if (cmd === "plugin:event|emit") {
            window.__paimLayoutEmitTauriEvent?.(args.event, args.payload);
            return null;
          }
          if (cmd === "path_kind") {
            return "file";
          }
          if (cmd === "read_file_base64") {
            return "JVBERi0xLjQK";
          }
          if (cmd === "read_directory_children") {
            return [];
          }
          if (cmd === "plugin:app|version") {
            return "1.0.3";
          }
          return null;
        },
      };
      window.__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener };
      window.__paimLayoutEmitTauriEvent = (event, payload) => {
        const eventListeners = [...(listeners.get(event) || [])];
        for (const listener of eventListeners) {
          callbacks.get(listener.callbackId)?.({
            event,
            id: listener.eventId,
            payload,
          });
        }
        return eventListeners.length;
      };
      window.__paimLayoutReadTauriMock = () => ({
        dragDropListeners: (listeners.get("tauri://drag-drop") || []).length,
      });
    })();
  `;
}

async function installPaimTauriMock(send) {
  return send("Page.addScriptToEvaluateOnNewDocument", {
    source: createPaimTauriMockScript(),
  });
}

// 테스트 세션을 실제 앱 저장 구조인 프로젝트 단위 state로 감싼다.
function createProjectStorageState(projects, selectedProjectId, selectedSessionId) {
  return JSON.stringify({
    projects,
    selectedProjectId,
    selectedSessionId,
  });
}

function createProjectStorage(
  projectId,
  projectName,
  sessions,
  selectedSessionId = sessions[0]?.id,
  files = [],
  extraProjectFields = {},
) {
  return createProjectStorageState(
    [
      {
        ...extraProjectFields,
        id: projectId,
        name: projectName,
        files,
        createdAt: Date.now(),
        sessions,
      },
    ],
    projectId,
    selectedSessionId,
  );
}

function createDefaultSmokeProjectStorage() {
  return createProjectStorage(
    "project-smoke",
    "Smoke Project",
    [
      {
        id: "session-smoke",
        title: "Smoke Chat",
        createdAt: Date.now(),
        messages: [
          {
            id: "assistant-smoke",
            role: "assistant",
            content: "저장된 응답입니다.",
          },
        ],
      },
    ],
    "session-smoke",
    [],
    { apiProjectId: 1 },
  );
}

async function setAuthScenario(send, scenario) {
  const authSetup = scenario === "anonymous"
    ? `localStorage.removeItem(${JSON.stringify(AUTH_STORAGE_KEY)})`
    : `localStorage.setItem(${JSON.stringify(AUTH_STORAGE_KEY)}, ${JSON.stringify(JSON.stringify(AUTH_SESSION))})`;

  await send("Runtime.evaluate", {
    expression: `localStorage.removeItem(${JSON.stringify(LEGACY_AUTH_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(AUTH_SCENARIO_STORAGE_KEY)}, ${JSON.stringify(scenario)}); ${authSetup}`,
  });
}

async function setSmokeServerUrl(send, serverUrl) {
  await send("Runtime.evaluate", {
    expression: `(() => {
      let settings = {};
      try {
        settings = JSON.parse(localStorage.getItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}) || '{}');
      } catch {
        settings = {};
      }
      settings.serverUrl = ${JSON.stringify(serverUrl)};
      localStorage.setItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}, JSON.stringify(settings));
    })()`,
  });
}

async function openAppWithProject(send) {
  const seededProjectState = createDefaultSmokeProjectStorage();

  await navigateAndWaitForSelector(send, APP_URL, ".app-shell");
  await evaluateAndNavigateToSelector(
    send,
    `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}, '272'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}, '360'); localStorage.removeItem(${JSON.stringify(PROJECT_COLLAPSED_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(seededProjectState)})`,
    APP_URL,
    ".project-panel-menu",
  );
  await waitForSelector(send, ".prompt textarea:not(:disabled)");
}

async function openAppWithoutProjects(send) {
  await navigateAndWaitForSelector(send, APP_URL, ".app-shell");
  await evaluateAndNavigateToSelector(
    send,
    `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.removeItem(${JSON.stringify(PROJECT_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}, '272'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}, '360'); localStorage.removeItem(${JSON.stringify(PROJECT_COLLAPSED_STORAGE_KEY)})`,
    APP_URL,
    ".project-start",
  );
}

async function openSidebarAccountMenu(send) {
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.sidebar-account-button')?.click()`,
  });
  await waitForSelector(send, ".account-menu");
  await sleep(100);
}

async function openSettingsFromAccountMenu(send) {
  await openSidebarAccountMenu(send);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.account-menu-settings')?.click()`,
  });
  await waitForSelector(send, ".settings-page");
}

async function pressKey(send, key, code = key, keyCode = 0) {
  await send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key,
    code,
    windowsVirtualKeyCode: keyCode,
    nativeVirtualKeyCode: keyCode,
  });
  await send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key,
    code,
    windowsVirtualKeyCode: keyCode,
    nativeVirtualKeyCode: keyCode,
  });
}

async function openProjectMembersPanel(send) {
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-group[data-active="true"] .project-action-menu-button')?.click()`,
  });
  await waitForSelector(send, '[data-action="manage-project-members"]');
  await send("Runtime.evaluate", {
    expression: `document.querySelector('[data-action="manage-project-members"]')?.click()`,
  });
  await waitForSelector(send, ".project-members-list");
}

async function readProjectMemberPermissionSnapshot(send) {
  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const requests = window.__paimLayoutApiRequests || [];
      const protectedRequests = requests.filter((request) =>
        request.call.includes('/api/v1/') &&
        !request.call.includes('/api/v1/auth/login') &&
        !request.call.includes('/api/v1/auth/signup')
      );
      return {
        addForm: Boolean(document.querySelector('.project-members-add-form')),
        permissionNote: Boolean(document.querySelector('.project-members-permission-note')),
        removeButtons: document.querySelectorAll('.project-members-remove').length,
        roleSelects: document.querySelectorAll('.project-members-role-select').length,
        roles: Array.from(document.querySelectorAll('.project-members-role[data-role]'))
          .map((element) => element.getAttribute('data-role')),
        authMeBearer: requests.some((request) =>
          request.call === 'GET /api/v1/auth/me' &&
          request.authorization === ${JSON.stringify(`Bearer ${SMOKE_ACCESS_TOKEN}`)}
        ),
        membersBearer: requests.some((request) =>
          request.call === 'GET /api/v1/projects/1/members' &&
          request.authorization === ${JSON.stringify(`Bearer ${SMOKE_ACCESS_TOKEN}`)}
        ),
        allProtectedRequestsAuthenticated: protectedRequests.length > 0 &&
          protectedRequests.every((request) =>
            request.authorization === ${JSON.stringify(`Bearer ${SMOKE_ACCESS_TOKEN}`)}
          ),
        requests,
      };
    })()`,
  });

  return result.result.value;
}

// 서버별 저장 세션, Bearer 격리, 401 만료 처리와 역할별 멤버 패널 권한을 함께 확인한다.
async function verifyAuthAndMemberPermissions(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 820,
    deviceScaleFactor: 1,
    mobile: false,
  });

  const value = {};
  const failures = [];

  try {
    await setAuthScenario(send, "owner");
    await openAppWithProject(send);
    await openProjectMembersPanel(send);
    value.owner = await readProjectMemberPermissionSnapshot(send);

    await setAuthScenario(send, "member");
    await navigateAndWaitForSelector(send, APP_URL, ".project-panel-menu");
    await waitForSelector(send, '.prompt textarea:not([aria-disabled="true"])');
    await openProjectMembersPanel(send);
    value.member = await readProjectMemberPermissionSnapshot(send);

    await setAuthScenario(send, "viewer");
    await navigateAndWaitForSelector(send, APP_URL, ".project-panel-menu");
    await waitForSelector(send, '.prompt textarea[aria-disabled="true"][readonly]');
    value.viewerPrompt = (await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => ({
        ariaDisabled: document.querySelector('.prompt textarea')?.getAttribute('aria-disabled'),
        readOnly: document.querySelector('.prompt textarea')?.readOnly === true,
        visibleReason: document.querySelector('.prompt-readonly-note')?.textContent?.trim() || '',
      }))()`,
    })).result.value;
    await openProjectMembersPanel(send);
    value.viewer = await readProjectMemberPermissionSnapshot(send);

    await setAuthScenario(send, "owner");
    await send("Runtime.evaluate", {
      expression: `localStorage.setItem(${JSON.stringify(LEGACY_AUTH_STORAGE_KEY)}, ${JSON.stringify(JSON.stringify(AUTH_SESSION))}); localStorage.removeItem(${JSON.stringify(SERVER_B_AUTH_STORAGE_KEY)})`,
    });
    await setSmokeServerUrl(send, API_SERVER_B);
    await navigateAndWaitForSelector(send, APP_URL, ".auth-form");
    const serverIsolationResult = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => {
        const requests = window.__paimLayoutApiRequests || [];
        const serverBRequests = requests.filter((request) =>
          request.serverOrigin === ${JSON.stringify(API_SERVER_B)}
        );
        return {
          authForm: Boolean(document.querySelector('.auth-form')),
          legacySessionCleared: localStorage.getItem(${JSON.stringify(LEGACY_AUTH_STORAGE_KEY)}) === null,
          serverASessionPreserved: localStorage.getItem(${JSON.stringify(AUTH_STORAGE_KEY)}) !== null,
          serverBSessionAbsent: localStorage.getItem(${JSON.stringify(SERVER_B_AUTH_STORAGE_KEY)}) === null,
          serverBAuthMeWithoutToken: serverBRequests.some((request) =>
            request.call === 'GET /api/v1/auth/me' && request.authorization === ''
          ),
          leakedServerAToken: serverBRequests.some((request) =>
            request.authorization === ${JSON.stringify(`Bearer ${SMOKE_ACCESS_TOKEN}`)}
          ),
          requests,
        };
      })()`,
    });
    value.serverIsolation = serverIsolationResult.result.value;

    await setSmokeServerUrl(send, "");
    await setAuthScenario(send, "expired");
    await navigateAndWaitForSelector(send, APP_URL, ".auth-form");
    const expiredResult = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => {
        const requests = window.__paimLayoutApiRequests || [];
        return {
          authSessionCleared: localStorage.getItem(${JSON.stringify(AUTH_STORAGE_KEY)}) === null,
          expiredRequestUsedBearer: requests.some((request) =>
            request.call === 'GET /api/v1/auth/me' &&
            request.authorization === ${JSON.stringify(`Bearer ${SMOKE_ACCESS_TOKEN}`)}
          ),
          authForm: Boolean(document.querySelector('.auth-form')),
          requests,
        };
      })()`,
    });
    value.expired = expiredResult.result.value;
  } finally {
    await setSmokeServerUrl(send, "");
    await setAuthScenario(send, "owner");
  }

  if (!value.owner?.authMeBearer ||
      !value.owner?.membersBearer ||
      !value.owner?.allProtectedRequestsAuthenticated) {
    failures.push("authenticated desktop API requests should use the stored Bearer token");
  }
  if (!value.owner?.addForm ||
      value.owner?.roleSelects < 2 ||
      value.owner?.removeButtons < 1 ||
      !value.owner?.roles.includes("owner") ||
      !value.owner?.roles.includes("member")) {
    failures.push("project Owner should be able to add, update, and remove members");
  }
  if (value.member?.addForm ||
      !value.member?.permissionNote ||
      value.member?.roleSelects !== 0 ||
      value.member?.removeButtons !== 1 ||
      !value.member?.roles.includes("member") ||
      !value.member?.membersBearer) {
    failures.push("project Member should only be able to leave the project");
  }
  if (value.viewer?.addForm ||
      !value.viewer?.permissionNote ||
      value.viewer?.roleSelects !== 0 ||
      value.viewer?.removeButtons !== 0 ||
      !value.viewer?.roles.includes("viewer") ||
      !value.viewer?.membersBearer) {
    failures.push("project Viewer should have read-only member access");
  }
  if (value.viewerPrompt?.ariaDisabled !== "true" ||
      !value.viewerPrompt?.readOnly ||
      !value.viewerPrompt?.visibleReason) {
    failures.push("project Viewer prompt should stay focusable and explain why it is read-only");
  }
  if (!value.expired?.authForm ||
      !value.expired?.authSessionCleared ||
      !value.expired?.expiredRequestUsedBearer) {
    failures.push("a 401 /auth/me response should clear the expired session and show authentication");
  }
  if (!value.serverIsolation?.authForm ||
      !value.serverIsolation?.legacySessionCleared ||
      !value.serverIsolation?.serverASessionPreserved ||
      !value.serverIsolation?.serverBSessionAbsent ||
      !value.serverIsolation?.serverBAuthMeWithoutToken ||
      value.serverIsolation?.leakedServerAToken) {
    failures.push("server-scoped auth should never send server A credentials to server B");
  }

  debugLayout("auth and member permissions", value);
  return { value, failures };
}

// 연결 테스트는 초안을 검사만 하고, 앱 설정 초기화는 사용자 데이터와 서버 범위를 보존한다.
async function verifySettingsConnectionAndResetSafety(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 820,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await setAuthScenario(send, "owner");
  await send("Runtime.evaluate", {
    expression: `(() => {
      localStorage.setItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}, JSON.stringify({
        dueSoonDays: 7,
        language: 'ko',
        serverUrl: ${JSON.stringify(API_SERVER_A)},
        suggestionMin: 'high',
        theme: 'dark',
      }));
      localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'true');
      localStorage.setItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}, '318');
      localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'true');
      localStorage.setItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}, '444');
      localStorage.setItem(${JSON.stringify(ZOOM_STORAGE_KEY)}, '1.4');
    })()`,
  });
  await openAppWithProject(send);
  await sleep(300);
  await openSettingsFromAccountMenu(send);
  await sleep(120);

  const beforeResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      window.__paimSettingsSafetyMarker = 'before-connection-test';
      return {
        authRaw: localStorage.getItem(${JSON.stringify(AUTH_STORAGE_KEY)}),
        href: location.href,
        projectRaw: localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}),
        settingsRaw: localStorage.getItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}),
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `(() => {
      const input = document.querySelector('.settings-group[aria-label="서버 주소"] input');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, ${JSON.stringify(API_SERVER_B)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`,
  });
  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.settings-server-actions button'))
      .find((button) => button.textContent.trim() === '연결 테스트')?.click()`,
  });

  const connectionStartedAt = Date.now();
  while (Date.now() - connectionStartedAt < 4000) {
    const statusResult = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `document.querySelector('.settings-draft-status')?.textContent?.includes('새 주소에 연결할 수 있습니다') === true`,
    });
    if (statusResult.result.value) {
      break;
    }
    await sleep(50);
  }

  const afterConnectionResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const requests = window.__paimLayoutApiRequests || [];
      return {
        applyLabel: Array.from(document.querySelectorAll('.settings-server-actions button'))
          .find((button) => button.textContent.includes('적용'))?.textContent.trim() || '',
        authRaw: localStorage.getItem(${JSON.stringify(AUTH_STORAGE_KEY)}),
        draftStatus: document.querySelector('.settings-draft-status')?.textContent.trim() || '',
        draftValue: document.querySelector('.settings-group[aria-label="서버 주소"] input')?.value || '',
        href: location.href,
        marker: window.__paimSettingsSafetyMarker || '',
        projectRaw: localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}),
        serverBHealthRequested: requests.some((request) =>
          request.serverOrigin === ${JSON.stringify(API_SERVER_B)} && request.call === 'GET /health'
        ),
        settingsPage: Boolean(document.querySelector('.settings-page')),
        settingsRaw: localStorage.getItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}),
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.settings-danger-group button')?.click()`,
  });
  await sleep(80);
  const firstResetPressResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      authRaw: localStorage.getItem(${JSON.stringify(AUTH_STORAGE_KEY)}),
      marker: window.__paimSettingsSafetyMarker || '',
      projectRaw: localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}),
      resetLabels: Array.from(document.querySelectorAll('.settings-danger-group button'))
        .map((button) => button.textContent.trim()),
      settingsRaw: localStorage.getItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}),
    }))()`,
  });

  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.settings-danger-group button'))
      .find((button) => button.textContent.trim() === '설정 초기화')?.click()`,
  });

  const reloadStartedAt = Date.now();
  let didReload = false;
  while (Date.now() - reloadStartedAt < 5000) {
    try {
      const markerResult = await send("Runtime.evaluate", {
        returnByValue: true,
        expression: `window.__paimSettingsSafetyMarker !== 'before-connection-test' && Boolean(document.querySelector('.app-shell'))`,
      });
      if (markerResult.result.value) {
        didReload = true;
        break;
      }
    } catch {
      // reload 중 교체되는 execution context는 다음 poll에서 확인한다.
    }
    await sleep(50);
  }
  await waitForSelector(send, ".app-shell");
  await sleep(300);

  const afterResetResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const settings = JSON.parse(localStorage.getItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}) || '{}');
      const projectState = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const project = projectState.projects?.find(
        (entry) => entry.id === projectState.selectedProjectId,
      );
      const session = project?.sessions?.find(
        (entry) => entry.id === projectState.selectedSessionId,
      );
      return {
        authForm: Boolean(document.querySelector('.auth-form')),
        authRaw: localStorage.getItem(${JSON.stringify(AUTH_STORAGE_KEY)}),
        dueSoonDays: settings.dueSoonDays,
        language: settings.language,
        layoutSettings: {
          panelCollapsed: localStorage.getItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}),
          panelWidth: localStorage.getItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}),
          sidebarCollapsed: localStorage.getItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}),
          sidebarWidth: localStorage.getItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}),
          zoom: localStorage.getItem(${JSON.stringify(ZOOM_STORAGE_KEY)}),
        },
        messageContent: session?.messages?.[0]?.content || '',
        projectId: project?.id || '',
        serverUrl: settings.serverUrl,
        sessionId: session?.id || '',
        suggestionMin: settings.suggestionMin,
        theme: settings.theme,
      };
    })()`,
  });

  const value = {
    afterConnection: afterConnectionResult.result.value,
    afterReset: afterResetResult.result.value,
    before: beforeResult.result.value,
    didReload,
    firstResetPress: firstResetPressResult.result.value,
  };
  const failures = [];

  if (!value.afterConnection.settingsPage ||
      value.afterConnection.marker !== "before-connection-test" ||
      value.afterConnection.href !== value.before.href ||
      value.afterConnection.settingsRaw !== value.before.settingsRaw ||
      value.afterConnection.projectRaw !== value.before.projectRaw ||
      value.afterConnection.authRaw !== value.before.authRaw ||
      value.afterConnection.draftValue !== API_SERVER_B ||
      value.afterConnection.applyLabel !== "서버 전환 적용" ||
      !value.afterConnection.draftStatus.includes("새 주소에 연결할 수 있습니다") ||
      !value.afterConnection.serverBHealthRequested) {
    failures.push("connection test should only validate the draft URL without saving, applying, or reloading");
  }

  if (!value.firstResetPress.resetLabels.includes("취소") ||
      !value.firstResetPress.resetLabels.includes("설정 초기화") ||
      value.firstResetPress.marker !== "before-connection-test" ||
      value.firstResetPress.settingsRaw !== value.before.settingsRaw ||
      value.firstResetPress.projectRaw !== value.before.projectRaw ||
      value.firstResetPress.authRaw !== value.before.authRaw) {
    failures.push("first app-settings reset press should only expose the destructive confirmation");
  }

  if (!value.didReload ||
      value.afterReset.authForm ||
      value.afterReset.authRaw !== value.before.authRaw ||
      value.afterReset.serverUrl !== API_SERVER_A ||
      value.afterReset.projectId !== "project-smoke" ||
      value.afterReset.sessionId !== "session-smoke" ||
      !value.afterReset.messageContent.includes("저장된 응답입니다") ||
      value.afterReset.theme !== "system" ||
      value.afterReset.language !== "ko" ||
      value.afterReset.suggestionMin !== "medium" ||
      value.afterReset.dueSoonDays !== 3 ||
      value.afterReset.layoutSettings.panelCollapsed !== "true" ||
      value.afterReset.layoutSettings.panelWidth !== "300" ||
      value.afterReset.layoutSettings.sidebarCollapsed !== "false" ||
      value.afterReset.layoutSettings.sidebarWidth !== "232" ||
      value.afterReset.layoutSettings.zoom !== "1") {
    failures.push("app-settings reset should preserve projects, conversations, auth, and server URL while restoring app defaults");
  }

  debugLayout("settings connection and reset safety", value);
  return { value, failures };
}

// 하단 계정 트리거는 사이드바 상태와 테마에 관계없이 프로필·설정·로그아웃으로 연결된다.
async function verifyAccountMenuContract(send) {
  const failures = [];
  const value = {
    layouts: [],
    keyboard: null,
    outsideClick: null,
    profile: null,
    profileReturned: false,
    settings: null,
    settingsReturned: false,
    logout: null,
  };
  const layoutScenarios = [
    { theme: "dark", collapsed: false },
    { theme: "dark", collapsed: true },
    { theme: "light", collapsed: false },
    { theme: "light", collapsed: true },
  ];

  const setTheme = async (theme) => {
    await send("Runtime.evaluate", {
      expression: `(() => {
        let settings = {};
        try {
          settings = JSON.parse(localStorage.getItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}) || '{}');
        } catch {
          settings = {};
        }
        settings.language = 'ko';
        settings.theme = ${JSON.stringify(theme)};
        localStorage.setItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}, JSON.stringify(settings));
      })()`,
    });
  };

  const readOpenMenuSnapshot = async () => {
    const result = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => {
        const shell = document.querySelector('.app-shell');
        const sidebar = document.querySelector('.sidebar');
        const footer = document.querySelector('.sidebar-footer');
        const trigger = document.querySelector('.sidebar-account-button');
        const visibleName = document.querySelector('.sidebar-account-name');
        const menu = document.querySelector('.account-menu');
        const activeMenuItem = document.activeElement?.closest?.('[role="menuitem"]');
        if (!shell || !sidebar || !footer || !trigger || !menu) return null;
        const sidebarBox = sidebar.getBoundingClientRect();
        const footerBox = footer.getBoundingClientRect();
        const triggerBox = trigger.getBoundingClientRect();
        const menuBox = menu.getBoundingClientRect();
        const menuStyle = getComputedStyle(menu);
        const themeHost = document.querySelector('[data-astryx-theme][data-theme]') ||
          document.querySelector('[data-theme]');
        return {
          collapsed: shell.getAttribute('data-sidebar-collapsed') === 'true',
          theme: themeHost?.getAttribute('data-theme') || '',
          trigger: {
            bottom: triggerBox.bottom,
            height: triggerBox.height,
            left: triggerBox.left,
            right: triggerBox.right,
            top: triggerBox.top,
            width: triggerBox.width,
          },
          menu: {
            bottom: menuBox.bottom,
            height: menuBox.height,
            left: menuBox.left,
            right: menuBox.right,
            top: menuBox.top,
            width: menuBox.width,
          },
          sidebar: {
            bottom: sidebarBox.bottom,
            left: sidebarBox.left,
            right: sidebarBox.right,
            top: sidebarBox.top,
            width: sidebarBox.width,
          },
          footer: {
            bottom: footerBox.bottom,
            top: footerBox.top,
          },
          triggerLabel: trigger.getAttribute('aria-label') || '',
          triggerHasPopup: trigger.getAttribute('aria-haspopup') || '',
          triggerExpanded: trigger.getAttribute('aria-expanded') || '',
          triggerControlsMenu: trigger.getAttribute('aria-controls') === menu.id,
          triggerTag: trigger.tagName,
          visibleName: visibleName?.textContent?.trim() || '',
          visibleNameWidth: visibleName?.getBoundingClientRect().width ?? 0,
          triggerInitials: trigger.querySelector('.sidebar-account-avatar')?.textContent?.trim() || '',
          menuRole: menu.getAttribute('role') || '',
          menuLabel: menu.getAttribute('aria-label') || '',
          menuItems: Array.from(menu.querySelectorAll('[role="menuitem"]'))
            .map((item) => item.textContent.trim()),
          identityName: menu.querySelector('.account-menu-identity-copy strong')?.textContent?.trim() || '',
          identityEmail: menu.querySelector('.account-menu-identity-copy small')?.textContent?.trim() || '',
          identityInitials: menu.querySelector('.account-menu-avatar')?.textContent?.trim() || '',
          focusedItem: activeMenuItem?.textContent?.trim() || '',
          focusedItemClass: activeMenuItem?.className || '',
          surface: {
            backdropFilter: menuStyle.backdropFilter || menuStyle.webkitBackdropFilter || '',
            backgroundColor: menuStyle.backgroundColor,
            boxShadow: menuStyle.boxShadow,
            color: menuStyle.color,
          },
          documentScrollWidth: document.documentElement.scrollWidth,
          innerWidth,
        };
      })()`,
    });
    return result.result.value;
  };

  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 820,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await setAuthScenario(send, "owner");

  for (const scenario of layoutScenarios) {
    await setTheme(scenario.theme);
    await openAppWithProject(send);
    if (scenario.collapsed) {
      await send("Runtime.evaluate", {
        expression: `document.querySelector('.sidebar-collapse-button')?.click()`,
      });
      await sleep(220);
    }
    await openSidebarAccountMenu(send);
    const snapshot = await readOpenMenuSnapshot();
    value.layouts.push({ ...scenario, snapshot });

    if (!snapshot) {
      failures.push(`${scenario.theme} ${scenario.collapsed ? "collapsed" : "expanded"} should render the account menu`);
      continue;
    }
    if (snapshot.theme !== scenario.theme) {
      failures.push(`${scenario.theme} account menu should inherit the selected theme`);
    }
    if (snapshot.collapsed !== scenario.collapsed) {
      failures.push(`${scenario.theme} account trigger should preserve the requested sidebar state`);
    }
    if (snapshot.triggerTag !== "BUTTON" ||
        snapshot.triggerHasPopup !== "menu" ||
        snapshot.triggerExpanded !== "true" ||
        !snapshot.triggerControlsMenu ||
        !snapshot.triggerLabel.includes("Smoke Owner")) {
      failures.push(`${scenario.theme} account trigger should expose the menu-button accessibility contract`);
    }
    if (snapshot.menuRole !== "menu" ||
        !snapshot.menuLabel.includes("Smoke Owner") ||
        snapshot.menuItems.length !== 3 ||
        !snapshot.menuItems.some((item) => item.includes("프로필")) ||
        !snapshot.menuItems.some((item) => item.includes("설정")) ||
        !snapshot.menuItems.some((item) => item.includes("로그아웃"))) {
      failures.push(`${scenario.theme} account popover should expose Profile, Settings, and Logout as menu items`);
    }
    if (snapshot.identityName !== SMOKE_USER.name ||
        snapshot.identityEmail !== SMOKE_USER.email ||
        snapshot.identityInitials !== "SO" ||
        snapshot.triggerInitials !== "SO") {
      failures.push(`${scenario.theme} account chrome should show the authenticated name, email, and initials`);
    }
    if (!snapshot.focusedItemClass.includes("account-menu-profile")) {
      failures.push(`${scenario.theme} account menu should focus Profile when it opens`);
    }
    const menuGap = snapshot.trigger.top - snapshot.menu.bottom;
    if (snapshot.menu.left < 7.5 ||
        snapshot.menu.right > snapshot.innerWidth - 7.5 ||
        menuGap < -0.5 ||
        menuGap > 16 ||
        snapshot.trigger.left < snapshot.sidebar.left - 0.5 ||
        snapshot.trigger.right > snapshot.sidebar.right + 0.5 ||
        snapshot.trigger.bottom > snapshot.footer.bottom + 0.5 ||
        snapshot.documentScrollWidth > snapshot.innerWidth) {
      failures.push(`${scenario.theme} account popover should stay anchored above the bottom-left trigger inside the viewport`);
    }
    if (scenario.collapsed) {
      if (Math.abs(snapshot.trigger.width - 32) > 1 || Math.abs(snapshot.sidebar.width - 52) > 1) {
        failures.push(`${scenario.theme} collapsed account access should remain a 32px button in the 52px rail`);
      }
    } else if (snapshot.trigger.width < 200 ||
        snapshot.visibleName !== SMOKE_USER.name ||
        snapshot.visibleNameWidth <= 0) {
      failures.push(`${scenario.theme} expanded account access should show the signed-in user name`);
    }
    if (!snapshot.surface.backgroundColor ||
        snapshot.surface.backgroundColor === "transparent" ||
        snapshot.surface.backgroundColor === "rgba(0, 0, 0, 0)" ||
        snapshot.surface.boxShadow === "none" ||
        !snapshot.surface.color) {
      failures.push(`${scenario.theme} account menu should render a legible material surface`);
    }

    await send("Runtime.evaluate", {
      expression: `document.querySelector('.sidebar-account-button')?.click()`,
    });
    await sleep(100);
  }

  const darkExpanded = value.layouts.find((entry) => entry.theme === "dark" && !entry.collapsed)?.snapshot;
  const lightExpanded = value.layouts.find((entry) => entry.theme === "light" && !entry.collapsed)?.snapshot;
  if (!darkExpanded || !lightExpanded ||
      darkExpanded.surface.backgroundColor === lightExpanded.surface.backgroundColor ||
      Math.abs(darkExpanded.trigger.width - lightExpanded.trigger.width) > 1 ||
      Math.abs(darkExpanded.menu.width - lightExpanded.menu.width) > 1) {
    failures.push("light and dark account menus should change material colors without shifting geometry");
  }

  await setTheme("dark");
  await openAppWithProject(send);
  await send("Runtime.evaluate", {
    expression: `(() => {
      const trigger = document.querySelector('.sidebar-account-button');
      trigger?.focus();
    })()`,
  });
  await pressKey(send, "ArrowDown", "ArrowDown", 40);
  await waitForSelector(send, ".account-menu");
  await sleep(100);
  const keyboardOpenedResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      expanded: document.querySelector('.sidebar-account-button')?.getAttribute('aria-expanded') || '',
      focusedClass: document.activeElement?.closest?.('[role="menuitem"]')?.className || '',
    }))()`,
  });
  await pressKey(send, "ArrowDown", "ArrowDown", 40);
  const keyboardDownResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.activeElement?.closest?.('[role="menuitem"]')?.className || ''`,
  });
  await pressKey(send, "End", "End", 35);
  const keyboardEndResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.activeElement?.closest?.('[role="menuitem"]')?.className || ''`,
  });
  await pressKey(send, "Home", "Home", 36);
  const keyboardHomeResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.activeElement?.closest?.('[role="menuitem"]')?.className || ''`,
  });
  await pressKey(send, "Escape", "Escape", 27);
  await sleep(140);
  const keyboardClosedResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const menu = document.querySelector('.account-menu');
      const menuVisible = Boolean(menu && menu.getClientRects().length > 0 && (() => {
        let element = menu;
        while (element) {
          const style = getComputedStyle(element);
          if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
          element = element.parentElement;
        }
        return true;
      })());
      return {
        expanded: document.querySelector('.sidebar-account-button')?.getAttribute('aria-expanded') || '',
        focusReturned: document.activeElement === document.querySelector('.sidebar-account-button'),
        menuVisible,
      };
    })()`,
  });
  value.keyboard = {
    opened: keyboardOpenedResult.result.value,
    afterArrowDown: keyboardDownResult.result.value,
    afterEnd: keyboardEndResult.result.value,
    afterHome: keyboardHomeResult.result.value,
    closed: keyboardClosedResult.result.value,
  };
  if (value.keyboard.opened.expanded !== "true" ||
      !value.keyboard.opened.focusedClass.includes("account-menu-profile") ||
      !value.keyboard.afterArrowDown.includes("account-menu-settings") ||
      !value.keyboard.afterEnd.includes("account-menu-logout") ||
      !value.keyboard.afterHome.includes("account-menu-profile") ||
      value.keyboard.closed.expanded !== "false" ||
      value.keyboard.closed.menuVisible ||
      !value.keyboard.closed.focusReturned) {
    failures.push("account menu should support keyboard opening, item navigation, Escape, and trigger focus restoration");
  }

  await openSidebarAccountMenu(send);
  await send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: 1240,
    y: 120,
    button: "left",
    clickCount: 1,
  });
  await send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: 1240,
    y: 120,
    button: "left",
    clickCount: 1,
  });
  await sleep(140);
  const outsideClickResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const menu = document.querySelector('.account-menu');
      const menuVisible = Boolean(menu && menu.getClientRects().length > 0 && (() => {
        let element = menu;
        while (element) {
          const style = getComputedStyle(element);
          if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
          element = element.parentElement;
        }
        return true;
      })());
      return {
        expanded: document.querySelector('.sidebar-account-button')?.getAttribute('aria-expanded') || '',
        menuVisible,
      };
    })()`,
  });
  value.outsideClick = outsideClickResult.result.value;
  if (value.outsideClick.expanded !== "false" || value.outsideClick.menuVisible) {
    failures.push("clicking outside should light-dismiss the account menu");
  }

  await openSidebarAccountMenu(send);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.account-menu-profile')?.click()`,
  });
  await waitForSelector(send, ".profile-page");
  await sleep(140);
  const profileResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const heading = document.querySelector('.profile-page h1');
      const page = document.querySelector('.profile-page');
      const content = document.querySelector('.profile-content');
      const backButton = document.querySelector('.profile-page .settings-back-button');
      const card = document.querySelector('.profile-identity-card');
      const detailsList = document.querySelector('.profile-details');
      const chat = document.querySelector('.chat');
      const details = Array.from(document.querySelectorAll('.profile-details > div')).map((row) => ({
        label: row.querySelector('dt')?.textContent?.trim() || '',
        value: row.querySelector('dd')?.textContent?.trim() || '',
      }));
      const rect = (element) => {
        if (!element) return null;
        const box = element.getBoundingClientRect();
        return { bottom: box.bottom, height: box.height, left: box.left, right: box.right, top: box.top, width: box.width };
      };
      return {
        mainView: document.querySelector('.app-shell')?.getAttribute('data-main-view') || '',
        heading: heading?.textContent?.trim() || '',
        headingFocused: document.activeElement === heading,
        identityName: document.querySelector('.profile-identity-copy h2')?.textContent?.trim() || '',
        identityEmail: document.querySelector('.profile-identity-copy p')?.textContent?.trim() || '',
        initials: document.querySelector('.profile-avatar')?.textContent?.trim() || '',
        details,
        geometry: {
          backButton: rect(backButton),
          card: rect(card),
          chat: rect(chat),
          content: rect(content),
          details: rect(detailsList),
          heading: rect(heading),
          pageClientWidth: page?.clientWidth ?? 0,
          pageScrollWidth: page?.scrollWidth ?? 0,
        },
        documentScrollWidth: document.documentElement.scrollWidth,
        innerWidth,
        menuVisible: (() => {
          const menu = document.querySelector('.account-menu');
          if (!menu || menu.getClientRects().length === 0) return false;
          let element = menu;
          while (element) {
            const style = getComputedStyle(element);
            if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
            element = element.parentElement;
          }
          return true;
        })(),
      };
    })()`,
  });
  value.profile = profileResult.result.value;
  if (value.profile.mainView !== "profile" ||
      value.profile.heading !== "프로필" ||
      !value.profile.headingFocused ||
      value.profile.identityName !== SMOKE_USER.name ||
      value.profile.identityEmail !== SMOKE_USER.email ||
      value.profile.initials !== "SO" ||
      value.profile.details.length !== 2 ||
      !value.profile.details.some((detail) => detail.label === "가입일" && !detail.value.includes("확인할 수 없음")) ||
      !value.profile.details.some((detail) => detail.label === "서버 상태" && detail.value.includes("서버")) ||
      value.profile.menuVisible) {
    failures.push("Profile should show the authenticated identity and focus its heading");
  }
  const profileGeometry = value.profile.geometry;
  if (!profileGeometry?.backButton ||
      !profileGeometry?.heading ||
      !profileGeometry?.content ||
      !profileGeometry?.chat ||
      !profileGeometry?.card ||
      !profileGeometry?.details ||
      profileGeometry.backButton.left < profileGeometry.content.left - 0.5 ||
      profileGeometry.backButton.right > profileGeometry.content.right + 0.5 ||
      Math.abs(
        profileGeometry.backButton.top + profileGeometry.backButton.height / 2 -
        (profileGeometry.heading.top + profileGeometry.heading.height / 2)
      ) > 2 ||
      profileGeometry.card.left < profileGeometry.content.left - 0.5 ||
      profileGeometry.card.right > profileGeometry.content.right + 0.5 ||
      profileGeometry.details.left < profileGeometry.content.left - 0.5 ||
      profileGeometry.details.right > profileGeometry.content.right + 0.5 ||
      profileGeometry.content.left < profileGeometry.chat.left - 0.5 ||
      profileGeometry.content.right > profileGeometry.chat.right + 0.5 ||
      profileGeometry.pageScrollWidth > profileGeometry.pageClientWidth + 1 ||
      value.profile.documentScrollWidth > value.profile.innerWidth) {
    failures.push("Profile header and account content should share one aligned, non-clipping layout");
  }
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.profile-page .settings-back-button')?.click()`,
  });
  await sleep(140);
  const profileReturnedResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.querySelector('.app-shell')?.getAttribute('data-main-view') === 'workspace' &&
      Boolean(document.querySelector('.sidebar-account-button'))`,
  });
  value.profileReturned = profileReturnedResult.result.value;
  if (!value.profileReturned) {
    failures.push("returning from Profile should restore the workspace with its account trigger");
  }

  await openSettingsFromAccountMenu(send);
  await sleep(140);
  const settingsResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const heading = document.querySelector('.settings-page h1');
      const backButton = document.querySelector('.settings-page .settings-back-button');
      const rect = (element) => {
        if (!element) return null;
        const box = element.getBoundingClientRect();
        return { height: box.height, left: box.left, right: box.right, top: box.top };
      };
      return {
        mainView: document.querySelector('.app-shell')?.getAttribute('data-main-view') || '',
        heading: heading?.textContent?.trim() || '',
        headingFocused: document.activeElement === heading,
        legacyAccountSection: Boolean(document.querySelector('.settings-group[aria-label="계정"]')),
        backButton: rect(backButton),
        contentRect: rect(document.querySelector('.settings-content')),
        headingRect: rect(heading),
        menuVisible: (() => {
          const menu = document.querySelector('.account-menu');
          if (!menu || menu.getClientRects().length === 0) return false;
          let element = menu;
          while (element) {
            const style = getComputedStyle(element);
            if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
            element = element.parentElement;
          }
          return true;
        })(),
      };
    })()`,
  });
  value.settings = settingsResult.result.value;
  if (value.settings.mainView !== "settings" ||
      value.settings.heading !== "설정" ||
      !value.settings.headingFocused ||
      value.settings.legacyAccountSection ||
      value.settings.menuVisible) {
    failures.push("Settings should open from the account menu without duplicating the Profile section");
  }
  if (!value.settings.backButton ||
      !value.settings.contentRect ||
      !value.settings.headingRect ||
      Math.abs(
        value.settings.backButton.left - value.settings.contentRect.left -
        (profileGeometry.backButton.left - profileGeometry.content.left)
      ) > 0.5 ||
      Math.abs(
        value.settings.headingRect.left - value.settings.backButton.right -
        (profileGeometry.heading.left - profileGeometry.backButton.right)
      ) > 0.5 ||
      Math.abs(
        value.settings.backButton.top + value.settings.backButton.height / 2 -
        (value.settings.headingRect.top + value.settings.headingRect.height / 2)
      ) > 2) {
    failures.push("Profile and Settings should use the same back-navigation header geometry");
  }
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.settings-page .settings-back-button')?.click()`,
  });
  await sleep(140);
  const settingsReturnedResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.querySelector('.app-shell')?.getAttribute('data-main-view') === 'workspace' &&
      Boolean(document.querySelector('.sidebar-account-button'))`,
  });
  value.settingsReturned = settingsReturnedResult.result.value;
  if (!value.settingsReturned) {
    failures.push("returning from Settings should restore the workspace with its account trigger");
  }

  await openSidebarAccountMenu(send);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.account-menu-logout')?.click()`,
  });
  await waitForSelector(send, ".auth-form");
  const logoutResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      authCleared: localStorage.getItem(${JSON.stringify(AUTH_STORAGE_KEY)}) === null,
      authForm: Boolean(document.querySelector('.auth-form')),
      workspaceGone: !document.querySelector('.app-shell'),
    }))()`,
  });
  value.logout = logoutResult.result.value;
  if (!value.logout.authCleared || !value.logout.authForm || !value.logout.workspaceGone) {
    failures.push("Logout should clear the local session and return to authentication");
  }
  await setAuthScenario(send, "owner");

  debugLayout("account menu contract", value);
  return { value, failures };
}

// 테스트에 사용할 Chromium 계열 브라우저 실행 파일을 찾는다.
function findBrowserPath() {
  const browserPath = BROWSER_CANDIDATES.find((candidate) => existsSync(candidate));

  if (!browserPath) {
    throw new Error("No supported Chromium browser found. Set PAIM_BROWSER_PATH.");
  }

  return browserPath;
}

// Vite 서버가 요청을 받을 수 있을 때까지 기다린다.
function getChildExitMessage(child, label) {
  const spawnError = childSpawnErrors.get(child);
  if (spawnError) {
    return `${label} failed to start (${spawnError.message})`;
  }
  if (child.exitCode !== null) {
    return `${label} exited before becoming ready (code ${child.exitCode})`;
  }
  if (child.signalCode !== null) {
    return `${label} exited before becoming ready (signal ${child.signalCode})`;
  }
  return "";
}

function trackChild(child) {
  child.once("error", (error) => {
    childSpawnErrors.set(child, error);
  });
  return child;
}

function assertValidPort(port, label) {
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${label} must be an integer between 1 and 65535, got ${port}`);
  }
}

async function waitForHttp(url, child, label) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const exitMessage = getChildExitMessage(child, label);
    if (exitMessage) {
      throw new Error(exitMessage);
    }

    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
    } catch {
      // 서버가 뜨는 중이면 다음 polling에서 다시 확인한다.
    }

    await sleep(100);
  }

  throw new Error(`Timed out waiting for ${url}`);
}

// Chrome DevTools Protocol 포트가 열릴 때까지 기다린다.
async function waitForDebuggingPort(child) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const exitMessage = getChildExitMessage(child, "browser");
    if (exitMessage) {
      throw new Error(exitMessage);
    }

    try {
      const response = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/version`);
      if (response.ok) {
        return;
      }
    } catch {
      // 브라우저가 뜨는 중이면 다음 polling에서 다시 확인한다.
    }

    await sleep(100);
  }

  throw new Error("Timed out waiting for headless browser debugging port");
}

function isPortListening(port) {
  return new Promise((resolve) => {
    const socket = createConnection({ host: "127.0.0.1", port });
    let settled = false;

    const finish = (isListening) => {
      if (settled) {
        return;
      }
      settled = true;
      socket.destroy();
      resolve(isListening);
    };

    socket.setTimeout(300);
    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
    socket.once("timeout", () => finish(false));
  });
}

async function stopChild(child) {
  if (!child || !child.pid || child.exitCode !== null || child.signalCode !== null) {
    return;
  }

  child.kill("SIGTERM");
  await waitForChildExit(child, 1000);

  if (child.exitCode === null && child.signalCode === null) {
    child.kill("SIGKILL");
    await waitForChildExit(child, 1000);
  }
}

function waitForChildExit(child, timeoutMs) {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    let timeoutId;
    const finish = () => {
      child.removeListener("exit", finish);
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      resolve();
    };

    child.once("exit", finish);
    timeoutId = setTimeout(finish, timeoutMs);

    if (child.exitCode !== null || child.signalCode !== null) {
      finish();
    }
  });
}

function waitForWebSocketOpen(ws, timeoutMs = WEBSOCKET_OPEN_TIMEOUT_MS) {
  if (ws.readyState === 1) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    let timeoutId;
    const cleanup = () => {
      ws.removeEventListener("open", handleOpen);
      ws.removeEventListener("error", handleError);
      ws.removeEventListener("close", handleClose);
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    };
    const handleOpen = () => {
      cleanup();
      resolve();
    };
    const handleError = () => {
      cleanup();
      reject(new Error("CDP WebSocket failed to open"));
    };
    const handleClose = (event) => {
      cleanup();
      reject(new Error(`CDP WebSocket closed before opening (code ${event.code})`));
    };

    ws.addEventListener("open", handleOpen, { once: true });
    ws.addEventListener("error", handleError, { once: true });
    ws.addEventListener("close", handleClose, { once: true });
    timeoutId = setTimeout(() => {
      cleanup();
      reject(new Error(`Timed out opening CDP WebSocket after ${timeoutMs}ms`));
    }, timeoutMs);
  });
}

// CDP 요청/응답을 Promise 형태로 보낸다.
function createCdpClient(ws, timeoutMs = CDP_REQUEST_TIMEOUT_MS) {
  let nextId = 1;
  let closed = false;
  const pending = new Map();

  const rejectAll = (error) => {
    if (closed) {
      return;
    }
    closed = true;
    for (const request of pending.values()) {
      clearTimeout(request.timeoutId);
      request.reject(error);
    }
    pending.clear();
  };

  const onMessage = (event) => {
    let message;
    try {
      message = JSON.parse(typeof event.data === "string" ? event.data : event.data.toString());
    } catch (error) {
      rejectAll(new Error(`Invalid CDP message: ${error instanceof Error ? error.message : String(error)}`));
      return;
    }

    if (typeof message.id !== "number") {
      return;
    }

    const request = pending.get(message.id);
    if (!request) {
      return;
    }

    pending.delete(message.id);
    clearTimeout(request.timeoutId);

    if (message.error) {
      request.reject(new Error(`${request.method}: ${message.error.message}`));
      return;
    }

    request.resolve(message.result);
  };
  const onError = () => rejectAll(new Error("CDP WebSocket error"));
  const onClose = (event) => {
    const reason = event.reason ? `: ${event.reason}` : "";
    rejectAll(new Error(`CDP WebSocket closed (code ${event.code}${reason})`));
  };

  ws.addEventListener("message", onMessage);
  ws.addEventListener("error", onError);
  ws.addEventListener("close", onClose);

  const send = function send(method, params = {}) {
    if (closed || ws.readyState !== 1) {
      return Promise.reject(new Error(`${method}: CDP WebSocket is not open`));
    }

    const id = nextId;
    nextId += 1;

    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`${method}: CDP request timed out after ${timeoutMs}ms`));
      }, timeoutMs);

      pending.set(id, { method, reject, resolve, timeoutId });
      try {
        ws.send(JSON.stringify({ id, method, params }));
      } catch (error) {
        pending.delete(id);
        clearTimeout(timeoutId);
        reject(error instanceof Error ? error : new Error(String(error)));
      }
    });
  };

  send.dispose = () => {
    ws.removeEventListener("message", onMessage);
    ws.removeEventListener("error", onError);
    ws.removeEventListener("close", onClose);
    rejectAll(new Error("CDP client disposed"));
  };

  return send;
}

// 지연 로딩과 인증 확인이 끝나 실제 UI가 붙을 때까지 DOM 기준으로 기다린다.
async function waitForSelector(send, selector, timeoutMs = 5000, expectedUrl = null) {
  const startedAt = Date.now();
  let lastError = null;

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const result = await send("Runtime.evaluate", {
        returnByValue: true,
        expression: `${expectedUrl ? `location.href === ${JSON.stringify(expectedUrl)} && ` : ""}Boolean(document.querySelector(${JSON.stringify(selector)}))`,
      });

      if (result.result.value) {
        return;
      }
    } catch (error) {
      // 탐색 직후 execution context가 교체되는 동안에는 다음 polling에서 다시 확인한다.
      lastError = error;
    }

    await sleep(50);
  }

  const suffix = lastError instanceof Error ? ` (${lastError.message})` : "";
  let diagnostic = "";
  try {
    const result = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `JSON.stringify({
        url: location.href,
        authLoading: Boolean(document.querySelector('.auth-loading')),
        authForm: Boolean(document.querySelector('.auth-form')),
        appShell: Boolean(document.querySelector('.app-shell')),
        projectHome: Boolean(document.querySelector('.project-home')),
        projectPanel: Boolean(document.querySelector('.project-panel')),
        projectPanelView: document.querySelector('.project-panel')?.getAttribute('data-view') || '',
        projectPanelText: document.querySelector('.project-panel')?.textContent?.trim().slice(0, 500) || '',
        projectPanelMenuButtons: Array.from(document.querySelectorAll('.project-panel-menu button'))
          .map((button) => ({
            disabled: button.disabled,
            text: button.textContent?.trim() || '',
          })),
        projectPanelTabs: Array.from(document.querySelectorAll('.project-panel-tab'))
          .map((tab) => tab.textContent?.trim() || ''),
        prompt: Boolean(document.querySelector('.prompt')),
        apiCalls: window.__paimLayoutApiCalls || [],
      })`,
    });
    diagnostic = ` ${result.result.value}`;
  } catch {
    // 진단 평가도 navigation과 겹치면 기본 timeout 정보만 사용한다.
  }

  throw new Error(`Timed out waiting for selector: ${selector}${suffix}${diagnostic}`);
}

function createSmokeNavigationUrl(url) {
  const target = new URL(url);
  target.searchParams.set("__paimSmokeNavigation", String(nextSmokeNavigationId));
  nextSmokeNavigationId += 1;
  return target.toString();
}

async function navigateAndWaitForSelector(send, url, selector, timeoutMs = 5000) {
  const targetUrl = createSmokeNavigationUrl(url);

  await send("Page.navigate", { url: targetUrl });
  await waitForSelector(send, selector, timeoutMs, targetUrl);
}

async function evaluateAndNavigateToSelector(send, expression, url, selector, timeoutMs = 5000) {
  const setupScript = await send("Page.addScriptToEvaluateOnNewDocument", {
    source: `(() => { ${expression}; })()`,
  });

  try {
    let lastError = null;

    for (let attempt = 0; attempt < 2; attempt += 1) {
      const targetUrl = createSmokeNavigationUrl(url);
      await send("Page.navigate", { url: targetUrl });

      try {
        await waitForSelector(send, selector, timeoutMs, targetUrl);
        return;
      } catch (error) {
        lastError = error;
      }
    }

    throw lastError;
  } finally {
    await send("Page.removeScriptToEvaluateOnNewDocument", {
      identifier: setupScript.identifier,
    });
  }
}

async function clickVisibleMenuItem(send, label, timeoutMs = 5000) {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    const result = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => {
        const item = Array.from(document.querySelectorAll(${JSON.stringify(PROJECT_PANEL_TAB_MENU_ITEM_SELECTOR)}))
          .find((candidate) => {
            const rect = candidate.getBoundingClientRect();
            return candidate.textContent.includes(${JSON.stringify(label)}) &&
              rect.width > 0 && rect.height > 0 &&
              getComputedStyle(candidate).visibility !== 'hidden';
          });
        item?.click();
        return Boolean(item);
      })()`,
    });

    if (result.result.value) {
      return;
    }

    await sleep(50);
  }

  throw new Error(`Timed out waiting for visible menu item: ${label}`);
}

// 요소가 viewport 좌우 경계를 넘지 않는지 검사한다.
function assertInside(name, box, width, failures) {
  if (box.left < -0.5) {
    failures.push(`${name} left overflow: ${box.left}`);
  }

  if (box.right > width + 0.5) {
    failures.push(`${name} right overflow: ${box.right} > ${width}`);
  }
}

// 주어진 viewport와 UI 상태에서 프롬프트/버튼 레이아웃을 측정한다.
async function measureScenario(send, scenario) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: scenario.width,
    height: scenario.height,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithProject(send);
  await send("Runtime.evaluate", {
    expression: `localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false')`,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);

  if (scenario.collapsed) {
    await send("Runtime.evaluate", {
      expression: "document.querySelector('.sidebar-collapse-button')?.click()",
    });
    await sleep(200);
  }

  if (scenario.dragActive) {
    await send("Runtime.evaluate", {
      expression: "document.querySelector('.app-shell')?.setAttribute('data-drag-active', 'true')",
    });
  }

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const rect = (selector) => {
        const element = document.querySelector(selector);
        const box = element.getBoundingClientRect();
        return {
          left: box.left,
          right: box.right,
          top: box.top,
          bottom: box.bottom,
          width: box.width,
          height: box.height,
        };
      };
      const projectPanel = document.querySelector('.project-panel');
      const projectPanelBox = projectPanel?.getBoundingClientRect();
      const projectPanelBackdrop = document.querySelector('.project-panel-backdrop');
      const sidebar = document.querySelector('.sidebar');
      const sidebarBox = sidebar?.getBoundingClientRect();
      const prompt = rect('.prompt');
      const actions = rect('.prompt-actions');
      const buttons = Array.from(document.querySelectorAll('.prompt-actions button')).map((button) => {
        const box = button.getBoundingClientRect();
        return {
          label: button.getAttribute('aria-label') || button.textContent.trim(),
          left: box.left,
          right: box.right,
          width: box.width,
        };
      });

      return {
        scrollWidth: document.documentElement.scrollWidth,
        bodyScrollWidth: document.body.scrollWidth,
        prompt,
        actions,
        buttons,
        projectPanelVisible: Boolean(projectPanel) && getComputedStyle(projectPanel).display !== 'none',
        projectPanelInsideViewport: Boolean(projectPanelBox) &&
          projectPanelBox.left >= -0.5 && projectPanelBox.right <= innerWidth + 0.5,
        projectPanelRole: projectPanel?.getAttribute('role') || '',
        projectPanelAriaModal: projectPanel?.getAttribute('aria-modal') || '',
        projectPanelMenuButtons: document.querySelectorAll('.project-panel-menu button').length,
        projectPanelBackdropVisible: Boolean(projectPanelBackdrop) &&
          getComputedStyle(projectPanelBackdrop).display !== 'none',
        sidebarVisible: Boolean(sidebarBox?.width && sidebarBox?.height),
        sidebarAccountExists: Boolean(document.querySelector('.sidebar-account-button')),
        settingsExists: Boolean(document.querySelector('.settings-float')),
      };
    })()`,
  });

  const value = result.result.value;
  const failures = [];

  if (value.scrollWidth > scenario.width) {
    failures.push(`document horizontal overflow: ${value.scrollWidth} > ${scenario.width}`);
  }

  if (value.bodyScrollWidth > scenario.width) {
    failures.push(`body horizontal overflow: ${value.bodyScrollWidth} > ${scenario.width}`);
  }

  assertInside("prompt", value.prompt, scenario.width, failures);
  assertInside("prompt actions", value.actions, scenario.width, failures);
  value.buttons.forEach((button) => assertInside(`button ${button.label}`, button, scenario.width, failures));

  if (value.actions.left < value.prompt.left - 0.5 || value.actions.right > value.prompt.right + 0.5) {
    failures.push("prompt actions exceed prompt bounds");
  }

  if (!value.projectPanelVisible || !value.projectPanelInsideViewport || value.projectPanelMenuButtons < 2) {
    failures.push("project panel menu should stay visible inside the viewport");
  }

  if (scenario.width <= 1024 && !value.projectPanelBackdropVisible) {
    failures.push("project panel should use a backdrop overlay in narrow desktop windows");
  }

  if (scenario.width <= 1024 &&
      (value.projectPanelRole !== "dialog" || value.projectPanelAriaModal !== "true")) {
    failures.push("narrow desktop project panel should expose its overlay as a modal dialog");
  }

  if (!value.sidebarVisible || !value.sidebarAccountExists) {
    failures.push("sidebar chrome and account access should stay available in supported desktop window sizes");
  }

  if (value.settingsExists) {
    failures.push("settings floating button should not exist");
  }

  return { scenario, value, failures };
}

// 960px 창을 200%로 본 것과 같은 480 CSS px에서도 overlay가 rail과 viewport 안에 붙는다.
async function verifyZoomedOverlayPanelBounds(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 480,
    height: 410,
    deviceScaleFactor: 2,
    mobile: false,
  });
  await openAppWithProject(send);
  await sleep(180);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const shell = document.querySelector('.app-shell');
      const panel = document.querySelector('.project-panel');
      const panelBox = panel?.getBoundingClientRect();
      const backdrop = document.querySelector('.project-panel-backdrop');

      return {
        backdropVisible: Boolean(backdrop) && getComputedStyle(backdrop).display !== 'none',
        bodyScrollWidth: document.body.scrollWidth,
        documentScrollWidth: document.documentElement.scrollWidth,
        innerWidth,
        overlay: shell?.getAttribute('data-project-panel-overlay') || "",
        panelAriaModal: panel?.getAttribute('aria-modal') || "",
        panelLeft: panelBox?.left ?? -1,
        panelRight: panelBox?.right ?? -1,
        panelRole: panel?.getAttribute('role') || "",
        panelWidth: panelBox?.width ?? -1,
        state: shell?.getAttribute('data-project-panel-state') || "",
      };
    })()`,
  });
  const value = result.result.value;

  const failures = [];

  if (value.innerWidth !== 480 || value.overlay !== "true" || value.state !== "open") {
    failures.push("200% effective viewport should keep the open project panel in overlay mode");
  }

  if (value.panelLeft < 52 - 0.5 ||
      Math.abs(value.panelRight - value.innerWidth) > 0.5 ||
      value.panelWidth > value.innerWidth - 52 + 0.5) {
    failures.push(`zoomed overlay should stay right-anchored after the 52px rail: ${value.panelLeft}-${value.panelRight} / ${value.innerWidth}`);
  }

  if (!value.backdropVisible || value.panelRole !== "dialog" || value.panelAriaModal !== "true") {
    failures.push("zoomed overlay should preserve its modal backdrop and dialog semantics");
  }

  if (value.documentScrollWidth > value.innerWidth || value.bodyScrollWidth > value.innerWidth) {
    failures.push("zoomed overlay should not create horizontal document overflow");
  }

  debugLayout("zoomed overlay panel bounds", value);
  return { value, failures };
}

// 960px 창의 200% 확대에 해당하는 viewport에서도 project home은 rail과 단일 열을 쓴다.
async function verifyZoomedProjectHomeLayout(send) {
  const projectHomeState = createProjectStorage(
    "project-zoomed-home",
    "Zoomed Project Home",
    [],
    null,
    [],
    { apiProjectId: 1 },
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 480,
    height: 410,
    deviceScaleFactor: 2,
    mobile: false,
  });
  await navigateAndWaitForSelector(send, APP_URL, ".app-shell");
  await evaluateAndNavigateToSelector(
    send,
    `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}, '272'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(projectHomeState)})`,
    APP_URL,
    ".project-home",
  );
  await sleep(180);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const shell = document.querySelector('.app-shell');
      const sidebar = document.querySelector('.sidebar');
      const sidebarPanel = document.querySelector('.sidebar-panel');
      const home = document.querySelector('.project-home');
      const content = document.querySelector('.project-home-content');
      const main = document.querySelector('.project-home-main');
      const slots = document.querySelector('.project-home-slots');
      const slotList = document.querySelector('.project-home-slot-list');
      const actions = document.querySelector('.project-home-actions');
      const buttons = Array.from(actions?.querySelectorAll('button') || []);
      if (!shell || !sidebar || !home || !content || !main || !slots || !slotList || !actions) {
        return null;
      }

      actions.scrollIntoView({ block: 'nearest' });
      const homeBox = home.getBoundingClientRect();
      const contentBox = content.getBoundingClientRect();
      const mainBox = main.getBoundingClientRect();
      const slotsBox = slots.getBoundingClientRect();
      const actionBoxes = buttons.map((button) => {
        const box = button.getBoundingClientRect();
        return {
          bottom: box.bottom,
          display: getComputedStyle(button).display,
          left: box.left,
          right: box.right,
          top: box.top,
        };
      });
      const contentStyles = getComputedStyle(content);
      const slotsStyles = getComputedStyle(slots);

      return {
        actionBoxes,
        actionLabels: buttons.map((button) => button.textContent.trim()),
        contentColumns: contentStyles.gridTemplateColumns,
        contentLeft: contentBox.left,
        contentRight: contentBox.right,
        documentScrollWidth: document.documentElement.scrollWidth,
        homeClientHeight: home.clientHeight,
        homeClientWidth: home.clientWidth,
        homeLeft: homeBox.left,
        homeOverflowY: getComputedStyle(home).overflowY,
        homeRight: homeBox.right,
        homeScrollHeight: home.scrollHeight,
        homeScrollWidth: home.scrollWidth,
        innerWidth,
        mainBottom: mainBox.bottom,
        railWidth: sidebar.getBoundingClientRect().width,
        sidebarCollapsed: shell.getAttribute('data-sidebar-collapsed') || '',
        sidebarPanelDisplay: sidebarPanel ? getComputedStyle(sidebarPanel).display : '',
        slotColumns: getComputedStyle(slotList).gridTemplateColumns,
        slotCount: slotList.querySelectorAll('.project-home-slot').length,
        slotsBorderLeft: Number.parseFloat(slotsStyles.borderLeftWidth),
        slotsBorderTop: Number.parseFloat(slotsStyles.borderTopWidth),
        slotsLeft: slotsBox.left,
        slotsRight: slotsBox.right,
        slotsTop: slotsBox.top,
      };
    })()`,
  });
  const value = result.result.value;
  const failures = [];

  if (!value ||
      value.innerWidth !== 480 ||
      value.sidebarCollapsed !== "true" ||
      Math.abs(value.railWidth - 52) > 1 ||
      value.sidebarPanelDisplay !== "none") {
    failures.push("200% project home should automatically collapse the project tree to the 52px rail");
  }

  if (!value ||
      value.documentScrollWidth > value.innerWidth ||
      value.homeScrollWidth > value.homeClientWidth + 1 ||
      value.contentLeft < value.homeLeft - 0.5 ||
      value.contentRight > value.homeRight + 0.5) {
    failures.push("200% project home should not create horizontal overflow");
  }

  if (!value ||
      value.contentColumns.trim().split(/\s+/).length !== 1 ||
      value.slotsTop < value.mainBottom - 0.5 ||
      value.slotsLeft < value.contentLeft - 0.5 ||
      value.slotsRight > value.contentRight + 0.5 ||
      value.slotsBorderLeft !== 0 ||
      value.slotsBorderTop < 0.5 ||
      value.slotCount !== 4) {
    failures.push("200% project home should stack the memory slots below the main setup content");
  }

  if (!value ||
      value.actionLabels.join("|") !== "분석 없이 채팅|분석 시작" ||
      value.actionBoxes.some((box) =>
        box.display === "none" ||
        box.left < value.homeLeft - 0.5 ||
        box.right > value.homeRight + 0.5 ||
        box.top < 44 - 0.5 ||
        box.bottom > 410 + 0.5
      ) ||
      value.homeOverflowY !== "auto" ||
      value.homeScrollHeight <= value.homeClientHeight) {
    failures.push("200% project home should keep both core actions reachable through its vertical scroll area");
  }

  debugLayout("zoomed project home", value);
  return { value, failures };
}

// Astryx AppShell이 기존 PaiM 프레임을 감싸고 단일 main landmark를 소유하는지 확인한다.
async function verifyAstryxAppShell(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithProject(send);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const astryxShell = document.querySelector('.paim-app-shell');
      const astryxMain = document.querySelector('#astryx-app-shell-main');
      const paimFrame = document.querySelector('.app-shell');
      const chat = document.querySelector('.chat');
      const chrome = document.querySelector('.app-chrome');
      const sidebar = document.querySelector('.sidebar');
      const projectPanel = document.querySelector('.project-panel');
      const skipLink = document.querySelector('[data-testid="skip-to-content"]');
      const box = (element) => {
        const rect = element?.getBoundingClientRect();
        return rect
          ? { top: rect.top, right: rect.right, bottom: rect.bottom, left: rect.left }
          : null;
      };

      return {
        astryxShellCount: document.querySelectorAll('.paim-app-shell').length,
        astryxMainCount: document.querySelectorAll('#astryx-app-shell-main').length,
        mainLandmarkCount: document.querySelectorAll('main, [role="main"]').length,
        astryxMainRole: astryxMain?.getAttribute('role') || '',
        astryxVariant: astryxShell?.getAttribute('data-variant') || '',
        chatTagName: chat?.tagName || '',
        chatIsLayoutContent: Boolean(chat?.classList.contains('astryx-layout-content')),
        chatOverflow: chat ? getComputedStyle(chat).overflow : '',
        chatPadding: chat ? getComputedStyle(chat).padding : '',
        frameInsideMain: Boolean(astryxMain?.contains(paimFrame)),
        framePanelState: paimFrame?.getAttribute('data-project-panel-state') || '',
        hasLegacyPanelStateAttributes: Boolean(
          paimFrame?.hasAttribute('data-project-panel-collapsed') ||
          paimFrame?.hasAttribute('data-project-panel-maximized')
        ),
        chatInsideMain: Boolean(astryxMain?.contains(chat)),
        frameOwnsGridRegions: [chrome, sidebar, chat, projectPanel]
          .every((element) => element?.parentElement === paimFrame),
        projectPanelContract: {
          ariaLabel: projectPanel?.getAttribute('aria-label') || '',
          isLayoutPanel: Boolean(projectPanel?.classList.contains('astryx-layout-panel')),
          overflow: projectPanel ? getComputedStyle(projectPanel).overflow : '',
          padding: projectPanel ? getComputedStyle(projectPanel).padding : '',
          role: projectPanel?.getAttribute('role') || '',
          state: projectPanel?.getAttribute('data-state') || '',
          tagName: projectPanel?.tagName || '',
        },
        hasNestedMain: Boolean(astryxMain?.querySelector('main, [role="main"]')),
        skipLinkHref: skipLink?.getAttribute('href') || '',
        mainOverflow: astryxMain ? getComputedStyle(astryxMain).overflow : '',
        mainHasOverflow: astryxMain
          ? astryxMain.scrollHeight > astryxMain.clientHeight + 1 ||
            astryxMain.scrollWidth > astryxMain.clientWidth + 1
          : true,
        mainBox: box(astryxMain),
        frameBox: box(paimFrame),
      };
    })()`,
  });
  const value = result.result.value;
  const failures = [];

  if (value.astryxShellCount !== 1 ||
      value.astryxMainCount !== 1 ||
      value.mainLandmarkCount !== 1 ||
      value.astryxMainRole !== "main" ||
      value.astryxVariant !== "wash") {
    failures.push("Astryx AppShell should render exactly one shell and main content region");
  }

  if (!value.frameInsideMain ||
      !value.chatInsideMain ||
      !value.frameOwnsGridRegions ||
      value.framePanelState !== "open" ||
      value.hasLegacyPanelStateAttributes ||
      !value.chatIsLayoutContent ||
      value.chatTagName !== "DIV" ||
      value.chatOverflow !== "clip" ||
      value.chatPadding !== "0px") {
    failures.push("Astryx AppShell main should own the existing PaiM frame without a nested main element");
  }

  if (value.hasNestedMain || value.skipLinkHref !== "#astryx-app-shell-main") {
    failures.push("Astryx AppShell should expose a valid skip link and a single main landmark");
  }

  if (!value.projectPanelContract.isLayoutPanel ||
      value.projectPanelContract.tagName !== "DIV" ||
      !["complementary", "dialog"].includes(value.projectPanelContract.role) ||
      value.projectPanelContract.ariaLabel !== "프로젝트 보조 패널" ||
      value.projectPanelContract.overflow !== "clip" ||
      value.projectPanelContract.padding !== "0px" ||
      value.projectPanelContract.state !== "open") {
    failures.push("project tools should use an edge-to-edge Astryx LayoutPanel");
  }

  if (value.mainOverflow !== "hidden" || value.mainHasOverflow) {
    failures.push("Astryx AppShell should preserve PaiM as the only scrolling layout owner");
  }

  if (!value.mainBox ||
      !value.frameBox ||
      Math.abs(value.mainBox.left - value.frameBox.left) > 1 ||
      Math.abs(value.mainBox.right - value.frameBox.right) > 1 ||
      Math.abs(value.mainBox.top - value.frameBox.top) > 1 ||
      Math.abs(value.mainBox.bottom - value.frameBox.bottom) > 1 ||
      Math.abs(value.frameBox.left) > 1 ||
      Math.abs(value.frameBox.top) > 1 ||
      Math.abs(value.frameBox.right - 960) > 1 ||
      Math.abs(value.frameBox.bottom - 680) > 1) {
    failures.push("PaiM frame should remain edge-to-edge inside Astryx AppShell");
  }

  return { value, failures };
}

// 저장 세션에서 이미지 data URL 미리보기가 제거되는지 확인한다.
async function verifyStorageSanitization(send) {
  const seededSessions = [
    {
      id: "session-storage-smoke",
      title: "Storage smoke",
      createdAt: Date.now(),
      messages: [
        {
          id: "assistant-storage-smoke",
          role: "assistant",
          content: "저장된 응답입니다.",
        },
        {
          id: "user-storage-smoke",
          role: "user",
          content: "첨부 저장 테스트",
          attachments: [
            {
              id: "attachment-storage-smoke",
              name: "preview.png",
              path: "/tmp/preview.png",
              previewUrl: "data:image/png;base64,AAAA",
            },
          ],
        },
      ],
    },
  ];

  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  const seededProjectState = createProjectStorage(
    "project-storage-smoke",
    "Storage Smoke",
    seededSessions,
  );
  await send("Runtime.evaluate", {
    expression: `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(seededProjectState)})`,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const savedValue = localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || "";
      return {
        containsPreviewUrl: savedValue.includes("previewUrl"),
        containsDataUrl: savedValue.includes("data:image"),
        attachmentVisible: document.body.textContent.includes("preview.png"),
      };
    })()`,
  });
  const value = result.result.value;
  const failures = [];

  if (value.containsPreviewUrl || value.containsDataUrl) {
    failures.push("stored sessions should not include attachment preview data URLs");
  }

  if (!value.attachmentVisible) {
    failures.push("stored attachment name should remain visible after sanitization");
  }

  return { value, failures };
}

// 아이콘 버튼은 접근성 라벨과 hover tooltip을 함께 가져야 한다.
async function verifyIconButtonTooltips(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `Array.from(document.querySelectorAll('button[aria-label]'))
      .map((button) => ({
        label: button.getAttribute('aria-label') || '',
      }))
      .filter((button) => button.label.trim().length === 0)`,
  });
  const value = result.result.value;
  const failures = [];

  if (value.length > 0) {
    failures.push(`icon buttons missing accessible label: ${value.length}`);
  }

  return { value, failures };
}

// 첫 실행 빈 화면과 사이드바 기본 톤을 확인한다.
async function verifySidebarBrandTypography(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithoutProjects(send);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const box = (selector) => {
        const element = document.querySelector(selector);
        if (!element) {
          return null;
        }
        const rect = element.getBoundingClientRect();
        return {
          top: rect.top,
          right: rect.right,
          bottom: rect.bottom,
          left: rect.left,
          width: rect.width,
          height: rect.height,
        };
      };
      const fontSize = (selector) => {
        const element = document.querySelector(selector);
        return element ? Number.parseFloat(getComputedStyle(element).fontSize) : null;
      };
      const sidebar = box('.sidebar');
      const panel = box('.sidebar-panel');
      const sideNav = document.querySelector('.sidebar-panel');
      const sideNavContent = sideNav?.firstElementChild;
      const sidebarElement = document.querySelector('.sidebar');
      const shell = box('.app-shell');
      const chromeHeight = Number.parseFloat(
        getComputedStyle(document.querySelector('.app-shell')).getPropertyValue('--chrome-height'),
      );
      const startMark = box('.project-start-mark');

      return {
        rootFont: getComputedStyle(document.documentElement).fontFamily,
        codeFont: getComputedStyle(document.documentElement).getPropertyValue('--code-font-family'),
        hasSidebarBrand: Boolean(document.querySelector('.sidebar-brand')),
        hasPrompt: Boolean(document.querySelector('.prompt')),
        hasMessage: Boolean(document.querySelector('.message')),
        startMark,
        startMarkText: document.querySelector('.project-start-mark')?.textContent.trim() || "",
        startMarkAriaHidden: document.querySelector('.project-start-mark')?.getAttribute('aria-hidden') || "",
        hasLegacyWatermark: Boolean(document.querySelector('.project-start-watermark')),
        startButtonText: document.querySelector('.project-start-button')?.textContent.trim() || "",
        panel,
        sideNavContract: {
          ariaLabel: sideNav?.getAttribute('aria-label') || '',
          contentOverflow: sideNavContent ? getComputedStyle(sideNavContent).overflow : '',
          display: sideNav ? getComputedStyle(sideNav).display : '',
          isAstryx: Boolean(sideNav?.classList.contains('astryx-side-nav')),
          isDirectChild: sideNav?.parentElement?.classList.contains('sidebar') || false,
          role: sideNav?.getAttribute('role') || '',
          tagName: sideNav?.tagName || '',
        },
        projectCreateCount: document.querySelectorAll('.project-create-trigger').length,
        customTrafficLightCount: document.querySelectorAll('.mac-traffic-button').length,
        hasWindowControlCluster: Boolean(document.querySelector('.window-control-cluster')),
        shell,
        sidebarCollapsed: document.querySelector('.app-shell')?.getAttribute('data-sidebar-collapsed') || '',
        chromeHeight,
        sidebar,
        sidebarBorderRightWidth: sidebarElement
          ? Number.parseFloat(getComputedStyle(sidebarElement).borderRightWidth)
          : null,
        sidebarCollapseButtonCount: document.querySelectorAll('.sidebar-collapse-button').length,
        sidebarAccountButtonCount: document.querySelectorAll('.sidebar-account-button').length,
        legacySidebarSettingsButtonCount: document.querySelectorAll('.sidebar-settings-button').length,
        navFontSize: fontSize('.history-item'),
      };
    })()`,
  });
  const value = result.result.value;
  const failures = [];

  if (!/^\s*-apple-system\b/.test(value.rootFont)) {
    failures.push(`the macOS system UI font should be the first configured app font: ${value.rootFont}`);
  }

  if (!/^\s*["']?SFMono-Regular["']?\b/.test(value.codeFont)) {
    failures.push(`SF Mono should be the first configured code font: ${value.codeFont}`);
  }

  if (value.hasSidebarBrand) {
    failures.push("sidebar should not render the watermark logo");
  }

  if (value.hasPrompt || value.hasMessage) {
    failures.push("empty first-run state should not render chat UI");
  }

  if (!value.sideNavContract.isAstryx ||
      !value.sideNavContract.isDirectChild ||
      value.sideNavContract.tagName !== "NAV" ||
      value.sideNavContract.role !== "navigation" ||
      value.sideNavContract.ariaLabel !== "프로젝트와 대화" ||
      value.sideNavContract.contentOverflow !== "hidden") {
    failures.push("sidebar panel should use Astryx SideNav without changing frame ownership");
  }

  if (!value.startMark ||
      value.startMarkText !== "PaiM" ||
      value.startMarkAriaHidden !== "true" ||
      value.startMark.width < 64 ||
      value.hasLegacyWatermark) {
    failures.push("empty first-run state should center the compact PaiM mark without the legacy watermark");
  }

  if (!value.startButtonText.includes("새 프로젝트 시작하기")) {
    failures.push("empty first-run state should render the start project button");
  }

  if (value.sidebarCollapsed !== "true" ||
      Math.abs(value.sidebar.width - 52) > 1 ||
      value.sideNavContract.display !== "none" ||
      value.panel.width !== 0 ||
      value.sidebarBorderRightWidth !== 0 ||
      value.sidebarCollapseButtonCount !== 0 ||
      value.sidebarAccountButtonCount !== 1 ||
      value.legacySidebarSettingsButtonCount !== 0) {
    failures.push("empty first-run state should keep only compact account chrome without a divider or collapse control");
  }

  if (value.projectCreateCount !== 0) {
    failures.push("empty first-run state should expose only the centered New Project action");
  }

  if (value.customTrafficLightCount !== 0 || value.hasWindowControlCluster) {
    failures.push("web content should not render custom macOS window controls");
  }

  if (value.navFontSize !== null && value.navFontSize > 13.5) {
    failures.push("sidebar panel text should stay compact");
  }

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-start-button')?.click()`,
  });
  await waitForSelector(send, ".project-home");
  const afterStartResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const savedState = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const activeProject = savedState.projects?.find((project) => project.id === savedState.selectedProjectId);
      const selectedSession = activeProject?.sessions.find(
        (session) => session.id === savedState.selectedSessionId,
      );
      const projectHomeActions = Array.from(
        document.querySelectorAll('.project-home-actions button'),
      );
      return {
        projectCount: savedState.projects?.length ?? 0,
        activeProjectName: document.querySelector('.project-item[data-active="true"]')?.getAttribute('data-project-name') || "",
        activeSessionCount: activeProject?.sessions.length ?? 0,
        selectedSessionMessageCount: selectedSession?.messages.length ?? -1,
        selectedSessionId: savedState.selectedSessionId ?? null,
        hasPrompt: Boolean(document.querySelector('.prompt')),
        messageCount: document.querySelectorAll('.message').length,
        emptyTitle: document.querySelector('.chat-empty h1')?.textContent.trim() || "",
        hasProjectHome: Boolean(document.querySelector('.project-home')),
        uploadText: document.querySelector('.project-home-canvas-empty')?.textContent.trim() || "",
        analysisDisabled: Boolean(document.querySelector('.project-home-primary')?.disabled),
        panelMenuTexts: Array.from(document.querySelectorAll('.project-panel-menu button'))
          .map((button) => button.textContent.trim()),
        hasProjectOverview: Boolean(document.querySelector('.project-overview')),
        hasProjectPanel: Boolean(document.querySelector('.project-panel')),
        hasOverviewPrompt: Boolean(document.querySelector('input[aria-label="프로젝트 질문 입력"]')),
        projectCreateText: document.querySelector('.sidebar-panel .project-create-trigger')?.textContent.trim() || "",
        sidebarCollapsed: document.querySelector('.app-shell')?.getAttribute('data-sidebar-collapsed') || "",
        sidebarPanelWidth: document.querySelector('.sidebar-panel')?.getBoundingClientRect().width ?? 0,
        sidebarCollapseButtonCount: document.querySelectorAll('.sidebar-collapse-button').length,
        projectHomeActionOrder: projectHomeActions.map((button) => button.textContent.trim()),
        projectHomeActionHeights: projectHomeActions.map(
          (button) => button.getBoundingClientRect().height,
        ),
        projectHomeActionSizes: projectHomeActions.map(
          (button) => button.getAttribute('data-size') || '',
        ),
        projectHomeActionVariants: projectHomeActions.map(
          (button) => button.getAttribute('data-variant') || '',
        ),
        projectHomeActionFontWeights: projectHomeActions.map(
          (button) => getComputedStyle(button).fontWeight,
        ),
        projectHomeActionIconCount: document.querySelectorAll(
          '.project-home-actions button svg',
        ).length,
        projectHomeAnalysisNote: document.querySelector(
          '#project-home-analysis-note',
        )?.textContent.trim() || '',
        projectHomePrimaryDescribedBy: document.querySelector(
          '.project-home-primary',
        )?.getAttribute('aria-describedby') || '',
      };
    })()`,
  });
  value.afterStart = afterStartResult.result.value;

  if (value.afterStart.projectCount !== 1 ||
      value.afterStart.activeProjectName !== "New Project 1" ||
      value.afterStart.activeSessionCount !== 0 ||
      value.afterStart.selectedSessionMessageCount !== -1 ||
      value.afterStart.selectedSessionId !== null ||
      value.afterStart.hasPrompt ||
      value.afterStart.messageCount !== 0 ||
      value.afterStart.emptyTitle !== "" ||
      !value.afterStart.hasProjectHome ||
      !value.afterStart.uploadText.includes("자료를 여기에 끌어다 놓으세요") ||
      !value.afterStart.analysisDisabled ||
      value.afterStart.panelMenuTexts.some((text) => text.includes("메모리")) ||
      value.afterStart.hasProjectOverview ||
      value.afterStart.hasProjectPanel ||
      value.afterStart.hasOverviewPrompt ||
      !value.afterStart.projectCreateText.includes("새 프로젝트") ||
      value.afterStart.sidebarCollapsed !== "false" ||
      value.afterStart.sidebarPanelWidth <= 0 ||
      value.afterStart.sidebarCollapseButtonCount !== 1) {
    failures.push("start project button should create the first project and enter project home");
  }

  if (value.afterStart.projectHomeActionOrder.join('|') !== "분석 없이 채팅|분석 시작" ||
      value.afterStart.projectHomeActionHeights.some((height) => height > 30) ||
      value.afterStart.projectHomeActionSizes.some((size) => size !== "sm") ||
      value.afterStart.projectHomeActionVariants.join('|') !== "ghost|primary" ||
      value.afterStart.projectHomeActionFontWeights.some((weight) => Number(weight) > 600) ||
      value.afterStart.projectHomeActionIconCount !== 0 ||
      !value.afterStart.projectHomeAnalysisNote.includes("설명이나 자료를 추가하면") ||
      value.afterStart.projectHomePrimaryDescribedBy !== "project-home-analysis-note") {
    failures.push("project home actions should keep a compact secondary-to-primary hierarchy");
  }

  const measureSidebarTooltip = async (theme) => {
    await send("Runtime.evaluate", {
      expression: `(() => {
        let settings = {};
        try {
          settings = JSON.parse(localStorage.getItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}) || '{}');
        } catch {
          settings = {};
        }
        settings.theme = ${JSON.stringify(theme)};
        localStorage.setItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}, JSON.stringify(settings));
      })()`,
    });
    await send("Page.navigate", { url: APP_URL });
    await waitForSelector(send, ".project-home");
    await sleep(250);
    await send("Runtime.evaluate", {
      expression: `document.querySelector('.sidebar-collapse-button')?.dispatchEvent(
        new MouseEvent('mouseenter', { bubbles: false }),
      )`,
    });
    await sleep(300);
    const earlyResult = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `Boolean(
        document.querySelector('.astryx-tooltip[role="tooltip"]')?.matches(':popover-open'),
      )`,
    });
    await sleep(420);
    const settledResult = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => {
        const button = document.querySelector('.sidebar-collapse-button');
        const tooltip = document.querySelector('.astryx-tooltip[role="tooltip"]');
        if (!button || !tooltip) return null;
        const buttonRect = button.getBoundingClientRect();
        const tooltipRect = tooltip.getBoundingClientRect();
        const style = getComputedStyle(tooltip);
        return {
          isOpen: tooltip.matches(':popover-open'),
          height: tooltipRect.height,
          isPlacedBelowButton: tooltipRect.top >= buttonRect.bottom - 1,
          fontSize: style.fontSize,
          borderRadius: style.borderRadius,
          backgroundColor: style.backgroundColor,
          color: style.color,
        };
      })()`,
    });
    await send("Runtime.evaluate", {
      expression: `document.querySelector('.sidebar-collapse-button')?.dispatchEvent(
        new MouseEvent('mouseleave', { bubbles: false }),
      )`,
    });
    return {
      earlyOpen: earlyResult.result.value,
      settled: settledResult.result.value,
    };
  };

  value.sidebarTooltip = {
    dark: await measureSidebarTooltip("dark"),
    light: await measureSidebarTooltip("light"),
  };
  debugLayout("sidebar tooltip", value.sidebarTooltip);
  await send("Runtime.evaluate", {
    expression: `(() => {
      const settings = JSON.parse(
        localStorage.getItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}) || '{}',
      );
      settings.theme = 'system';
      localStorage.setItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}, JSON.stringify(settings));
    })()`,
  });

  const invalidTooltipTheme = (result) =>
    result.earlyOpen ||
    !result.settled?.isOpen ||
    result.settled.height > 24 ||
    !result.settled.isPlacedBelowButton ||
    result.settled.fontSize !== "11px" ||
    result.settled.borderRadius !== "6px" ||
    result.settled.backgroundColor === result.settled.color;

  if (invalidTooltipTheme(value.sidebarTooltip.dark) ||
      invalidTooltipTheme(value.sidebarTooltip.light) ||
      value.sidebarTooltip.dark.settled.backgroundColor ===
        value.sidebarTooltip.light.settled.backgroundColor) {
    failures.push("sidebar tooltip should appear late as a compact trailing help tag");
  }

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-home textarea')?.focus()`,
  });
  await send("Input.insertText", { text: "설명 입력 테스트" });
  await sleep(250);
  const descriptionInputResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const savedState = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const activeProject = savedState.projects?.find((project) => project.id === savedState.selectedProjectId);

      return {
        hasProjectHome: Boolean(document.querySelector('.project-home')),
        storedDescription: activeProject?.description || "",
        textareaValue: document.querySelector('.project-home textarea')?.value || "",
      };
    })()`,
  });
  value.descriptionInput = descriptionInputResult.result.value;

  if (!value.descriptionInput.hasProjectHome ||
      value.descriptionInput.storedDescription !== "설명 입력 테스트" ||
      value.descriptionInput.textareaValue !== "설명 입력 테스트") {
    failures.push("project description input should update state without crashing");
  }

  value.afterStartTabAddMenuTexts = [];

  return { value, failures };
}

// 응답 복사 버튼이 성공 피드백 상태로 바뀌는지 확인한다.
async function verifyCopyFeedback(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithProject(send);
  await send("Runtime.evaluate", {
    expression: `Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (text) => {
          window.__paimCopiedText = text;
        },
      },
    })`,
  });
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.copy-button')?.click()`,
  });
  await sleep(120);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const copiedButton = document.querySelector('.copy-button[data-copied="true"]');
      return {
        hasCopiedState: Boolean(copiedButton),
        copiedLabel: copiedButton?.getAttribute('aria-label') || "",
        copiedText: window.__paimCopiedText || "",
      };
    })()`,
  });
  const value = result.result.value;
  const failures = [];

  if (!value.hasCopiedState) {
    failures.push("copy button should enter the copied state");
  }

  if (value.copiedLabel !== "복사됨") {
    failures.push("copy button should expose copied feedback label");
  }

  if (!value.copiedText.includes("저장된 응답입니다.")) {
    failures.push("copy action should write the assistant response text");
  }

  return { value, failures };
}

// 공백 없는 긴 프로젝트명/파일명/메시지가 전체 가로 레이아웃을 밀지 않는지 확인한다.
async function verifyLongContentLayout(send) {
  const longToken =
    "PAIM_SUPER_LONG_PROJECT_IDENTIFIER_WITHOUT_BREAKS_1234567890_".repeat(5);
  const seededSessions = [
    {
      id: "session-long-content",
      title: longToken,
      createdAt: Date.now(),
      messages: [
        {
          id: "assistant-long-content",
          role: "assistant",
          content: `${longToken}\n${longToken}`,
        },
        {
          id: "user-long-content",
          role: "user",
          content: longToken,
          attachments: [
            {
              id: "attachment-long-content",
              name: `${longToken}.png`,
              path: `/tmp/${longToken}.png`,
            },
          ],
        },
      ],
    },
  ];

  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  const seededProjectState = createProjectStorage(
    "project-long-content",
    longToken,
    seededSessions,
  );
  await send("Runtime.evaluate", {
    expression: `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(seededProjectState)})`,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const overflowingMessages = Array.from(document.querySelectorAll('.message-content'))
        .filter((element) => element.scrollWidth > element.clientWidth + 1)
        .map((element) => ({
          role: element.closest('.message')?.getAttribute('data-role') || "",
          messageWidth: element.closest('.message')?.getBoundingClientRect().width ?? 0,
          conversationWidth: document.querySelector('.conversation')?.getBoundingClientRect().width ?? 0,
          scrollWidth: element.scrollWidth,
          clientWidth: element.clientWidth,
          text: element.textContent.slice(0, 24),
        }));

      return {
        scrollWidth: document.documentElement.scrollWidth,
        bodyScrollWidth: document.body.scrollWidth,
        overflowingMessages,
        historyWidth: document.querySelector('.history-item')?.getBoundingClientRect().width ?? 0,
        attachmentVisible: document.body.textContent.includes('.png'),
      };
    })()`,
  });
  const value = result.result.value;
  const failures = [];

  if (value.scrollWidth > 960) {
    failures.push(`document horizontal overflow with long content: ${value.scrollWidth} > 960`);
  }

  if (value.bodyScrollWidth > 960) {
    failures.push(`body horizontal overflow with long content: ${value.bodyScrollWidth} > 960`);
  }

  if (value.overflowingMessages.length > 0) {
    failures.push(
      `message content should wrap long unbroken text: ${JSON.stringify(value.overflowingMessages)}`,
    );
  }

  if (!value.attachmentVisible) {
    failures.push("long attachment name should remain represented in the message");
  }

  return { value, failures };
}

// 채팅 세션이 전역 목록이 아니라 선택된 프로젝트 안에서만 관리되는지 확인한다.
async function verifyProjectScopedSessions(send) {
  const alphaSessions = [
    {
      id: "session-alpha",
      title: "Alpha Kickoff",
      createdAt: Date.now(),
      messages: [
        {
          id: "assistant-alpha",
          role: "assistant",
          content: "저장된 응답입니다.",
        },
        {
          id: "user-alpha",
          role: "user",
          content: "Alpha 프로젝트 일정 확인",
        },
      ],
    },
  ];
  const betaSessions = [
    {
      id: "session-beta",
      title: "Beta Risk Review",
      createdAt: Date.now(),
      messages: [
        {
          id: "assistant-beta",
          role: "assistant",
          content: "저장된 응답입니다.",
        },
        {
          id: "user-beta",
          role: "user",
          content: "Beta 프로젝트 리스크 확인",
        },
      ],
    },
  ];
  const seededProjectState = createProjectStorageState(
    [
      {
        id: "project-alpha",
        name: "Alpha Project",
        createdAt: Date.now(),
        sessions: alphaSessions,
      },
      {
        id: "project-beta",
        name: "Beta Project",
        createdAt: Date.now() - 1,
        sessions: betaSessions,
      },
    ],
    "project-alpha",
    "session-alpha",
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  await send("Runtime.evaluate", {
    expression: `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(seededProjectState)})`,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);

  const initialResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      projectNames: Array.from(document.querySelectorAll('.project-item[data-project-name]')).map((item) => item.getAttribute('data-project-name') || ''),
      visibleTitles: Array.from(document.querySelectorAll('.history-title')).map((item) => item.textContent.trim()),
      activeProject: document.querySelector('.project-item[data-active="true"]')?.getAttribute('data-project-name') || "",
      activeTitle: document.querySelector('.history-row[data-active="true"] .history-title')?.textContent.trim() || "",
    }))()`,
  });

  await send("Input.insertText", { text: "프로젝트 전환 후 비워져야 하는 초안" });
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-item[data-project-name="Beta Project"]')?.click()`,
  });
  await sleep(250);

  const switchResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      visibleTitles: Array.from(document.querySelectorAll('.history-title')).map((item) => item.textContent.trim()),
      activeProject: document.querySelector('.project-item[data-active="true"]')?.getAttribute('data-project-name') || "",
      activeTitle: document.querySelector('.history-row[data-active="true"] .history-title')?.textContent.trim() || "",
      selectedSessionId: JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}').selectedSessionId ?? null,
      hasPrompt: Boolean(document.querySelector('.prompt')),
      hasProjectOverview: Boolean(document.querySelector('.project-overview')),
      conversationText: document.querySelector('.conversation')?.textContent || "",
    }))()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-group[data-active="true"] .project-chat-create-button')?.click()`,
  });
  await sleep(250);

  const newChatResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const savedState = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const alpha = savedState.projects.find((project) => project.id === 'project-alpha');
      const beta = savedState.projects.find((project) => project.id === 'project-beta');

      return {
        alphaCount: alpha?.sessions.length ?? 0,
        betaCount: beta?.sessions.length ?? 0,
        betaHasNewChat: Boolean(beta?.sessions.some((session) => session.title === 'New Chat')),
        visibleTitles: Array.from(document.querySelectorAll('.history-title')).map((item) => item.textContent.trim()),
        activeProject: document.querySelector('.project-item[data-active="true"]')?.getAttribute('data-project-name') || "",
        activeTitle: document.querySelector('.history-row[data-active="true"] .history-title')?.textContent.trim() || "",
      };
    })()`,
  });

  const initialValue = initialResult.result.value;
  const switchValue = switchResult.result.value;
  const newChatValue = newChatResult.result.value;
  const failures = [];

  if (!initialValue.projectNames.some((name) => name.includes("Alpha Project")) ||
      !initialValue.projectNames.some((name) => name.includes("Beta Project"))) {
    failures.push("project list should render both saved projects");
  }

  if (initialValue.activeProject !== "Alpha Project") {
    failures.push("saved selected project should be active on load");
  }

  if (!initialValue.visibleTitles.includes("Alpha Kickoff") ||
      initialValue.visibleTitles.includes("Beta Risk Review")) {
    failures.push("project panel should show only the selected project's chats");
  }

  if (initialValue.activeTitle !== "Alpha Kickoff") {
    failures.push("saved selected chat should be active on load");
  }

  if (switchValue.activeProject !== "Beta Project") {
    failures.push("project switch should activate the clicked project");
  }

  if (switchValue.activeTitle !== "Beta Risk Review" ||
      switchValue.selectedSessionId !== "session-beta" ||
      !switchValue.hasPrompt ||
      switchValue.hasProjectOverview) {
    failures.push("project switch should enter the clicked project's active chat");
  }

  if (!switchValue.visibleTitles.includes("Beta Risk Review") ||
      switchValue.visibleTitles.includes("Alpha Kickoff")) {
    failures.push("project panel should replace visible chats after switching projects");
  }

  if (!switchValue.conversationText.includes("Beta 프로젝트 리스크 확인") ||
      switchValue.conversationText.includes("Alpha 프로젝트 일정 확인")) {
    failures.push("project switch should show only the clicked project's chat");
  }

  if (newChatValue.alphaCount !== 1 || newChatValue.betaCount !== 2 || !newChatValue.betaHasNewChat) {
    failures.push("new chat should be created inside the selected project only");
  }

  if (newChatValue.activeProject !== "Beta Project" ||
      newChatValue.activeTitle !== "New Chat" ||
      !newChatValue.visibleTitles.includes("New Chat")) {
    failures.push("new project-scoped chat should appear as the active chat in the project tree");
  }

  return { value: { initialValue, switchValue, newChatValue }, failures };
}

// 새 프로젝트가 생성 즉시 선택되고 빈 채팅 세션을 포함하는지 확인한다.
async function verifyProjectCreationFlow(send) {
  const seededSessions = [
    {
      id: "session-existing-project",
      title: "Existing Planning",
      createdAt: Date.now(),
      messages: [
        {
          id: "assistant-existing-project",
          role: "assistant",
          content: "저장된 응답입니다.",
        },
        {
          id: "user-existing-project",
          role: "user",
          content: "기존 프로젝트 계획",
        },
      ],
    },
  ];
  const seededProjectState = createProjectStorage(
    "project-existing",
    "Existing Project",
    seededSessions,
    "session-existing-project",
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  await send("Runtime.evaluate", {
    expression: `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(seededProjectState)})`,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);

  await send("Input.insertText", { text: "새 프로젝트 생성 후 남으면 안 되는 초안" });
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.sidebar-panel .project-create-trigger')?.click()`,
  });
  await sleep(250);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const savedState = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const activeProjectName = document.querySelector('.project-item[data-active="true"]')?.getAttribute('data-project-name') || "";
      const activeProject = savedState.projects.find((project) => project.id === savedState.selectedProjectId);
      const selectedSession = activeProject?.sessions.find(
        (session) => session.id === savedState.selectedSessionId,
      );

      return {
        projectCount: savedState.projects.length,
        activeProjectName,
        activeProjectStoredName: activeProject?.name || "",
        activeProjectSessionCount: activeProject?.sessions.length ?? 0,
        selectedSessionMessageCount: selectedSession?.messages.length ?? -1,
        selectedSessionId: savedState.selectedSessionId ?? null,
        selectedSessionTitle: selectedSession?.title || "",
        visibleTitles: Array.from(document.querySelectorAll('.history-title')).map((item) => item.textContent.trim()),
        promptValue: document.querySelector('.prompt textarea')?.value ?? "",
        hasPrompt: Boolean(document.querySelector('.prompt')),
        messageCount: document.querySelectorAll('.message').length,
        emptyTitle: document.querySelector('.chat-empty h1')?.textContent.trim() || "",
        hasProjectHome: Boolean(document.querySelector('.project-home')),
        uploadText: document.querySelector('.project-home-canvas-empty')?.textContent.trim() || "",
        analysisDisabled: Boolean(document.querySelector('.project-home-primary')?.disabled),
        hasProjectOverview: Boolean(document.querySelector('.project-overview')),
        hasProjectPanel: Boolean(document.querySelector('.project-panel')),
        hasOverviewPrompt: Boolean(document.querySelector('input[aria-label="프로젝트 질문 입력"]')),
        hasCreateTrigger: Boolean(document.querySelector('.sidebar-panel .project-create-trigger')),
        hasCreateMenu: Boolean(document.querySelector('.project-create-menu')),
      };
    })()`,
  });
  const value = result.result.value;

  const renameResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(async () => {
      const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const input = document.querySelector('.project-home-name input');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      const readStoredName = () => {
        const state = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
        return state.projects?.find((project) => project.id === state.selectedProjectId)?.name || '';
      };

      input.focus();
      setter.call(input, 'Discarded Name');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await wait(40);
      input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Escape' }));
      await wait(80);
      const escaped = { input: input.value, stored: readStoredName() };

      input.focus();
      setter.call(input, 'Renamed Project');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await wait(40);
      input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Enter' }));
      await wait(80);

      return {
        escaped,
        entered: {
          input: input.value,
          stored: readStoredName(),
          inputStillFocused: document.activeElement === input,
        },
      };
    })()`,
    awaitPromise: true,
  });
  value.rename = renameResult.result.value;
  const failures = [];

  if (!value.hasCreateTrigger) {
    failures.push("sidebar should expose a New Project trigger");
  }

  if (value.projectCount !== 2) {
    failures.push(`creating a project should add one project: ${value.projectCount}`);
  }

  if (value.activeProjectName !== "New Project 1" || value.activeProjectStoredName !== "New Project 1") {
    failures.push("newly created project should become the active project");
  }

  if (value.activeProjectSessionCount !== 0 ||
      value.selectedSessionMessageCount !== -1 ||
      value.selectedSessionId !== null ||
      value.selectedSessionTitle !== "") {
    failures.push("new project should be created without an automatic starter chat");
  }

  if (value.messageCount !== 0 ||
      value.emptyTitle !== "" ||
      !value.hasProjectHome ||
      !value.uploadText.includes("자료를 여기에 끌어다 놓으세요") ||
      !value.analysisDisabled) {
    failures.push("new project should show the project home upload step");
  }

  if (value.hasCreateMenu) {
    failures.push("project create menu should close after creating a project");
  }

  if (value.visibleTitles.includes("New Chat")) {
    failures.push("project tree should not add a starter chat before chat starts");
  }

  if (value.hasPrompt ||
      value.hasProjectOverview ||
      value.hasProjectPanel ||
      value.hasOverviewPrompt) {
    failures.push("new project should enter project home without chat or right panel");
  }

  if (value.promptValue !== "") {
    failures.push("draft text should clear when creating a project");
  }

  if (value.rename.escaped.input !== "New Project 1" ||
      value.rename.escaped.stored !== "New Project 1" ||
      value.rename.entered.input !== "Renamed Project" ||
      value.rename.entered.stored !== "Renamed Project" ||
      value.rename.entered.inputStillFocused) {
    failures.push("project home name editing should cancel with Escape and commit with Enter");
  }

  return { value, failures };
}

// 프로젝트 홈 native drop은 로컬 행만 남기지 않고 PDF를 서버 문서로 확정해야 한다.
async function verifyProjectHomeDroppedPdfUpload(send) {
  const seededProjectState = createProjectStorage(
    "project-drop-upload",
    "Drop Upload Project",
    [],
    null,
    [],
  );
  const tauriMockScript = await installPaimTauriMock(send);
  const value = {};
  const failures = [];

  try {
    await send("Emulation.setDeviceMetricsOverride", {
      width: 960,
      height: 680,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await evaluateAndNavigateToSelector(
      send,
      `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}, '272'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}, '360'); localStorage.removeItem(${JSON.stringify(PROJECT_COLLAPSED_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(seededProjectState)})`,
      APP_URL,
      ".project-home",
    );

    const readyResult = await send("Runtime.evaluate", {
      awaitPromise: true,
      returnByValue: true,
      expression: `(async () => {
        const timeoutAt = Date.now() + 5000;
        while (Date.now() < timeoutAt) {
          const listenerCount =
            window.__paimLayoutReadTauriMock?.().dragDropListeners ?? 0;
          if (listenerCount > 0) {
            window.__paimLayoutConfigureDocument?.({ delayMs: 150 });
            return { listenerCount, ready: true };
          }
          await new Promise((resolve) => setTimeout(resolve, 25));
        }
        return {
          listenerCount: window.__paimLayoutReadTauriMock?.().dragDropListeners ?? 0,
          ready: false,
        };
      })()`,
    });
    value.nativeReady = readyResult.result.value;

    const dropResult = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => {
        const canvas = document.querySelector('.project-home-canvas');
        if (!canvas) {
          return { emittedListeners: 0, foundCanvas: false };
        }
        const rect = canvas.getBoundingClientRect();
        const scale = window.devicePixelRatio || 1;
        const position = {
          x: (rect.left + rect.width / 2) * scale,
          y: (rect.top + rect.height / 2) * scale,
        };
        return {
          emittedListeners: window.__paimLayoutEmitTauriEvent?.(
            'tauri://drag-drop',
            { paths: ['/mock/drop.pdf'], position },
          ) ?? 0,
          foundCanvas: true,
        };
      })()`,
    });
    value.drop = dropResult.result.value;

    const uploadResult = await send("Runtime.evaluate", {
      awaitPromise: true,
      returnByValue: true,
      expression: `(async () => {
        const timeoutAt = Date.now() + 6000;
        while (Date.now() < timeoutAt) {
          const control = window.__paimLayoutReadDocumentControl?.();
          const row = document.querySelector('.project-home-source-row');
          if (
            control?.resolved >= 1 &&
            (row?.getAttribute('data-status') === 'indexed' || control.deleted > 0)
          ) {
            break;
          }
          await new Promise((resolve) => setTimeout(resolve, 25));
        }
        await new Promise((resolve) => setTimeout(resolve, 250));

        const savedState = JSON.parse(
          localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}',
        );
        const activeProject = savedState.projects?.find(
          (project) => project.id === savedState.selectedProjectId,
        );
        const storedFile = activeProject?.files?.find(
          (file) => file.name === 'drop.pdf',
        );
        const apiCalls = window.__paimLayoutApiCalls || [];
        const summary = Object.fromEntries(
          Array.from(document.querySelectorAll('.project-home-summary-item')).map(
            (item) => [item.getAttribute('data-kind'), item.textContent.trim()],
          ),
        );
        const row = document.querySelector('.project-home-source-row');

        return {
          apiProjectId: activeProject?.apiProjectId ?? null,
          deleteCalls: apiCalls.filter(
            (call) => /^DELETE \\/api\\/v1\\/projects\\/\\d+\\/documents\\/\\d+$/.test(call),
          ),
          documentControl: window.__paimLayoutReadDocumentControl?.() ?? null,
          documentPostCalls: apiCalls.filter(
            (call) => /^POST \\/api\\/v1\\/projects\\/\\d+\\/documents$/.test(call),
          ),
          projectPostCalls: apiCalls.filter(
            (call) => call === 'POST /api/v1/projects',
          ),
          rowName: row?.querySelector('.project-home-source-name')?.textContent.trim() || '',
          rowStatus: row?.getAttribute('data-status') || '',
          rowStatusText:
            row?.querySelector('.project-home-source-status')?.textContent.trim() || '',
          storedFile: storedFile
            ? {
                docId: storedFile.docId ?? null,
                documentStatus: storedFile.documentStatus ?? null,
                name: storedFile.name,
              }
            : null,
          summary,
        };
      })()`,
    });
    value.upload = uploadResult.result.value;

    if (!value.nativeReady.ready ||
        value.nativeReady.listenerCount !== 1 ||
        !value.drop.foundCanvas ||
        value.drop.emittedListeners !== 1) {
      failures.push("project home should register exactly one native file-drop listener");
    }

    if (value.upload.projectPostCalls.length !== 1 ||
        value.upload.documentPostCalls.length !== 1 ||
        value.upload.apiProjectId !== 1000) {
      failures.push("dropping a PDF should create its server project and upload one document");
    }

    const lastFile = value.upload.documentControl?.lastFile;
    if (value.upload.documentControl?.requested !== 1 ||
        value.upload.documentControl?.resolved !== 1 ||
        !lastFile ||
        lastFile.name !== "drop.pdf" ||
        lastFile.type !== "application/pdf" ||
        lastFile.size <= 0) {
      failures.push("native PDF drop should send one non-empty application/pdf multipart file");
    }

    if (value.upload.documentControl?.deleted !== 0 ||
        value.upload.deleteCalls.length !== 0) {
      failures.push("a completed native PDF drop must not issue a compensating document DELETE");
    }

    if (value.upload.storedFile?.name !== "drop.pdf" ||
        value.upload.storedFile?.docId !== 7000 ||
        value.upload.storedFile?.documentStatus !== "indexed" ||
        value.upload.rowName !== "drop.pdf" ||
        value.upload.rowStatus !== "indexed" ||
        value.upload.rowStatusText !== "완료") {
      failures.push("a dropped PDF should remain linked to its indexed server document");
    }

    if (value.upload.summary.ready !== "1개 완료" ||
        value.upload.summary.processing !== "0개 처리 중" ||
        value.upload.summary.failed !== "0개 실패") {
      failures.push("project home should count the dropped PDF as one completed document");
    }
  } finally {
    await send("Page.removeScriptToEvaluateOnNewDocument", {
      identifier: tauriMockScript.identifier,
    });
    await navigateAndWaitForSelector(send, APP_URL, ".app-shell");
    const cleanupResult = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => ({
        hasTauriInternals: '__TAURI_INTERNALS__' in window,
        hasTauriMock: Boolean(window.__paimLayoutTauriMockInstalled),
        pageZoomMode: document.documentElement.dataset.pageZoomMode || '',
      }))()`,
    });
    value.cleanup = cleanupResult.result.value;
  }

  if (value.cleanup.hasTauriInternals ||
      value.cleanup.hasTauriMock ||
      value.cleanup.pageZoomMode !== "css") {
    failures.push("the native drop preload should be removed before later browser-mode scenarios");
  }

  debugLayout("project home dropped PDF upload", value);
  return { value, failures };
}

// 사용자가 전송 중인 PDF를 명시적으로 지우면 늦게 생성된 서버 문서도 한 번만 정리한다.
async function verifyProjectHomeDroppedPdfCancellation(send) {
  const seededProjectState = createProjectStorage(
    "project-drop-cancel",
    "Drop Cancel Project",
    [],
    null,
    [],
  );
  const tauriMockScript = await installPaimTauriMock(send);
  const value = {};
  const failures = [];

  try {
    await send("Emulation.setDeviceMetricsOverride", {
      width: 960,
      height: 680,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await evaluateAndNavigateToSelector(
      send,
      `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}, '272'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}, '360'); localStorage.removeItem(${JSON.stringify(PROJECT_COLLAPSED_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(seededProjectState)})`,
      APP_URL,
      ".project-home",
    );

    const readyResult = await send("Runtime.evaluate", {
      awaitPromise: true,
      returnByValue: true,
      expression: `(async () => {
        const timeoutAt = Date.now() + 5000;
        while (Date.now() < timeoutAt) {
          const listenerCount =
            window.__paimLayoutReadTauriMock?.().dragDropListeners ?? 0;
          if (listenerCount > 0) {
            window.__paimLayoutConfigureDocument?.({ delayMs: 2000 });
            return { listenerCount, ready: true };
          }
          await new Promise((resolve) => setTimeout(resolve, 25));
        }
        return {
          listenerCount: window.__paimLayoutReadTauriMock?.().dragDropListeners ?? 0,
          ready: false,
        };
      })()`,
    });
    value.nativeReady = readyResult.result.value;

    const dropResult = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => {
        const canvas = document.querySelector('.project-home-canvas');
        if (!canvas) {
          return { emittedListeners: 0, foundCanvas: false };
        }
        const rect = canvas.getBoundingClientRect();
        const scale = window.devicePixelRatio || 1;
        const position = {
          x: (rect.left + rect.width / 2) * scale,
          y: (rect.top + rect.height / 2) * scale,
        };
        return {
          emittedListeners: window.__paimLayoutEmitTauriEvent?.(
            'tauri://drag-drop',
            { paths: ['/mock/cancel-drop.pdf'], position },
          ) ?? 0,
          foundCanvas: true,
        };
      })()`,
    });
    value.drop = dropResult.result.value;

    const startedResult = await send("Runtime.evaluate", {
      awaitPromise: true,
      returnByValue: true,
      expression: `(async () => {
        const timeoutAt = Date.now() + 5000;
        while (Date.now() < timeoutAt) {
          const control = window.__paimLayoutReadDocumentControl?.();
          const row = document.querySelector('.project-home-source-row');
          if (
            control?.requested === 1 &&
            control.resolved === 0 &&
            row?.getAttribute('data-status') === 'uploading'
          ) {
            break;
          }
          await new Promise((resolve) => setTimeout(resolve, 25));
        }
        const row = document.querySelector('.project-home-source-row');
        return {
          control: window.__paimLayoutReadDocumentControl?.() ?? null,
          deleteButton: Boolean(row?.querySelector('.project-home-source-delete')),
          rowName: row?.querySelector('.project-home-source-name')?.textContent.trim() || '',
          rowStatus: row?.getAttribute('data-status') || '',
        };
      })()`,
    });
    value.started = startedResult.result.value;

    await send("Runtime.evaluate", {
      expression: `document.querySelector('.project-home-source-delete')?.click()`,
    });
    const armedResult = await send("Runtime.evaluate", {
      awaitPromise: true,
      returnByValue: true,
      expression: `(async () => {
        const timeoutAt = Date.now() + 1000;
        while (Date.now() < timeoutAt) {
          const row = document.querySelector('.project-home-source-row');
          if (row?.getAttribute('data-delete') === 'confirm') {
            return {
              armed: true,
              control: window.__paimLayoutReadDocumentControl?.() ?? null,
            };
          }
          await new Promise((resolve) => setTimeout(resolve, 20));
        }
        return {
          armed: false,
          control: window.__paimLayoutReadDocumentControl?.() ?? null,
        };
      })()`,
    });
    value.armed = armedResult.result.value;

    await send("Runtime.evaluate", {
      expression: `document.querySelector('.project-home-source-delete')?.click()`,
    });
    const localCancelResult = await send("Runtime.evaluate", {
      awaitPromise: true,
      returnByValue: true,
      expression: `(async () => {
        const timeoutAt = Date.now() + 750;
        while (
          Date.now() < timeoutAt &&
          document.querySelector('.project-home-source-row')
        ) {
          await new Promise((resolve) => setTimeout(resolve, 20));
        }
        await new Promise((resolve) => setTimeout(resolve, 50));
        const savedState = JSON.parse(
          localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}',
        );
        const activeProject = savedState.projects?.find(
          (project) => project.id === savedState.selectedProjectId,
        );
        return {
          control: window.__paimLayoutReadDocumentControl?.() ?? null,
          rowGone: !document.querySelector('.project-home-source-row'),
          storedFileCount: activeProject?.files?.length ?? -1,
        };
      })()`,
    });
    value.localCancel = localCancelResult.result.value;

    const settledResult = await send("Runtime.evaluate", {
      awaitPromise: true,
      returnByValue: true,
      expression: `(async () => {
        const timeoutAt = Date.now() + 6000;
        while (Date.now() < timeoutAt) {
          const control = window.__paimLayoutReadDocumentControl?.();
          if (
            control?.resolved === 1 &&
            control.deleted === 1 &&
            control.serverDocumentCount === 0
          ) {
            break;
          }
          await new Promise((resolve) => setTimeout(resolve, 25));
        }
        await new Promise((resolve) => setTimeout(resolve, 250));

        const savedState = JSON.parse(
          localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}',
        );
        const activeProject = savedState.projects?.find(
          (project) => project.id === savedState.selectedProjectId,
        );
        const apiCalls = window.__paimLayoutApiCalls || [];

        return {
          apiProjectId: activeProject?.apiProjectId ?? null,
          canvasState:
            document.querySelector('.project-home-canvas')?.getAttribute('data-state') || '',
          deleteCalls: apiCalls.filter(
            (call) => /^DELETE \\/api\\/v1\\/projects\\/\\d+\\/documents\\/\\d+$/.test(call),
          ),
          documentControl: window.__paimLayoutReadDocumentControl?.() ?? null,
          documentPostCalls: apiCalls.filter(
            (call) => /^POST \\/api\\/v1\\/projects\\/\\d+\\/documents$/.test(call),
          ),
          emptyText:
            document.querySelector('.project-home-canvas-empty')?.textContent.trim() || '',
          projectPostCalls: apiCalls.filter(
            (call) => call === 'POST /api/v1/projects',
          ),
          runtimeStatus: document.querySelector('.runtime-status')?.textContent.trim() || '',
          sourceRowCount: document.querySelectorAll('.project-home-source-row').length,
          storedFileCount: activeProject?.files?.length ?? -1,
        };
      })()`,
    });
    value.settled = settledResult.result.value;

    if (!value.nativeReady.ready ||
        value.nativeReady.listenerCount !== 1 ||
        !value.drop.foundCanvas ||
        value.drop.emittedListeners !== 1) {
      failures.push("cancel test should register and invoke exactly one native file-drop listener");
    }

    if (value.started.control?.requested !== 1 ||
        value.started.control?.resolved !== 0 ||
        value.started.rowName !== "cancel-drop.pdf" ||
        value.started.rowStatus !== "uploading" ||
        !value.started.deleteButton) {
      failures.push("the PDF upload should be in flight before explicit deletion");
    }

    if (!value.armed.armed ||
        value.armed.control?.resolved !== 0) {
      failures.push("the first source delete click should arm confirmation before upload response");
    }

    if (!value.localCancel.rowGone ||
        value.localCancel.storedFileCount !== 0 ||
        value.localCancel.control?.resolved !== 0 ||
        value.localCancel.control?.deleted !== 0) {
      failures.push("the confirmed delete should remove the local row and abort before the POST resolves");
    }

    const lastFile = value.settled.documentControl?.lastFile;
    if (value.settled.projectPostCalls.length !== 1 ||
        value.settled.documentPostCalls.length !== 1 ||
        value.settled.apiProjectId !== 1000 ||
        value.settled.documentControl?.requested !== 1 ||
        value.settled.documentControl?.resolved !== 1 ||
        !lastFile ||
        lastFile.name !== "cancel-drop.pdf" ||
        lastFile.type !== "application/pdf" ||
        lastFile.size <= 0) {
      failures.push("the cancelled native drop should still receive exactly one delayed PDF POST response");
    }

    if (value.settled.documentControl?.deleted !== 1 ||
        value.settled.documentControl?.serverDocumentCount !== 0 ||
        value.settled.deleteCalls.length !== 1 ||
        value.settled.deleteCalls[0] !==
          "DELETE /api/v1/projects/1000/documents/7000") {
      failures.push("the delayed cancelled upload should issue exactly one compensating document DELETE");
    }

    if (value.settled.storedFileCount !== 0 ||
        value.settled.sourceRowCount !== 0 ||
        value.settled.canvasState !== "empty" ||
        !value.settled.emptyText.includes("자료를 여기에 끌어다 놓으세요")) {
      failures.push("the cancelled PDF should stay removed from project home and local storage");
    }

    if (!value.settled.runtimeStatus.includes("0개 완료") ||
        !value.settled.runtimeStatus.includes("0개 실패") ||
        !value.settled.runtimeStatus.includes("1개 취소")) {
      failures.push("the upload result should report one explicit cancellation");
    }
  } finally {
    await send("Page.removeScriptToEvaluateOnNewDocument", {
      identifier: tauriMockScript.identifier,
    });
    await navigateAndWaitForSelector(send, APP_URL, ".app-shell");
    const cleanupResult = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => ({
        hasTauriInternals: '__TAURI_INTERNALS__' in window,
        hasTauriMock: Boolean(window.__paimLayoutTauriMockInstalled),
        pageZoomMode: document.documentElement.dataset.pageZoomMode || '',
      }))()`,
    });
    value.cleanup = cleanupResult.result.value;
  }

  if (value.cleanup.hasTauriInternals ||
      value.cleanup.hasTauriMock ||
      value.cleanup.pageZoomMode !== "css") {
    failures.push("the cancellation test preload should be removed before later browser scenarios");
  }

  debugLayout("project home dropped PDF cancellation", value);
  return { value, failures };
}

// 분석 시작은 숨겨진 사용자 프롬프트를 만들지 않고 브리핑 응답만 채팅에 연결해야 한다.
async function verifyProjectBriefingStartsWithoutVisiblePrompt(send) {
  const seededProjectState = createProjectStorage(
    "project-briefing",
    "Briefing Project",
    [],
    null,
    [],
    { description: "분석 시작 테스트용 프로젝트 설명" },
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  await send("Runtime.evaluate", {
    expression: `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(seededProjectState)})`,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-home-primary')?.click()`,
  });
  await sleep(1300);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const savedState = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const activeProject = savedState.projects?.find((project) => project.id === savedState.selectedProjectId);
      const selectedSession = activeProject?.sessions.find(
        (session) => session.id === savedState.selectedSessionId,
      );
      const storedMessages = selectedSession?.messages ?? [];

      return {
        selectedSessionTitle: selectedSession?.title || "",
        storedMessageCount: storedMessages.length,
        storedRoles: storedMessages.map((message) => message.role),
        storedText: storedMessages.map((message) => message.content).join("\\n"),
        visibleUserMessages: document.querySelectorAll('.message[data-role="user"]').length,
        visibleAssistantMessages: document.querySelectorAll('.message[data-role="assistant"]').length,
        hasBriefingCard: Boolean(document.querySelector('.message[data-briefing="true"]')),
        hasContextBar: Boolean(document.querySelector('.chat-context-bar')),
        hasProjectHome: Boolean(document.querySelector('.project-home')),
        hasPrompt: Boolean(document.querySelector('.prompt')),
        thinkingVisible: Boolean(document.querySelector('.thinking')),
        apiCalls: window.__paimLayoutApiCalls || [],
      };
    })()`,
  });
  const value = result.result.value;
  const failures = [];

  if (value.selectedSessionTitle !== "Project Briefing" ||
      value.storedMessageCount !== 1 ||
      value.storedRoles[0] !== "assistant" ||
      !value.storedText.includes("프로젝트 설명: 분석 시작 테스트용 프로젝트 설명")) {
    failures.push("project briefing should store only the assistant briefing response");
  }

  if (value.visibleUserMessages !== 0 ||
      value.visibleAssistantMessages !== 1 ||
      !value.hasBriefingCard ||
      !value.hasContextBar ||
      value.hasProjectHome ||
      !value.hasPrompt) {
    failures.push("project briefing should enter chat without rendering the generated user prompt");
  }

  debugLayout("project briefing", value);
  return { value, failures };
}

// ... 메뉴에서 프로젝트명과 채팅명을 변경할 수 있는지 확인한다.
async function verifyActionMenuRenameFlow(send) {
  const seededProjectState = createProjectStorage(
    "project-rename",
    "Rename Project",
    [
      {
        id: "session-rename",
        title: "Rename Chat",
        createdAt: Date.now(),
        messages: [
          {
            id: "assistant-rename",
            role: "assistant",
            content: "저장된 응답입니다.",
          },
        ],
      },
    ],
    "session-rename",
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  await send("Runtime.evaluate", {
    expression: `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(seededProjectState)})`,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-group[data-active="true"] .project-action-menu-button')?.click()`,
  });
  await sleep(80);
  await send("Runtime.evaluate", {
    expression: `window.__projectActionMenuBox = (() => {
      const menu = document.querySelector('.item-action-menu');
      const shell = document.querySelector('.app-shell');
      if (!menu || !shell) return null;
      const menuRect = menu.getBoundingClientRect();
      const shellRect = shell.getBoundingClientRect();
      return {
        left: menuRect.left,
        right: menuRect.right,
        top: menuRect.top,
        bottom: menuRect.bottom,
        shellLeft: shellRect.left,
        shellRight: shellRect.right,
        shellTop: shellRect.top,
        shellBottom: shellRect.bottom,
      };
    })()`,
  });
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.item-action-menu [data-action="rename-project"]')?.click()`,
  });
  await sleep(100);
  await send("Runtime.evaluate", {
    expression: `(() => {
      const input = document.querySelector('.project-rename-editor input');
      input?.focus();
      input?.select();
    })()`,
  });
  await send("Input.insertText", { text: "Renamed Project" });
  await sleep(80);
  await send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });
  await send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });
  await sleep(160);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.history-row[data-active="true"]')?.dispatchEvent(
      new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 210, clientY: 245 })
    )`,
  });
  await sleep(80);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.item-action-menu [data-action="rename-session"]')?.click()`,
  });
  await sleep(100);
  await send("Runtime.evaluate", {
    expression: `(() => {
      const input = document.querySelector('.history-rename-editor .rename-input');
      input?.focus();
      input?.select();
    })()`,
  });
  await send("Input.insertText", { text: "Renamed Chat" });
  await sleep(80);
  await send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });
  await send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });
  await sleep(160);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const savedState = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const project = savedState.projects.find((item) => item.id === 'project-rename');
      const session = project?.sessions.find((item) => item.id === 'session-rename');
      return {
        storedProjectName: project?.name || "",
        storedSessionTitle: session?.title || "",
        visibleProjectName: document.querySelector('.project-item[data-active="true"]')?.getAttribute('data-project-name') || "",
        visibleSessionTitle: document.querySelector('.history-title')?.textContent.trim() || "",
        menuOpen: Boolean(document.querySelector('.item-action-menu')),
        projectMenuBox: window.__projectActionMenuBox,
      };
    })()`,
  });
  const value = result.result.value;
  const failures = [];

  if (value.storedProjectName !== "Renamed Project" ||
      value.visibleProjectName !== "Renamed Project") {
    failures.push("project action menu should rename the project");
  }

  if (value.storedSessionTitle !== "Renamed Chat" ||
      value.visibleSessionTitle !== "Renamed Chat") {
    failures.push("session action menu should rename the chat");
  }

  if (value.menuOpen) {
    failures.push("action menu should close after rename");
  }

  if (!value.projectMenuBox ||
      value.projectMenuBox.left < value.projectMenuBox.shellLeft ||
      value.projectMenuBox.right > value.projectMenuBox.shellRight ||
      value.projectMenuBox.top < value.projectMenuBox.shellTop ||
      value.projectMenuBox.bottom > value.projectMenuBox.shellBottom) {
    failures.push("project action menu should render inside the app shell bounds");
  }

  return { value, failures };
}

// 프로젝트 삭제 후 마지막 프로젝트까지 제거 가능한지 확인한다.
async function verifyProjectDeleteFlow(send) {
  const alphaSessions = [
    {
      id: "session-delete-project-alpha",
      title: "Alpha Delete Scope",
      createdAt: Date.now(),
      messages: [
        {
          id: "assistant-delete-project-alpha",
          role: "assistant",
          content: "저장된 응답입니다.",
        },
      ],
    },
  ];
  const betaSessions = [
    {
      id: "session-delete-project-beta",
      title: "Beta Delete Scope",
      createdAt: Date.now() - 1,
      messages: [
        {
          id: "assistant-delete-project-beta",
          role: "assistant",
          content: "저장된 응답입니다.",
        },
      ],
    },
  ];
  const seededProjectState = createProjectStorageState(
    [
      {
        id: "project-delete-alpha",
        name: "Delete Alpha",
        createdAt: Date.now(),
        sessions: alphaSessions,
      },
      {
        id: "project-delete-beta",
        name: "Delete Beta",
        createdAt: Date.now() - 1,
        sessions: betaSessions,
      },
    ],
    "project-delete-beta",
    "session-delete-project-beta",
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  await send("Runtime.evaluate", {
    expression: `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(seededProjectState)})`,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);

  await send("Input.insertText", { text: "프로젝트 삭제 후 남으면 안 되는 초안" });
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-group[data-active="true"] .project-action-menu-button')?.click()`,
  });
  await sleep(80);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.item-action-menu [data-action="delete-project"]')?.click()`,
  });
  await sleep(120);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.item-action-menu [data-action="delete-project"]')?.click()`,
  });
  await sleep(250);
  const afterActiveDeleteResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const savedState = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      return {
        projectNames: savedState.projects.map((project) => project.name),
        selectedProjectId: savedState.selectedProjectId,
        selectedSessionId: savedState.selectedSessionId,
        activeProjectName: document.querySelector('.project-item[data-active="true"]')?.getAttribute('data-project-name') || "",
        activeTitle: document.querySelector('.history-row[data-active="true"] .history-title')?.textContent.trim() || "",
        visibleTitles: Array.from(document.querySelectorAll('.history-title')).map((item) => item.textContent.trim()),
        promptValue: document.querySelector('.prompt textarea')?.value ?? "",
        hasProjectOverview: Boolean(document.querySelector('.project-overview')),
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-group[data-active="true"] .project-action-menu-button')?.click()`,
  });
  await sleep(80);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.item-action-menu [data-action="delete-project"]')?.click()`,
  });
  await sleep(120);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.item-action-menu [data-action="delete-project"]')?.click()`,
  });
  await sleep(250);
  const readEmptyProjectStateExpression = `(() => {
    const savedState = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
    const projects = savedState.projects || [];
    const textarea = document.querySelector('.prompt textarea');
    return {
      projectCount: projects.length,
      selectedProjectId: savedState.selectedProjectId ?? null,
      selectedSessionId: savedState.selectedSessionId ?? null,
      visibleProjectNames: Array.from(document.querySelectorAll('.project-name')).map((item) => item.textContent.trim()),
      visibleTitles: Array.from(document.querySelectorAll('.history-title')).map((item) => item.textContent.trim()),
      hasPrompt: Boolean(textarea),
      hasMessage: Boolean(document.querySelector('.message')),
      hasProjectStart: Boolean(document.querySelector('.project-start')),
      startButtonText: document.querySelector('.project-start-button')?.textContent.trim() || "",
      projectCreateCount: document.querySelectorAll('.project-create-trigger').length,
      sidebarCollapsed: document.querySelector('.app-shell')?.getAttribute('data-sidebar-collapsed') || "",
      sidebarWidth: document.querySelector('.sidebar')?.getBoundingClientRect().width ?? 0,
      sidebarPanelDisplay: getComputedStyle(document.querySelector('.sidebar-panel')).display,
      sidebarBorderRightWidth: Number.parseFloat(
        getComputedStyle(document.querySelector('.sidebar')).borderRightWidth,
      ),
      hasSidebarCollapseButton: Boolean(document.querySelector('.sidebar-collapse-button')),
      hasSidebarAccountButton: Boolean(document.querySelector('.sidebar-account-button')),
      hasLegacySidebarSettingsButton: Boolean(document.querySelector('.sidebar-settings-button')),
    };
  })()`;
  const afterLastDeleteResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: readEmptyProjectStateExpression,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  const afterReloadResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: readEmptyProjectStateExpression,
  });
  await send("Runtime.evaluate", {
    expression: `localStorage.removeItem(${JSON.stringify(PROJECT_STORAGE_KEY)}); localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)})`,
  });
  const value = {
    afterActiveDelete: afterActiveDeleteResult.result.value,
    afterLastDelete: afterLastDeleteResult.result.value,
    afterReload: afterReloadResult.result.value,
  };
  const failures = [];

  if (value.afterActiveDelete.projectNames.includes("Delete Beta")) {
    failures.push("deleted active project should be removed from storage");
  }

  if (value.afterActiveDelete.selectedProjectId !== "project-delete-alpha" ||
      value.afterActiveDelete.selectedSessionId !== "session-delete-project-alpha") {
    failures.push("selection should move to the remaining project's active chat after deleting the active project");
  }

  if (value.afterActiveDelete.activeProjectName !== "Delete Alpha" ||
      value.afterActiveDelete.activeTitle !== "Alpha Delete Scope" ||
      value.afterActiveDelete.hasProjectOverview) {
    failures.push("remaining project should become active and show chat");
  }

  if (value.afterActiveDelete.visibleTitles.includes("Beta Delete Scope")) {
    failures.push("deleted project's chats should disappear from the tree");
  }

  if (value.afterActiveDelete.promptValue !== "") {
    failures.push("draft text should clear after deleting the active project");
  }

  if (value.afterLastDelete.projectCount !== 0 ||
      value.afterLastDelete.selectedProjectId !== null ||
      value.afterLastDelete.selectedSessionId !== null) {
    failures.push("deleting the last project should leave no selected project");
  }

  if (value.afterLastDelete.visibleProjectNames.length !== 0 ||
      value.afterLastDelete.visibleTitles.length !== 0) {
    failures.push("deleted last project should disappear from the sidebar tree");
  }

  if (value.afterLastDelete.hasPrompt ||
      value.afterLastDelete.hasMessage ||
      !value.afterLastDelete.hasProjectStart ||
      !value.afterLastDelete.startButtonText.includes("새 프로젝트 시작하기") ||
      value.afterLastDelete.projectCreateCount !== 0 ||
      value.afterLastDelete.sidebarCollapsed !== "true" ||
      Math.abs(value.afterLastDelete.sidebarWidth - 52) > 1 ||
      value.afterLastDelete.sidebarPanelDisplay !== "none" ||
      value.afterLastDelete.sidebarBorderRightWidth !== 0 ||
      value.afterLastDelete.hasSidebarCollapseButton ||
      !value.afterLastDelete.hasSidebarAccountButton ||
      value.afterLastDelete.hasLegacySidebarSettingsButton) {
    failures.push("empty project state should hide chat input and render the start screen");
  }

  if (value.afterReload.projectCount !== 0 ||
      value.afterReload.selectedProjectId !== null ||
      value.afterReload.selectedSessionId !== null ||
      value.afterReload.projectCreateCount !== 0 ||
      value.afterReload.sidebarCollapsed !== "true" ||
      Math.abs(value.afterReload.sidebarWidth - 52) > 1 ||
      value.afterReload.sidebarPanelDisplay !== "none" ||
      value.afterReload.sidebarBorderRightWidth !== 0 ||
      value.afterReload.hasSidebarCollapseButton ||
      !value.afterReload.hasSidebarAccountButton ||
      value.afterReload.hasLegacySidebarSettingsButton) {
    failures.push("empty project state should persist after reload");
  }

  return { value, failures };
}

// 전송 전 첨부가 많아져도 프롬프트와 액션 버튼이 화면 안에 남는지 확인한다.
async function verifyDraftAttachmentTrayLayout(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithProject(send);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const prompt = document.querySelector('.prompt');
      const actions = document.querySelector('.prompt-actions');
      const sampleImage =
        'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';

      if (!prompt || !actions) {
        return { hasPrompt: false };
      }

      const draft = document.createElement('div');
      draft.className = 'draft-attachments';
      draft.innerHTML = '<div class="attachment-list" aria-label="전송할 첨부 파일">' +
        Array.from({ length: 12 }, (_, index) =>
          '<div class="attachment-preview">' +
            '<img src="' + sampleImage + '" alt="첨부 미리보기" />' +
            '<span>very-long-project-attachment-preview-name-' + index + '.png</span>' +
            '<button class="remove-attachment-button" type="button" aria-label="첨부 제거">x</button>' +
          '</div>'
        ).join('') +
        '</div>';

      prompt.insertBefore(draft, actions);

      const box = (element) => {
        const rect = element.getBoundingClientRect();
        return {
          top: rect.top,
          right: rect.right,
          bottom: rect.bottom,
          left: rect.left,
          width: rect.width,
          height: rect.height,
        };
      };
      const promptBox = box(prompt);
      const draftBox = box(draft);
      const actionsBox = box(actions);
      const overflowingPreviews = Array.from(draft.querySelectorAll('.attachment-preview'))
        .filter((preview) => {
          const previewBox = preview.getBoundingClientRect();
          return previewBox.left < draftBox.left - 0.5 || previewBox.right > draftBox.right + 0.5;
        })
        .length;

      return {
        hasPrompt: true,
        scrollWidth: document.documentElement.scrollWidth,
        prompt: promptBox,
        draft: draftBox,
        actions: actionsBox,
        draftClientHeight: draft.clientHeight,
        draftScrollHeight: draft.scrollHeight,
        overflowingPreviews,
      };
    })()`,
  });
  const value = result.result.value;
  const failures = [];

  if (!value.hasPrompt) {
    failures.push("prompt should render before draft attachment layout check");
    return { value, failures };
  }

  if (value.scrollWidth > 960) {
    failures.push(`document horizontal overflow with draft attachments: ${value.scrollWidth} > 960`);
  }

  if (value.prompt.top < 0 || value.prompt.bottom > 680) {
    failures.push(
      `prompt should remain inside viewport with draft attachments: ${value.prompt.top}-${value.prompt.bottom}`,
    );
  }

  if (value.draftClientHeight > 124) {
    failures.push(`draft attachment tray should stay compact: ${value.draftClientHeight} > 124`);
  }

  if (value.draftScrollHeight <= value.draftClientHeight) {
    failures.push("draft attachment tray should scroll internally when previews overflow");
  }

  if (value.actions.left < value.prompt.left - 0.5 || value.actions.right > value.prompt.right + 0.5) {
    failures.push("prompt actions should remain inside prompt with draft attachments");
  }

  if (value.overflowingPreviews > 0) {
    failures.push("draft attachment previews should not overflow the tray horizontally");
  }

  return { value, failures };
}

// 지연된 응답도 즉시 사용자 입력을 반영하고, 다른 프로젝트에서 취소할 수 있어야 한다.
async function verifyInterruptibleBackgroundQuery(send) {
  const now = Date.now();
  const delayedQueryState = createProjectStorageState(
    [
      {
        apiProjectId: 1,
        createdAt: now,
        files: [],
        id: "project-query-alpha",
        name: "Query Alpha",
        sessions: [
          {
            createdAt: now,
            id: "session-query-alpha",
            messages: [],
            title: "Alpha Chat",
          },
        ],
      },
      {
        apiProjectId: 2,
        createdAt: now + 1,
        files: [],
        id: "project-query-beta",
        name: "Query Beta",
        sessions: [
          {
            createdAt: now + 1,
            id: "session-query-beta",
            messages: [],
            title: "Beta Chat",
          },
        ],
      },
    ],
    "project-query-alpha",
    "session-query-alpha",
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 820,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await navigateAndWaitForSelector(send, APP_URL, ".app-shell");
  await evaluateAndNavigateToSelector(
    send,
    `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}, '272'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}, '360'); localStorage.removeItem(${JSON.stringify(PROJECT_COLLAPSED_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(delayedQueryState)})`,
    APP_URL,
    ".prompt textarea:not(:disabled)",
  );
  await send("Runtime.evaluate", {
    expression: `window.__paimLayoutConfigureQuery({ delayMs: 900 })`,
  });
  await send("Runtime.evaluate", {
    expression: `(() => {
      const input = document.querySelector('.prompt textarea');
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(input, '중단 가능한 지연 응답');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    })()`,
  });
  await sleep(60);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('button[aria-label="메시지 보내기"]')?.click()`,
  });
  await waitForSelector(send, '.message[data-role="user"]');

  const immediateResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      assistantCount: document.querySelectorAll('.message[data-role="assistant"]').length,
      promptValue: document.querySelector('.prompt textarea')?.value ?? null,
      query: window.__paimLayoutReadQueryControl(),
      stopVisible: Boolean(document.querySelector('button[aria-label="응답 중지"]')),
      thinkingVisible: Boolean(document.querySelector('.thinking')),
      userText: document.querySelector('.message[data-role="user"]')?.textContent.trim() || "",
    }))()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-item[data-project-name="Query Beta"]')?.click()`,
  });
  await waitForSelector(send, ".pending-query-notice");

  const backgroundResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      activeProject: document.querySelector('.project-item[data-active="true"]')?.getAttribute('data-project-name') || "",
      bannerText: document.querySelector('.pending-query-notice')?.textContent.trim() || "",
      betaMessageCount: document.querySelectorAll('.message').length,
      hasMoveButton: Array.from(document.querySelectorAll('.pending-query-notice button')).some((button) => button.textContent.includes('채팅으로 이동')),
      hasStopButton: Array.from(document.querySelectorAll('.pending-query-notice button')).some((button) => button.textContent.includes('응답 중지')),
    }))()`,
  });

  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.pending-query-notice button'))
      .find((button) => button.textContent.includes('응답 중지'))?.click()`,
  });
  await sleep(1100);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-item[data-project-name="Query Alpha"]')?.click()`,
  });
  await waitForSelector(send, '.message[data-role="user"]');

  const stoppedResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      assistantCount: document.querySelectorAll('.message[data-role="assistant"]').length,
      errorCount: document.querySelectorAll('.message[data-role="error"]').length,
      query: window.__paimLayoutReadQueryControl(),
      statusText: document.querySelector('.runtime-status')?.textContent.trim() || "",
      stopVisible: Boolean(document.querySelector('button[aria-label="응답 중지"]')),
      thinkingVisible: Boolean(document.querySelector('.thinking')),
      userCount: document.querySelectorAll('.message[data-role="user"]').length,
    }))()`,
  });

  const value = {
    background: backgroundResult.result.value,
    immediate: immediateResult.result.value,
    stopped: stoppedResult.result.value,
  };
  const failures = [];

  if (!value.immediate.userText.includes("중단 가능한 지연 응답") ||
      value.immediate.promptValue !== "" ||
      !value.immediate.stopVisible ||
      !value.immediate.thinkingVisible ||
      value.immediate.assistantCount !== 1 ||
      value.immediate.query.resolved !== 0) {
    failures.push("delayed query should show the user message, clear the draft, and expose Stop before the response resolves");
  }

  if (value.background.activeProject !== "Query Beta" ||
      !value.background.bannerText.includes("Query Alpha") ||
      !value.background.bannerText.includes("Alpha Chat") ||
      !value.background.hasMoveButton ||
      !value.background.hasStopButton ||
      value.background.betaMessageCount !== 0) {
    failures.push("a query running elsewhere should stay owned by its source chat and expose move/stop actions");
  }

  if (value.stopped.userCount !== 1 ||
      value.stopped.assistantCount !== 0 ||
      value.stopped.errorCount !== 0 ||
      value.stopped.stopVisible ||
      value.stopped.thinkingVisible ||
      value.stopped.query.aborted !== 1 ||
      value.stopped.query.resolved !== 0 ||
      !value.stopped.statusText.includes("응답 생성을 중지했습니다")) {
    failures.push("Stop should abort the request and prevent a late assistant or error message from appearing");
  }

  debugLayout("interruptible background query", value);
  return { value, failures };
}

// Stop은 생성 POST의 서버 ID를 회수하되, 그 뒤 query는 시작하지 않아야 한다.
async function verifyCancelledPreflightIdCommit(send) {
  const now = Date.now();
  const failures = [];
  const value = {};

  async function waitForCreationRequest(field, timeoutMs = 3000) {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      const result = await send("Runtime.evaluate", {
        returnByValue: true,
        expression: `window.__paimLayoutReadCreationControl()?.[${JSON.stringify(field)}] || 0`,
      });
      if (result.result.value > 0) {
        return;
      }
      await sleep(25);
    }
    throw new Error(`Timed out waiting for creation mock counter: ${field}`);
  }

  async function submitAndStop(promptText, counterField) {
    await send("Runtime.evaluate", {
      expression: `(() => {
        const input = document.querySelector('.prompt textarea');
        const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        setter.call(input, ${JSON.stringify(promptText)});
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
      })()`,
    });
    await sleep(60);
    await send("Runtime.evaluate", {
      expression: `document.querySelector('button[aria-label="메시지 보내기"]')?.click()`,
    });
    await waitForSelector(send, 'button[aria-label="응답 중지"]');
    await waitForCreationRequest(counterField);
    await send("Runtime.evaluate", {
      expression: `document.querySelector('button[aria-label="응답 중지"]')?.click()`,
    });
  }

  const projectCreationState = createProjectStorage(
    "project-preflight-create",
    "Preflight Project",
    [
      {
        createdAt: now,
        id: "session-preflight-project",
        messages: [],
        title: "New Chat",
      },
    ],
    "session-preflight-project",
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 820,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await navigateAndWaitForSelector(send, APP_URL, ".app-shell");
  await evaluateAndNavigateToSelector(
    send,
    `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}, '272'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}, '360'); localStorage.removeItem(${JSON.stringify(PROJECT_COLLAPSED_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(projectCreationState)})`,
    APP_URL,
    ".prompt textarea:not(:disabled)",
  );
  await send("Runtime.evaluate", {
    expression: `window.__paimLayoutConfigureCreation({ projectDelayMs: 650 }); window.__paimLayoutConfigureQuery({ delayMs: 0 })`,
  });
  await submitAndStop("프로젝트 생성 중 중지", "projectRequested");
  await sleep(850);

  const projectResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const state = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const project = state.projects?.find((item) => item.id === 'project-preflight-create');
      const session = project?.sessions?.find((item) => item.id === 'session-preflight-project');
      return {
        apiCalls: window.__paimLayoutApiCalls || [],
        apiProjectId: project?.apiProjectId ?? null,
        creation: window.__paimLayoutReadCreationControl(),
        query: window.__paimLayoutReadQueryControl(),
        serverSessionId: session?.serverSessionId ?? null,
        stopVisible: Boolean(document.querySelector('button[aria-label="응답 중지"]')),
      };
    })()`,
  });
  value.project = projectResult.result.value;

  const sessionCreationState = createProjectStorage(
    "project-preflight-session",
    "Preflight Session",
    [
      {
        createdAt: now + 1,
        id: "session-preflight-session",
        messages: [],
        title: "New Chat",
      },
    ],
    "session-preflight-session",
    [],
    { apiProjectId: 1 },
  );

  await evaluateAndNavigateToSelector(
    send,
    `localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(sessionCreationState)})`,
    APP_URL,
    ".prompt textarea:not(:disabled)",
  );
  await send("Runtime.evaluate", {
    expression: `window.__paimLayoutConfigureCreation({ sessionDelayMs: 650 }); window.__paimLayoutConfigureQuery({ delayMs: 0 })`,
  });
  await submitAndStop("세션 생성 중 중지", "sessionRequested");
  await sleep(850);

  const sessionResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const state = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const project = state.projects?.find((item) => item.id === 'project-preflight-session');
      const session = project?.sessions?.find((item) => item.id === 'session-preflight-session');
      return {
        apiCalls: window.__paimLayoutApiCalls || [],
        apiProjectId: project?.apiProjectId ?? null,
        creation: window.__paimLayoutReadCreationControl(),
        query: window.__paimLayoutReadQueryControl(),
        serverSessionId: session?.serverSessionId ?? null,
        stopVisible: Boolean(document.querySelector('button[aria-label="응답 중지"]')),
      };
    })()`,
  });
  value.session = sessionResult.result.value;

  const projectQueryCalls = value.project.apiCalls.filter((call) => /POST \/api\/v1\/projects\/\d+\/query/.test(call));
  const projectSessionCalls = value.project.apiCalls.filter((call) => /POST \/api\/v1\/projects\/\d+\/sessions/.test(call));
  if (value.project.apiProjectId !== 1000 ||
      value.project.serverSessionId !== null ||
      value.project.creation.projectRequested !== 1 ||
      value.project.creation.projectResolved !== 1 ||
      value.project.creation.sessionRequested !== 0 ||
      value.project.query.requested !== 0 ||
      projectQueryCalls.length !== 0 ||
      projectSessionCalls.length !== 0 ||
      value.project.stopVisible) {
    failures.push("Stop during project creation should retain the committed project id without creating a session or query");
  }

  const sessionQueryCalls = value.session.apiCalls.filter((call) => /POST \/api\/v1\/projects\/\d+\/query/.test(call));
  if (value.session.apiProjectId !== 1 ||
      value.session.serverSessionId !== "smoke-session-1000" ||
      value.session.creation.projectRequested !== 0 ||
      value.session.creation.sessionRequested !== 1 ||
      value.session.creation.sessionResolved !== 1 ||
      value.session.query.requested !== 0 ||
      sessionQueryCalls.length !== 0 ||
      value.session.stopVisible) {
    failures.push("Stop during session creation should retain the committed session id without starting a query");
  }

  debugLayout("cancelled preflight id commit", value);
  return { value, failures };
}

// Stop 직후 재전송은 진행 중인 생성 Promise를 공유하고 두 번째 query만 실행한다.
async function verifyPreflightRetrySharesCreation(send) {
  const now = Date.now();
  const failures = [];
  const value = {};

  async function waitForRuntime(expression, timeoutMs = 4000) {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      const result = await send("Runtime.evaluate", {
        returnByValue: true,
        expression,
      });
      if (result.result.value) {
        return;
      }
      await sleep(25);
    }
    throw new Error(`Timed out waiting for runtime condition: ${expression}`);
  }

  async function setPromptAndSend(text) {
    await send("Runtime.evaluate", {
      expression: `(() => {
        const input = document.querySelector('.prompt textarea');
        const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        setter.call(input, ${JSON.stringify(text)});
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
      })()`,
    });
    await sleep(45);
    await send("Runtime.evaluate", {
      expression: `document.querySelector('button[aria-label="메시지 보내기"]:not(:disabled)')?.click()`,
    });
  }

  async function stopAndRetry(firstText, secondText, creationCounter) {
    await setPromptAndSend(firstText);
    await waitForSelector(send, 'button[aria-label="응답 중지"]');
    await waitForRuntime(
      `window.__paimLayoutReadCreationControl()?.[${JSON.stringify(creationCounter)}] === 1`,
    );
    await send("Runtime.evaluate", {
      expression: `document.querySelector('button[aria-label="응답 중지"]')?.click()`,
    });
    await waitForSelector(send, 'button[aria-label="메시지 보내기"]');
    await setPromptAndSend(secondText);
    await waitForRuntime(`document.querySelectorAll('.message[data-role="user"]').length === 2`);
  }

  const projectRetryState = createProjectStorage(
    "project-preflight-retry",
    "Preflight Project Retry",
    [
      {
        createdAt: now,
        id: "session-preflight-project-retry",
        messages: [],
        title: "New Chat",
      },
    ],
    "session-preflight-project-retry",
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 820,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await navigateAndWaitForSelector(send, APP_URL, ".app-shell");
  await evaluateAndNavigateToSelector(
    send,
    `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}, '272'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}, '360'); localStorage.removeItem(${JSON.stringify(PROJECT_COLLAPSED_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(projectRetryState)})`,
    APP_URL,
    ".prompt textarea:not(:disabled)",
  );
  await send("Runtime.evaluate", {
    expression: `window.__paimLayoutConfigureCreation({ projectDelayMs: 750 }); window.__paimLayoutConfigureQuery({ delayMs: 0 })`,
  });
  await stopAndRetry("프로젝트 생성 첫 요청", "프로젝트 생성 재요청", "projectRequested");

  const projectDuringResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      creation: window.__paimLayoutReadCreationControl(),
      query: window.__paimLayoutReadQueryControl(),
      userCount: document.querySelectorAll('.message[data-role="user"]').length,
    }))()`,
  });
  await waitForRuntime(`window.__paimLayoutReadQueryControl()?.resolved === 1`);
  await sleep(120);
  const projectDoneResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const state = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const project = state.projects?.find((item) => item.id === 'project-preflight-retry');
      const session = project?.sessions?.find((item) => item.id === 'session-preflight-project-retry');
      return {
        apiCalls: window.__paimLayoutApiCalls || [],
        apiProjectId: project?.apiProjectId ?? null,
        assistantCount: document.querySelectorAll('.message[data-role="assistant"]').length,
        creation: window.__paimLayoutReadCreationControl(),
        errorCount: document.querySelectorAll('.message[data-role="error"]').length,
        query: window.__paimLayoutReadQueryControl(),
        serverSessionId: session?.serverSessionId ?? null,
        userCount: document.querySelectorAll('.message[data-role="user"]').length,
      };
    })()`,
  });
  value.project = {
    during: projectDuringResult.result.value,
    done: projectDoneResult.result.value,
  };

  const sessionRetryState = createProjectStorage(
    "project-session-retry",
    "Preflight Session Retry",
    [
      {
        createdAt: now + 1,
        id: "session-preflight-retry",
        messages: [],
        title: "New Chat",
      },
    ],
    "session-preflight-retry",
    [],
    { apiProjectId: 1 },
  );

  await evaluateAndNavigateToSelector(
    send,
    `localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(sessionRetryState)})`,
    APP_URL,
    ".prompt textarea:not(:disabled)",
  );
  await send("Runtime.evaluate", {
    expression: `window.__paimLayoutConfigureCreation({ sessionDelayMs: 750 }); window.__paimLayoutConfigureQuery({ delayMs: 0 })`,
  });
  await stopAndRetry("세션 생성 첫 요청", "세션 생성 재요청", "sessionRequested");

  const sessionDuringResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      creation: window.__paimLayoutReadCreationControl(),
      query: window.__paimLayoutReadQueryControl(),
      userCount: document.querySelectorAll('.message[data-role="user"]').length,
    }))()`,
  });
  await waitForRuntime(`window.__paimLayoutReadQueryControl()?.resolved === 1`);
  await sleep(120);
  const sessionDoneResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const state = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const project = state.projects?.find((item) => item.id === 'project-session-retry');
      const session = project?.sessions?.find((item) => item.id === 'session-preflight-retry');
      return {
        apiCalls: window.__paimLayoutApiCalls || [],
        apiProjectId: project?.apiProjectId ?? null,
        assistantCount: document.querySelectorAll('.message[data-role="assistant"]').length,
        creation: window.__paimLayoutReadCreationControl(),
        errorCount: document.querySelectorAll('.message[data-role="error"]').length,
        query: window.__paimLayoutReadQueryControl(),
        serverSessionId: session?.serverSessionId ?? null,
        userCount: document.querySelectorAll('.message[data-role="user"]').length,
      };
    })()`,
  });
  value.session = {
    during: sessionDuringResult.result.value,
    done: sessionDoneResult.result.value,
  };

  const projectCalls = value.project.done.apiCalls;
  if (value.project.during.userCount !== 2 ||
      value.project.during.creation.projectRequested !== 1 ||
      value.project.during.creation.projectResolved !== 0 ||
      value.project.during.query.requested !== 0 ||
      projectCalls.filter((call) => call === "POST /api/v1/projects").length !== 1 ||
      projectCalls.filter((call) => /POST \/api\/v1\/projects\/\d+\/sessions/.test(call)).length !== 1 ||
      projectCalls.filter((call) => /POST \/api\/v1\/projects\/\d+\/query/.test(call)).length !== 1 ||
      value.project.done.creation.projectRequested !== 1 ||
      value.project.done.query.requested !== 1 ||
      value.project.done.query.resolved !== 1 ||
      value.project.done.apiProjectId !== 1000 ||
      value.project.done.serverSessionId !== "smoke-session-1000" ||
      value.project.done.userCount !== 2 ||
      value.project.done.assistantCount !== 1 ||
      value.project.done.errorCount !== 0) {
    failures.push("retry during project creation should share one project POST and complete exactly one query");
  }

  const sessionCalls = value.session.done.apiCalls;
  if (value.session.during.userCount !== 2 ||
      value.session.during.creation.sessionRequested !== 1 ||
      value.session.during.creation.sessionResolved !== 0 ||
      value.session.during.query.requested !== 0 ||
      sessionCalls.filter((call) => call === "POST /api/v1/projects").length !== 0 ||
      sessionCalls.filter((call) => /POST \/api\/v1\/projects\/\d+\/sessions/.test(call)).length !== 1 ||
      sessionCalls.filter((call) => /POST \/api\/v1\/projects\/\d+\/query/.test(call)).length !== 1 ||
      value.session.done.creation.sessionRequested !== 1 ||
      value.session.done.query.requested !== 1 ||
      value.session.done.query.resolved !== 1 ||
      value.session.done.apiProjectId !== 1 ||
      value.session.done.serverSessionId !== "smoke-session-1000" ||
      value.session.done.userCount !== 2 ||
      value.session.done.assistantCount !== 1 ||
      value.session.done.errorCount !== 0) {
    failures.push("retry during session creation should share one session POST and complete exactly one query");
  }

  debugLayout("preflight retry shares creation", value);
  return { value, failures };
}

// 채팅 입력이 textarea이며 Enter/Shift+Enter 동작이 유지되는지 확인한다.
async function verifyMultilineInput(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 820,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithProject(send);
  const initialResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const input = document.querySelector('.prompt textarea');
      const initialMessages = document.querySelectorAll('.message').length;

      if (!input) {
        return { hasTextarea: false };
      }

      input.focus();
      return {
        hasTextarea: true,
        initialMessages,
        initialHeight: input.getBoundingClientRect().height,
      };
    })()`,
  });
  const initialValue = initialResult.result.value;
  const failures = [];

  if (!initialValue.hasTextarea) {
    failures.push("message input should render as textarea");
    return { value: initialValue, failures };
  }

  await send("Input.insertText", { text: "첫 줄" });
  await send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "Enter",
    code: "Enter",
    modifiers: 8,
    text: "\r",
    unmodifiedText: "\r",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });
  await send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "Enter",
    code: "Enter",
    modifiers: 8,
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });
  await send("Input.insertText", { text: "둘째 줄" });
  await sleep(100);

  const newlineResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.querySelector('.prompt textarea').value`,
  });
  const afterShiftEnterValue = newlineResult.result.value;

  const autosizeResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(async () => {
      const input = document.querySelector('.prompt textarea');
      const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      const twoLineHeight = input.getBoundingClientRect().height;
      setValue.call(input, Array.from({ length: 10 }, (_, index) => '줄 ' + (index + 1)).join('\\n'));
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      const tenLineHeight = input.getBoundingClientRect().height;
      const tenLineOverflow = getComputedStyle(input).overflowY;
      setValue.call(input, ${JSON.stringify(afterShiftEnterValue)});
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      return {
        restoredHeight: input.getBoundingClientRect().height,
        tenLineHeight,
        tenLineOverflow,
        twoLineHeight,
      };
    })()`,
    awaitPromise: true,
  });
  const autosizeValue = autosizeResult.result.value;

  await send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });
  await send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });
  await sleep(700);

  const submitResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const input = document.querySelector('.prompt textarea');
      return {
        afterShiftEnterValue: ${JSON.stringify(afterShiftEnterValue)},
        messagesAfterEnter: document.querySelectorAll('.message').length,
        textAfterEnter: input.value,
        userTextVisible: document.body.textContent.includes('첫 줄') &&
          document.body.textContent.includes('둘째 줄'),
        demoReplyVisible: document.body.textContent.includes('좋아요. 이 내용을 프로젝트 메모로 정리할 수 있습니다.'),
        runtimeErrorVisible: document.body.textContent.includes('응답 실패') ||
          document.body.textContent.includes('응답을 받지 못했습니다'),
        runtimeStatusVisible: Boolean(document.querySelector('.runtime-status')),
        clearedHeight: input.getBoundingClientRect().height,
        initialMessages: ${initialValue.initialMessages},
        autosize: ${JSON.stringify(autosizeValue)},
        initialHeight: ${initialValue.initialHeight},
      };
    })()`,
  });
  const value = submitResult.result.value;

  if (!afterShiftEnterValue.includes("\n")) {
    failures.push("Shift+Enter should keep a newline in the textarea");
  }

  if (value.autosize.twoLineHeight <= value.initialHeight ||
      value.autosize.tenLineHeight <= value.autosize.twoLineHeight ||
      value.autosize.tenLineHeight > 147 ||
      value.autosize.tenLineOverflow !== "auto" ||
      Math.abs(value.autosize.restoredHeight - value.autosize.twoLineHeight) > 1 ||
      Math.abs(value.clearedHeight - value.initialHeight) > 1) {
    failures.push(`textarea should grow, cap at six lines, and shrink again: ${JSON.stringify(value.autosize)}`);
  }

  if (value.messagesAfterEnter <= value.initialMessages) {
    failures.push("Enter should submit a new message");
  }

  if (value.textAfterEnter !== "") {
    failures.push("textarea should clear after submit");
  }

  if (!value.userTextVisible) {
    failures.push("submitted multiline text should be visible in the conversation");
  }

  if (!value.demoReplyVisible) {
    failures.push("frontend demo reply should appear without a local runtime");
  }

  if (value.runtimeErrorVisible) {
    failures.push("chat demo should not show a local runtime error");
  }

  if (value.runtimeStatusVisible) {
    failures.push("chat submit should not add a sidebar runtime status");
  }

  debugLayout("multiline input", value);
  return { value, failures };
}

// 우측 패널 메뉴가 프로젝트 보조 정보를 상세 화면으로 전환하는지 확인한다.
async function verifyProjectPanelMenu(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithProject(send);
  await send("Runtime.evaluate", {
    expression: `(() => {
      const originalFetch = window.fetch.bind(window);
      window.fetch = (input, init) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
        if (url.includes('/projects/1/memory')) {
          return Promise.resolve(new Response(JSON.stringify([
            {
              id: 1,
              project_id: 1,
              doc_id: 1,
              category: 'decision',
              content: '프로젝트 메모리는 FastAPI에서 조회한다',
              topic: '아키텍처',
              owner: 'PM',
              source: 'meeting.md',
            },
            {
              id: 2,
              project_id: 1,
              doc_id: 1,
              category: 'action',
              content: 'API 연결 상태를 확인한다',
              owner: '백엔드',
              source: 'meeting.md',
            },
            {
              id: 3,
              project_id: 1,
              doc_id: 1,
              category: 'issue',
              content: '서버 미연결 상태에서는 메모리를 숨긴다',
              source: 'meeting.md',
            },
            {
              id: 4,
              project_id: 1,
              doc_id: 1,
              category: 'risk',
              content: '프론트 임시 데이터가 실제 메모리처럼 보일 수 있다',
              source: 'meeting.md',
            },
          ]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }));
        }
        return originalFetch(input, init);
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.project-panel-menu button'))
      .find((button) => button.textContent.includes('메모리'))?.click()`,
  });
  await waitForSelector(send, ".project-panel .project-memory");

  const memoryResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
	      hasPrompt: Boolean(document.querySelector('.prompt')),
	      hasOverview: Boolean(document.querySelector('.project-overview')),
	      summaryStats: document.querySelectorAll('.project-panel .project-memory-stat').length,
	      summaryActionRows: document.querySelectorAll('.project-panel .project-memory-summary-action').length,
	      summarySections: document.querySelectorAll('.project-panel .project-memory-summary-section').length,
	      text: document.querySelector('.project-panel')?.textContent || "",
	      tabText: document.querySelector('.project-panel-tab[data-active="true"] > span')?.textContent.trim() || "",
	      hasCloseButton: Boolean(document.querySelector('button[aria-label="프로젝트 메모리 탭 닫기"]')),
	      hasAddButton: Boolean(document.querySelector(${JSON.stringify(PROJECT_PANEL_TAB_ADD_SELECTOR)})),
	      modelSelectorExists: Boolean(document.querySelector('.model-pill')),
	    }))()`,
  });
  await send("Runtime.evaluate", {
    expression: `document.querySelector('button[aria-label="프로젝트 메모리 패널 최대화"]')?.click()`,
  });
  await sleep(120);
  const memoryMaximizeResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      maximized: document.querySelector('.app-shell')?.getAttribute('data-project-panel-state') === 'maximized',
      detailStats: document.querySelectorAll('.project-panel .project-memory-stats [data-tone]').length,
      detailCards: document.querySelectorAll('.project-panel .project-memory-manage-item').length,
    }))()`,
  });
  await send("Runtime.evaluate", {
    expression: `document.querySelector('button[aria-label="프로젝트 메모리 패널 축소"]')?.click()`,
  });
	  await sleep(120);
	  await send("Runtime.evaluate", {
	    expression: `document.querySelector(${JSON.stringify(PROJECT_PANEL_TAB_ADD_SELECTOR)})?.click()`,
	  });
  await clickVisibleMenuItem(send, "GitHub");
  await waitForSelector(send, ".project-panel .github-panel-content");
  await send("Runtime.evaluate", {
    expression: `document.querySelector('button[aria-label="GitHub 패널 최대화"]')?.click()`,
  });
  await sleep(120);
  const githubMaximizeResult = await send("Runtime.evaluate", {
    returnByValue: true,
	    expression: `(() => ({
	      maximized: document.querySelector('.app-shell')?.getAttribute('data-project-panel-state') === 'maximized',
	      tabText: document.querySelector('.project-panel-tab[data-active="true"] > span')?.textContent.trim() || "",
	      tabLabels: Array.from(document.querySelectorAll('.project-panel-tab > span')).map((item) => item.textContent.trim()),
	    }))()`,
  });
  await send("Runtime.evaluate", {
    expression: `document.querySelector('button[aria-label="GitHub 패널 축소"]')?.click()`,
  });
	  await sleep(120);
	  await send("Runtime.evaluate", {
	    expression: `document.querySelector(${JSON.stringify(PROJECT_PANEL_TAB_ADD_SELECTOR)})?.click()`,
	  });
  await clickVisibleMenuItem(send, "메모리");
  await waitForSelector(send, ".project-panel .project-memory");
  const memorySingletonResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      activeTabText: document.querySelector('.project-panel-tab[data-active="true"] > span')?.textContent.trim() || "",
      memoryTabs: Array.from(document.querySelectorAll('.project-panel-tab > span'))
        .filter((item) => item.textContent.includes('프로젝트 메모리')).length,
      tabCount: document.querySelectorAll('.project-panel-tab').length,
      tabLabels: Array.from(document.querySelectorAll('.project-panel-tab > span')).map((item) => item.textContent.trim()),
    }))()`,
  });
	  await send("Runtime.evaluate", {
	    expression: `document.querySelector('button[aria-label="GitHub 탭 닫기"]')?.click()`,
	  });
  await sleep(100);
  const menuResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      hasMenu: Boolean(document.querySelector('.project-panel-menu')),
      activeTabText: document.querySelector('.project-panel-tab[data-active="true"] > span')?.textContent.trim() || "",
      tabLabels: Array.from(document.querySelectorAll('.project-panel-tab > span')).map((item) => item.textContent.trim()),
    }))()`,
  });
  for (let index = 0; index < 2; index += 1) {
    await send("Runtime.evaluate", {
      expression: `document.querySelector(${JSON.stringify(PROJECT_PANEL_TAB_ADD_SELECTOR)})?.click()`,
    });
    await clickVisibleMenuItem(send, "자료");
    await sleep(120);
  }
  const duplicateTabsResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      fileTabs: Array.from(document.querySelectorAll('.project-panel-tab > span'))
        .filter((item) => item.textContent.trim() === '자료').length,
      activeTabText: document.querySelector('.project-panel-tab[data-active="true"] > span')?.textContent.trim() || "",
    }))()`,
  });
  const value = {
    memory: memoryResult.result.value,
    memoryMaximize: memoryMaximizeResult.result.value,
    memorySingleton: memorySingletonResult.result.value,
    githubMaximize: githubMaximizeResult.result.value,
    menu: menuResult.result.value,
    duplicateTabs: duplicateTabsResult.result.value,
  };
  const failures = [];

  if (!value.memory.hasPrompt || value.memory.hasOverview) {
    failures.push("project panel should not replace the chat surface");
  }

	  if (value.memory.summaryStats !== 4 ||
	      value.memory.summaryActionRows < 1 ||
	      value.memory.summarySections !== 4 ||
	      !value.memory.text.includes("프로젝트 메모리는 FastAPI에서 조회한다") ||
	      !value.memory.text.includes("API 연결 상태를 확인한다") ||
	      !value.memory.tabText.includes("프로젝트 메모리") ||
	      !value.memory.hasCloseButton ||
	      !value.memory.hasAddButton) {
	    failures.push("project panel memory view should render FastAPI memory rows");
	  }

	  if (!value.memoryMaximize.maximized ||
	      value.memoryMaximize.detailStats !== 4 ||
	      value.memoryMaximize.detailCards !== 4 ||
	      !value.githubMaximize.maximized ||
	      !value.githubMaximize.tabText.includes("GitHub") ||
	      !value.githubMaximize.tabLabels.includes("프로젝트 메모리") ||
	      !value.githubMaximize.tabLabels.includes("GitHub")) {
	    failures.push("memory and GitHub panels should support maximize and tab switching");
	  }

  if (value.memorySingleton.memoryTabs !== 1 ||
      value.memorySingleton.tabCount !== 2 ||
      !value.memorySingleton.activeTabText.includes("프로젝트 메모리") ||
      !value.memorySingleton.tabLabels.includes("GitHub")) {
    failures.push("reopening project memory should activate its existing singleton tab");
  }

  if (value.menu.hasMenu ||
      !value.menu.activeTabText.includes("프로젝트 메모리") ||
      value.menu.tabLabels.includes("GitHub")) {
	    failures.push("project panel tabs should keep existing tabs and close only the selected tab");
	  }

	  if (value.duplicateTabs.fileTabs !== 2 ||
	      value.duplicateTabs.activeTabText !== "자료") {
	    failures.push("project panel should allow duplicate file tabs");
	  }

  if (value.memory.modelSelectorExists) {
    failures.push("model selector should not render in the prompt");
  }

  debugLayout("project panel menu", value);
  return { value, failures };
}

const SUPERSEDE_SUGGESTION_LIST_CALL =
  "GET /api/v1/projects/1/suggestions?status=pending&kind=all";

async function runSupersedeResolutionCase(send, { id, resolution, responseStatus = 204 }) {
  await openAppWithProject(send);
  await send("Runtime.evaluate", {
    expression: `(() => {
      window.__paimLayoutSeedSupersedeSuggestion?.(${id});
      ${responseStatus === 204
        ? ""
        : `window.__paimLayoutSetSuggestionResolutionStatus?.(${responseStatus});`}
      window.__paimLayoutApiCalls.length = 0;
    })()`,
  });
  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.project-panel-menu button'))
      .find((button) => button.textContent.includes('메모리'))?.click()`,
  });
  await waitForSelector(send, ".project-memory-suggestion-card");

  const buttonSelector = `.project-memory-suggestion-${resolution}`;
  const resolutionCall = `POST /api/v1/projects/1/suggestions/${id}/${resolution}`;
  const beforeResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const card = document.querySelector('.project-memory-suggestion-card');
      const button = card?.querySelector(${JSON.stringify(buttonSelector)});
      const apiCalls = window.__paimLayoutApiCalls || [];
      return {
        cardCount: document.querySelectorAll('.project-memory-suggestion-card').length,
        text: card?.textContent || "",
        resolutionEnabled: Boolean(button) && !button.disabled &&
          button.getAttribute('aria-disabled') !== 'true',
        suggestionFetches: apiCalls.filter((call) =>
          call === ${JSON.stringify(SUPERSEDE_SUGGESTION_LIST_CALL)}
        ).length,
        apiCalls,
      };
    })()`,
  });
  const before = beforeResult.result.value;

  await send("Runtime.evaluate", {
    expression: `document.querySelector(${JSON.stringify(`${buttonSelector}:not(:disabled)`)})?.click()`,
  });

  let resolutionObserved = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const resolutionResult = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => {
        const apiCalls = window.__paimLayoutApiCalls || [];
        const resolutionIndex = apiCalls.indexOf(${JSON.stringify(resolutionCall)});
        const refetchIndex = apiCalls.findIndex((call, index) =>
          index > resolutionIndex &&
          call === ${JSON.stringify(SUPERSEDE_SUGGESTION_LIST_CALL)}
        );
        return !document.querySelector('.project-memory-suggestion-card') &&
          resolutionIndex >= 0 && refetchIndex > resolutionIndex;
      })()`,
    });

    if (resolutionResult.result.value) {
      resolutionObserved = true;
      break;
    }

    await sleep(50);
  }

  const afterResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const apiCalls = window.__paimLayoutApiCalls || [];
      const resolutionIndex = apiCalls.indexOf(${JSON.stringify(resolutionCall)});
      const refetchIndex = apiCalls.findIndex((call, index) =>
        index > resolutionIndex &&
        call === ${JSON.stringify(SUPERSEDE_SUGGESTION_LIST_CALL)}
      );
      return {
        cardCount: document.querySelectorAll('.project-memory-suggestion-card').length,
        operationError: Boolean(document.querySelector('.project-memory-operation-error')),
        resolutionIndex,
        refetchIndex,
        suggestionFetches: apiCalls.filter((call) =>
          call === ${JSON.stringify(SUPERSEDE_SUGGESTION_LIST_CALL)}
        ).length,
        apiCalls,
      };
    })()`,
  });

  return {
    id,
    resolution,
    responseStatus,
    resolutionCall,
    before,
    after: afterResult.result.value,
    resolutionObserved,
  };
}

// 승인·거절과 400/404/409 충돌 응답 모두 pending kind=all을 재조회하는지 확인한다.
async function verifySupersedeSuggestionFlow(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 820,
    deviceScaleFactor: 1,
    mobile: false,
  });

  const accept = await runSupersedeResolutionCase(send, {
    id: 901,
    resolution: "accept",
  });
  const reject = await runSupersedeResolutionCase(send, {
    id: 902,
    resolution: "reject",
  });
  const refreshableErrors = [];
  for (const [responseStatus, id, resolution] of [
    [400, 940, "accept"],
    [404, 944, "reject"],
    [409, 949, "accept"],
  ]) {
    refreshableErrors.push(await runSupersedeResolutionCase(send, {
      id,
      resolution,
      responseStatus,
    }));
  }

  const value = { accept, reject, refreshableErrors };
  const failures = [];

  if (accept.before.cardCount !== 1 || accept.before.suggestionFetches < 1) {
    failures.push(`Supersede inbox should load through ${SUPERSEDE_SUGGESTION_LIST_CALL}`);
  }
  if (!accept.before.text.includes("기존 결정 · 프로젝트 메모리는 FastAPI에서 조회한다") ||
      !accept.before.text.includes("새 결정 · 프로젝트 메모리는 GraphQL 게이트웨이를 통해 조회한다") ||
      !accept.before.text.includes("변경 근거 · 새 아키텍처 결정이 기존 결정을 대체합니다")) {
    failures.push("Supersede card should show the existing decision, replacement decision, and rationale");
  }
  if (!accept.before.resolutionEnabled || !reject.before.resolutionEnabled) {
    failures.push("project Owner should be able to accept and reject a Supersede suggestion");
  }

  for (const result of [accept, reject]) {
    if (!result.resolutionObserved ||
        !result.after.apiCalls.includes(result.resolutionCall) ||
        result.after.refetchIndex <= result.after.resolutionIndex ||
        result.after.cardCount !== 0 ||
        result.after.operationError) {
      failures.push(`${result.resolution} should resolve the Supersede suggestion and refetch pending kind=all suggestions`);
    }
  }

  for (const result of refreshableErrors) {
    if (!result.resolutionObserved ||
        !result.after.apiCalls.includes(result.resolutionCall) ||
        result.after.refetchIndex <= result.after.resolutionIndex ||
        result.after.cardCount !== 0 ||
        !result.after.operationError) {
      failures.push(`${result.responseStatus} suggestion responses should preserve the error and refetch server state`);
    }
  }

  debugLayout("supersede suggestion flow", value);
  return { value, failures };
}

// 새 구조에서는 기본 채팅 입력이 바로 데모 응답 흐름으로 이어진다.
async function verifyProjectChatQuestion(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithProject(send);

  await send("Runtime.evaluate", {
    expression: `(() => {
      const input = document.querySelector('.prompt textarea');
      const valueSetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;

      valueSetter?.call(input, '이번 주 액션 알려줘');
      input?.dispatchEvent(new Event('input', { bubbles: true }));
    })()`,
  });
  await sleep(100);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('button[aria-label="메시지 보내기"]')?.click()`,
  });
  await sleep(1200);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const savedState = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const activeProject = savedState.projects?.find((project) => project.id === savedState.selectedProjectId);
      const activeSession = activeProject?.sessions.find((session) => session.id === savedState.selectedSessionId);

      return {
        sessionCount: activeProject?.sessions.length ?? 0,
          activeTitle: activeSession?.title || "",
          hasPrompt: Boolean(document.querySelector('.prompt')),
          hasOverview: Boolean(document.querySelector('.project-overview')),
        conversationText: document.querySelector('.conversation')?.textContent || "",
      };
    })()`,
  });
  const value = result.result.value;
  const failures = [];

  if (value.sessionCount !== 1 || value.activeTitle !== "Smoke Chat") {
    failures.push("chat question should stay in the active chat session");
  }

    if (!value.hasPrompt || value.hasOverview) {
      failures.push("chat question should stay in the chat view");
    }

  if (!value.conversationText.includes("이번 주 액션 알려줘") ||
        !value.conversationText.includes("좋아요. 이 내용을 프로젝트 메모로 정리할 수 있습니다.")) {
      failures.push("chat question should submit through the demo chat flow");
    }

  debugLayout("project chat question", value);
  return { value, failures };
}

// 파일 패널은 프로젝트 폴더 트리를 검색, 접기/펼치기, 최대화 상태로 보여줘야 한다.
async function verifyProjectOverviewFiles(send) {
  const projectFiles = [
    {
      id: "root-desktop",
	      name: "desktop",
	      path: "/mock/desktop",
	      kind: "directory",
		      uploadedAt: 86400000,
      childrenLoaded: true,
      isExpanded: true,
      children: [
        {
          id: "dir-src",
          name: "src",
          path: "/mock/desktop/src",
          kind: "directory",
          childrenLoaded: true,
          isExpanded: false,
          children: [
            {
              id: "file-app",
              name: "App.tsx",
              path: "/mock/desktop/src/App.tsx",
              kind: "file",
            },
            {
              id: "file-style",
              name: "styles.css",
              path: "/mock/desktop/src/styles.css",
              kind: "file",
            },
          ],
        },
        {
          id: "file-package",
          name: "package.json",
          path: "/mock/desktop/package.json",
          kind: "file",
        },
        {
          id: "file-long-notebook",
          name: "02_RAG_Load_Documents(튜터용).ipynb",
          path: "/mock/desktop/data/02_RAG/02_RAG_Load_Documents(튜터용).ipynb",
          kind: "file",
        },
      ],
    },
	    {
	      id: "root-backend",
	      name: "backend",
	      path: "/mock/backend",
	      kind: "directory",
	      uploadedAt: 60000,
      childrenLoaded: true,
      isExpanded: false,
      children: [
        {
          id: "file-main",
          name: "main.py",
          path: "/mock/backend/main.py",
          kind: "file",
	        },
	      ],
	    },
	    {
	      id: "root-readme",
	      name: "README.md",
	      path: "/mock/README.md",
	      kind: "file",
		      uploadedAt: 86460000,
	    },
	  ];
  const seededProjectState = createProjectStorage(
    "project-files",
    "Files Project",
    [
      {
        id: "session-files",
        title: "Files Chat",
        createdAt: Date.now(),
        messages: [],
      },
    ],
    "session-files",
    projectFiles,
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await navigateAndWaitForSelector(send, APP_URL, ".app-shell");
  await evaluateAndNavigateToSelector(
    send,
    `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}, '272'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}, '360'); localStorage.removeItem(${JSON.stringify(PROJECT_COLLAPSED_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(seededProjectState)})`,
    APP_URL,
    ".project-panel-menu",
  );
  await waitForSelector(send, ".prompt textarea:not(:disabled)");
  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.project-panel-menu button'))
      .find((button) => button.textContent.includes('자료'))?.click()`,
  });
  await waitForSelector(send, ".project-sources-panel");

	    const libraryResult = await send("Runtime.evaluate", {
	      returnByValue: true,
	      expression: `(() => ({
	        hasSourcesPanel: Boolean(document.querySelector('.project-sources-panel')),
	        sourceNames: Array.from(document.querySelectorAll('.project-source-body strong')).map((item) => item.textContent.trim()),
	        hasTreeBeforeDetail: Boolean(document.querySelector('.project-file-tree')),
	        hasOriginalView: Array.from(document.querySelectorAll('.project-sources-secondary'))
	          .some((button) => button.textContent.includes('원본 보기')),
	        sourceSearchPlaceholder: document.querySelector('.project-sources-search input')?.getAttribute('placeholder') || "",
	        uploadButtons: Array.from(document.querySelectorAll('.project-files-open-button')).map((button) => button.textContent.trim()),
	        timeLabels: Array.from(document.querySelectorAll('.project-source-time-label')).map((item) => item.textContent.trim()),
	        sourceMenuCount: document.querySelectorAll('.project-source-actions button[aria-label$="관리"]').length,
	        hasVisibleDeleteButton: Array.from(document.querySelectorAll('.project-source-actions > button'))
	          .some((button) => button.textContent.includes('삭제') || button.textContent.includes('제거')),
	      }))()`,
	    });

	    await send("Runtime.evaluate", {
	      expression: `(() => {
	        const input = document.querySelector('.project-sources-search input');
	        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
	        setter.call(input, 'backend');
	        input.dispatchEvent(new Event('input', { bubbles: true }));
	      })()`,
	    });
	    await sleep(200);

	    const librarySearchResult = await send("Runtime.evaluate", {
	      returnByValue: true,
	      expression: `Array.from(document.querySelectorAll('.project-source-body strong')).map((item) => item.textContent.trim())`,
	    });

	    await send("Runtime.evaluate", {
	      expression: `(() => {
	        const input = document.querySelector('.project-sources-search input');
	        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
	        setter.call(input, '');
	        input.dispatchEvent(new Event('input', { bubbles: true }));
	      })()`,
	    });
	    await sleep(120);

	    await send("Runtime.evaluate", {
	      expression: `Array.from(document.querySelectorAll('.project-source-card'))
	        .find((card) => card.textContent.includes('README.md'))?.click()`,
	    });
	    await waitForSelector(send, '.project-files-panel[data-single-file="true"]');

	    const singleFileSourceResult = await send("Runtime.evaluate", {
	      returnByValue: true,
	      expression: `(() => ({
	        dataSingleFile: document.querySelector('.project-files-panel')?.getAttribute('data-single-file') || "",
	        hasTreePane: Boolean(document.querySelector('.project-files-tree-pane')),
	        hasTreeToggle: Boolean(document.querySelector('button[aria-label="파일 목록 접기"]')),
	        hasTreeSearch: Boolean(document.querySelector('.project-files-tree-pane .project-files-search')),
	        previewTab: document.querySelector('.project-panel-tab[data-active="true"] > span')?.textContent.trim() || "",
	        rootText: document.querySelector('.project-files-root')?.textContent.trim() || "",
	      }))()`,
	    });

	    await send("Runtime.evaluate", {
	      expression: `Array.from(document.querySelectorAll('.project-sources-secondary'))
	        .find((button) => button.textContent.includes('자료함'))?.click()`,
	    });
	    await waitForSelector(send, ".project-sources-panel");

	    await send("Runtime.evaluate", {
	      expression: `Array.from(document.querySelectorAll('.project-source-card'))
	        .find((card) => card.textContent.includes('desktop'))?.click()`,
	    });
	    await waitForSelector(send, ".project-file-tree");

    const initialResult = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => ({
        fileNames: Array.from(document.querySelectorAll('.project-file-name')).map((item) => item.textContent.trim()),
        fileCountText: document.querySelector('.project-files-count')?.textContent.trim() || "",
	        rootText: document.querySelector('.project-files-root')?.textContent.trim() || "",
	        uploadButtons: Array.from(document.querySelectorAll('.project-files-header .project-files-open-button')).map((button) => button.textContent.trim()),
	        searchPlaceholder: document.querySelector('.project-files-search input')?.getAttribute('placeholder') || "",
        treeOverflow: getComputedStyle(document.querySelector('.project-file-tree')).overflowY,
        hasPrompt: Boolean(document.querySelector('.prompt')),
        hasOverview: Boolean(document.querySelector('.project-overview')),
        hasPanel: Boolean(document.querySelector('.project-panel')),
      }))()`,
    });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('button[aria-label="src 펼치기"]')?.click()`,
  });
  await sleep(180);

  await send("Runtime.evaluate", {
    expression: `(() => {
      const input = document.querySelector('.project-files-search input');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, 'App');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`,
  });
  await sleep(180);

  const afterFilterResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      visibleFileNames: Array.from(document.querySelectorAll('.project-file-name')).map((item) => item.textContent.trim()),
        appIconColor: (() => {
          const nameElement = Array.from(document.querySelectorAll('.project-file-name'))
            .find((item) => item.textContent.trim() === "App.tsx");
          return nameElement?.closest('.project-file-row')?.querySelector('.project-file-icon')?.style.color || "";
        })(),
        hasPreviewEmpty: Boolean(document.querySelector('.project-files-preview-empty')),
        hasTreeResizeHandle: Boolean(document.querySelector('.project-files-tree-resize-handle')),
        hasTreeToggle: Boolean(document.querySelector('button[aria-label="파일 목록 접기"]')),
        hasFileHeader: Boolean(document.querySelector('.project-files-header')),
        headerBorderBottom: getComputedStyle(document.querySelector('.project-files-header')).borderBottomWidth,
        panelWidth: document.querySelector('.project-panel')?.getBoundingClientRect().width ?? 0,
        previewWidth: document.querySelector('.project-files-main')?.getBoundingClientRect().width ?? 0,
        treeWidth: document.querySelector('.project-files-tree-pane')?.getBoundingClientRect().width ?? 0,
        treeRovingTabStops: document.querySelectorAll('.project-file-tree [role="treeitem"][tabindex="0"]').length,
        nestedTreeButtonTabStops: document.querySelectorAll('.project-file-row button:not([tabindex="-1"])').length,
        panelGridTransition: getComputedStyle(document.querySelector('.project-files-panel')).transitionProperty,
    }))()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('button[aria-label="자료 패널 최대화"]')?.click()`,
  });
  await sleep(180);

  const afterMaximizeResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const shell = document.querySelector('.app-shell');
      const panel = document.querySelector('.project-panel').getBoundingClientRect();
      const sidebarElement = document.querySelector('.sidebar');
      const sidebar = sidebarElement.getBoundingClientRect();
      const sidebarStyle = getComputedStyle(sidebarElement);
      const chat = document.querySelector('.chat').getBoundingClientRect();

      return {
        maximized: shell?.getAttribute('data-project-panel-state') === 'maximized',
        state: shell?.getAttribute('data-project-panel-state') || "",
        sidebarCollapsed: shell?.getAttribute('data-sidebar-collapsed') === 'true',
        panelLeft: panel.left,
        panelTop: panel.top,
        panelBottom: panel.bottom,
        panelHeight: panel.height,
        chatLeft: chat.left,
        chatTop: chat.top,
        chatBottom: chat.bottom,
        chatHeight: chat.height,
        chatRight: chat.right,
        shellRight: shell.getBoundingClientRect().right,
        sidebarRight: sidebar.right,
        sidebarZIndex: Number(sidebarStyle.zIndex) || 0,
        treeWidth: document.querySelector('.project-files-tree-pane')?.getBoundingClientRect().width ?? 0,
        hasTreeResizeHandle: Boolean(document.querySelector('.project-files-tree-resize-handle')),
        hasTreeToggle: Boolean(document.querySelector('button[aria-label="파일 목록 접기"]')),
        hasPreviewEmpty: Boolean(document.querySelector('.project-files-preview-empty')),
        hasTree: Boolean(document.querySelector('.project-file-tree')),
      };
    })()`,
  });

  const maxTreeResizeStartResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const handle = document.querySelector('.project-files-tree-resize-handle')?.getBoundingClientRect();
      const tree = document.querySelector('.project-files-tree-pane')?.getBoundingClientRect();

      return {
        x: (handle?.left ?? 0) + 3,
        y: (handle?.top ?? 0) + ((handle?.height ?? 0) / 2),
        width: tree?.width ?? 0,
      };
    })()`,
  });
  const maxTreeDragStart = maxTreeResizeStartResult.result.value;

  await send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: maxTreeDragStart.x,
    y: maxTreeDragStart.y,
    button: "left",
    clickCount: 1,
  });
  await send("Input.dispatchMouseEvent", {
    type: "mouseMoved",
    x: maxTreeDragStart.x - 72,
    y: maxTreeDragStart.y,
    button: "left",
  });
  const duringMaxTreeResizeResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      transitionDuration: getComputedStyle(document.querySelector('.project-files-panel')).transitionDuration,
    }))()`,
  });
  await send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: maxTreeDragStart.x - 72,
    y: maxTreeDragStart.y,
    button: "left",
    clickCount: 1,
  });
  await sleep(220);

  const afterMaxTreeResizeResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const shell = document.querySelector('.app-shell');
      const tree = document.querySelector('.project-files-tree-pane')?.getBoundingClientRect();
      const handle = document.querySelector('.project-files-tree-resize-handle');

      return {
        treeWidth: tree?.width ?? 0,
        ariaValue: Number(handle?.getAttribute('aria-valuenow') || 0),
        treeResizing: shell?.getAttribute('data-project-file-tree-resizing') || "",
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('button[aria-label="파일 목록 접기"]')?.click()`,
  });
  await sleep(180);

  const afterMaxTreeCollapseResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const treePane = document.querySelector('.project-files-tree-pane');
      const search = document.querySelector('.project-files-search');
      const tree = document.querySelector('.project-file-tree');
      const handle = document.querySelector('.project-files-tree-resize-handle');

      return {
        collapsed: document.querySelector('.project-files-panel')?.getAttribute('data-tree-collapsed') === 'true',
        treeWidth: treePane?.getBoundingClientRect().width ?? 0,
        searchDisplay: search ? getComputedStyle(search).display : "",
        treeDisplay: tree ? getComputedStyle(tree).display : "",
        handleDisplay: handle ? getComputedStyle(handle).display : "",
        hasOpenButton: Boolean(document.querySelector('button[aria-label="파일 목록 펼치기"]')),
      };
    })()`,
  });

  const collapsedTreeResizeStartResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const handle = document.querySelector('.project-files-tree-resize-handle')?.getBoundingClientRect();

      return {
        x: (handle?.left ?? 0) + 3,
        y: (handle?.top ?? 0) + ((handle?.height ?? 0) / 2),
      };
    })()`,
  });
  const collapsedTreeDragStart = collapsedTreeResizeStartResult.result.value;

  await send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: collapsedTreeDragStart.x,
    y: collapsedTreeDragStart.y,
    button: "left",
    clickCount: 1,
  });
  await send("Input.dispatchMouseEvent", {
    type: "mouseMoved",
    x: collapsedTreeDragStart.x - 72,
    y: collapsedTreeDragStart.y,
    button: "left",
  });
  await send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: collapsedTreeDragStart.x - 72,
    y: collapsedTreeDragStart.y,
    button: "left",
    clickCount: 1,
  });
  await sleep(220);

  const afterCollapsedTreeResizeResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const shell = document.querySelector('.app-shell');
      const treePane = document.querySelector('.project-files-tree-pane');
      const search = document.querySelector('.project-files-search');

      return {
        collapsed: document.querySelector('.project-files-panel')?.getAttribute('data-tree-collapsed') === 'true',
        treeWidth: treePane?.getBoundingClientRect().width ?? 0,
        searchDisplay: search ? getComputedStyle(search).display : "",
        treeResizing: shell?.getAttribute('data-project-file-tree-resizing') || "",
        hasCloseButton: Boolean(document.querySelector('button[aria-label="파일 목록 접기"]')),
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('button[aria-label="파일 목록 접기"]')?.click()`,
  });
  await sleep(180);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('button[aria-label="파일 목록 펼치기"]')?.click()`,
  });
  await sleep(180);

  const afterMaxTreeExpandResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const treePane = document.querySelector('.project-files-tree-pane');
      const search = document.querySelector('.project-files-search');

      return {
        collapsed: document.querySelector('.project-files-panel')?.getAttribute('data-tree-collapsed') === 'true',
        treeWidth: treePane?.getBoundingClientRect().width ?? 0,
        searchDisplay: search ? getComputedStyle(search).display : "",
        hasCloseButton: Boolean(document.querySelector('button[aria-label="파일 목록 접기"]')),
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('button[aria-label="프로젝트 패널 접기"]')?.click()`,
  });
  await sleep(220);

  const afterWholePanelCollapseResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const shell = document.querySelector('.app-shell');
      const panel = document.querySelector('.project-panel');

      return {
        collapsed: shell?.getAttribute('data-project-panel-state') === 'closed',
        maximized: shell?.getAttribute('data-project-panel-state') === 'maximized',
        state: shell?.getAttribute('data-project-panel-state') || "",
        hasPanel: Boolean(panel),
        panelState: panel?.getAttribute('data-state') || "",
        panelAriaHidden: panel?.getAttribute('aria-hidden') || "",
        panelInert: panel?.hasAttribute('inert') || false,
        hasRailButton: Boolean(document.querySelector('.project-panel-rail-toggle')),
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-panel-rail-toggle')?.click()`,
  });
  await sleep(220);

  const afterWholePanelReopenResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const shell = document.querySelector('.app-shell');
      const panel = document.querySelector('.project-panel').getBoundingClientRect();
      const sidebarElement = document.querySelector('.sidebar');
      const sidebar = sidebarElement.getBoundingClientRect();
      const sidebarStyle = getComputedStyle(sidebarElement);
      const chat = document.querySelector('.chat').getBoundingClientRect();

      return {
        collapsed: shell?.getAttribute('data-project-panel-state') === 'closed',
        maximized: shell?.getAttribute('data-project-panel-state') === 'maximized',
        state: shell?.getAttribute('data-project-panel-state') || "",
        sidebarCollapsed: shell?.getAttribute('data-sidebar-collapsed') === 'true',
        panelLeft: panel.left,
        sidebarRight: sidebar.right,
        sidebarZIndex: Number(sidebarStyle.zIndex) || 0,
        chatLeft: chat.left,
        hasPreviewEmpty: Boolean(document.querySelector('.project-files-preview-empty')),
        hasTree: Boolean(document.querySelector('.project-file-tree')),
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `(() => {
      const input = document.querySelector('.project-files-search input');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, '');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`,
  });
  await sleep(120);

  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.project-file-name'))
      .find((item) => item.textContent.includes('02_RAG_Load_Documents'))?.closest('.project-file-row')?.click()`,
  });
  await sleep(220);

  const afterLongPreviewResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const main = document.querySelector('.project-files-main')?.getBoundingClientRect();
      const path = document.querySelector('.project-file-preview-path')?.getBoundingClientRect();

      return {
        hasPreview: Boolean(document.querySelector('.project-file-preview')),
        selectedName: document.querySelector('.project-panel-tab[data-active="true"] > span')?.textContent.trim() || "",
        selectedRow: Boolean(document.querySelector('.project-file-row[data-selected="true"]')),
        mainRight: main?.right ?? 0,
        pathRight: path?.right ?? 0,
        mainOverflow: getComputedStyle(document.querySelector('.project-files-main')).overflow,
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `(() => {
      const row = Array.from(document.querySelectorAll('.project-file-row'))
        .find((item) => item.querySelector('.project-file-name')?.textContent.trim() === 'App.tsx');
      row?.focus();
      row?.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Delete' }));
    })()`,
  });
  await sleep(120);

  const afterDeleteArmResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      visibleFileNames: Array.from(document.querySelectorAll('.project-file-name')).map((item) => item.textContent.trim()),
      activeControl: document.activeElement?.textContent.trim() || '',
      confirmationText: document.querySelector('.project-file-delete-confirmation')?.textContent.trim() || '',
      hasCancelButton: Array.from(document.querySelectorAll('.project-file-delete-confirmation button'))
        .some((button) => button.textContent.trim() === '취소'),
      hasDeleteButton: Array.from(document.querySelectorAll('.project-file-delete-confirmation button'))
        .some((button) => button.textContent.trim() === '삭제'),
    }))()`,
  });

  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.project-file-delete-confirmation button'))
      .find((button) => button.textContent.trim() === '삭제')?.click()`,
  });
  await sleep(200);

  const afterDeleteResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const savedState = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const activeProject = savedState.projects?.find((project) => project.id === savedState.selectedProjectId);

      return {
        storedState: activeProject?.files ?? [],
        visibleFileNames: Array.from(document.querySelectorAll('.project-file-name')).map((item) => item.textContent.trim()),
      };
    })()`,
  });

    await send("Runtime.evaluate", {
      expression: `document.querySelector('.project-files-open-button')?.click()`,
    });
  await sleep(200);

  const afterAddClickResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const savedState = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const activeProject = savedState.projects?.find((project) => project.id === savedState.selectedProjectId);

      return {
          sessionCount: activeProject?.sessions?.length ?? 0,
          selectedSessionId: savedState.selectedSessionId ?? null,
          hasChatPrompt: Boolean(document.querySelector('.prompt')),
          hasOverview: Boolean(document.querySelector('.project-overview')),
          hasPanel: Boolean(document.querySelector('.project-panel')),
        };
    })()`,
  });

	  const value = {
	    library: libraryResult.result.value,
	    librarySearch: librarySearchResult.result.value,
	    singleFileSource: singleFileSourceResult.result.value,
		    initial: initialResult.result.value,
		    afterFilter: afterFilterResult.result.value,
		    afterMaximize: afterMaximizeResult.result.value,
	    duringMaxTreeResize: duringMaxTreeResizeResult.result.value,
    afterMaxTreeResize: afterMaxTreeResizeResult.result.value,
    afterMaxTreeCollapse: afterMaxTreeCollapseResult.result.value,
    afterCollapsedTreeResize: afterCollapsedTreeResizeResult.result.value,
    afterMaxTreeExpand: afterMaxTreeExpandResult.result.value,
    afterWholePanelCollapse: afterWholePanelCollapseResult.result.value,
    afterWholePanelReopen: afterWholePanelReopenResult.result.value,
    afterLongPreview: afterLongPreviewResult.result.value,
    afterDeleteArm: afterDeleteArmResult.result.value,
    afterDelete: afterDeleteResult.result.value,
    afterAddClick: afterAddClickResult.result.value,
  };
  const failures = [];

	  if (!value.library.hasSourcesPanel ||
	      !value.library.sourceNames.includes("desktop") ||
	      !value.library.sourceNames.includes("backend") ||
	      value.library.sourceNames[0] !== "README.md" ||
	      value.library.hasTreeBeforeDetail ||
	      value.library.hasOriginalView ||
	      value.library.sourceSearchPlaceholder !== "자료 검색..." ||
	      !value.library.uploadButtons.includes("자료 추가") ||
	      value.library.timeLabels.length < 2 ||
	      value.library.sourceMenuCount < 3 ||
	      value.library.hasVisibleDeleteButton) {
	    failures.push("sources view should show upload, search, and project sources before opening a source");
	  }

	  if (!value.librarySearch.includes("backend") || value.librarySearch.includes("desktop")) {
	    failures.push("sources search should filter uploaded sources");
	  }

	  if (value.singleFileSource.dataSingleFile !== "true" ||
	      value.singleFileSource.hasTreePane ||
	      value.singleFileSource.hasTreeToggle ||
	      value.singleFileSource.hasTreeSearch ||
	      value.singleFileSource.previewTab !== "README.md" ||
	      value.singleFileSource.rootText !== "README.md") {
	    failures.push("single file sources should open a preview without the side tree");
	  }

	  if (!value.initial.fileNames.includes("desktop") ||
	      !value.initial.fileNames.includes("src") ||
	      !value.initial.fileNames.includes("package.json") ||
	      value.initial.fileNames.includes("backend") ||
	      value.initial.fileCountText !== "6") {
	    failures.push("file panel should render only the selected source tree and item count");
	  }

	  if (value.initial.rootText !== "desktop" ||
	      value.initial.searchPlaceholder !== "파일 필터링..." ||
	      value.initial.uploadButtons.length !== 0) {
	    failures.push("file panel should show Codex-like root path and filter input");
	  }

  if (!value.initial.hasPrompt || value.initial.hasOverview || !value.initial.hasPanel) {
    failures.push("project files should render in the right panel beside chat");
  }

  if (!value.afterFilter.visibleFileNames.includes("App.tsx") ||
      value.afterFilter.visibleFileNames.includes("package.json")) {
    failures.push("file filter should keep matching files and their parent folders only");
  }

  if (!value.afterFilter.appIconColor) {
    failures.push("file panel should apply file-type icon colors");
  }

  if (!value.afterFilter.hasPreviewEmpty ||
      !value.afterFilter.hasTreeResizeHandle ||
      !value.afterFilter.hasTreeToggle ||
      value.afterFilter.panelWidth > 380 ||
      value.afterFilter.previewWidth < 90 ||
      value.afterFilter.treeWidth < 170 ||
      value.afterFilter.treeRovingTabStops !== 1 ||
      value.afterFilter.nestedTreeButtonTabStops !== 0 ||
      !value.afterFilter.hasFileHeader ||
      value.afterFilter.headerBorderBottom === "0px" ||
      !value.afterFilter.panelGridTransition.includes("grid-template-columns")) {
    failures.push("file panel should use one roving tree focus target in the split preview/tree layout before maximizing");
  }

  if (!value.afterMaximize.maximized ||
      value.afterMaximize.state !== "maximized" ||
      (value.afterMaximize.sidebarCollapsed
        ? value.afterMaximize.panelLeft > 2 ||
          value.afterMaximize.sidebarZIndex < 61
        : value.afterMaximize.panelLeft < value.afterMaximize.sidebarRight - 2) ||
      value.afterMaximize.panelTop > value.afterMaximize.chatTop + 4 ||
      value.afterMaximize.panelBottom < value.afterMaximize.chatBottom - 4 ||
      value.afterMaximize.panelHeight < value.afterMaximize.chatHeight - 4 ||
      Math.abs(value.afterMaximize.chatRight - value.afterMaximize.shellRight) > 2 ||
      !value.afterMaximize.hasTreeResizeHandle ||
      !value.afterMaximize.hasTreeToggle ||
      !value.afterMaximize.hasPreviewEmpty ||
      !value.afterMaximize.hasTree) {
    failures.push("file panel maximize should cover the chat area while preserving the left rail");
  }

  if (value.afterMaxTreeResize.treeWidth < value.afterMaximize.treeWidth + 40 ||
      value.afterMaxTreeResize.ariaValue < value.afterMaximize.treeWidth + 40 ||
      value.afterMaxTreeResize.treeResizing !== "false") {
    failures.push("maximized file tree pane should resize by dragging the divider");
  }

  if (value.duringMaxTreeResize.transitionDuration !== "0s") {
    failures.push("file tree drag should not wait on column transition");
  }

  if (!value.afterMaxTreeCollapse.collapsed ||
      value.afterMaxTreeCollapse.treeWidth > 70 ||
      value.afterMaxTreeCollapse.searchDisplay !== "none" ||
      value.afterMaxTreeCollapse.treeDisplay !== "none" ||
      value.afterMaxTreeCollapse.handleDisplay === "none" ||
      !value.afterMaxTreeCollapse.hasOpenButton) {
    failures.push("maximized file tree pane should collapse to a reopen rail");
  }

  if (value.afterCollapsedTreeResize.collapsed ||
      value.afterCollapsedTreeResize.treeWidth < 250 ||
      value.afterCollapsedTreeResize.searchDisplay === "none" ||
      value.afterCollapsedTreeResize.treeResizing !== "false" ||
      !value.afterCollapsedTreeResize.hasCloseButton) {
    failures.push("collapsed file tree pane should resize open by dragging the divider");
  }

  if (value.afterMaxTreeExpand.collapsed ||
      value.afterMaxTreeExpand.treeWidth < value.afterCollapsedTreeResize.treeWidth - 4 ||
      value.afterMaxTreeExpand.searchDisplay === "none" ||
      !value.afterMaxTreeExpand.hasCloseButton) {
    failures.push("collapsed file tree pane should reopen to the resized width");
  }

  if (!value.afterWholePanelCollapse.collapsed ||
      value.afterWholePanelCollapse.maximized ||
      value.afterWholePanelCollapse.state !== "closed" ||
      !value.afterWholePanelCollapse.hasPanel ||
      value.afterWholePanelCollapse.panelState !== "closed" ||
      value.afterWholePanelCollapse.panelAriaHidden !== "true" ||
      !value.afterWholePanelCollapse.panelInert ||
      !value.afterWholePanelCollapse.hasRailButton) {
    failures.push("closing the maximized right panel should preserve one inert closed LayoutPanel");
  }

  if (value.afterWholePanelReopen.collapsed ||
      !value.afterWholePanelReopen.maximized ||
      value.afterWholePanelReopen.state !== "maximized" ||
      (value.afterWholePanelReopen.sidebarCollapsed
        ? value.afterWholePanelReopen.panelLeft > 2 ||
          value.afterWholePanelReopen.sidebarZIndex < 61
        : value.afterWholePanelReopen.panelLeft < value.afterWholePanelReopen.sidebarRight - 2) ||
      !value.afterWholePanelReopen.hasPreviewEmpty ||
      !value.afterWholePanelReopen.hasTree) {
    failures.push("reopening the whole right panel should restore the maximized file layout");
  }

  if (!value.afterLongPreview.hasPreview ||
      !value.afterLongPreview.selectedName.includes("02_RAG_Load_Documents") ||
      !value.afterLongPreview.selectedRow ||
      value.afterLongPreview.mainOverflow !== "hidden" ||
      value.afterLongPreview.pathRight > value.afterLongPreview.mainRight + 1) {
    failures.push("long file preview headers should stay clipped inside the preview pane");
  }

  if (!value.afterDeleteArm.visibleFileNames.includes("App.tsx") ||
      value.afterDeleteArm.activeControl !== "취소" ||
      !value.afterDeleteArm.hasCancelButton ||
      !value.afterDeleteArm.hasDeleteButton ||
      !value.afterDeleteArm.confirmationText.includes("App.tsx") ||
      !value.afterDeleteArm.confirmationText.includes("디스크의 원본은 삭제하지 않습니다") ||
      !value.afterDeleteArm.confirmationText.includes("파생된 메모리")) {
    failures.push("file tree Delete shortcut should open a visible consequence-aware confirmation");
  }

  const storedAfterDelete = JSON.stringify(value.afterDelete.storedState);

  if (storedAfterDelete.includes("App.tsx") ||
      value.afterDelete.visibleFileNames.includes("App.tsx")) {
    failures.push("file tree delete should remove nested entries");
  }

  if (value.afterAddClick.sessionCount !== 1 ||
      !value.afterAddClick.selectedSessionId ||
      !value.afterAddClick.hasChatPrompt ||
      value.afterAddClick.hasOverview ||
      !value.afterAddClick.hasPanel) {
    failures.push("panel file add should keep the active chat and panel");
  }

  debugLayout("project overview files", value);
  return { value, failures };
}

// GitHub 섹션은 로그인, repo 선택, 연결 상태, timeline을 한 패널에서 보여준다.
async function verifyGithubTimelineState(send) {
  const now = Date.now();
  const unlinkedState = createProjectStorage(
    "project-github-unlinked",
    "GitHub Unlinked",
    [
      {
        id: "session-github-unlinked",
        title: "GitHub Chat",
        createdAt: now,
        messages: [],
      },
    ],
    "session-github-unlinked",
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  await send("Runtime.evaluate", {
    expression: `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}, '272'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}, '360'); localStorage.removeItem(${JSON.stringify(PROJECT_COLLAPSED_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(GITHUB_CLIENT_ID_STORAGE_KEY)}, 'smoke-client'); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(unlinkedState)})`,
  });
    await send("Page.navigate", { url: APP_URL });
    await sleep(700);
    await send("Runtime.evaluate", {
      expression: `Array.from(document.querySelectorAll('.project-panel-menu button'))
        .find((button) => button.textContent.includes('GitHub'))?.click()`,
    });
    await waitForSelector(send, ".project-panel .github-panel-content");

    const unlinkedResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
        stateText: document.querySelector('.project-panel-header-status-label')?.textContent.replace('·', '').trim() || "",
        hasLoginCard: Boolean(document.querySelector('.overview-github-login-card')),
        hasLoginTitle: document.body.textContent.includes('GitHub 연결'),
        hasTimelineCopy: document.body.textContent.includes('PR · 이슈'),
        hasLoginButton: Boolean(Array.from(document.querySelectorAll('.overview-github-primary-button')).find((button) => button.textContent.includes('GitHub 로그인'))),
      hasUrlInput: Boolean(document.querySelector('.overview-github-connect-form input')),
      hasConnectedCard: Boolean(document.querySelector('.overview-github-connected-card')),
      hasTimelineRows: Boolean(document.querySelector('.overview-timeline-row')),
    }))()`,
  });

  await send("Runtime.evaluate", {
    expression: `(() => {
      window.__paimOriginalFetch = window.fetch.bind(window);
      window.fetch = async (input) => {
        if (String(input).includes('github.com/login/device/code')) {
          throw new Error('Load failed');
        }

        return window.__paimOriginalFetch(input);
      };
      document.querySelector('.overview-github-primary-button')?.click();
    })()`,
  });
  await sleep(250);

  const failedLoginResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
        const githubPanel = document.querySelector('.project-panel');
        const githubStatus = githubPanel?.querySelector('.runtime-status');
      const status = document.querySelector('.runtime-status');
      return {
        githubPanelHasStatus: Boolean(githubStatus),
        githubStatusText: githubStatus?.textContent.trim() ?? "",
        sidebarHasRuntimeStatus: Boolean(document.querySelector('.sidebar .runtime-status')),
        runtimeStatusCount: document.querySelectorAll('.runtime-status').length,
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `(() => {
      window.open = (url) => {
        window.__paimOpenedUrl = String(url);
        return null;
      };
      window.fetch = async (input, init) => {
        const url = String(input);

        if (url.includes('github.com/login/device/code') && init?.method === 'POST') {
          return new Response(JSON.stringify({
            device_code: 'smoke-device',
            user_code: 'SMOKE-123',
            verification_uri: 'https://github.com/login/device',
            expires_in: 900,
            interval: 5,
          }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        return window.__paimOriginalFetch(input, init);
      };
      document.querySelector('.overview-github-primary-button')?.click();
    })()`,
  });
  await sleep(800);

  const authingResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      stateText: document.querySelector('.project-panel-header-status-label')?.textContent.replace('·', '').trim() || "",
      openedUrl: window.__paimOpenedUrl || "",
      hasAuthCard: Boolean(document.querySelector('.overview-github-auth-card')),
      hasWaitingText: document.body.textContent.includes('브라우저에서 GitHub 연결을 완료해 주세요'),
      hasCheckButton: Boolean(Array.from(document.querySelectorAll('.overview-github-auth-card button')).find((button) => button.textContent.includes('로그인 완료했어요'))),
    }))()`,
  });

  await send("Runtime.evaluate", {
    expression: `(() => {
      const events = [
        {
          id: 'github-pr',
          type: 'pull_request',
          title: 'PR #18 프로젝트 Overview 연결',
          status: 'open',
          createdAt: ${now - 1000 * 60 * 30},
        },
        {
          id: 'github-issue',
          type: 'issue',
          title: 'issue #21 파일 목록 스크롤',
          status: 'open',
          createdAt: ${now - 1000 * 60 * 60 * 3},
        },
        {
          id: 'github-commit',
          type: 'commit',
          title: 'feat: project file management',
          createdAt: ${now - 1000 * 60 * 60 * 8},
        },
      ];

      window.fetch = async (input, init) => {
        const url = String(input);

        if (url.includes('github.com/login/oauth/access_token') && init?.method === 'POST') {
          return new Response(JSON.stringify({
            access_token: 'smoke-token',
            token_type: 'bearer',
            scope: 'repo read:user',
          }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        if (url.includes('api.github.com/user/repos')) {
          return new Response(JSON.stringify([
            {
              full_name: 'j3s30p/Stampy',
              name: 'Stampy',
              private: true,
              default_branch: 'main',
              html_url: 'https://github.com/j3s30p/Stampy',
            },
            {
              full_name: 'j3s30p/PaiM',
              name: 'PaiM',
              private: false,
              default_branch: 'main',
              html_url: 'https://github.com/j3s30p/PaiM',
            },
          ]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        if (url === 'https://api.github.com/user') {
          return new Response(JSON.stringify({
            avatar_url: '',
            html_url: 'https://github.com/j3s30p',
            login: 'j3s30p',
            name: 'Smoke User',
          }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        if (url.includes('api.github.com/repos/j3s30p/Stampy/commits')) {
          return new Response(JSON.stringify([
            {
              html_url: 'https://github.com/j3s30p/Stampy/commit/smoke',
              sha: 'abcdef123456',
              commit: {
                author: { date: new Date(${now - 1000 * 60 * 60 * 8}).toISOString() },
                message: 'feat: project file management',
              },
            },
          ]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        if (url.includes('api.github.com/repos/j3s30p/Stampy/issues')) {
          return new Response(JSON.stringify([
            {
              html_url: 'https://github.com/j3s30p/Stampy/issues/21',
              number: 21,
              title: '파일 목록 스크롤',
              state: 'open',
              updated_at: new Date(${now - 1000 * 60 * 60 * 3}).toISOString(),
            },
          ]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        if (url.includes('api.github.com/repos/j3s30p/Stampy/pulls')) {
          return new Response(JSON.stringify([
            {
              html_url: 'https://github.com/j3s30p/Stampy/pull/18',
              number: 18,
              title: '프로젝트 Overview 연결',
              state: 'open',
              updated_at: new Date(${now - 1000 * 60 * 30}).toISOString(),
            },
          ]), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        if (url.includes('api.github.com/repos/j3s30p/Stampy')) {
          return new Response(JSON.stringify({
            default_branch: 'main',
            full_name: 'j3s30p/Stampy',
            html_url: 'https://github.com/j3s30p/Stampy',
            name: 'Stampy',
            private: true,
          }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        if (url.includes('/github/sync')) {
          return new Response(JSON.stringify({ ok: true }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }

        return window.__paimOriginalFetch(input, init);
      };
      Array.from(document.querySelectorAll('.overview-github-auth-card button'))
        .find((button) => button.textContent.includes('로그인 완료했어요'))?.click();
    })()`,
  });
  await sleep(800);

  const reposResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      stateText: document.querySelector('.project-panel-header-status-label')?.textContent.replace('·', '').trim() || "",
      hasReposCard: Boolean(document.querySelector('.overview-github-repos-card')),
      hasSearchInput: Boolean(document.querySelector('.overview-github-search input')),
      repoNames: Array.from(document.querySelectorAll('.overview-github-repo-copy p')).map((item) => item.textContent.trim()),
      visibilityLabels: Array.from(document.querySelectorAll('.overview-github-repo-visibility')).map((item) => item.textContent.trim()),
      hasLogoutButton: Boolean(Array.from(document.querySelectorAll('.overview-github-toolbar button')).find((button) => button.textContent.includes('로그아웃'))),
      hasUrlInput: Boolean(document.querySelector('.overview-github-connect-form input')),
    }))()`,
  });

  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.overview-github-repo-row button'))
      .find((button) => button.textContent.includes('연결'))?.click()`,
  });
  await waitForSelector(send, ".overview-github-connected-card");
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.overview-github-more-menu')?.click()`,
  });
  await sleep(80);

  const linkedResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      titles: Array.from(document.querySelectorAll('.overview-timeline-row p')).map((item) => item.textContent.trim()),
      meta: Array.from(document.querySelectorAll('.overview-timeline-row small')).map((item) => item.textContent.trim()),
      labels: Array.from(document.querySelectorAll('.overview-timeline-label')).map((item) => item.textContent.trim()),
      repoName: document.querySelector('.overview-github-repo-name')?.textContent.trim() || "",
      repoMeta: document.querySelector('.overview-github-meta')?.textContent.trim() || "",
      stateText: document.querySelector('.project-panel-header-status-label')?.textContent.replace('·', '').trim() || "",
      visibleIconCount: Array.from(document.querySelectorAll('.overview-timeline-icon .tabler-icon')).filter((item) => {
        const rect = item.getBoundingClientRect();
        return rect.width >= 12 && rect.height >= 12;
      }).length,
      boxedIconCount: Array.from(document.querySelectorAll('.overview-timeline-icon .tabler-icon')).filter((item) => (
        getComputedStyle(item).backgroundColor !== 'rgba(0, 0, 0, 0)'
      )).length,
      hasConnectedCard: Boolean(document.querySelector('.overview-github-connected-card')),
      hasSyncButton: Boolean(document.querySelector('button[aria-label="GitHub 동기화"]')),
      hasChangeButton: Boolean(Array.from(document.querySelectorAll('[role="menuitem"]')).find((item) => item.textContent.includes('repo 변경'))),
      hasDisconnectButton: Boolean(Array.from(document.querySelectorAll('[role="menuitem"]')).find((item) => item.textContent.includes('연결 해제'))),
    }))()`,
  });

  const value = {
    unlinked: unlinkedResult.result.value,
    failedLogin: failedLoginResult.result.value,
    authing: authingResult.result.value,
    repos: reposResult.result.value,
    linked: linkedResult.result.value,
  };
  const failures = [];

  if (value.unlinked.stateText !== "미연결" ||
        !value.unlinked.hasLoginCard ||
        !value.unlinked.hasLoginTitle ||
        !value.unlinked.hasTimelineCopy ||
      !value.unlinked.hasLoginButton ||
      value.unlinked.hasUrlInput ||
      value.unlinked.hasConnectedCard ||
      value.unlinked.hasTimelineRows) {
    failures.push("unlinked GitHub panel should show the reference login card only");
  }

  if (!value.failedLogin.githubPanelHasStatus ||
      !value.failedLogin.githubStatusText.includes("GitHub 로그인 서버에 연결할 수 없습니다") ||
      value.failedLogin.sidebarHasRuntimeStatus ||
      value.failedLogin.runtimeStatusCount !== 1) {
    failures.push("GitHub login failure status should render inside the GitHub panel only");
  }

  if (value.authing.stateText !== "로그인 중" ||
      !value.authing.openedUrl.includes("github.com/login/device") ||
      !value.authing.hasAuthCard ||
      !value.authing.hasWaitingText ||
      !value.authing.hasCheckButton) {
    failures.push("GitHub authing state should render the browser login waiting card");
  }

  if (value.repos.stateText !== "로그인됨" ||
      !value.repos.hasReposCard ||
      !value.repos.hasSearchInput ||
      !value.repos.repoNames.includes("j3s30p/Stampy") ||
      !value.repos.repoNames.includes("j3s30p/PaiM") ||
      !value.repos.visibilityLabels.includes("PRIVATE") ||
      !value.repos.visibilityLabels.includes("PUBLIC") ||
      !value.repos.hasLogoutButton ||
      value.repos.hasUrlInput) {
    failures.push("GitHub repos state should render searchable repositories without the old URL form");
  }

  if (value.linked.stateText !== "연결됨" ||
      !value.linked.hasConnectedCard ||
      value.linked.hasChangeButton ||
      !value.linked.hasDisconnectButton ||
      !value.linked.titles.includes("프로젝트 Overview 연결") ||
      !value.linked.titles.includes("파일 목록 스크롤") ||
      !value.linked.titles.includes("feat: project file management")) {
    failures.push("linked GitHub timeline should render issue, PR, and commit events");
  }

  if (!value.linked.labels.includes("PR #18") ||
      !value.linked.labels.includes("ISSUE #21") ||
      !value.linked.labels.includes("COMMIT")) {
    failures.push("linked GitHub timeline should label event types");
  }

  if (value.linked.visibleIconCount !== 3) {
    failures.push("linked GitHub timeline should render visible event icons");
  }

  if (value.linked.boxedIconCount !== 0) {
    failures.push("linked GitHub timeline icons should not render boxed backgrounds");
  }

  if (!value.linked.repoName.includes("Stampy") ||
      !value.linked.repoMeta.includes("main") ||
      !value.linked.repoMeta.includes("j3s30p")) {
    failures.push("linked GitHub timeline should show repository metadata");
  }

  debugLayout("github timeline", value);
  return { value, failures };
}

// GitHub 지연 작업을 취소하면 늦은 응답이 인증/연결 상태를 되살리지 않아야 한다.
async function verifyGithubOperationOwnership(send) {
  const now = Date.now();
  const unlinkedState = createProjectStorage(
    "project-github-ownership",
    "GitHub Ownership",
    [
      {
        id: "session-github-ownership",
        title: "GitHub Ownership Chat",
        createdAt: now,
        messages: [],
      },
    ],
    "session-github-ownership",
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 820,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await navigateAndWaitForSelector(send, APP_URL, ".app-shell");
  await send("Runtime.evaluate", {
    expression: `(() => {
      const settings = JSON.parse(
        localStorage.getItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}) || '{}',
      );
      settings.language = 'ko';
      settings.serverUrl = ${JSON.stringify(API_SERVER_A)};
      localStorage.setItem(${JSON.stringify(SETTINGS_STORAGE_KEY)}, JSON.stringify(settings));
      localStorage.setItem(${JSON.stringify(AUTH_SCENARIO_STORAGE_KEY)}, 'owner');
      localStorage.setItem(${JSON.stringify(AUTH_STORAGE_KEY)}, ${JSON.stringify(JSON.stringify(AUTH_SESSION))});
      localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)});
      localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false');
      localStorage.setItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}, '272');
      localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'false');
      localStorage.setItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}, '420');
      localStorage.removeItem(${JSON.stringify(PROJECT_COLLAPSED_STORAGE_KEY)});
      localStorage.setItem(${JSON.stringify(GITHUB_CLIENT_ID_STORAGE_KEY)}, 'smoke-client');
      localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(unlinkedState)});
    })()`,
  });
  await navigateAndWaitForSelector(send, APP_URL, ".project-panel-menu");
  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.project-panel-menu button'))
      .find((button) => button.textContent.includes('GitHub'))?.click()`,
  });
  await waitForSelector(send, ".github-panel-content");
  const githubStartedConnected = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `Boolean(document.querySelector('.overview-github-connected-card'))`,
  });
  // 앞선 timeline 시나리오의 마지막 저장 effect가 navigation과 겹쳐도
  // 공개 repo 연결을 실제 UI로 해제해 이 소유권 검사를 독립 상태로 시작한다.
  if (githubStartedConnected.result.value) {
    await send("Runtime.evaluate", {
      expression: `document.querySelector('.overview-github-more-menu')?.click()`,
    });
    await waitForSelector(send, '[role="menuitem"]');
    await send("Runtime.evaluate", {
      expression: `Array.from(document.querySelectorAll('[role="menuitem"]'))
        .find((item) => item.textContent.includes('연결 해제'))?.click()`,
    });
  }
  await waitForSelector(send, ".overview-github-login-card");

  await send("Runtime.evaluate", {
    expression: `(() => {
      window.__paimGithubOwnershipBaseFetch = window.fetch.bind(window);
      window.__paimGithubOwnership = {
        delayedCheckResolved: 0,
        delayedConnectResolved: 0,
        mode: 'device',
      };
      window.open = (url) => {
        window.__paimGithubOwnership.openedUrl = String(url);
        return null;
      };
      const response = (payload, status = 200) => Promise.resolve(new Response(
        JSON.stringify(payload),
        { status, headers: { 'Content-Type': 'application/json' } },
      ));
      const repository = (name, isPrivate) => ({
        default_branch: 'main',
        full_name: 'j3s30p/' + name,
        html_url: 'https://github.com/j3s30p/' + name,
        name,
        owner: {
          avatar_url: '',
          html_url: 'https://github.com/j3s30p',
          login: 'j3s30p',
        },
        private: isPrivate,
      });
      window.fetch = (input, init = {}) => {
        const url = typeof input === 'string'
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
        const state = window.__paimGithubOwnership;

        if (url.includes('github.com/login/device/code')) {
          return response({
            device_code: 'ownership-device',
            user_code: 'OWNER-123',
            verification_uri: 'https://github.com/login/device',
            expires_in: 900,
            interval: 5,
          });
        }

        if (url.includes('github.com/login/oauth/access_token')) {
          if (state.mode === 'check-delay') {
            return new Promise((resolve) => {
              window.setTimeout(() => {
                state.delayedCheckResolved += 1;
                resolve(new Response(JSON.stringify({
                  access_token: 'late-check-token',
                  token_type: 'bearer',
                  scope: 'repo read:user',
                }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
              }, 650);
            });
          }

          return response({
            access_token: 'ownership-token',
            token_type: 'bearer',
            scope: 'repo read:user',
          });
        }

        if (url.includes('api.github.com/user/installations')) {
          return response({ installations: [] });
        }

        if (url.includes('api.github.com/user/repos')) {
          return response([
            repository('Stampy', true),
            repository('PaiM', false),
          ]);
        }

        if (url === 'https://api.github.com/user') {
          return response({
            avatar_url: '',
            html_url: 'https://github.com/j3s30p',
            login: 'j3s30p',
            name: 'Smoke User',
          });
        }

        if (url === 'https://api.github.com/repos/j3s30p/Stampy') {
          if (state.mode === 'connect-delay') {
            return new Promise((resolve) => {
              window.setTimeout(() => {
                state.delayedConnectResolved += 1;
                resolve(new Response(JSON.stringify(repository('Stampy', true)), {
                  status: 200,
                  headers: { 'Content-Type': 'application/json' },
                }));
              }, 650);
            });
          }
          return response(repository('Stampy', true));
        }

        if (url.includes('api.github.com/repos/j3s30p/Stampy/commits')) {
          return response([]);
        }
        if (url.includes('api.github.com/repos/j3s30p/Stampy/issues')) {
          return response([]);
        }
        if (url.includes('api.github.com/repos/j3s30p/Stampy/pulls')) {
          return response([]);
        }

        return window.__paimGithubOwnershipBaseFetch(input, init);
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.overview-github-primary-button')?.click()`,
  });
  await waitForSelector(send, ".overview-github-auth-card");
  await send("Runtime.evaluate", {
    expression: `window.__paimGithubOwnership.mode = 'check-delay'; Array.from(document.querySelectorAll('.overview-github-auth-card button')).find((button) => button.textContent.includes('로그인 완료했어요'))?.click()`,
  });
  await sleep(80);

  const checkingResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      checkingLabel: Array.from(document.querySelectorAll('.overview-github-auth-card button')).find((button) => button.textContent.includes('확인 중'))?.textContent.trim() || "",
      stateText: document.querySelector('.project-panel-header-status-label')?.textContent.replace('·', '').trim() || "",
    }))()`,
  });

  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.overview-github-auth-card button')).find((button) => button.textContent.trim() === '취소')?.click()`,
  });
  await sleep(780);

  const afterCheckCancelResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      delayedCheckResolved: window.__paimGithubOwnership.delayedCheckResolved,
      hasLoginCard: Boolean(document.querySelector('.overview-github-login-card')),
      hasReposCard: Boolean(document.querySelector('.overview-github-repos-card')),
      stateText: document.querySelector('.project-panel-header-status-label')?.textContent.replace('·', '').trim() || "",
    }))()`,
  });

  await send("Runtime.evaluate", {
    expression: `window.__paimGithubOwnership.mode = 'device'; document.querySelector('.overview-github-primary-button')?.click()`,
  });
  await waitForSelector(send, ".overview-github-auth-card");
  await send("Runtime.evaluate", {
    expression: `window.__paimGithubOwnership.mode = 'ready'; Array.from(document.querySelectorAll('.overview-github-auth-card button')).find((button) => button.textContent.includes('로그인 완료했어요'))?.click()`,
  });
  await waitForSelector(send, ".overview-github-repos-card");
  await send("Runtime.evaluate", {
    expression: `window.__paimGithubOwnership.mode = 'connect-delay'; Array.from(document.querySelectorAll('.overview-github-repo-row')).find((row) => row.textContent.includes('j3s30p/Stampy'))?.querySelector('button')?.click()`,
  });
  await sleep(80);

  const targetedConnectResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      rows: Array.from(document.querySelectorAll('.overview-github-repo-row')).map((row) => ({
        buttonDisabled: Boolean(row.querySelector('button')?.disabled),
        buttonText: row.querySelector('button')?.textContent.trim() || "",
        repo: row.querySelector('.overview-github-repo-copy p')?.textContent.trim() || "",
      })),
      stateText: document.querySelector('.project-panel-header-status-label')?.textContent.replace('·', '').trim() || "",
    }))()`,
  });

  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.overview-github-toolbar button')).find((button) => button.textContent.includes('로그아웃'))?.click()`,
  });
  await sleep(800);

  const afterConnectResetResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      delayedConnectResolved: window.__paimGithubOwnership.delayedConnectResolved,
      hasConnectedCard: Boolean(document.querySelector('.overview-github-connected-card')),
      hasLoginCard: Boolean(document.querySelector('.overview-github-login-card')),
      hasReposCard: Boolean(document.querySelector('.overview-github-repos-card')),
      stateText: document.querySelector('.project-panel-header-status-label')?.textContent.replace('·', '').trim() || "",
    }))()`,
  });

  const value = {
    afterCheckCancel: afterCheckCancelResult.result.value,
    afterConnectReset: afterConnectResetResult.result.value,
    checking: checkingResult.result.value,
    targetedConnect: targetedConnectResult.result.value,
  };
  const failures = [];
  const stampyRow = value.targetedConnect.rows.find((row) => row.repo === "j3s30p/Stampy");
  const paimRow = value.targetedConnect.rows.find((row) => row.repo === "j3s30p/PaiM");

  if (!value.checking.checkingLabel.includes("확인 중") || value.checking.stateText !== "로그인 중") {
    failures.push("GitHub auth check should expose immediate checking feedback");
  }

  if (value.afterCheckCancel.delayedCheckResolved !== 1 ||
      !value.afterCheckCancel.hasLoginCard ||
      value.afterCheckCancel.hasReposCard ||
      value.afterCheckCancel.stateText !== "미연결") {
    failures.push("cancelling GitHub auth check should keep the signed-out state after a late token response");
  }

  if (!stampyRow || !paimRow ||
      stampyRow.buttonText !== "연결 중..." ||
      paimRow.buttonText !== "연결" ||
      !stampyRow.buttonDisabled ||
      !paimRow.buttonDisabled) {
    failures.push("GitHub connecting feedback should identify only the target repo row while preventing duplicate connects");
  }

  if (value.afterConnectReset.delayedConnectResolved !== 1 ||
      !value.afterConnectReset.hasLoginCard ||
      value.afterConnectReset.hasReposCard ||
      value.afterConnectReset.hasConnectedCard ||
      value.afterConnectReset.stateText !== "미연결") {
    failures.push("resetting GitHub login should prevent a late repository response from restoring connection state");
  }

  debugLayout("github operation ownership", value);
  return { value, failures };
}

// macOS 사이드바 토글은 접기 전후에도 신호등 옆의 같은 toolbar 좌표를 유지한다.
async function verifySidebarToggleChromeGeometry(send) {
  const projectHomeState = createProjectStorage(
    "project-sidebar-anchor",
    "Sidebar Anchor Project",
    [],
    null,
    [],
    { apiProjectId: 1 },
  );
  const scenarios = [
    { width: 1280, height: 800, deviceScaleFactor: 1, autoCollapsed: false },
    { width: 960, height: 680, deviceScaleFactor: 1, autoCollapsed: false },
    { width: 480, height: 340, deviceScaleFactor: 2, autoCollapsed: true },
  ];
  const value = [];
  const failures = [];

  const measure = async () => {
    const result = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => {
        const shell = document.querySelector('.app-shell');
        const sidebar = document.querySelector('.sidebar');
        const button = document.querySelector('.sidebar-collapse-button');
        if (!shell || !sidebar || !button) return null;
        const buttonBox = button.getBoundingClientRect();
        const sidebarBox = sidebar.getBoundingClientRect();
        const shellStyle = getComputedStyle(shell);
        const centerTarget = document.elementFromPoint(
          buttonBox.left + buttonBox.width / 2,
          buttonBox.top + buttonBox.height / 2,
        );
        return {
          button: {
            bottom: buttonBox.bottom,
            height: buttonBox.height,
            left: buttonBox.left,
            right: buttonBox.right,
            top: buttonBox.top,
            width: buttonBox.width,
          },
          buttonCount: document.querySelectorAll('.sidebar-collapse-button').length,
          buttonDisabled: button.matches(':disabled'),
          buttonLabel: button.getAttribute('aria-label') || '',
          collapsed: shell.getAttribute('data-sidebar-collapsed') === 'true',
          documentScrollWidth: document.documentElement.scrollWidth,
          highZoomViewport: matchMedia('(max-width: 720px)').matches,
          hitTarget: centerTarget === button || Boolean(centerTarget?.closest('.sidebar-collapse-button')),
          innerWidth,
          ownedByAppChrome: Boolean(button.closest('.app-chrome')),
          ownedBySidebar: Boolean(button.closest('.sidebar')),
          platform: shell.getAttribute('data-platform') || '',
          projectHomeNameCount: document.querySelectorAll('.project-home-name').length,
          projectLabelCount: document.querySelectorAll('.chrome-project-area').length,
          sidebar: {
            left: sidebarBox.left,
            right: sidebarBox.right,
            width: sidebarBox.width,
          },
          windowControlClusterWidth: Number.parseFloat(
            shellStyle.getPropertyValue('--window-control-cluster-width'),
          ),
        };
      })()`,
    });
    return result.result.value;
  };

  const checkSnapshot = (snapshot, label) => {
    if (!snapshot) {
      failures.push(`${label} should expose sidebar toggle geometry`);
      return;
    }
    const expectedLeft = snapshot.windowControlClusterWidth - 36;
    const expectedRight = snapshot.windowControlClusterWidth - 8;
    if (Math.abs(snapshot.button.width - 28) > 0.5 ||
        Math.abs(snapshot.button.height - 28) > 0.5 ||
        Math.abs(snapshot.button.top - 8) > 1 ||
        Math.abs(snapshot.button.bottom - 36) > 1) {
      failures.push(`${label} should keep the 28px toggle on the 44px toolbar axis`);
    }
    if (snapshot.platform === "macos" &&
        (Math.abs(snapshot.button.left - expectedLeft) > 0.75 ||
          Math.abs(snapshot.button.right - expectedRight) > 0.75)) {
      failures.push(`${label} should stay anchored immediately after native traffic lights`);
    }
    if (snapshot.platform === "macos" &&
        (!snapshot.ownedByAppChrome || snapshot.ownedBySidebar)) {
      failures.push(`${label} should keep the macOS sidebar toggle in the shared app chrome`);
    }
    if (snapshot.buttonCount !== 1 || !snapshot.hitTarget) {
      failures.push(`${label} should keep one visible sidebar toggle target`);
    }
    if (!snapshot.highZoomViewport && snapshot.buttonDisabled) {
      failures.push(`${label} should keep the sidebar toggle enabled at a normal desktop size`);
    }
    if (snapshot.projectLabelCount !== 0 || snapshot.projectHomeNameCount !== 1) {
      failures.push(`${label} should keep one project-home title without a duplicate chrome label`);
    }
    if (snapshot.documentScrollWidth > snapshot.innerWidth) {
      failures.push(`${label} should not create horizontal document overflow`);
    }
  };

  for (const scenario of scenarios) {
    await send("Emulation.setDeviceMetricsOverride", {
      width: scenario.width,
      height: scenario.height,
      deviceScaleFactor: scenario.deviceScaleFactor,
      mobile: false,
    });
    await navigateAndWaitForSelector(send, APP_URL, ".app-shell");
    await evaluateAndNavigateToSelector(
      send,
      `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false'); localStorage.setItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}, '272'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'true'); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(projectHomeState)})`,
      APP_URL,
      ".project-home",
    );
    await sleep(360);

    if (scenario.autoCollapsed) {
      const collapsed = await measure();
      value.push({ scenario, collapsed });
      checkSnapshot(collapsed, `${scenario.width}x${scenario.height} auto-collapsed sidebar`);
      if (!collapsed?.collapsed || Math.abs((collapsed?.sidebar.width ?? 0) - 52) > 1) {
        failures.push(`${scenario.width}x${scenario.height} should use the 52px accessibility rail`);
      }
      if (!collapsed?.buttonDisabled || !collapsed?.buttonLabel.includes("창을 넓혀")) {
        failures.push(`${scenario.width}x${scenario.height} forced rail should explain why it cannot expand`);
      }
      continue;
    }

    const expanded = await measure();
    await send("Runtime.evaluate", {
      expression: `document.querySelector('.sidebar-collapse-button')?.click()`,
    });
    await sleep(360);
    const collapsed = await measure();
    await send("Runtime.evaluate", {
      expression: `document.querySelector('.sidebar-collapse-button')?.click()`,
    });
    await sleep(360);
    const reopened = await measure();
    value.push({ scenario, expanded, collapsed, reopened });

    checkSnapshot(expanded, `${scenario.width}x${scenario.height} expanded sidebar`);
    checkSnapshot(collapsed, `${scenario.width}x${scenario.height} collapsed sidebar`);
    checkSnapshot(reopened, `${scenario.width}x${scenario.height} reopened sidebar`);

    if (expanded?.collapsed || !collapsed?.collapsed || reopened?.collapsed) {
      failures.push(`${scenario.width}x${scenario.height} should preserve expanded/collapsed/expanded states`);
    }
    if (Math.abs((expanded?.sidebar.width ?? 0) - 272) > 1 ||
        Math.abs((collapsed?.sidebar.width ?? 0) - 52) > 1 ||
        Math.abs((reopened?.sidebar.width ?? 0) - 272) > 1) {
      failures.push(`${scenario.width}x${scenario.height} should preserve 272px sidebar and 52px rail widths`);
    }
    if (expanded && collapsed && reopened &&
        (Math.abs(expanded.button.left - collapsed.button.left) > 0.75 ||
          Math.abs(expanded.button.top - collapsed.button.top) > 0.75 ||
          Math.abs(expanded.button.left - reopened.button.left) > 0.75 ||
          Math.abs(expanded.button.top - reopened.button.top) > 0.75)) {
      failures.push(`${scenario.width}x${scenario.height} toggle should not jump when the sidebar changes state`);
    }
  }

  // Keep the breadcrumb check in the non-overlay desktop layout so chrome remains interactive.
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 800,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithProject(send);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.sidebar-collapse-button')?.click()`,
  });
  await sleep(360);
  const breadcrumbResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const button = document.querySelector('.sidebar-collapse-button');
      const context = document.querySelector('.chat-context-bar');
      const project = document.querySelector('.chat-context-project');
      const separator = document.querySelector('.chat-context-separator');
      const title = document.querySelector('.chat-context-title');
      if (!button || !context || !project || !separator || !title) return null;
      const buttonBox = button.getBoundingClientRect();
      const contextBox = context.getBoundingClientRect();
      return {
        buttonRight: buttonBox.right,
        contextLeft: contextBox.left,
        ownedByAppChrome: Boolean(button.closest('.app-chrome')),
        projectLabelCount: document.querySelectorAll('.chrome-project-area').length,
        projectText: project.textContent?.trim() || '',
        separatorVisible: getComputedStyle(separator).display !== 'none',
        titleText: title.textContent?.trim() || '',
      };
    })()`,
  });
  const breadcrumb = breadcrumbResult.result.value;
  value.push({ chatBreadcrumb: breadcrumb });
  if (!breadcrumb ||
      !breadcrumb.ownedByAppChrome ||
      breadcrumb.projectLabelCount !== 0 ||
      breadcrumb.projectText !== "Smoke Project" ||
      !breadcrumb.separatorVisible ||
      !breadcrumb.titleText.includes("Smoke Chat") ||
      breadcrumb.contextLeft - breadcrumb.buttonRight < 7.5) {
    failures.push("collapsed chat should keep one non-overlapping project/session breadcrumb after the chrome toggle");
  }

  debugLayout("sidebar toggle chrome geometry", value);
  return { value, failures };
}

// 접은 사이드바 상태가 reload 이후에도 유지되는지 확인한다.
async function verifySidebarPersistence(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithProject(send);
  await send("Runtime.evaluate", {
    expression: `localStorage.removeItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)})`,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.sidebar-collapse-button')?.click()`,
  });
  await sleep(200);
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const shell = document.querySelector('.app-shell');
      const prompt = document.querySelector('.prompt').getBoundingClientRect();
      return {
        collapsed: shell?.getAttribute('data-sidebar-collapsed') === 'true',
        stored: localStorage.getItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}) || "",
        scrollWidth: document.documentElement.scrollWidth,
        prompt: {
          left: prompt.left,
          right: prompt.right,
        },
      };
    })()`,
  });
  const value = result.result.value;
  const failures = [];

  if (!value.collapsed) {
    failures.push("sidebar collapsed state should persist after reload");
  }

  if (value.stored !== "true") {
    failures.push("sidebar collapsed state should be stored in localStorage");
  }

  if (value.scrollWidth > 960) {
    failures.push(`collapsed reload should not overflow horizontally: ${value.scrollWidth} > 960`);
  }

  assertInside("prompt after collapsed reload", value.prompt, 960, failures);

  return { value, failures };
}

// 사이드바 드래그 리사이즈와 선택 프로젝트 채팅 유지 여부를 확인한다.
async function verifySidebarResizeAndProjectContext(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithProject(send);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-panel-collapse-toggle')?.click()`,
  });
  await sleep(200);

  const dragStartResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const sidebar = document.querySelector('.sidebar').getBoundingClientRect();
      return { x: sidebar.right - 2, y: sidebar.top + 120, width: sidebar.width };
    })()`,
  });
  const dragStart = dragStartResult.result.value;

  await send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: dragStart.x,
    y: dragStart.y,
    button: "left",
    clickCount: 1,
  });
  await send("Input.dispatchMouseEvent", {
    type: "mouseMoved",
    x: dragStart.x + 64,
    y: dragStart.y,
    button: "left",
  });
  await send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: dragStart.x + 64,
    y: dragStart.y,
    button: "left",
    clickCount: 1,
  });
  await sleep(220);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const sidebar = document.querySelector('.sidebar').getBoundingClientRect();
      return {
        resizedWidth: sidebar.width,
        storedWidth: Number(localStorage.getItem(${JSON.stringify(SIDEBAR_WIDTH_STORAGE_KEY)}) || 0),
        sessionCountAfterResize: document.querySelectorAll('.history-row').length,
      };
    })()`,
  });
  const value = result.result.value;
  const failures = [];

  if (value.resizedWidth < dragStart.width + 40) {
    failures.push(`sidebar drag should widen the sidebar: ${value.resizedWidth} <= ${dragStart.width}`);
  }

  if (value.storedWidth < dragStart.width + 40) {
    failures.push("resized sidebar width should be stored in localStorage");
  }

  if (value.sessionCountAfterResize !== 1) {
    failures.push("selected project sessions should remain visible after sidebar resize");
  }

  return { value, failures };
}

// 우측 프로젝트 패널이 드래그로 넓어지고 폭이 저장되는지 확인한다.
async function verifyProjectPanelResize(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 820,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithProject(send);

  const dragStartResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const panel = document.querySelector('.project-panel').getBoundingClientRect();
      const handle = document.querySelector('.project-panel-resize-handle').getBoundingClientRect();
      return {
        x: handle.left + handle.width / 2,
        y: handle.top + 120,
        width: panel.width,
      };
    })()`,
  });
  const dragStart = dragStartResult.result.value;

  await send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: dragStart.x,
    y: dragStart.y,
    button: "left",
    clickCount: 1,
  });
  await send("Input.dispatchMouseEvent", {
    type: "mouseMoved",
    x: dragStart.x - 72,
    y: dragStart.y,
    button: "left",
  });
  const duringResizeResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `getComputedStyle(document.querySelector('.app-shell')).transitionDuration`,
  });
  await send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: dragStart.x - 72,
    y: dragStart.y,
    button: "left",
    clickCount: 1,
  });
  await sleep(220);

  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const panel = document.querySelector('.project-panel').getBoundingClientRect();
      const handle = document.querySelector('.project-panel-resize-handle');
      return {
        resizedWidth: panel.width,
        storedWidth: Number(localStorage.getItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}) || 0),
        ariaValue: Number(handle?.getAttribute('aria-valuenow') || 0),
        isAstryxHandle: Boolean(handle?.classList.contains('astryx-resize-handle')),
        orientation: handle?.getAttribute('aria-orientation') || "",
        resizing: handle?.hasAttribute('data-resizing') ?? false,
        role: handle?.getAttribute('role') || "",
      };
    })()`,
  });
  const value = result.result.value;
  value.transitionDuration = duringResizeResult.result.value;
  const failures = [];

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-panel-resize-handle')?.focus()`,
  });
  await send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "ArrowLeft",
    code: "ArrowLeft",
    windowsVirtualKeyCode: 37,
    nativeVirtualKeyCode: 37,
  });
  await send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "ArrowLeft",
    code: "ArrowLeft",
    windowsVirtualKeyCode: 37,
    nativeVirtualKeyCode: 37,
  });
  await sleep(120);

  const keyboardResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const panel = document.querySelector('.project-panel').getBoundingClientRect();
      const handle = document.querySelector('.project-panel-resize-handle');
      return {
        ariaValue: Number(handle?.getAttribute('aria-valuenow') || 0),
        panelWidth: panel.width,
        storedWidth: Number(localStorage.getItem(${JSON.stringify(PROJECT_PANEL_WIDTH_STORAGE_KEY)}) || 0),
      };
    })()`,
  });
  value.keyboard = keyboardResult.result.value;

  if (value.resizedWidth < dragStart.width + 40) {
    failures.push(`project panel drag should widen the panel: ${value.resizedWidth} <= ${dragStart.width}`);
  }

  if (value.storedWidth < dragStart.width + 40) {
    failures.push("resized project panel width should be stored in localStorage");
  }

  if (value.ariaValue < dragStart.width + 40) {
    failures.push("project panel resize handle should expose the current width");
  }

  if (!value.isAstryxHandle || value.role !== "separator" || value.orientation !== "vertical") {
    failures.push("project panel should use an accessible Astryx ResizeHandle");
  }

  if (value.resizing) {
    failures.push("project panel resizing state should clear after mouse release");
  }

  if (value.transitionDuration !== "0s") {
    failures.push("project panel drag should not wait on the grid transition");
  }

  if (value.keyboard.panelWidth < value.resizedWidth + 9 ||
      value.keyboard.storedWidth < value.resizedWidth + 9 ||
      value.keyboard.ariaValue < value.resizedWidth + 9) {
    failures.push("ArrowLeft should widen and persist the project panel by keyboard");
  }

  return { value, failures };
}

// 우측 프로젝트 패널 접기 버튼이 채팅 화면을 유지한 채 접고 펼치는지 확인한다.
async function verifyProjectPanelCollapse(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 820,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithProject(send);

  const initialResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      hasCollapseButton: Boolean(document.querySelector('.project-panel-collapse-toggle')),
      hasMaximizeButton: Boolean(document.querySelector('.project-panel-maximize-toggle')),
      panelWidth: document.querySelector('.project-panel')?.getBoundingClientRect().width ?? 0,
      state: document.querySelector('.app-shell')?.getAttribute('data-project-panel-state') || "",
    }))()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-panel-collapse-toggle')?.click()`,
  });
  await sleep(340);

  const collapsedResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const shell = document.querySelector('.app-shell');
      const panel = document.querySelector('.project-panel');
      const panelBox = panel?.getBoundingClientRect();
      const chat = document.querySelector('.chat').getBoundingClientRect();
      const shellBox = shell.getBoundingClientRect();
      return {
        collapsed: shell?.getAttribute('data-project-panel-state') === 'closed',
        state: shell?.getAttribute('data-project-panel-state') || "",
        panelLeft: panelBox?.left ?? 0,
        panelWidth: panelBox?.width ?? 0,
        hasPanel: Boolean(panel),
        panelState: panel?.getAttribute('data-state') || "",
        panelAriaHidden: panel?.getAttribute('aria-hidden') || "",
        panelInert: panel?.hasAttribute('inert') || false,
        hasRailButton: Boolean(document.querySelector('.project-panel-rail-toggle')),
        hasPrompt: Boolean(document.querySelector('.prompt')),
        chatRight: chat.right,
        shellRight: shellBox.right,
        stored: localStorage.getItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}) || "",
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-panel-rail-toggle')?.click()`,
  });
  await sleep(340);

  const expandedResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const shell = document.querySelector('.app-shell');
      const panel = document.querySelector('.project-panel').getBoundingClientRect();
      return {
        collapsed: shell?.getAttribute('data-project-panel-state') === 'closed',
        state: shell?.getAttribute('data-project-panel-state') || "",
        panelWidth: panel.width,
        hasPanel: Boolean(document.querySelector('.project-panel')),
        menuButtons: document.querySelectorAll('.project-panel-menu button').length,
        stored: localStorage.getItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}) || "",
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-panel-maximize-toggle')?.click()`,
  });
  await sleep(180);

  const maximizedBeforeSettingsResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      hasPanel: Boolean(document.querySelector('.project-panel')),
      state: document.querySelector('.app-shell')?.getAttribute('data-project-panel-state') || "",
    }))()`,
  });

  await openSettingsFromAccountMenu(send);
  await sleep(180);

  const hiddenForSettingsResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const shell = document.querySelector('.app-shell');
      return {
        hasPanel: Boolean(document.querySelector('.project-panel')),
        mainView: shell?.getAttribute('data-main-view') || "",
        maximized: shell?.getAttribute('data-project-panel-state') === 'maximized',
        state: shell?.getAttribute('data-project-panel-state') || "",
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.settings-page .settings-back-button')?.click()`,
  });
  await sleep(180);

  const restoredAfterSettingsResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const shell = document.querySelector('.app-shell');
      return {
        hasPanel: Boolean(document.querySelector('.project-panel')),
        mainView: shell?.getAttribute('data-main-view') || "",
        maximized: shell?.getAttribute('data-project-panel-state') === 'maximized',
        state: shell?.getAttribute('data-project-panel-state') || "",
      };
    })()`,
  });

  const value = {
    initial: initialResult.result.value,
    collapsed: collapsedResult.result.value,
    expanded: expandedResult.result.value,
    maximizedBeforeSettings: maximizedBeforeSettingsResult.result.value,
    hiddenForSettings: hiddenForSettingsResult.result.value,
    restoredAfterSettings: restoredAfterSettingsResult.result.value,
  };
  const failures = [];

  if (!value.initial.hasCollapseButton ||
      !value.initial.hasMaximizeButton ||
      value.initial.state !== "open" ||
      value.initial.panelWidth < 300) {
    failures.push("project panel menu should expose both collapse and maximize buttons");
  }

  if (!value.collapsed.collapsed ||
      value.collapsed.state !== "closed" ||
      value.collapsed.stored !== "true") {
    failures.push("project panel collapsed state should be stored after clicking collapse");
  }

  if (!value.collapsed.hasPanel ||
      value.collapsed.panelState !== "closed" ||
      value.collapsed.panelAriaHidden !== "true" ||
      !value.collapsed.panelInert ||
      value.collapsed.panelWidth < 300 ||
      value.collapsed.panelLeft < value.collapsed.shellRight - 2 ||
      value.collapsed.shellRight - value.collapsed.chatRight > 2 ||
      !value.collapsed.hasRailButton) {
    failures.push(`closed project panel should remain inert off-canvas without reserving content width: ${value.collapsed.panelWidth}`);
  }

  if (!value.collapsed.hasPrompt) {
    failures.push("collapsing the project panel should keep the chat prompt visible");
  }

  if (value.expanded.collapsed ||
      value.expanded.state !== "open" ||
      !value.expanded.hasPanel ||
      Math.abs(value.expanded.panelWidth - value.initial.panelWidth) > 2 ||
      value.expanded.stored !== "false") {
    failures.push("project panel should expand again from the rail button");
  }

  if (value.expanded.panelWidth < 300 || value.expanded.menuButtons !== 3) {
    failures.push("expanded project panel should restore its menu content");
  }

  if (value.maximizedBeforeSettings.state !== "maximized" ||
      !value.maximizedBeforeSettings.hasPanel ||
      value.hiddenForSettings.mainView !== "settings" ||
      value.hiddenForSettings.state !== "closed" ||
      value.hiddenForSettings.maximized ||
      value.hiddenForSettings.hasPanel ||
      value.restoredAfterSettings.mainView !== "workspace" ||
      value.restoredAfterSettings.state !== "maximized" ||
      !value.restoredAfterSettings.maximized ||
      !value.restoredAfterSettings.hasPanel) {
    failures.push("hidden views should suspend panel CSS and restore the previous visible mode");
  }

  debugLayout("project panel collapse", value);
  return { value, failures };
}

// 초기 진입, 프로젝트 내부 새 채팅, 전송 후에 입력창 포커스가 유지되는지 확인한다.
async function verifyPromptFocusFlow(send) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 820,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await openAppWithProject(send);
  await sleep(100);

  const initialFocusResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.activeElement === document.querySelector('.prompt textarea')`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-group[data-active="true"] .project-chat-create-button')?.click()`,
  });
  await sleep(200);
  const newChatFocusResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.activeElement === document.querySelector('.prompt textarea')`,
  });
  const wrappedTitleLayoutResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const chat = document.querySelector('.chat[data-empty-chat="true"]');
      const title = document.querySelector('.chat-empty h1');
      const prompt = document.querySelector('.prompt');
      if (!chat || !title || !prompt) return null;
      title.style.maxWidth = '420px';
      title.textContent = 'New Project 1에서 무엇을 도와드릴까요?';
      chat.scrollTop = 0;
      const chatRect = chat.getBoundingClientRect();
      const titleRect = title.getBoundingClientRect();
      const promptRect = prompt.getBoundingClientRect();
      const lineHeight = Number.parseFloat(getComputedStyle(title).lineHeight);
      return {
        chatClientHeight: chat.clientHeight,
        chatClientWidth: chat.clientWidth,
        chatScrollHeight: chat.scrollHeight,
        chatScrollWidth: chat.scrollWidth,
        chatTop: chatRect.top,
        chatBottom: chatRect.bottom,
        documentScrollWidth: document.documentElement.scrollWidth,
        gap: promptRect.top - titleRect.bottom,
        innerWidth,
        lineCount: Math.round(titleRect.height / lineHeight),
        pageScrollY: scrollY,
        promptBottom: promptRect.bottom,
        promptTop: promptRect.top,
        titleBottom: titleRect.bottom,
        titleLeft: titleRect.left,
        titleRight: titleRect.right,
        overflowY: getComputedStyle(chat).overflowY,
      };
    })()`,
  });

  await send("Input.insertText", { text: "포커스 테스트" });
  await send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });
  await send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });
  await sleep(400);
  const afterSubmitFocusResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.activeElement === document.querySelector('.prompt textarea')`,
  });
  const value = {
    initialFocused: initialFocusResult.result.value,
    newChatFocused: newChatFocusResult.result.value,
    afterSubmitFocused: afterSubmitFocusResult.result.value,
    wrappedTitleLayout: wrappedTitleLayoutResult.result.value,
  };
  const failures = [];

  if (!value.initialFocused) {
    failures.push("prompt should be focused on initial load");
  }

  if (!value.newChatFocused) {
    failures.push("prompt should stay focused after creating a project chat");
  }

  if (!value.wrappedTitleLayout ||
      value.wrappedTitleLayout.lineCount < 2 ||
      value.wrappedTitleLayout.gap < 23.5 ||
      value.wrappedTitleLayout.gap > 36.5 ||
      value.wrappedTitleLayout.titleBottom > value.wrappedTitleLayout.promptTop ||
      value.wrappedTitleLayout.overflowY !== "auto" ||
      value.wrappedTitleLayout.chatScrollWidth > value.wrappedTitleLayout.chatClientWidth + 1 ||
      value.wrappedTitleLayout.documentScrollWidth > value.wrappedTitleLayout.innerWidth ||
      value.wrappedTitleLayout.titleLeft < -0.5 ||
      value.wrappedTitleLayout.titleRight > value.wrappedTitleLayout.innerWidth + 0.5 ||
      value.wrappedTitleLayout.pageScrollY !== 0 ||
      (value.wrappedTitleLayout.chatScrollHeight > value.wrappedTitleLayout.chatClientHeight + 1 &&
        (value.wrappedTitleLayout.promptTop < value.wrappedTitleLayout.chatTop - 0.5 ||
          value.wrappedTitleLayout.promptBottom > value.wrappedTitleLayout.chatBottom + 0.5))) {
    failures.push("wrapped empty-chat title should stay in flow above the prompt");
  }

  if (!value.afterSubmitFocused) {
    failures.push("prompt should refocus after submit");
  }

  return { value, failures };
}

// 알림 수 추산이 아니라 실제 stack 높이를 따라 빈 채팅의 제목과 입력창을 안전하게 민다.
async function verifyMeasuredNoticeStackClearance(send) {
  const emptySessionState = createProjectStorage(
    "project-notice-clearance",
    "Notice Clearance",
    [
      {
        id: "session-notice-clearance",
        title: "Notice Chat",
        createdAt: Date.now(),
        messages: [],
      },
    ],
    "session-notice-clearance",
    [],
    { apiProjectId: 1 },
  );

  await send("Emulation.setDeviceMetricsOverride", {
    width: 480,
    height: 410,
    deviceScaleFactor: 2,
    mobile: false,
  });
  await navigateAndWaitForSelector(send, APP_URL, ".app-shell");
  await evaluateAndNavigateToSelector(
    send,
    `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'true'); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'true'); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(emptySessionState)})`,
    APP_URL,
    '.chat[data-empty-chat="true"]',
  );
  await waitForSelector(send, ".prompt textarea:not(:disabled)");

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-group[data-active="true"] .project-action-menu-button')?.click()`,
  });
  await waitForSelector(send, '[data-action="delete-project"]');
  await send("Runtime.evaluate", {
    expression: `document.querySelector('[data-action="delete-project"]')?.click()`,
  });
  await waitForSelector(send, ".notice-stack .notice");
  await sleep(100);

  const initialResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const chat = document.querySelector('.chat[data-empty-chat="true"]');
      const stack = document.querySelector('.notice-stack');
      return {
        cssHeight: Number.parseFloat(getComputedStyle(chat).getPropertyValue('--notice-stack-height')),
        stackHeight: stack.getBoundingClientRect().height,
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `(() => {
      const stack = document.querySelector('.notice-stack');
      const notice = stack?.querySelector('.notice');
      if (!stack || !notice) return;
      const title = Array.from(notice.querySelectorAll('div')).find((element) =>
        element.children.length === 0 && element.textContent.trim().includes('한 번 더')
      );
      if (title) {
        title.textContent = '아주 긴 상태 알림이 여러 줄로 표시되어도 작업 제목과 입력창을 가리지 않아야 합니다. 확대된 데스크탑 창에서도 알림의 전체 높이를 측정합니다.';
      }
      stack.append(notice.cloneNode(true), notice.cloneNode(true));
    })()`,
  });
  await sleep(180);

  const measuredResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const chat = document.querySelector('.chat[data-empty-chat="true"]');
      const stack = document.querySelector('.notice-stack');
      const title = document.querySelector('.chat-empty h1');
      const prompt = document.querySelector('.prompt');
      if (!chat || !stack || !title || !prompt) return null;
      chat.scrollTop = 0;
      const chatBox = chat.getBoundingClientRect();
      const stackBox = stack.getBoundingClientRect();
      const titleBox = title.getBoundingClientRect();
      const promptBox = prompt.getBoundingClientRect();
      const styles = getComputedStyle(chat);
      return {
        chatClientHeight: chat.clientHeight,
        chatPaddingTop: Number.parseFloat(styles.paddingTop),
        chatScrollHeight: chat.scrollHeight,
        cssHeight: Number.parseFloat(styles.getPropertyValue('--notice-stack-height')),
        documentScrollWidth: document.documentElement.scrollWidth,
        innerWidth,
        noticeCountAttribute: chat.getAttribute('data-notice-count'),
        noticeElements: stack.querySelectorAll('.notice').length,
        overflowY: styles.overflowY,
        promptTop: promptBox.top,
        stackBottom: stackBox.bottom,
        stackHeight: stackBox.height,
        stackTopOffset: stackBox.top - chatBox.top,
        titleBottom: titleBox.bottom,
        titleTop: titleBox.top,
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.notice-stack .notice')).slice(1).forEach((notice) => notice.remove())`,
  });
  await sleep(100);
  await openSettingsFromAccountMenu(send);
  await waitForSelector(send, ".settings-page .settings-back-button");
  await sleep(100);

  async function readBackButtonClearance(pageSelector) {
    const result = await send("Runtime.evaluate", {
      returnByValue: true,
      expression: `(() => {
        const chat = document.querySelector('.chat');
        const stack = document.querySelector('.notice-stack');
        const page = document.querySelector(${JSON.stringify(pageSelector)});
        const button = page?.querySelector('.settings-back-button');
        if (!chat || !stack || !page || !button) return null;
        const chatBox = chat.getBoundingClientRect();
        const stackBox = stack.getBoundingClientRect();
        const buttonBox = button.getBoundingClientRect();
        const chatStyles = getComputedStyle(chat);
        return {
          buttonTop: buttonBox.top,
          cssHeight: Number.parseFloat(chatStyles.getPropertyValue('--notice-stack-height')),
          pagePaddingTop: Number.parseFloat(getComputedStyle(page).paddingTop),
          stackBottom: stackBox.bottom,
          stackHeight: stackBox.height,
          stackTopOffset: stackBox.top - chatBox.top,
        };
      })()`,
    });
    return result.result.value;
  }

  const settingsBackButton = await readBackButtonClearance(".settings-page");

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.settings-page .settings-back-button')?.click()`,
  });
  await waitForSelector(send, '.chat[data-empty-chat="true"]');
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-group[data-active="true"] .project-action-menu-button')?.click()`,
  });
  await waitForSelector(send, '[data-action="manage-project-members"]');
  await send("Runtime.evaluate", {
    expression: `document.querySelector('[data-action="manage-project-members"]')?.click()`,
  });
  await waitForSelector(send, ".members-page .settings-back-button");
  await sleep(100);
  const membersBackButton = await readBackButtonClearance(".members-page");

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.members-page .settings-back-button')?.click()`,
  });
  await waitForSelector(send, '.chat[data-empty-chat="true"]');
  await openSidebarAccountMenu(send);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.account-menu-profile')?.click()`,
  });
  await waitForSelector(send, ".profile-page .settings-back-button");
  await sleep(100);
  const profileBackButton = await readBackButtonClearance(".profile-page");

  const value = {
    initial: initialResult.result.value,
    measured: measuredResult.result.value,
    membersBackButton,
    profileBackButton,
    settingsBackButton,
  };
  const failures = [];

  if (!value.measured ||
      value.measured.noticeElements !== 3 ||
      value.measured.noticeCountAttribute !== "1" ||
      value.measured.stackHeight <= value.initial.stackHeight * 2.5) {
    failures.push("the notice regression fixture should contain three dynamically resized banners");
  }

  if (!value.measured ||
      Math.abs(value.measured.cssHeight - value.measured.stackHeight) > 1 ||
      value.measured.cssHeight <= value.initial.cssHeight) {
    failures.push("ResizeObserver should publish the rendered notice stack height to CSS");
  }

  if (!value.measured ||
      value.measured.titleTop < value.measured.stackBottom + 13 ||
      value.measured.promptTop <= value.measured.titleBottom ||
      value.measured.chatPaddingTop <
        value.measured.stackTopOffset + value.measured.stackHeight + 13) {
    failures.push("wrapped and multiple notices should not overlap the empty-chat title or prompt");
  }

  if (!value.measured ||
      value.measured.overflowY !== "auto" ||
      value.measured.chatScrollHeight <= value.measured.chatClientHeight ||
      value.measured.documentScrollWidth > value.measured.innerWidth) {
    failures.push("200% effective viewport should keep notice-safe empty chat vertically scrollable without horizontal overflow");
  }

  for (const [pageName, backButton] of [
    ["settings", value.settingsBackButton],
    ["members", value.membersBackButton],
    ["profile", value.profileBackButton],
  ]) {
    if (!backButton ||
        Math.abs(backButton.cssHeight - backButton.stackHeight) > 1 ||
        backButton.buttonTop < backButton.stackBottom + 13 ||
        backButton.pagePaddingTop <
          backButton.stackTopOffset + backButton.stackHeight + 13) {
      failures.push(`${pageName} back button should stay below the measured notice stack`);
    }
  }

  debugLayout("measured notice stack clearance", value);
  return { value, failures };
}

// Tauri pageZoom과 같은 CSS 확대를 적용해도 프로필·설정은 같은 유효 폭에서 재배치된다.
async function verifyZoomedProfileLayout(send) {
  const failures = [];

  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await setAuthScenario(send, "owner");
  await send("Runtime.evaluate", {
    expression: `(() => {
      localStorage.setItem(${JSON.stringify(ZOOM_STORAGE_KEY)}, '2');
      localStorage.setItem(${JSON.stringify(SIDEBAR_STORAGE_KEY)}, 'false');
      localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, 'true');
    })()`,
  });
  await openAppWithProject(send);
  await sleep(260);
  await openSidebarAccountMenu(send);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.account-menu-profile')?.click()`,
  });
  await waitForSelector(send, ".profile-page");
  await sleep(160);

  const profileResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const rect = (selector) => {
        const element = document.querySelector(selector);
        if (!element) return null;
        const box = element.getBoundingClientRect();
        return { bottom: box.bottom, height: box.height, left: box.left, right: box.right, top: box.top, width: box.width };
      };
      const page = document.querySelector('.profile-page');
      const shell = document.querySelector('.app-shell');
      return {
        back: rect('.profile-page .settings-back-button'),
        card: rect('.profile-identity-card'),
        chat: rect('.chat'),
        content: rect('.profile-content'),
        details: rect('.profile-details'),
        documentScrollWidth: document.documentElement.scrollWidth,
        heading: rect('.profile-page h1'),
        highZoomLayout: shell?.getAttribute('data-high-zoom-layout') || '',
        innerWidth,
        pageClientWidth: page?.clientWidth ?? 0,
        pageScrollWidth: page?.scrollWidth ?? 0,
        root: rect('#root'),
        sidebar: rect('.sidebar'),
        sidebarCollapsed: shell?.getAttribute('data-sidebar-collapsed') || '',
        zoomMode: document.documentElement.dataset.pageZoomMode || '',
      };
    })()`,
  });
  const profile = profileResult.result.value;

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.profile-page .settings-back-button')?.click()`,
  });
  await waitForSelector(send, ".sidebar-account-button");
  await openSettingsFromAccountMenu(send);
  await waitForSelector(send, ".settings-page");
  await sleep(140);
  const settingsResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const readRect = (selector) => {
        const box = document.querySelector(selector)?.getBoundingClientRect();
        return box ? { height: box.height, left: box.left, top: box.top } : null;
      };
      const page = document.querySelector('.settings-page');
      return {
        back: readRect('.settings-page .settings-back-button'),
        heading: readRect('.settings-page h1'),
        pageClientWidth: page?.clientWidth ?? 0,
        pageScrollWidth: page?.scrollWidth ?? 0,
      };
    })()`,
  });
  const settings = settingsResult.result.value;

  if (!profile ||
      profile.zoomMode !== "css" ||
      profile.highZoomLayout !== "true" ||
      profile.sidebarCollapsed !== "true" ||
      !profile.root ||
      profile.root.right > profile.innerWidth + 1 ||
      profile.documentScrollWidth > profile.innerWidth ||
      profile.pageScrollWidth > profile.pageClientWidth + 1) {
    failures.push("200% zoom should use the compact desktop rail inside the visible app frame");
  }

  if (!profile?.back ||
      !profile?.heading ||
      !profile?.content ||
      !profile?.chat ||
      !profile?.card ||
      !profile?.details ||
      profile.back.left < profile.content.left - 0.5 ||
      profile.back.right > profile.content.right + 0.5 ||
      Math.abs(
        profile.back.top + profile.back.height / 2 -
        (profile.heading.top + profile.heading.height / 2)
      ) > 2 ||
      profile.card.left < profile.content.left - 0.5 ||
      profile.card.right > profile.content.right + 0.5 ||
      profile.details.left < profile.content.left - 0.5 ||
      profile.details.right > profile.content.right + 0.5 ||
      profile.content.left < profile.chat.left - 0.5 ||
      profile.content.right > profile.chat.right + 0.5) {
    failures.push("200% Profile should keep its shared header, card, and details inside the chat pane");
  }

  if (!settings?.back ||
      !settings?.heading ||
      settings.pageScrollWidth > settings.pageClientWidth + 1 ||
      Math.abs(settings.back.left - profile?.back?.left) > 0.5 ||
      Math.abs(
        settings.back.top + settings.back.height / 2 -
        (settings.heading.top + settings.heading.height / 2)
      ) > 2) {
    failures.push("200% Profile and Settings should preserve the same back-navigation header");
  }

  await send("Runtime.evaluate", {
    expression: `localStorage.setItem(${JSON.stringify(ZOOM_STORAGE_KEY)}, '1'); location.reload()`,
  });
  await waitForSelector(send, ".app-shell");

  debugLayout("zoomed profile layout", { profile, settings });
  return { value: { profile, settings }, failures };
}

// 초안은 다른 세션으로 새지 않되 원래 세션으로 돌아오면 복원되는지 확인한다.
async function verifyDraftScopingOnSessionChange(send) {
  const seededSessions = [
    {
      id: "session-draft-a",
      title: "Draft A",
      createdAt: Date.now(),
      messages: [
        {
          id: "assistant-draft-a",
          role: "assistant",
          content: "저장된 응답입니다.",
        },
      ],
    },
    {
      id: "session-draft-b",
      title: "Draft B",
      createdAt: Date.now() - 1,
      messages: [
        {
          id: "assistant-draft-b",
          role: "assistant",
          content: "저장된 응답입니다.",
        },
        {
          id: "user-draft-b",
          role: "user",
          content: "이전 대화",
        },
      ],
    },
  ];

  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  const seededProjectState = createProjectStorage(
    "project-draft-smoke",
    "Draft Smoke",
    seededSessions,
  );
  await send("Runtime.evaluate", {
    expression: `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(seededProjectState)})`,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);

  await send("Runtime.evaluate", {
    expression: `(() => {
      const input = document.querySelector('.prompt textarea');
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      input.focus();
      setter.call(input, '다른 세션으로 새면 안 되는 초안');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`,
  });
  await sleep(80);
  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.history-item')).find((item) => item.textContent.includes('Draft B'))?.click()`,
  });
  await sleep(200);
  const afterHistoryClickResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.querySelector('.prompt textarea').value`,
  });

  await send("Runtime.evaluate", {
    expression: `(() => {
      const input = document.querySelector('.prompt textarea');
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      input.focus();
      setter.call(input, 'B 세션에 남아야 하는 초안');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    })()`,
  });
  await sleep(80);
  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.history-item')).find((item) => item.textContent.includes('Draft A'))?.click()`,
  });
  await sleep(200);
  const restoredFirstDraftResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.querySelector('.prompt textarea').value`,
  });

  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.history-item')).find((item) => item.textContent.includes('Draft B'))?.click()`,
  });
  await sleep(200);
  const restoredSecondDraftResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.querySelector('.prompt textarea').value`,
  });

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.project-group[data-active="true"] .project-chat-create-button')?.click()`,
  });
  await sleep(200);
  const afterNewChatResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `document.querySelector('.prompt textarea').value`,
  });
  const value = {
    afterHistoryClick: afterHistoryClickResult.result.value,
    restoredFirstDraft: restoredFirstDraftResult.result.value,
    restoredSecondDraft: restoredSecondDraftResult.result.value,
    afterNewChat: afterNewChatResult.result.value,
  };
  const failures = [];

  if (value.afterHistoryClick !== "") {
    failures.push("a draft should not leak into another session");
  }

  if (value.restoredFirstDraft !== "다른 세션으로 새면 안 되는 초안") {
    failures.push("returning to a session should restore its draft");
  }

  if (value.restoredSecondDraft !== "B 세션에 남아야 하는 초안") {
    failures.push("each session should preserve its own draft");
  }

  if (value.afterNewChat !== "") {
    failures.push("a new project chat should start with an empty draft");
  }

  return { value, failures };
}

// 히스토리에서 세션을 삭제하고 마지막 세션 삭제 시 새 채팅이 남는지 확인한다.
async function verifyDeleteSessionFlow(send) {
  const seededSessions = [
    {
      id: "session-delete-a",
      title: "Delete A",
      createdAt: Date.now(),
      messages: [
        {
          id: "assistant-delete-a",
          role: "assistant",
          content: "저장된 응답입니다.",
        },
        {
          id: "user-delete-a",
          role: "user",
          content: "삭제될 대화",
        },
      ],
    },
    {
      id: "session-delete-b",
      title: "Delete B",
      createdAt: Date.now() - 1,
      messages: [
        {
          id: "assistant-delete-b",
          role: "assistant",
          content: "저장된 응답입니다.",
        },
        {
          id: "user-delete-b",
          role: "user",
          content: "남을 대화",
        },
      ],
    },
  ];

  await send("Emulation.setDeviceMetricsOverride", {
    width: 960,
    height: 680,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);
  const seededProjectState = createProjectStorage(
    "project-delete-smoke",
    "Delete Smoke",
    seededSessions,
  );
  await send("Runtime.evaluate", {
    expression: `localStorage.removeItem(${JSON.stringify(LEGACY_STORAGE_KEY)}); localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(seededProjectState)})`,
  });
  await send("Page.navigate", { url: APP_URL });
  await sleep(700);

  await send("Input.insertText", { text: "삭제 후 남으면 안 되는 초안" });
  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.history-row')).find((item) => item.textContent.includes('Delete A'))?.querySelector('.history-action-menu-button')?.click()`,
  });
  await sleep(80);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.item-action-menu [data-action="delete-session"]')?.click()`,
  });
  await sleep(80);
  const firstDeleteConfirmationResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      titles: Array.from(document.querySelectorAll('.history-title')).map((item) => item.textContent.trim()),
      deleteLabel: document.querySelector('.item-action-menu [data-action="delete-session"]')?.textContent.trim() || "",
      warning: document.querySelector('.runtime-status')?.textContent.trim() || "",
    }))()`,
  });
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.item-action-menu [data-action="delete-session"]')?.click()`,
  });
  await sleep(250);
  const afterFirstDeleteResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const titles = Array.from(document.querySelectorAll('.history-title')).map((item) => item.textContent.trim());
      const activeTitle = document.querySelector('.history-row[data-active="true"] .history-title')?.textContent.trim() || "";
      return {
        titles,
        activeTitle,
        textAfterDelete: document.querySelector('.prompt textarea')?.value ?? "",
      };
    })()`,
  });

  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.history-row')).find((item) => item.textContent.includes('Delete B'))?.querySelector('.history-action-menu-button')?.click()`,
  });
  await sleep(80);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.item-action-menu [data-action="delete-session"]')?.click()`,
  });
  await sleep(80);
  await send("Runtime.evaluate", {
    expression: `document.querySelector('.item-action-menu [data-action="delete-session"]')?.click()`,
  });
  await sleep(250);
  const afterLastDeleteResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const savedState = JSON.parse(localStorage.getItem(${JSON.stringify(PROJECT_STORAGE_KEY)}) || '{}');
      const activeProject = savedState.projects.find((project) => project.id === savedState.selectedProjectId);
      const selectedSession = activeProject?.sessions.find(
        (session) => session.id === savedState.selectedSessionId,
      );
      return {
        titles: Array.from(document.querySelectorAll('.history-title')).map((item) => item.textContent.trim()),
        sessionCount: activeProject?.sessions.length ?? 0,
        selectedSessionMessageCount: selectedSession?.messages.length ?? -1,
        selectedSessionId: savedState.selectedSessionId ?? null,
        hasPrompt: Boolean(document.querySelector('.prompt')),
        messageCount: document.querySelectorAll('.message').length,
        emptyTitle: document.querySelector('.chat-empty h1')?.textContent.trim() || "",
        hasProjectHome: Boolean(document.querySelector('.project-home')),
        uploadText: document.querySelector('.project-home-upload-card')?.textContent.trim() || "",
        hasProjectOverview: Boolean(document.querySelector('.project-overview')),
        hasOverviewPrompt: Boolean(document.querySelector('input[aria-label="프로젝트 질문 입력"]')),
      };
    })()`,
  });
  const value = {
    firstDeleteConfirmation: firstDeleteConfirmationResult.result.value,
    afterFirstDelete: afterFirstDeleteResult.result.value,
    afterLastDelete: afterLastDeleteResult.result.value,
  };
  const failures = [];

  if (!value.firstDeleteConfirmation.titles.includes("Delete A")) {
    failures.push("first delete press should preserve the session during confirmation");
  }
  if (value.firstDeleteConfirmation.deleteLabel !== "다시 삭제") {
    failures.push("session delete should expose an explicit second-press label");
  }
  if (!value.firstDeleteConfirmation.warning.includes("채팅과 대화 기록")) {
    failures.push("session delete should explain the destructive consequence");
  }

  if (value.afterFirstDelete.titles.includes("Delete A")) {
    failures.push("deleted session should disappear from history");
  }

  if (!value.afterFirstDelete.titles.includes("Delete B")) {
    failures.push("remaining session should stay in history");
  }

  if (value.afterFirstDelete.activeTitle !== "Delete B") {
    failures.push("selection should move to the next session after deleting the active session");
  }

  if (value.afterFirstDelete.textAfterDelete !== "") {
    failures.push("draft text should clear after deleting the active session");
  }

    if (value.afterLastDelete.titles.length !== 1 ||
        !value.afterLastDelete.titles.includes("New Chat") ||
        value.afterLastDelete.sessionCount !== 1 ||
        value.afterLastDelete.selectedSessionMessageCount !== 0 ||
        !value.afterLastDelete.selectedSessionId) {
      failures.push("deleting the last session should create a replacement empty chat");
    }

    if (!value.afterLastDelete.hasPrompt ||
        value.afterLastDelete.messageCount !== 0 ||
        !value.afterLastDelete.emptyTitle.includes("Delete Smoke") ||
        value.afterLastDelete.hasProjectHome ||
        value.afterLastDelete.uploadText !== "" ||
        value.afterLastDelete.hasProjectOverview ||
        value.afterLastDelete.hasOverviewPrompt) {
      failures.push("project should stay in chat after deleting the last session");
    }

  return { value, failures };
}

const browserPath = findBrowserPath();
let vite = null;
let browser = null;
let ws = null;
let send = null;
let userDataDir = null;

try {
  assertValidPort(APP_PORT, "PAIM_LAYOUT_PORT");
  assertValidPort(DEBUG_PORT, "PAIM_LAYOUT_DEBUG_PORT");
  if (APP_PORT === DEBUG_PORT) {
    throw new Error("PAIM_LAYOUT_PORT and PAIM_LAYOUT_DEBUG_PORT must be different");
  }
  if (await isPortListening(APP_PORT)) {
    throw new Error(
      `Port ${APP_PORT} is already in use. Set PAIM_LAYOUT_PORT to an unused test port.`,
    );
  }
  if (await isPortListening(DEBUG_PORT)) {
    throw new Error(
      `Debug port ${DEBUG_PORT} is already in use. Set PAIM_LAYOUT_DEBUG_PORT to an unused port.`,
    );
  }

  userDataDir = mkdtempSync(join(tmpdir(), `paim-layout-smoke-${APP_PORT}-`));

  vite = trackChild(spawn(process.execPath, [VITE_BIN, "--host", "127.0.0.1", "--port", String(APP_PORT), "--strictPort", "--force"], {
    env: { ...process.env, VITE_GITHUB_CLIENT_ID: "smoke-client" },
    stdio: "ignore",
  }));

  browser = trackChild(spawn(browserPath, [
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    `--remote-debugging-port=${DEBUG_PORT}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], {
    stdio: "ignore",
  }));

  await waitForHttp(APP_URL, vite, "Vite");
  await waitForDebuggingPort(browser);

  const tab = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/new?about%3Ablank`, {
    method: "PUT",
  }).then((response) => response.json());
  ws = new WebSocket(tab.webSocketDebuggerUrl);
  await waitForWebSocketOpen(ws);

  send = createCdpClient(ws);
  await send("Page.enable");
  await send("Runtime.enable");
  await installPaimApiMock(send);
  await navigateAndWaitForSelector(send, APP_URL, ".app-shell");

  let hasFailures = false;
  const measuredNoticeStackResult = await verifyMeasuredNoticeStackClearance(send);

  if (measuredNoticeStackResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL measured notice stack clearance");
    measuredNoticeStackResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS measured notices stay clear of empty chat at 200% effective viewport");
  }

  const promptFocusResult = await verifyPromptFocusFlow(send);

  if (promptFocusResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL prompt focus and wrapped empty-chat flow");
    promptFocusResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS wrapped empty-chat title stays clear of the prompt and preserves focus");
  }

  const appShellResult = await verifyAstryxAppShell(send);

  if (appShellResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL Astryx AppShell contract");
    appShellResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS Astryx AppShell owns the edge-to-edge PaiM frame");
  }

  const zoomedOverlayResult = await verifyZoomedOverlayPanelBounds(send);

  if (zoomedOverlayResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL 200% effective viewport overlay bounds");
    zoomedOverlayResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS 200% effective viewport keeps the overlay anchored inside the desktop frame");
  }

  const zoomedProjectHomeResult = await verifyZoomedProjectHomeLayout(send);

  if (zoomedProjectHomeResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL 200% effective viewport project home");
    zoomedProjectHomeResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS 200% project home uses the rail, stacked slots, and vertical scroll without horizontal overflow");
  }

  const zoomedProfileResult = await verifyZoomedProfileLayout(send);

  if (zoomedProfileResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL 200% profile and settings layout");
    zoomedProfileResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS 200% Profile and Settings share one non-clipping header layout");
  }

  const settingsSafetyResult = await verifySettingsConnectionAndResetSafety(send);

  if (settingsSafetyResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL settings connection/reset safety");
    settingsSafetyResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS settings connection test is non-mutating and app reset preserves user data");
  }

  const accountMenuResult = await verifyAccountMenuContract(send);

  if (accountMenuResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL account menu and profile navigation");
    accountMenuResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS account menu stays anchored and routes to Profile, Settings, and Logout");
  }

  const authAndMemberResult = await verifyAuthAndMemberPermissions(send);

  if (authAndMemberResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL auth and project member permissions");
    authAndMemberResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS server-scoped Bearer auth, 401 expiry, and Owner/Member/Viewer permissions");
  }

  const storageResult = await verifyStorageSanitization(send);

  if (storageResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL storage sanitization");
    storageResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS storage sanitization excludes preview data URLs");
  }

  const iconTooltipResult = await verifyIconButtonTooltips(send);

  if (iconTooltipResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL icon button tooltips");
    iconTooltipResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS icon buttons expose hover tooltips");
  }

  const sidebarBrandTypographyResult = await verifySidebarBrandTypography(send);

  if (sidebarBrandTypographyResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL empty first-run project start");
    sidebarBrandTypographyResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS empty first-run state shows project start screen");
  }

  const copyFeedbackResult = await verifyCopyFeedback(send);

  if (copyFeedbackResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL copy feedback");
    copyFeedbackResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS copy button exposes copied feedback");
  }

  const longContentResult = await verifyLongContentLayout(send);

  if (longContentResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL long content layout");
    longContentResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS long content stays inside the layout");
  }

  const projectScopedSessionsResult = await verifyProjectScopedSessions(send);

  if (projectScopedSessionsResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL project-scoped sessions");
    projectScopedSessionsResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS chat sessions are scoped to the active project");
  }

  const projectCreationResult = await verifyProjectCreationFlow(send);

  if (projectCreationResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL project creation flow");
    projectCreationResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS new projects are created as active workspaces");
  }

  const projectHomeDroppedPdfResult = await verifyProjectHomeDroppedPdfUpload(send);

  if (projectHomeDroppedPdfResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL project home native PDF drop upload");
    projectHomeDroppedPdfResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS project home native PDF drop uploads without cancellation");
  }

  const projectHomeDroppedPdfCancellationResult =
    await verifyProjectHomeDroppedPdfCancellation(send);

  if (projectHomeDroppedPdfCancellationResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL project home native PDF drop cancellation");
    projectHomeDroppedPdfCancellationResult.failures.forEach(
      (failure) => console.log(`  - ${failure}`),
    );
  } else {
    console.log("PASS project home native PDF drop cancellation cleans the server document once");
  }

  const projectBriefingResult = await verifyProjectBriefingStartsWithoutVisiblePrompt(send);

  if (projectBriefingResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL project briefing start flow");
    projectBriefingResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS project briefing enters chat without exposing the generated prompt");
  }

  const actionMenuRenameResult = await verifyActionMenuRenameFlow(send);

  if (actionMenuRenameResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL action menu rename flow");
    actionMenuRenameResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS action menus rename projects and chats");
  }

  const projectDeleteResult = await verifyProjectDeleteFlow(send);

  if (projectDeleteResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL project delete flow");
    projectDeleteResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS projects can be deleted down to an empty state");
  }

  const draftAttachmentTrayResult = await verifyDraftAttachmentTrayLayout(send);

  if (draftAttachmentTrayResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL draft attachment tray layout");
    draftAttachmentTrayResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS draft attachment tray stays compact inside the prompt");
  }

  const multilineInputResult = await verifyMultilineInput(send);

  if (multilineInputResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL multiline input");
    multilineInputResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS multiline input supports Enter submit and Shift+Enter newline");
  }

  const interruptibleBackgroundQueryResult = await verifyInterruptibleBackgroundQuery(send);

  if (interruptibleBackgroundQueryResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL interruptible background query");
    interruptibleBackgroundQueryResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS delayed queries provide immediate feedback and remain interruptible across projects");
  }

  const cancelledPreflightIdCommitResult = await verifyCancelledPreflightIdCommit(send);

  if (cancelledPreflightIdCommitResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL cancelled query preflight id commit");
    cancelledPreflightIdCommitResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS cancelled query preflight retains committed project/session ids without querying");
  }

  const preflightRetrySharesCreationResult = await verifyPreflightRetrySharesCreation(send);

  if (preflightRetrySharesCreationResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL preflight retry creation ownership");
    preflightRetrySharesCreationResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS immediate retry shares in-flight project/session creation and completes one query");
  }

  const projectPanelMenuResult = await verifyProjectPanelMenu(send);

  if (projectPanelMenuResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL project panel menu");
    projectPanelMenuResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS project panel menu opens detail views");
  }

  const supersedeSuggestionResult = await verifySupersedeSuggestionFlow(send);

  if (supersedeSuggestionResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL Supersede suggestion flow");
    supersedeSuggestionResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS Supersede suggestion loads, resolves, and refetches pending suggestions");
  }

  const chatQuestionResult = await verifyProjectChatQuestion(send);

  if (chatQuestionResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL project chat question");
    chatQuestionResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS project chat question uses the demo response flow");
  }

  const overviewFilesResult = await verifyProjectOverviewFiles(send);

  if (overviewFilesResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL project overview files");
    overviewFilesResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS project overview files can be managed");
  }

  const githubTimelineResult = await verifyGithubTimelineState(send);

  if (githubTimelineResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL GitHub timeline state");
    githubTimelineResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS GitHub timeline switches between connect and events");
  }

  const githubOperationOwnershipResult = await verifyGithubOperationOwnership(send);

  if (githubOperationOwnershipResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL GitHub operation ownership");
    githubOperationOwnershipResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS GitHub delayed operations stay cancelled and identify only their target repo");
  }

  const sidebarToggleChromeGeometryResult = await verifySidebarToggleChromeGeometry(send);

  if (sidebarToggleChromeGeometryResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL sidebar toggle chrome geometry");
    sidebarToggleChromeGeometryResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS sidebar toggle stays anchored beside native window controls");
  }

  const sidebarPersistenceResult = await verifySidebarPersistence(send);

  if (sidebarPersistenceResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL sidebar persistence");
    sidebarPersistenceResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS sidebar collapsed state persists after reload");
  }

  const sidebarResizeCollapseResult = await verifySidebarResizeAndProjectContext(send);

  if (sidebarResizeCollapseResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL sidebar resize and project context");
    sidebarResizeCollapseResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS sidebar resizes and keeps project context");
  }

  const projectPanelResizeResult = await verifyProjectPanelResize(send);

  if (projectPanelResizeResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL project panel resize");
    projectPanelResizeResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS project panel resizes and stores width");
  }

  const projectPanelCollapseResult = await verifyProjectPanelCollapse(send);

  if (projectPanelCollapseResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL project panel collapse");
    projectPanelCollapseResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS project panel collapses and reopens");
  }

  const draftClearResult = await verifyDraftScopingOnSessionChange(send);

  if (draftClearResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL session-scoped draft preservation");
    draftClearResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS drafts stay scoped to their sessions");
  }

  const deleteSessionResult = await verifyDeleteSessionFlow(send);

  if (deleteSessionResult.failures.length > 0) {
    hasFailures = true;
    console.log("FAIL delete session flow");
    deleteSessionResult.failures.forEach((failure) => console.log(`  - ${failure}`));
  } else {
    console.log("PASS chat sessions can be deleted");
  }

  for (const scenario of scenarios) {
    const result = await measureScenario(send, scenario);
    const state = [
      `${scenario.width}x${scenario.height}`,
      scenario.collapsed ? "collapsed" : "open",
      scenario.dragActive ? "drag" : "normal",
    ].join(" ");

    if (result.failures.length > 0) {
      hasFailures = true;
      console.log(`FAIL ${state}`);
      result.failures.forEach((failure) => console.log(`  - ${failure}`));
      continue;
    }

    console.log(
      `PASS ${state} prompt=${result.value.prompt.left.toFixed(1)}-${result.value.prompt.right.toFixed(1)} scroll=${result.value.scrollWidth}`,
    );
  }

  if (hasFailures) {
    process.exitCode = 1;
  }
} finally {
  send?.dispose();
  ws?.close();
  await Promise.all([stopChild(browser), stopChild(vite)]);
  if (userDataDir) {
    rmSync(userDataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}
