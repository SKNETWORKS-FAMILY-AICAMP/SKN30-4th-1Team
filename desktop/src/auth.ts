import {
  DEFAULT_PAIM_API_ROOT_URL,
  getPaimApiRootUrl,
  normalizePaimServerUrl,
} from "./settings";

export type PaimUser = {
  id: number;
  email: string;
  name: string;
  profile_image_url?: string | null;
  created_at?: string | null;
};

export type PaimAuthResponse = {
  access_token: string;
  token_type: "bearer" | string;
  user: PaimUser;
};

export type PaimAuthSession = {
  accessToken: string;
  user: PaimUser;
};

const LEGACY_PAIM_AUTH_STORAGE_KEY = "paim.auth.v1";
const PAIM_AUTH_STORAGE_KEY_PREFIX = "paim.auth.v2.server.";

let unauthorizedHandler: ((message: string) => void) | null = null;
let hasNotifiedUnauthorized = false;

function isPaimUser(value: unknown): value is PaimUser {
  if (!value || typeof value !== "object") {
    return false;
  }

  const user = value as Partial<PaimUser>;
  return (
    typeof user.id === "number" &&
    typeof user.email === "string" &&
    typeof user.name === "string" &&
    (user.profile_image_url === undefined ||
      user.profile_image_url === null ||
      typeof user.profile_image_url === "string")
  );
}

function getPaimAuthStorageKey() {
  const serverScope = normalizePaimServerUrl(getPaimApiRootUrl()) || DEFAULT_PAIM_API_ROOT_URL;
  return `${PAIM_AUTH_STORAGE_KEY_PREFIX}${encodeURIComponent(serverScope)}`;
}

export function loadPaimAuthSession(): PaimAuthSession | null {
  try {
    // v1은 서버 구분이 없어 다른 서버로 토큰이 전달될 수 있으므로 안전하게 폐기한다.
    window.localStorage.removeItem(LEGACY_PAIM_AUTH_STORAGE_KEY);
    const value = JSON.parse(window.localStorage.getItem(getPaimAuthStorageKey()) || "null") as
      | Partial<PaimAuthSession>
      | null;

    if (
      !value ||
      typeof value.accessToken !== "string" ||
      !value.accessToken ||
      !isPaimUser(value.user)
    ) {
      return null;
    }

    return {
      accessToken: value.accessToken,
      user: value.user,
    };
  } catch {
    return null;
  }
}

export function savePaimAuthSession(session: PaimAuthSession) {
  window.localStorage.removeItem(LEGACY_PAIM_AUTH_STORAGE_KEY);
  window.localStorage.setItem(getPaimAuthStorageKey(), JSON.stringify(session));
  hasNotifiedUnauthorized = false;
}

export function clearPaimAuthSession() {
  window.localStorage.removeItem(LEGACY_PAIM_AUTH_STORAGE_KEY);
  window.localStorage.removeItem(getPaimAuthStorageKey());
}

export function getPaimAccessToken() {
  return loadPaimAuthSession()?.accessToken ?? "";
}

export function setPaimUnauthorizedHandler(handler: ((message: string) => void) | null) {
  unauthorizedHandler = handler;
}

export function notifyPaimUnauthorized(message: string, requestAccessToken = "") {
  const currentAccessToken = getPaimAccessToken();

  // 로그아웃 직후 늦게 도착한 과거 요청의 401이 새 로그인 세션을 지우지 않게 한다.
  if (currentAccessToken !== requestAccessToken) {
    return;
  }
  if (hasNotifiedUnauthorized) {
    return;
  }

  hasNotifiedUnauthorized = true;
  clearPaimAuthSession();
  unauthorizedHandler?.(message);
}
