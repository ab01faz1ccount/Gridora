import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrfToken } from "@/api/client";
import { navigate } from "@/app/router";
import { WorkspaceDetailPage } from "@/features/workspaces/WorkspaceDetailPage";
import { catalogs } from "@/i18n";
import { useImports } from "@/state/imports";
import { reloadPrefs, usePrefs } from "@/state/prefs";
import { useUi } from "@/state/ui";
import { FakeXhr, installFakeXhr, lastXhr } from "@/test/fakeXhr";
import { err, mockApi, ok } from "@/test/mockApi";

const fa = catalogs.fa;
const WS = "11111111-1111-1111-1111-111111111111";
const FILE = { id: "f1", workspace_id: WS, owner_id: "u1", kind: "original", display_name: "x.csv", size_bytes: 5, sha256: "a", created_at: "2026-11-14T10:00:00Z" };
const REPORT = (items: { status: "supported" | "partial" | "unsupported"; code: string; location?: string }[]) => ({
  source: "import", generated_at: "2026-11-14T10:00:00Z",
  items: items.map((i) => ({ ...i, preserved: i.status !== "unsupported", editable: i.status === "supported", message: `msg ${i.code}` })),
  summary: { supported: 0, partial: 0, unsupported: 0 },
});
const WORKBOOK = (items: Parameters<typeof REPORT>[0]) => ({ id: "wb1", file_id: "f1", name: "x.csv", sheets: [], defined_names: [], date_system: "1900", compat: REPORT(items) });

function app() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><WorkspaceDetailPage id={WS} /></QueryClientProvider>);
}
const csv = (name = "x.csv", size = 5) => {
  const f = new File(["a,b\n1,2"], name, { type: "text/csv" });
  Object.defineProperty(f, "size", { value: size });
  return f;
};
const baseRoutes = (over: Record<string, Parameters<typeof mockApi>[0][string]> = {}) => ({
  [`GET /workspaces/${WS}`]: () => ok({ id: WS, owner_id: "u1", name: "فروش", created_at: "2026-11-14T10:00:00Z" }),
  [`GET /workspaces/${WS}/files`]: () => ok([]),
  ...over,
});
const choose = async (f: File) => userEvent.upload(screen.getByTestId("file-input"), f);

beforeEach(() => {
  reloadPrefs();
  usePrefs.setState({ digits: "latin" });
  localStorage.clear();
  useImports.setState({ entries: [] });
  useUi.setState({ panel: null, toasts: [] });
  installFakeXhr();
  setCsrfToken("csrf-9");
  window.history.replaceState(null, "", `/workspaces/${WS}`);
});
afterEach(() => { vi.unstubAllGlobals(); setCsrfToken(null); });

describe("empty workspace", () => {
  it("shows the big drop zone and the empty file list (UX spec section 8)", async () => {
    mockApi(baseRoutes());
    app();
    expect(await screen.findByText(fa["import.dropTitle"])).toBeInTheDocument();
    expect(await screen.findByText(fa["import.noFiles"])).toBeInTheDocument();
  });
});

