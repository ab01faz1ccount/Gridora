import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrfToken, setUnauthenticatedListener } from "@/api/client";
import { keys } from "@/api/hooks";
import { catalogs } from "@/i18n";
import { reloadPrefs } from "@/state/prefs";
import { useUi } from "@/state/ui";
import { App } from "@/app/App";
import { err, mockApi, ok, type Handler } from "@/test/mockApi";

const fa = catalogs.fa;
const ME = { user: { id: "u2", username: "newbie", role: "user" }, csrf_token: "csrf-2" };
const signedOut: Record<string, Handler> = {
  "GET /auth/me": () => err(401, "unauthenticated"),
  "GET /auth/config": () => ok({ registration_enabled: true, password_min_length: 10 }),
};

function renderApp() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  setUnauthenticatedListener(() => qc.setQueryData(keys.me, null));
  return render(<QueryClientProvider client={qc}><App /></QueryClientProvider>);
}

beforeEach(() => {
  reloadPrefs();
  useUi.setState({ implementation: {}, toasts: [] });
  window.history.replaceState(null, "", "/");
});
afterEach(() => {
  setCsrfToken(null);
  setUnauthenticatedListener(null);
  vi.unstubAllGlobals();
});

describe("sign-up", () => {
  it("offers sign-up only when the server allows it", async () => {
    mockApi({ ...signedOut, "GET /auth/config": () => ok({ registration_enabled: false, password_min_length: 10 }) });
    renderApp();
    await screen.findByRole("heading", { name: fa["auth.title"] });
    expect(screen.queryByRole("button", { name: fa["auth.signupLink"] })).toBeNull();
  });

  it("creates the account, sends the right body, and lands signed in", async () => {
    const m = mockApi({ ...signedOut, "POST /auth/register": () => ({ ...ok(ME), status: 201 }), "GET /workspaces": () => ok([]) });
    renderApp();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: fa["auth.signupLink"] }));
    await user.type(screen.getByLabelText(fa["auth.username"]), " newbie ");
    await user.type(screen.getAllByLabelText(fa["auth.password"])[0]!, "correct horse battery");
    await user.type(screen.getByLabelText(fa["auth.confirmPassword"]), "correct horse battery");
    await user.click(screen.getByRole("button", { name: fa["auth.signupSubmit"] }));
    expect(await screen.findByText("newbie")).toBeInTheDocument();
    expect(m.calls.find((c) => c.path === "/auth/register")?.body).toEqual({ username: "newbie", password: "correct horse battery" });
  });

  it("does not send when the two passwords differ", async () => {
    const m = mockApi({ ...signedOut });
    renderApp();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: fa["auth.signupLink"] }));
    await user.type(screen.getByLabelText(fa["auth.username"]), "newbie");
    await user.type(screen.getAllByLabelText(fa["auth.password"])[0]!, "correct horse battery");
    await user.type(screen.getByLabelText(fa["auth.confirmPassword"]), "something else here");
    expect(await screen.findByText(fa["auth.passwordMismatch"])).toBeInTheDocument();
    expect(screen.getByRole("button", { name: fa["auth.signupSubmit"] })).toBeDisabled();
    expect(m.calls.some((c) => c.path === "/auth/register")).toBe(false);
  });

  it("explains a taken username in plain language", async () => {
    mockApi({ ...signedOut, "POST /auth/register": () => err(409, "operation_conflict", {}, [{ code: "auth.username_taken", message: "x" }]) });
    renderApp();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: fa["auth.signupLink"] }));
    await user.type(screen.getByLabelText(fa["auth.username"]), "alice");
    await user.type(screen.getAllByLabelText(fa["auth.password"])[0]!, "correct horse battery");
    await user.type(screen.getByLabelText(fa["auth.confirmPassword"]), "correct horse battery");
    await user.click(screen.getByRole("button", { name: fa["auth.signupSubmit"] }));
    expect(await screen.findByText(fa["error.reason.username_taken"])).toBeInTheDocument();
  });
});

describe("account page", () => {
  it("changes the password and says the other devices were signed out", async () => {
    window.history.replaceState(null, "", "/account");
    const m = mockApi({ "GET /auth/me": () => ok(ME), "POST /auth/password": () => ({ status: 204 }) });
    renderApp();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(fa["account.current"]), "correct horse battery");
    await user.type(screen.getByLabelText(fa["account.new"]), "a different long phrase");
    await user.type(screen.getByLabelText(fa["auth.confirmPassword"]), "a different long phrase");
    await user.click(screen.getByRole("button", { name: fa["account.save"] }));
    expect(await screen.findByText(fa["account.saved"])).toBeInTheDocument();
    expect(m.calls.find((c) => c.path === "/auth/password")?.body).toEqual({
      current_password: "correct horse battery", new_password: "a different long phrase",
    });
  });

  it("a wrong current password stays on the page (it is not a lost session)", async () => {
    window.history.replaceState(null, "", "/account");
    mockApi({ "GET /auth/me": () => ok(ME), "POST /auth/password": () => err(401, "unauthenticated") });
    renderApp();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(fa["account.current"]), "nope nope nope");
    await user.type(screen.getByLabelText(fa["account.new"]), "a different long phrase");
    await user.type(screen.getByLabelText(fa["auth.confirmPassword"]), "a different long phrase");
    await user.click(screen.getByRole("button", { name: fa["account.save"] }));
    expect(await screen.findByText(fa["account.wrongCurrent"])).toBeInTheDocument();
    expect(window.location.pathname).toBe("/account");
  });
});
