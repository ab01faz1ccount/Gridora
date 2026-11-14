// Fetch wrapper: unwraps the success envelope, turns every failure into ApiError, adds the CSRF
// header, and reports which engine implementation the server runs (stub badge).
import type { ApiErrorEnvelope, ApiSuccess, ErrorDetail } from "@contracts";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: ErrorDetail[];
  readonly requestId: string;
  readonly retryAfter?: number;

  constructor(init: {
    code: string;
    message: string;
    status: number;
    details?: ErrorDetail[];
    requestId?: string;
    retryAfter?: number;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.code = init.code;
    this.status = init.status;
    this.details = init.details ?? [];
    this.requestId = init.requestId ?? "";
    this.retryAfter = init.retryAfter;
  }
}

export interface Implementation {
  engine?: string;
  dataops?: string;
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);
let csrfToken: string | null = null;
let onImplementation: ((i: Implementation) => void) | null = null;
let onUnauthenticated: (() => void) | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}
export function setImplementationListener(fn: ((i: Implementation) => void) | null): void {
  onImplementation = fn;
}
export function setUnauthenticatedListener(fn: (() => void) | null): void {
  onUnauthenticated = fn;
}

export interface RequestOptions {
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  signal?: AbortSignal;
}

const AUTH_PATHS = new Set(["/auth/login", "/auth/me"]);

export async function request<T>(
  method: string,
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const qs = opts.query
    ? Object.entries(opts.query)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join("&")
    : "";
  const url = `/api/v1${path}${qs ? `?${qs}` : ""}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE.has(method) && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      credentials: "same-origin",
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: opts.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError({ code: "network", message: "network error", status: 0 });
  }

  const engine = res.headers.get("X-Gridora-Engine") ?? undefined;
  const dataops = res.headers.get("X-Gridora-Dataops") ?? undefined;
  if (onImplementation && (engine || dataops)) onImplementation({ engine, dataops });

  if (res.status === 204) return undefined as T;

  let json: unknown;
  try {
    json = await res.json();
  } catch {
    throw new ApiError({
      code: res.ok ? "internal_error" : statusToCode(res.status),
      message: "unreadable response",
      status: res.status,
    });
  }

  if (!res.ok) {
    const env = json as Partial<ApiErrorEnvelope> | null;
    const retry = Number(res.headers.get("Retry-After"));
    const err = new ApiError({
      code: env?.error?.code ?? statusToCode(res.status),
      message: env?.error?.message ?? "request failed",
      status: res.status,
      details: env?.error?.details,
      requestId: env?.error?.request_id,
      retryAfter: Number.isFinite(retry) && retry > 0 ? retry : undefined,
    });
    // A 401 anywhere except the sign-in calls means the session is gone.
    if (err.status === 401 && !AUTH_PATHS.has(path)) onUnauthenticated?.();
    throw err;
  }

  const ok = json as ApiSuccess<T>;
  return ok.data;
}

function statusToCode(status: number): string {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 429) return "rate_limited";
  if (status >= 500) return "internal_error";
  return "bad_request";
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>("GET", path, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>("POST", path, { ...opts, body }),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>("PATCH", path, { ...opts, body }),
  delete: <T>(path: string, opts?: RequestOptions) => request<T>("DELETE", path, opts),
};