describe("F1: opening a file", () => {
  it("uploads with CSRF, shows progress, then opens cleanly and goes straight to Open", async () => {
    const m = mockApi(baseRoutes({
      "GET /jobs/job1": () => ok({ id: "job1", kind: "import", status: "succeeded", result_ref: "wb1", progress: 1 }),
      "POST /files/f1/open": () => ok(WORKBOOK([{ status: "supported", code: "rtl_view" }])),
    }));
    app();
    await screen.findByText(fa["import.dropTitle"]);
    await choose(csv("sales.csv", 1000));

    const x = lastXhr();
    expect(x.method).toBe("POST");
    expect(x.url).toBe(`/api/v1/workspaces/${WS}/files`);
    expect(x.headers["X-CSRF-Token"]).toBe("csrf-9");
    expect(x.withCredentials).toBe(true);
    expect((x.body?.get("file") as File).name).toBe("sales.csv");

    act(() => x.progress(500, 1000));
    expect(await screen.findByText(/50/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    x.respond(201, { data: { file: { ...FILE, id: "f1" }, job_id: "job1" } });

    expect(await screen.findByText(fa["import.openedClean"])).toBeInTheDocument();
    expect(screen.queryByText(fa["import.showReport"])).toBeNull(); // nothing needs attention
    expect(m.calls.some((c) => c.path === "/jobs/job1")).toBe(true);

    await userEvent.click(screen.getByRole("button", { name: fa["import.open"] }));
    expect(window.location.pathname).toBe("/workbooks/wb1");
  });

  it("counts what needs attention (everything not fully supported) and offers the report", async () => {
    mockApi(baseRoutes({
      "GET /jobs/job1": () => ok({ id: "job1", kind: "import", status: "succeeded", result_ref: "wb1" }),
      "POST /files/f1/open": () => ok(WORKBOOK([
        { status: "supported", code: "rtl_view" }, { status: "partial", code: "formulas", location: "Sheet1!F12" },
        { status: "unsupported", code: "vba" },
      ])),
    }));
    app();
    await screen.findByText(fa["import.dropTitle"]);
    await choose(csv());
    lastXhr().respond(201, { data: { file: FILE, job_id: "job1" } });
    expect(await screen.findByText(fa["import.openedAttention"].replace("{count}", "2"))).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: fa["import.showReport"] }));
    expect(useUi.getState().panel).toBe("report");
    expect(window.location.pathname).toBe("/workbooks/wb1");
  });

  it("keeps polling while the job runs, and says it may take a minute after 5 s", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let finished = false;
      mockApi(baseRoutes({
        "GET /jobs/job1": () => ok({ id: "job1", kind: "import", status: finished ? "succeeded" : "running", result_ref: "wb1" }),
        "POST /files/f1/open": () => ok(WORKBOOK([])),
      }));
      app();
      await screen.findByText(fa["import.dropTitle"]);
      await choose(csv());
      lastXhr().respond(201, { data: { file: FILE, job_id: "job1" } });
      expect(await screen.findByText(fa["import.processing"])).toBeInTheDocument();
      expect(screen.queryByText(new RegExp(fa["import.slow"]))).toBeNull();
      await act(async () => { await vi.advanceTimersByTimeAsync(5200); });
      expect(await screen.findByText(new RegExp(fa["import.slow"]))).toBeInTheDocument();
      expect(screen.getByText(fa["import.cannotCancelJob"])).toBeInTheDocument(); // honest: no cancel API
      finished = true;
      await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
      await waitFor(() => expect(screen.getByText(fa["import.openedClean"])).toBeInTheDocument(), { timeout: 8000 });
    } finally { vi.useRealTimers(); }
  });

  it("the upload can be cancelled while it is being sent", async () => {
    mockApi(baseRoutes());
    app();
    await screen.findByText(fa["import.dropTitle"]);
    await choose(csv());
    const x = lastXhr();
    await userEvent.click(screen.getByRole("button", { name: fa["import.cancel"] }));
    expect(x.aborted).toBe(true);
    await waitFor(() => expect(useImports.getState().entries).toHaveLength(0));
  });
});

