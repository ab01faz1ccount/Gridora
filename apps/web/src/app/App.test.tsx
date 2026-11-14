import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  setCsrfToken,
  setImplementationListener,
  setUnauthenticatedListener,
} from "@/api/client";
import { keys } from "@/api/hooks";
import { catalogs } from "@/i18n";
import { reloadPrefs } from "@/state/prefs";
import { useUi } from "@/state/ui";
import { err, mockApi, ok, type Handler } from "@/test/mockApi";
import { App } from "./App";

const fa = catalogs.fa;
const en = catalogs.en;
const ME = { user: { id: "u1", username: "alice", role: "user" }, csrf_token: "csrf-1" };
const WS = (id: string, name: string) => ({
  id, owner_id: "u1", name, created_at: "2026-11-14T10:00:00Z",
});

function renderApp() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  setImplementationListener((i) => useUi.getState().setImplementation(i));
  setUnauthenticatedListener(() => qc.setQueryData(keys.me, null));
  return { qc, ...render(<QueryClientProvider client={qc}><App /></QueryClientProvider>) };
}

beforeEach(() => {
  reloadPrefs();
  useUi.setState({ implementation: {}, toasts: [] });
  window.history.replaceState(null, "", "/");
});
afterEach(() => {
  setCsrfToken(null);
  setImplementationListener(null);
  setUnauthenticatedListener(null);
  vi.unstubAllGlobals();
});

const signedOut: Record<string, Handler> = { "GET /auth/me": () => err(401, "unauthenticated") };

describe("signed out", () => {
  it("shows the Persian, RTL login page and sends the user to /login", async () => {
    mockApi(signedOut);
    renderApp();
    expect(await screen.findByRole("heading", { name: fa["auth.title"] })).toBeInTheDocument();
    expect(document.documentElement.dir).toBe("rtl");
    expect(document.documentElement.lang).toBe("fa");
    expect(window.location.pathname).toBe("/login");
    expect(screen.getByLabelText(fa["auth.username"])).toBeInTheDocument();
  });

  it("a wrong password shows the localized message, not the server's text", async () => {
    mockApi({ ...signedOut, "POST /auth/login": () => err(401, "unauthenticated") });
    renderApp();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(fa["auth.username"]), "alice");
    await user.type(screen.getByLabelText(fa["auth.password"]), "wrong");
    await user.click(screen.getByRole("button", { name: fa["auth.submit"] }));
    expect(await screen.findByRole("alert")).toHaveTextContent(fa["auth.invalidCredentials"]);
    expect(screen.queryByText(/server text/)).toBeNull();
  });

  it("rate limiting tells the user how long to wait", async () => {
    mockApi({ ...signedOut, "POST /auth/login": () => err(429, "rate_limited", { "Retry-After": "90" }) });
    renderApp();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(fa["auth.username"]), "a");
    await user.type(screen.getByLabelText(fa["auth.password"]), "b");
    await user.click(screen.getByRole("button", { name: fa["auth.submit"] }));
    expect(await screen.findByRole("alert")).toHaveTextContent("90");
  });

  it("login success shows the workspaces and keeps the CSRF token for later calls", async () => {
    const m = mockApi({
      ...signedOut,
      "POST /auth/login": () => ok(ME),
      "GET /workspaces": () => ok([WS("w1", "فروش ۱۴۰۵")]),
    });
    renderApp();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(fa["auth.username"]), "alice");
    await user.type(screen.getByLabelText(fa["auth.password"]), "correct horse battery");
    await user.click(screen.getByRole("button", { name: fa["auth.submit"] }));
    expect(await screen.findByText("فروش ۱۴۰۵")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/workspaces");
    expect(m.calls.find((c) => c.path === "/auth/login")?.body).toEqual({
      username: "alice",
      password: "correct horse battery",
    });
  });
});

