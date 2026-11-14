import { afterEach, describe, expect, it, vi } from "vitest";
import { err, mockApi, ok } from "@/test/mockApi";
import {
  api,
  ApiError,
  setCsrfToken,
  setImplementationListener,
  setUnauthenticatedListener,
} from "./client";
import { errorKey } from "./errors";

afterEach(() => {
  setCsrfToken(null);
  setImplementationListener(null);
  setUnauthenticatedListener(null);
  vi.unstubAllGlobals();
});

describe("request", () => {
  it("unwraps the success envelope", async () => {
    mockApi({ "GET /workspaces": () => ok([{ id: "1" }]) });
    expect(await api.get("/workspaces")).toEqual([{ id: "1" }]);
  });

  it("sends the CSRF token on mutating calls only", async () => {
    const m = mockApi({ "GET /x": () => ok(1), "POST /x": () => ok(1), "DELETE /x?confirm=true": () => ok(1) });
    setCsrfToken("tok-123");
    await api.get("/x");
    await api.post("/x", { a: 1 });
    await api.delete("/x", { query: { confirm: true } });
    expect(m.calls[0]?.headers["X-CSRF-Token"]).toBeUndefined();
    expect(m.calls[1]?.headers["X-CSRF-Token"]).toBe("tok-123");
    expect(m.calls[1]?.body).toEqual({ a: 1 });
    expect(m.calls[2]?.headers["X-CSRF-Token"]).toBe("tok-123");
  });

  it("uses same-origin credentials", async () => {
    const m = mockApi({ "GET /x": () => ok(1) });
    await api.get("/x");
    expect(m.fetch.mock.calls[0]?.[1]?.credentials).toBe("same-origin");
  });

  it("turns an error envelope into ApiError with code, status, request id", async () => {
    mockApi({ "GET /x": () => err(404, "not_found") });
    const e = await api.get("/x").catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ code: "not_found", status: 404, requestId: "r9" });
  });

  it("keeps Retry-After on 429", async () => {
    mockApi({ "POST /auth/login": () => err(429, "rate_limited", { "Retry-After": "42" }) });
    const e = (await api.post("/auth/login", {}).catch((x: unknown) => x)) as ApiError;
    expect(e.retryAfter).toBe(42);
  });

  it("maps a dropped connection to code 'network'", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const e = (await api.get("/x").catch((x: unknown) => x)) as ApiError;
    expect(e).toMatchObject({ code: "network", status: 0 });
  });

  it("does not trust a non-JSON body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>oops</html>", { status: 502 })));
    const e = (await api.get("/x").catch((x: unknown) => x)) as ApiError;
    expect(e).toMatchObject({ code: "internal_error", status: 502 });
  });

  it("falls back to a code derived from the status when the envelope is missing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 403 })));
    expect(((await api.get("/x").catch((x: unknown) => x)) as ApiError).code).toBe("forbidden");
  });

  it("returns undefined for 204", async () => {
    mockApi({ "POST /auth/logout": () => undefined });
    expect(await api.post("/auth/logout")).toBeUndefined();
  });

  it("reports a 401 as 'session gone' except for the sign-in calls", async () => {
    const gone = vi.fn();
    setUnauthenticatedListener(gone);
    mockApi({
      "GET /workspaces": () => err(401, "unauthenticated"),
      "GET /auth/me": () => err(401, "unauthenticated"),
      "POST /auth/login": () => err(401, "unauthenticated"),
    });
    await api.get("/workspaces").catch(() => undefined);
    expect(gone).toHaveBeenCalledTimes(1);
    await api.get("/auth/me").catch(() => undefined);
    await api.post("/auth/login", {}).catch(() => undefined);
    expect(gone).toHaveBeenCalledTimes(1);
  });

  it("reports which implementation the server runs", async () => {
    const seen = vi.fn();
    setImplementationListener(seen);
    mockApi({ "GET /x": () => ok(1) }, { "X-Gridora-Engine": "stub", "X-Gridora-Dataops": "stub" });
    await api.get("/x");
    expect(seen).toHaveBeenCalledWith({ engine: "stub", dataops: "stub" });
  });
});

describe("errorKey", () => {
  it("maps known codes and never leaks unknown text", () => {
    expect(errorKey(new ApiError({ code: "file_too_large", message: "m", status: 413 }))).toBe(
      "error.file_too_large",
    );
    expect(errorKey(new ApiError({ code: "network", message: "m", status: 0 }))).toBe("error.network");
    expect(errorKey(new ApiError({ code: "made_up", message: "m", status: 400 }))).toBe("error.generic");
    expect(errorKey(new Error("boom"))).toBe("error.generic");
  });
});