describe("F1: files that cannot be opened say what to do", () => {
  it(".xls is refused BEFORE sending anything, with the Save-As-xlsx advice", async () => {
    mockApi(baseRoutes());
    app();
    await screen.findByText(fa["import.dropTitle"]);
    await choose(csv("old.xls"));
    expect(FakeXhr.instances).toHaveLength(0);
    expect(await screen.findByRole("alert")).toHaveTextContent(fa["error.reason.legacy_xls"]);
  });

  it("a file over 100 MB is refused before sending", async () => {
    mockApi(baseRoutes());
    app();
    await screen.findByText(fa["import.dropTitle"]);
    await choose(csv("huge.csv", 100 * 1024 * 1024 + 1));
    expect(FakeXhr.instances).toHaveLength(0);
    expect(await screen.findByRole("alert")).toHaveTextContent(fa["error.file_too_large"]);
  });

  it("an encrypted workbook (import job fails with the engine's reason) gets the plain message, not a code", async () => {
    mockApi(baseRoutes({
      "GET /jobs/job1": () => ok({ id: "job1", kind: "import", status: "failed", error: { code: "unsupported_workbook", message: "English text", details: [{ code: "xlsx.encrypted", message: "m" }], request_id: "r" } }),
    }));
    app();
    await screen.findByText(fa["import.dropTitle"]);
    await choose(csv("locked.xlsx"));
    lastXhr().respond(201, { data: { file: FILE, job_id: "job1" } });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(fa["error.reason.encrypted"]);
    expect(alert).not.toHaveTextContent(/xlsx\.encrypted|unsupported_workbook|English text/);
  });

  it("a server refusal at upload time (415) and a dropped connection are explained too", async () => {
    mockApi(baseRoutes());
    app();
    await screen.findByText(fa["import.dropTitle"]);
    await choose(csv("a.csv"));
    lastXhr().respond(415, { error: { code: "unsupported_media_type", message: "x", details: [], request_id: "r" } });
    expect(await screen.findByRole("alert")).toHaveTextContent(fa["error.unsupported_media_type"]);
    await userEvent.click(screen.getByRole("button", { name: fa["import.dismiss"] }));
    await choose(csv("b.csv"));
    lastXhr().fail();
    expect(await screen.findByRole("alert")).toHaveTextContent(fa["error.network"]);
  });

  it("the stub engine's XLSX refusal is explained in Persian", async () => {
    mockApi(baseRoutes({
      "GET /jobs/job1": () => ok({ id: "job1", kind: "import", status: "failed", error: { code: "unsupported_workbook", message: "m", details: [{ code: "stub.xlsx_unsupported", message: "m" }], request_id: "r" } }),
    }));
    app();
    await screen.findByText(fa["import.dropTitle"]);
    await choose(csv("a.xlsx"));
    lastXhr().respond(201, { data: { file: FILE, job_id: "job1" } });
    expect(await screen.findByRole("alert")).toHaveTextContent(fa["error.reason.stub_xlsx"]);
  });
});

describe("resuming after a page reload", () => {
  it("a processing import is remembered by job id and polling resumes", async () => {
    mockApi(baseRoutes({
      "GET /jobs/job7": () => ok({ id: "job7", kind: "import", status: "succeeded", result_ref: "wb7" }),
      "POST /files/f7/open": () => ok(WORKBOOK([])),
    }));
    localStorage.setItem("gridora.imports", JSON.stringify([{ key: "k", workspaceId: WS, name: "big.xlsx", size: 99, jobId: "job7", fileId: "f7" }]));
    const { restoreImports } = await import("@/state/imports");
    useImports.setState({ entries: restoreImports() });
    app();
    expect(await screen.findByText(fa["import.openedClean"])).toBeInTheDocument();
    expect(screen.getByText("big.xlsx")).toBeInTheDocument();
  });

  it("only processing imports are persisted, and corrupt storage is ignored", async () => {
    const { restoreImports } = await import("@/state/imports");
    localStorage.setItem("gridora.imports", "{nope");
    expect(restoreImports()).toEqual([]);
    localStorage.setItem("gridora.imports", JSON.stringify([{ key: 1 }, { key: "a", jobId: "j", workspaceId: "w" }]));
    expect(restoreImports()).toHaveLength(1);
  });
});

describe("the file list", () => {
  it("lists stored files and opens one (a failed open is explained, not silent)", async () => {
    mockApi(baseRoutes({
      [`GET /workspaces/${WS}/files`]: () => ok([FILE, { ...FILE, id: "f2", display_name: "y.xlsx" }]),
      "POST /files/f1/open": () => ok({ ...WORKBOOK([]), id: "wb1" }),
      "POST /files/f2/open": () => err(422, "unsupported_workbook"),
    }));
    app();
    const list = await screen.findByRole("list", { name: "" }).catch(() => null);
    void list;
    const buttons = await screen.findAllByRole("button", { name: fa["import.openFile"] });
    await userEvent.click(buttons[1]!);
    await waitFor(() => expect(useUi.getState().toasts[0]?.text).toBe(fa["error.unsupported_workbook"]));
    await userEvent.click(buttons[0]!);
    await waitFor(() => expect(window.location.pathname).toBe("/workbooks/wb1"));
    navigate(`/workspaces/${WS}`);
    void within; void fireEvent;
  });
});