describe("signed in", () => {
  function signedInApi(extra: Record<string, Handler> = {}, list = [WS("w1", "Alpha")]) {
    return mockApi({ "GET /auth/me": () => ok(ME), "GET /workspaces": () => ok(list), ...extra });
  }

  it("restores the session on reload and lists workspaces with formatted dates", async () => {
    signedInApi();
    renderApp();
    expect(await screen.findByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("alice")).toBeInTheDocument();
    // Persian digits by default (display only)
    expect(screen.getByText(/[۰-۹]{4}/)).toBeInTheDocument();
  });

  it("an empty list explains what to do", async () => {
    signedInApi({}, []);
    renderApp();
    expect(await screen.findByText(fa["workspaces.empty"])).toBeInTheDocument();
  });

  it("switching language flips direction and text; the choice is remembered", async () => {
    signedInApi();
    renderApp();
    const user = userEvent.setup();
    await screen.findByText("Alpha");
    await user.click(screen.getByRole("button", { name: fa["nav.language"] }));
    expect(await screen.findByRole("heading", { name: en["workspaces.title"] })).toBeInTheDocument();
    expect(document.documentElement.dir).toBe("ltr");
    expect(document.documentElement.lang).toBe("en");
    expect(JSON.parse(localStorage.getItem("gridora.prefs") ?? "{}").locale).toBe("en");
  });

  it("digits and calendar are display choices", async () => {
    signedInApi();
    renderApp();
    const user = userEvent.setup();
    await screen.findByText("Alpha");
    await user.selectOptions(screen.getByLabelText(fa["nav.digits"]), "latin");
    await user.selectOptions(screen.getByLabelText(fa["nav.calendar"]), "jalali");
    expect(screen.getByText(/1405/)).toBeInTheDocument();
  });

  it("creates a workspace (trimmed name, CSRF header) and refreshes the list", async () => {
    let list = [WS("w1", "Alpha")];
    const m = mockApi({
      "GET /auth/me": () => ok(ME),
      "GET /workspaces": () => ok(list),
      "POST /workspaces": (c) => {
        const created = WS("w2", (c.body as { name: string }).name);
        list = [...list, created];
        return { status: 201, body: { data: created } };
      },
    });
    renderApp();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(fa["workspaces.nameLabel"]), "  Beta  ");
    await user.click(screen.getByRole("button", { name: fa["workspaces.create"] }));
    expect(await screen.findByText("Beta")).toBeInTheDocument();
    const post = m.calls.find((c) => c.method === "POST" && c.path === "/workspaces");
    expect(post?.body).toEqual({ name: "Beta" });
    expect(post?.headers["X-CSRF-Token"]).toBe("csrf-1");
  });

  it("delete asks first, cancel does nothing, confirm sends ?confirm=true", async () => {
    let list = [WS("w1", "Alpha")];
    const m = mockApi({
      "GET /auth/me": () => ok(ME),
      "GET /workspaces": () => ok(list),
      "DELETE /workspaces/w1?confirm=true": () => { list = []; return undefined; },
    });
    renderApp();
    const user = userEvent.setup();
    await screen.findByText("Alpha");

    await user.click(screen.getByRole("button", { name: fa["workspaces.delete"] }));
    let dialog = screen.getByRole("dialog", { name: fa["workspaces.deleteTitle"] });
    expect(dialog).toHaveTextContent("Alpha");
    await user.click(within(dialog).getByRole("button", { name: fa["common.cancel"] }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(m.calls.some((c) => c.method === "DELETE")).toBe(false);

    await user.click(screen.getByRole("button", { name: fa["workspaces.delete"] }));
    dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: fa["workspaces.deleteAction"] }));
    await waitFor(() => expect(m.calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(await screen.findByText(fa["workspaces.empty"])).toBeInTheDocument();
  });

  it("Escape closes a dialog and focus returns to the button that opened it", async () => {
    signedInApi();
    renderApp();
    const user = userEvent.setup();
    await screen.findByText("Alpha");
    const opener = screen.getByRole("button", { name: fa["workspaces.rename"] });
    await user.click(opener);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText(fa["workspaces.nameLabel"], { selector: "[role=dialog] input" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("a failed call shows a localized toast, never the server's text", async () => {
    signedInApi({ "POST /workspaces": () => err(409, "operation_conflict") });
    renderApp();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(fa["workspaces.nameLabel"]), "X");
    await user.click(screen.getByRole("button", { name: fa["workspaces.create"] }));
    expect(await screen.findByRole("alert")).toHaveTextContent(fa["error.operation_conflict"]);
    expect(screen.queryByText(/server text/)).toBeNull();
  });

  it("a session that disappears sends the user back to the login page", async () => {
    let alive = true;
    mockApi({
      "GET /auth/me": () => ok(ME),
      "GET /workspaces": () => (alive ? ok([WS("w1", "Alpha")]) : err(401, "unauthenticated")),
      "POST /workspaces": () => err(401, "unauthenticated"),
    });
    renderApp();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(fa["workspaces.nameLabel"]), "X");
    alive = false;
    await user.click(screen.getByRole("button", { name: fa["workspaces.create"] }));
    expect(await screen.findByRole("heading", { name: fa["auth.title"] })).toBeInTheDocument();
  });

  it("shows the stub-engine badge only when the server says it runs stubs", async () => {
    mockApi(
      { "GET /auth/me": () => ok(ME), "GET /workspaces": () => ok([]) },
      { "X-Gridora-Engine": "stub", "X-Gridora-Dataops": "stub" },
    );
    const { unmount } = renderApp();
    expect(await screen.findByText(fa["app.stubBadge"])).toBeInTheDocument();
    unmount();

    useUi.setState({ implementation: {} });
    mockApi(
      { "GET /auth/me": () => ok(ME), "GET /workspaces": () => ok([]) },
      { "X-Gridora-Engine": "real", "X-Gridora-Dataops": "real" },
    );
    renderApp();
    await screen.findByText(fa["workspaces.empty"]);
    expect(screen.queryByText(fa["app.stubBadge"])).toBeNull();
  });

  it("logout clears the session and returns to login", async () => {
    let alive = true;
    const m = mockApi({
      "GET /auth/me": () => (alive ? ok(ME) : err(401, "unauthenticated")),
      "GET /workspaces": () => ok([WS("w1", "Alpha")]),
      "POST /auth/logout": () => {
        alive = false; // the real server deletes the session
        return undefined;
      },
    });
    renderApp();
    const user = userEvent.setup();
    await screen.findByText("Alpha");
    await user.click(screen.getByRole("button", { name: fa["nav.logout"] }));
    expect(await screen.findByRole("heading", { name: fa["auth.title"] })).toBeInTheDocument();
    expect(m.calls.find((c) => c.path === "/auth/logout")?.headers["X-CSRF-Token"]).toBe("csrf-1");
    expect(screen.queryByText("Alpha")).toBeNull(); // no data of the previous user stays cached
  });
});
