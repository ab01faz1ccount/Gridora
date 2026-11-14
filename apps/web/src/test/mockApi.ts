import { vi } from "vitest";

export interface Call {
  method: string;
  path: string; // without /api/v1, with query
  headers: Record<string, string>;
  body: unknown;
}
export type Handler = (call: Call) => { status?: number; body?: unknown; headers?: Record<string, string> } | undefined;

/** Installs a fake fetch. Handlers are matched by "METHOD /path" (exact, query included). */
export function mockApi(routes: Record<string, Handler>, defaults: Record<string, string> = {}) {
  const calls: Call[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.replace(/^\/api\/v1/, "");
    const headers = Object.fromEntries(
      Object.entries((init?.headers ?? {}) as Record<string, string>),
    );
    const call: Call = {
      method,
      path,
      headers,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    calls.push(call);
    const handler = routes[`${method} ${path}`];
    if (!handler) throw new Error(`unmocked request: ${method} ${path}`);
    const out = handler(call) ?? { status: 204 };
    const status = out.status ?? 200;
    const h = new Headers({ "Content-Type": "application/json", ...defaults, ...out.headers });
    if (status === 204) return new Response(null, { status, headers: h });
    return new Response(JSON.stringify(out.body), { status, headers: h });
  });
  vi.stubGlobal("fetch", fn);
  return { calls, fetch: fn };
}

export const ok = <T>(data: T) => ({ status: 200, body: { data, meta: { request_id: "r1" } } });
export const err = (status: number, code: string, headers?: Record<string, string>) => ({
  status,
  headers,
  body: { error: { code, message: "server text must not be shown", details: [], request_id: "r9" } },
});
