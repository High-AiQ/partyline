/** Authenticated HTTP transport shared by every REST surface. */

import type { ZodError, ZodType } from "zod";
import { ApiErrorBodySchema, AuthTokenResponseSchema } from "./contracts";
import type { AuthTokenResponse } from "./contracts";

const ACCESS_TOKEN_KEY = "partyline_access_token";
const REFRESH_TOKEN_KEY = "partyline_refresh_token";
const SESSION_ID_KEY = "partyline_session_id";
export const AUTH_REQUIRED_CLOSE = 4401;

export interface RequestOptions<Output> {
  schema: ZodType<Output>;
  method?: string;
  body?: unknown;
  form?: FormData;
  fallback?: string;
  skipRefresh?: boolean;
}

export interface AuthHandlers {
  onRefreshed(tokens: AuthTokenResponse): void;
  onSessionCleared(): void;
}

export type SocketAuthPhase = "initial" | "retried-access" | "refreshed";

export interface SocketRecovery {
  retry: boolean;
  phase: SocketAuthPhase;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export class ApiContractError extends Error {
  readonly path: string;

  constructor(path: string, cause: ZodError) {
    super(`the server returned invalid data for ${path}`, { cause });
    this.name = "ApiContractError";
    this.path = path;
  }
}

export function readAccessToken(): string | null {
  return readToken(ACCESS_TOKEN_KEY);
}

export function readRefreshToken(): string | null {
  return readToken(REFRESH_TOKEN_KEY);
}

export function storeTokens(accessToken: string, refreshToken: string): void {
  const sessionId = mintSessionId();
  try {
    localStorage.setItem(SESSION_ID_KEY, sessionId);
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  } catch {
    // Never leave half a token pair behind if storage fails between writes.
    clearStoredTokens();
  }
}

export function clearStoredTokens(): void {
  try {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(SESSION_ID_KEY);
  } catch {
    // The in-memory session can still be cleared when storage is unavailable.
  }
}

export function isAuthStorageKey(key: string | null): boolean {
  return key === ACCESS_TOKEN_KEY || key === REFRESH_TOKEN_KEY || key === SESSION_ID_KEY;
}

let authHandlers: AuthHandlers | null = null;

export function configureAuthHandlers(handlers: AuthHandlers): void {
  authHandlers = handlers;
}

interface RefreshFlight {
  refreshToken: string;
  promise: Promise<string>;
}

class StaleRefreshError extends Error {}

let refreshFlight: RefreshFlight | null = null;

/** Concurrent 401s in one tab share one refresh exchange and token pair.
 *  Tabs cannot share a promise, so stateless refresh tokens are required; a
 *  future revocation list must coordinate rotations across documents. */
export function refreshAccessToken(): Promise<string> {
  const refreshToken = readRefreshToken();
  if (!refreshToken) return Promise.reject(new ApiError("your session has expired — sign in again", 401));
  if (refreshFlight?.refreshToken === refreshToken) return refreshFlight.promise;

  const promise = performRefresh(refreshToken).finally(() => {
    if (refreshFlight?.promise === promise) refreshFlight = null;
  });
  refreshFlight = { refreshToken, promise };
  return promise;
}

/** Recover a rejected WebSocket without assuming every 4401 means expiry.
 *  Handle changes deliberately close good sockets with 4401, so the current
 *  access token gets one retry before refresh. A freshly issued token that is
 *  also rejected is terminal rather than an infinite refresh loop. */
export async function recoverSocketAuthentication(
  startedWith: string | null,
  phase: SocketAuthPhase,
): Promise<SocketRecovery> {
  const current = readAccessToken();
  if (current !== startedWith) return { retry: current !== null, phase: "initial" };
  if (!current) {
    clearSessionIfCurrent(startedWith);
    return { retry: false, phase: "initial" };
  }
  if (phase === "initial") return { retry: true, phase: "retried-access" };
  if (phase === "refreshed") {
    clearSessionIfCurrent(startedWith);
    return { retry: false, phase: "initial" };
  }
  try {
    await refreshAccessToken();
    return { retry: true, phase: "refreshed" };
  } catch (failure: unknown) {
    const replacement = readAccessToken();
    if (replacement !== null && replacement !== startedWith) {
      return { retry: true, phase: "initial" };
    }
    if (!isAuthenticationFailure(failure)) throw failure;
    clearSessionIfCurrent(startedWith);
    return { retry: false, phase: "initial" };
  }
}

/** Fetch protected binary content without putting a bearer token in its URL. */
export async function requestBlob(path: string, allowRetry = true): Promise<Blob> {
  const startedWith = readAccessToken();
  const headers = startedWith ? { Authorization: `Bearer ${startedWith}` } : undefined;
  let response: Response;
  try {
    response = await fetch(path, headers ? { headers } : undefined);
  } catch {
    throw new ApiError("the file is not reachable", 0);
  }
  if (response.status === 401 && allowRetry) {
    let refreshed = false;
    try {
      await refreshAccessToken();
      refreshed = true;
    } catch (failure: unknown) {
      if (!isAuthenticationFailure(failure)) throw failure;
      clearSessionIfCurrent(startedWith);
    }
    if (refreshed) return requestBlob(path, false);
  }
  if (response.status === 401) clearSessionIfCurrent(startedWith);
  if (!response.ok) throw await responseError(response, "could not download the original image");
  return response.blob();
}

export async function request<Output>(
  path: string,
  options: RequestOptions<Output>,
  allowRetry = true,
): Promise<Output> {
  const { schema, method = "GET", body, form, fallback, skipRefresh = false } = options;
  const startedWith = readAccessToken();
  const headers: Record<string, string> = {};
  if (startedWith) headers.Authorization = `Bearer ${startedWith}`;

  const requestInit: RequestInit = { method };
  if (form) {
    requestInit.body = form;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    requestInit.body = JSON.stringify(body);
  }
  if (Object.keys(headers).length > 0) requestInit.headers = headers;

  let response: Response;
  try {
    response = await fetch(path, requestInit);
  } catch {
    throw new ApiError(fallback ?? "the line is not reachable", 0);
  }

  if (response.status === 401 && allowRetry && !skipRefresh) {
    let refreshed = false;
    try {
      await refreshAccessToken();
      refreshed = true;
    } catch (failure: unknown) {
      // A stale request must not clear a newer login that completed meanwhile.
      if (!isAuthenticationFailure(failure)) throw failure;
      clearSessionIfCurrent(startedWith);
    }
    // Keep the retry outside the refresh catch: a 500 or network failure on
    // the second request is its own truth, not another authentication failure.
    if (refreshed) return request(path, options, false);
  }

  if (response.status === 401 && !skipRefresh) clearSessionIfCurrent(startedWith);

  if (!response.ok) throw await responseError(response, fallback);
  return decodeResponse(path, response, schema);
}

async function performRefresh(refreshToken: string): Promise<string> {
  const sessionId = readToken(SESSION_ID_KEY);
  if (!sessionId) throw new StaleRefreshError();
  let response: Response;
  try {
    response = await fetch("/api/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  } catch {
    throw new ApiError("the line is not reachable", 0);
  }
  if (!response.ok) throw await responseError(response, "your session has expired — sign in again");

  const tokens = await decodeResponse("/api/auth/refresh", response, AuthTokenResponseSchema);
  // A login or logout completed while this exchange was in flight. Its tokens
  // are newer authority; an old successful refresh must not overwrite them.
  // The stable session id deliberately survives same-account refreshes in
  // other tabs, whose rotated token is equally valid and may win this race.
  if (readToken(SESSION_ID_KEY) !== sessionId) throw new StaleRefreshError();
  storeRefreshedTokens(tokens.access_token, tokens.refresh_token);
  authHandlers?.onRefreshed(tokens);
  return tokens.access_token;
}

function readToken(key: string): string | null {
  try {
    const token = localStorage.getItem(key);
    return token && token.length > 0 ? token : null;
  } catch {
    return null;
  }
}

function storeRefreshedTokens(accessToken: string, refreshToken: string): void {
  try {
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  } catch {
    clearStoredTokens();
  }
}

function mintSessionId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function clearSessionIfCurrent(startedWith: string | null): void {
  if (readAccessToken() === startedWith) authHandlers?.onSessionCleared();
}

function isAuthenticationFailure(failure: unknown): boolean {
  return failure instanceof ApiError && failure.status === 401;
}

async function responseError(response: Response, fallback?: string): Promise<ApiError> {
  let detail = fallback ?? `request failed (${String(response.status)})`;
  try {
    const parsed = ApiErrorBodySchema.safeParse(await response.json());
    if (parsed.success && parsed.data.detail) detail = parsed.data.detail;
  } catch {
    // A non-JSON error body is still an error; keep the fallback wording.
  }
  return new ApiError(detail, response.status);
}

async function decodeResponse<Output>(
  path: string,
  response: Response,
  schema: ZodType<Output>,
): Promise<Output> {
  const payload: unknown = response.status === 204 ? null : await response.json();
  const parsed = schema.safeParse(payload);
  if (!parsed.success) throw new ApiContractError(path, parsed.error);
  return parsed.data;
}
