import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const DIST_INDEX = resolve("dist/index.html");
const DIST_ASSETS = resolve("dist/assets");
const DIST_LICENSES = resolve("dist/licenses");
const MACOS_TAURI_CONFIG = resolve("src-tauri/tauri.macos.conf.json");
const PROJECT_STORAGE_KEY = `paim.projects.v8.server.${encodeURIComponent("http://127.0.0.1:7272")}`;
const PROJECT_PANEL_COLLAPSED_STORAGE_KEY = "paim.projectPanelCollapsed.v2";
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

const sleep = (ms) => new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
let nextSmokeNavigationId = 1;

// 테스트에 사용할 Chromium 계열 브라우저 실행 파일을 찾는다.
function findBrowserPath() {
  const browserPath = BROWSER_CANDIDATES.find((candidate) => existsSync(candidate));

  if (!browserPath) {
    throw new Error("No supported Chromium browser found. Set PAIM_BROWSER_PATH.");
  }

  return browserPath;
}

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

// Chrome가 임시 프로필에 기록한 실제 DevTools 포트를 확인한다.
async function waitForDebuggingPort(child, userDataDir) {
  const activePortPath = join(userDataDir, "DevToolsActivePort");

  for (let attempt = 0; attempt < 80; attempt += 1) {
    const exitMessage = getChildExitMessage(child, "browser");
    if (exitMessage) {
      throw new Error(exitMessage);
    }

    try {
      const [portLine] = readFileSync(activePortPath, "utf8").trim().split(/\r?\n/);
      const port = Number(portLine);
      if (!Number.isInteger(port) || port < 1 || port > 65_535) {
        throw new Error(`Invalid DevTools port: ${portLine}`);
      }

      const response = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (response.ok) {
        return port;
      }
    } catch {
      // 브라우저가 뜨는 중이면 다음 polling에서 다시 확인한다.
    }

    await sleep(100);
  }

  throw new Error("Timed out waiting for headless browser debugging port");
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

  return new Promise((resolveWait) => {
    let timeoutId;
    const finish = () => {
      child.removeListener("exit", finish);
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      resolveWait();
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

  return new Promise((resolveOpen, reject) => {
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
      resolveOpen();
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

// 인증 확인과 지연 청크 로딩이 끝나 실제 UI가 붙을 때까지 DOM 기준으로 기다린다.
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
  throw new Error(`Timed out waiting for selector: ${selector}${suffix}`);
}

async function navigateAndWaitForSelector(send, url, selector, timeoutMs = 5000) {
  const target = new URL(url);
  target.searchParams.set("__paimSmokeNavigation", String(nextSmokeNavigationId));
  nextSmokeNavigationId += 1;
  const targetUrl = target.toString();

  await send("Page.navigate", { url: targetUrl });
  await waitForSelector(send, selector, timeoutMs, targetUrl);
}

// HTTP(S) fetch를 기록하고 즉시 거절해 앱이 실제 네트워크를 사용하지 못하게 한다.
async function installOfflineFetchMock(send) {
  await send("Page.addScriptToEvaluateOnNewDocument", {
    source: `(() => {
      const originalFetch = window.fetch.bind(window);
      window.__paimOfflineNetworkAttempts = [];
      window.fetch = (input, init) => {
        const rawUrl = typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;

        try {
          const url = new URL(rawUrl, window.location.href);
          if (url.protocol === "http:" || url.protocol === "https:") {
            window.__paimOfflineNetworkAttempts.push(url.href);
            return Promise.reject(new TypeError("Offline bundle smoke blocks all HTTP(S) requests"));
          }
        } catch {
          window.__paimOfflineNetworkAttempts.push(String(rawUrl));
          return Promise.reject(new TypeError("Offline bundle smoke blocks unparseable network requests"));
        }

        return originalFetch(input, init);
      };
    })()`,
  });
}

// fetch 외 XHR, WebSocket, 원격 이미지까지 브라우저 네트워크 계층에서 차단한다.
async function forceOfflineNetwork(send) {
  await send("Network.enable");
  await send("Network.emulateNetworkConditions", {
    offline: true,
    latency: 0,
    downloadThroughput: 0,
    uploadThroughput: 0,
    connectionType: "none",
  });
}

// 빌드 HTML이 서버 루트 경로 대신 상대 asset 경로를 사용하는지 확인한다.
function assertRelativeAssets() {
  const indexHtml = readFileSync(DIST_INDEX, "utf8");

  if (indexHtml.includes('src="/assets/') || indexHtml.includes('href="/assets/')) {
    throw new Error("dist/index.html should use relative asset paths for offline loading");
  }
}

// 릴리즈 번들에 SUIT/SUITE 원본과 각 OFL 고지 파일이 실제로 포함되는지 확인한다.
function assertBundledVariableFonts() {
  if (!existsSync(DIST_ASSETS)) {
    throw new Error("dist/assets does not exist. Run npm run build first.");
  }

  const assetNames = readdirSync(DIST_ASSETS);
  const css = assetNames
    .filter((name) => name.endsWith(".css"))
    .map((name) => readFileSync(resolve(DIST_ASSETS, name), "utf8"))
    .join("\n");
  const fontContracts = [
    {
      family: "SUIT Variable",
      assetPattern: /^SUIT-Variable-.*\.woff2$/,
      license: resolve(DIST_LICENSES, "SUIT-OFL.txt"),
    },
    {
      family: "SUITE Variable",
      assetPattern: /^SUITE-Variable-.*\.woff2$/,
      license: resolve(DIST_LICENSES, "SUITE-OFL.txt"),
    },
  ];

  for (const contract of fontContracts) {
    const assetName = assetNames.find((name) => contract.assetPattern.test(name));
    if (!assetName ||
        statSync(resolve(DIST_ASSETS, assetName)).size === 0 ||
        !css.includes(contract.family) ||
        !css.includes(assetName)) {
      throw new Error(`${contract.family} should be emitted as a local WOFF2 asset`);
    }
    if (!existsSync(contract.license) || statSync(contract.license).size === 0) {
      throw new Error(`${contract.family} OFL notice should be included in the release bundle`);
    }
  }
}

// 로그인·빈 시작·작업공간이 공유하는 단일 macOS 창은 항상 네이티브 신호등을 유지한다.
function assertMacNativeWindowChrome() {
  const macosConfig = JSON.parse(readFileSync(MACOS_TAURI_CONFIG, "utf8"));
  const mainWindow = macosConfig.app?.windows?.find((window) => window.label === "main");

  if (
    !mainWindow ||
    mainWindow.decorations !== true ||
    mainWindow.titleBarStyle !== "Overlay" ||
    mainWindow.hiddenTitle !== true ||
    mainWindow.trafficLightPosition !== undefined
  ) {
    throw new Error("macOS main window should use native traffic lights at the system position");
  }
}

const browserPath = findBrowserPath();

if (!existsSync(DIST_INDEX)) {
  throw new Error("dist/index.html does not exist. Run npm run build first.");
}

assertRelativeAssets();
assertBundledVariableFonts();
assertMacNativeWindowChrome();
let browser = null;
let ws = null;
let send = null;
let userDataDir = null;

try {
  userDataDir = mkdtempSync(join(tmpdir(), "paim-offline-bundle-smoke-"));
  browser = trackChild(spawn(browserPath, [
    "--headless=new",
    "--disable-gpu",
    "--allow-file-access-from-files",
    "--remote-debugging-port=0",
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ], {
    stdio: "ignore",
  }));

  const debugPort = await waitForDebuggingPort(browser, userDataDir);

  const fileUrl = pathToFileURL(DIST_INDEX).href;
  const tab = await fetch(`http://127.0.0.1:${debugPort}/json/new?about:blank`, {
    method: "PUT",
  }).then((response) => response.json());
  ws = new WebSocket(tab.webSocketDebuggerUrl);
  await waitForWebSocketOpen(ws);

  send = createCdpClient(ws);
  await send("Page.enable");
  await send("Runtime.enable");
  await forceOfflineNetwork(send);
  await installOfflineFetchMock(send);
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 820,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await navigateAndWaitForSelector(send, fileUrl, ".project-start", 8000);

  const fontLoadResult = await send("Runtime.evaluate", {
    awaitPromise: true,
    returnByValue: true,
    expression: `(async () => {
      await Promise.all([
        document.fonts.load('400 16px "SUIT Variable"', '가나다'),
        document.fonts.load('700 16px "SUITE Variable"', '가나다'),
      ]);
      return {
        suitLoaded: document.fonts.check('400 16px "SUIT Variable"', '가나다'),
        suiteLoaded: document.fonts.check('700 16px "SUITE Variable"', '가나다'),
      };
    })()`,
  });
  const result = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      protocol: location.protocol,
      hasAstryxShell: Boolean(document.querySelector('.paim-app-shell')),
      hasAstryxMain: Boolean(document.querySelector('#astryx-app-shell-main[role="main"]')),
      hasShell: Boolean(document.querySelector('.app-shell')),
      hasPrompt: Boolean(document.querySelector('.prompt')),
      hasSidebar: Boolean(document.querySelector('.sidebar')),
      hasProjectStart: Boolean(document.querySelector('.project-start')),
      startMarkText: document.querySelector('.project-start-mark')?.textContent.trim() || '',
      startMarkAriaHidden: document.querySelector('.project-start-mark')?.getAttribute('aria-hidden') || '',
      hasLegacyWatermark: Boolean(document.querySelector('.project-start-watermark')),
      startButtonText: document.querySelector('.project-start-button')?.textContent.trim() || '',
      projectCreateCount: document.querySelectorAll('.project-create-trigger').length,
      customTrafficLightCount: document.querySelectorAll('.mac-traffic-button').length,
      hasWindowControlCluster: Boolean(document.querySelector('.window-control-cluster')),
      sidebarCollapsed: document.querySelector('.app-shell')?.getAttribute('data-sidebar-collapsed') || '',
      sidebarWidth: document.querySelector('.sidebar')?.getBoundingClientRect().width ?? 0,
      sidebarPanelDisplay: getComputedStyle(document.querySelector('.sidebar-panel')).display,
      sidebarBorderRightWidth: Number.parseFloat(
        getComputedStyle(document.querySelector('.sidebar')).borderRightWidth,
      ),
      hasSidebarCollapseButton: Boolean(document.querySelector('.sidebar-collapse-button')),
      hasSidebarAccountButton: Boolean(document.querySelector('.sidebar-account-button')),
      hasLegacySidebarSettingsButton: Boolean(document.querySelector('.sidebar-settings-button')),
      sidebarAccountHasPopup: document.querySelector('.sidebar-account-button')?.getAttribute('aria-haspopup') || '',
      sidebarAccountLabel: document.querySelector('.sidebar-account-button')?.getAttribute('aria-label') || '',
      rootFont: getComputedStyle(document.documentElement).fontFamily,
      headingFont: getComputedStyle(document.querySelector('.project-start-copy h1')).fontFamily,
      scrollWidth: document.documentElement.scrollWidth,
      networkAttempts: window.__paimOfflineNetworkAttempts || [],
    }))()`,
  });
  const value = {
    ...result.result.value,
    fontLoad: fontLoadResult.result.value,
  };
  const failures = [];

  if (value.protocol !== "file:") {
    failures.push(`offline smoke should load file://, got ${value.protocol}`);
  }

  if (!value.fontLoad.suitLoaded ||
      !value.fontLoad.suiteLoaded ||
      !/^\s*(?:"SUIT Variable"|SUIT Variable)(?:,|$)/.test(value.rootFont) ||
      !/^\s*(?:"SUITE Variable"|SUITE Variable)(?:,|$)/.test(value.headingFont)) {
    failures.push(
      `offline bundle should load local SUIT/SUITE typography: ${JSON.stringify({
        fontLoad: value.fontLoad,
        rootFont: value.rootFont,
        headingFont: value.headingFont,
      })}`,
    );
  }

  if (!value.hasAstryxShell || !value.hasAstryxMain || !value.hasShell || !value.hasSidebar) {
    failures.push("offline bundle should render the app shell and sidebar");
  }

  if (value.hasPrompt) {
    failures.push("offline bundle should not render chat prompt before a project exists");
  }

  if (
    !value.hasProjectStart ||
    value.startMarkText !== "PaiM" ||
    value.startMarkAriaHidden !== "true" ||
    value.hasLegacyWatermark ||
    !value.startButtonText.includes("새 프로젝트 시작하기") ||
    value.projectCreateCount !== 0 ||
    value.customTrafficLightCount !== 0 ||
    value.hasWindowControlCluster ||
    value.sidebarCollapsed !== 'true' ||
    Math.abs(value.sidebarWidth - 52) > 1 ||
    value.sidebarPanelDisplay !== 'none' ||
    value.sidebarBorderRightWidth !== 0 ||
    value.hasSidebarCollapseButton ||
    !value.hasSidebarAccountButton ||
    value.hasLegacySidebarSettingsButton ||
    value.sidebarAccountHasPopup !== 'menu' ||
    !value.sidebarAccountLabel.includes('계정 메뉴')
  ) {
    failures.push("offline bundle should render the empty first-run project start UI");
  }

  if (value.scrollWidth > 1280) {
    failures.push(`offline bundle should not overflow horizontally: ${value.scrollWidth} > 1280`);
  }

  await send("Runtime.evaluate", {
    expression: `document.querySelector('.sidebar-account-button')?.click()`,
  });
  await waitForSelector(send, ".account-menu", 5000);
  const offlineAccountMenuResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => {
      const trigger = document.querySelector('.sidebar-account-button');
      const menu = document.querySelector('.account-menu');
      const menuBox = menu?.getBoundingClientRect();
      const triggerBox = trigger?.getBoundingClientRect();
      return {
        expanded: trigger?.getAttribute('aria-expanded') || '',
        identityName: menu?.querySelector('.account-menu-identity-copy strong')?.textContent?.trim() || '',
        identityStatus: menu?.querySelector('.account-menu-identity-copy small')?.textContent?.trim() || '',
        initials: menu?.querySelector('.account-menu-avatar')?.textContent?.trim() || '',
        menuItems: Array.from(menu?.querySelectorAll('[role="menuitem"]') || [])
          .map((item) => item.textContent.trim()),
        menuRole: menu?.getAttribute('role') || '',
        menuAboveTrigger: Boolean(menuBox && triggerBox && menuBox.bottom <= triggerBox.top + 0.5),
        menuInsideViewport: Boolean(menuBox && menuBox.left >= 0 && menuBox.right <= innerWidth),
        hasLogout: Boolean(menu?.querySelector('.account-menu-logout')),
      };
    })()`,
  });
  const offlineAccountMenuValue = offlineAccountMenuResult.result.value;

  if (offlineAccountMenuValue.expanded !== 'true' ||
      offlineAccountMenuValue.menuRole !== 'menu' ||
      offlineAccountMenuValue.identityName !== 'PaiM' ||
      !offlineAccountMenuValue.identityStatus.includes('오프라인') ||
      offlineAccountMenuValue.initials !== 'PA' ||
      !offlineAccountMenuValue.menuItems.some((item) => item.includes('프로필')) ||
      !offlineAccountMenuValue.menuItems.some((item) => item.includes('설정')) ||
      offlineAccountMenuValue.hasLogout ||
      !offlineAccountMenuValue.menuAboveTrigger ||
      !offlineAccountMenuValue.menuInsideViewport) {
    failures.push("offline bundle should keep Profile and Settings available from the compact account menu");
  }

  if (!value.networkAttempts.some((url) => /^https?:\/\//.test(url))) {
    failures.push("offline bundle should exercise and block at least one HTTP(S) startup request");
  }

  const offlineProjectState = JSON.stringify({
    projects: [
      {
        id: "offline-project",
        apiProjectId: 1,
        name: "Offline Project",
        files: [],
        createdAt: Date.now(),
        sessions: [
          {
            id: "offline-session",
            title: "Offline Chat",
            createdAt: Date.now(),
            messages: [],
          },
        ],
      },
    ],
    selectedProjectId: "offline-project",
    selectedSessionId: "offline-session",
  });

  await send("Runtime.evaluate", {
    expression: `localStorage.setItem(${JSON.stringify(PROJECT_STORAGE_KEY)}, ${JSON.stringify(offlineProjectState)}); localStorage.setItem(${JSON.stringify(PROJECT_PANEL_COLLAPSED_STORAGE_KEY)}, "false")`,
  });
  await navigateAndWaitForSelector(send, fileUrl, ".project-panel-menu", 8000);
  await send("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll('.project-panel-menu button'))
      .find((button) => button.textContent.includes('GitHub'))?.click()`,
  });
  await waitForSelector(send, ".project-panel .github-panel-content", 8000);

  const lazyPanelResult = await send("Runtime.evaluate", {
    returnByValue: true,
    expression: `(() => ({
      hasGithubPanel: Boolean(document.querySelector('.project-panel .github-panel-content')),
      activeTabText: document.querySelector('.project-panel-tab[data-active="true"] > span')?.textContent.trim() || "",
    }))()`,
  });
  const lazyPanelValue = lazyPanelResult.result.value;

  if (!lazyPanelValue.hasGithubPanel || !lazyPanelValue.activeTabText.includes("GitHub")) {
    failures.push("offline bundle should load and render the lazy GitHub panel chunk");
  }

  if (failures.length > 0) {
    console.log("FAIL offline bundle smoke");
    failures.forEach((failure) => console.log(`  - ${failure}`));
    process.exitCode = 1;
  } else {
    console.log("PASS offline bundle loads from file:// without a dev server");
  }
} finally {
  send?.dispose();
  ws?.close();
  await stopChild(browser);
  if (userDataDir) {
    rmSync(userDataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}
