import { getPaimApiRootUrl } from "./settings";
import { getPaimAccessToken, notifyPaimUnauthorized } from "./auth";

type PaimApiErrorPayload = {
  detail?: unknown;
  code?: unknown;
};

type PaimApiErrorDetail = {
  code?: unknown;
  message?: unknown;
};

const PAIM_SESSION_UNAUTHORIZED_DETAILS = new Set([
  "로그인이 필요합니다.",
  "유효하지 않은 토큰입니다.",
  "토큰이 만료되었습니다. 다시 로그인해주세요.",
  "존재하지 않는 사용자입니다.",
]);

export class PaimApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "PaimApiError";
    this.status = status;
    this.code = code;
  }
}

export function isPaimApiError(error: unknown): error is PaimApiError {
  return error instanceof PaimApiError;
}

async function readPaimResponse<T>(
  response: Response,
  handleUnauthorized = true,
  requestAccessToken = "",
  preserveGithubSessionUnauthorized = false,
): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as PaimApiErrorPayload | null;
    const nestedDetail =
      payload?.detail && typeof payload.detail === "object"
        ? (payload.detail as PaimApiErrorDetail)
        : null;
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : typeof nestedDetail?.message === "string"
          ? nestedDetail.message
          : "PaiM API 요청 실패";
    const code =
      typeof nestedDetail?.code === "string"
        ? nestedDetail.code
        : typeof payload?.code === "string"
          ? payload.code
          : undefined;

    // GitHub 전용 요청도 PaiM JWT 자체가 무효한 경우에는 반드시 전역 로그아웃한다.
    // 그 외 401은 GitHub upstream/App 인증 오류이므로 GitHub 패널에서 재인증한다.
    const shouldPreserveGithubSession =
      preserveGithubSessionUnauthorized && !PAIM_SESSION_UNAUTHORIZED_DETAILS.has(detail);

    if (
      response.status === 401 &&
      handleUnauthorized &&
      !shouldPreserveGithubSession
    ) {
      notifyPaimUnauthorized(detail, requestAccessToken);
    }

    throw new PaimApiError(detail, response.status, code);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

// PaiM FastAPI JSON 엔드포인트를 동일한 에러 형태로 호출한다.
async function fetchPaimJsonFrom<T>(
  baseUrl: string,
  path: string,
  init?: RequestInit,
  options: {
    auth?: boolean;
    handleUnauthorized?: boolean;
    preserveGithubSessionUnauthorized?: boolean;
  } = {},
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const accessToken = options.auth === false ? "" : getPaimAccessToken();

  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers,
  });

  return readPaimResponse<T>(
    response,
    options.handleUnauthorized !== false,
    accessToken,
    options.preserveGithubSessionUnauthorized === true,
  );
}

// 일반 PaiM API는 /api/v1 prefix를 사용한다.
export async function fetchPaimJson<T>(path: string, init?: RequestInit): Promise<T> {
  return fetchPaimJsonFrom<T>(`${getPaimApiRootUrl()}/api/v1`, path, init);
}

// Session restoration handles an expected 401 itself so a first launch does
// not briefly announce a global authentication error before showing sign-in.
export async function fetchPaimSessionJson<T>(path: string, init?: RequestInit): Promise<T> {
  return fetchPaimJsonFrom<T>(`${getPaimApiRootUrl()}/api/v1`, path, init, {
    handleUnauthorized: false,
  });
}

// GitHub App/upstream이 자체적으로 401을 반환할 수 있는 요청은 PaiM 로그인 세션을 유지한다.
export async function fetchPaimJsonPreservingSession<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  return fetchPaimJsonFrom<T>(`${getPaimApiRootUrl()}/api/v1`, path, init, {
    preserveGithubSessionUnauthorized: true,
  });
}

// 로그인·회원가입처럼 토큰 없이 호출해야 하는 공개 API.
export async function fetchPaimPublicJson<T>(path: string, init?: RequestInit): Promise<T> {
  return fetchPaimJsonFrom<T>(`${getPaimApiRootUrl()}/api/v1`, path, init, {
    auth: false,
    handleUnauthorized: false,
  });
}

// FormData 업로드는 브라우저가 multipart boundary를 붙이도록 Content-Type을 지정하지 않는다.
export async function fetchPaimFormData<T>(
  path: string,
  formData: FormData,
  init?: Omit<RequestInit, "body">,
): Promise<T> {
  return fetchPaimJsonFrom<T>(`${getPaimApiRootUrl()}/api/v1`, path, {
    ...init,
    method: init?.method ?? "POST",
    body: formData,
  });
}

// GitHub App API와 health check는 서버 루트 경로를 사용한다.
export async function fetchPaimRootJson<T>(path: string, init?: RequestInit): Promise<T> {
  return fetchPaimJsonFrom<T>(getPaimApiRootUrl(), path, init);
}

export async function fetchPaimRootJsonPreservingSession<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  return fetchPaimJsonFrom<T>(getPaimApiRootUrl(), path, init, {
    preserveGithubSessionUnauthorized: true,
  });
}

export function getErrorMessage(error: unknown, fallback: string) {
  if (typeof error === "string" && error) {
    return error;
  }

  return error instanceof Error && error.message ? error.message : fallback;
}
