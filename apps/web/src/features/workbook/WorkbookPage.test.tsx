import type { Cell } from "@contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { catalogs } from "@/i18n";
import { usePrefs } from "@/state/prefs";
import { useUi } from "@/state/ui";
import { err, mockApi, ok } from "@/test/mockApi";
import { WorkbookPage } from "./WorkbookPage";

const fa = catalogs.fa;
const SHEET = { id: "s1", name: "Sheet1", index: 0, visible: "visible", row_count: 50, col_count: 5, rtl: false };
const WORKBOOK = { id: "w1", file_id: "f1", name: "book", sheets: [SHEET], defined_names: [], date_system: "1900" };
const entry = (seq: number, undone = false) => ({
  id: `h${seq}`, document_id: "w1", seq, operation: {}, delta: { kind: "cell_patch", sheet_id: "s1", before: [], after: [] },
  label: "", created_at: "", undone,
});

/** A tiny server: cells live in a map; edits, undo and redo change it like the real one would. */
function server() {
  const cells = new Map<string, Cell>();
  const history: { seq: number; undone: boolean; before: Cell; after: Cell }[] = [];
  const key = (r: number, c: number) => `${r}:${c}`;
  const get = (r: number, c: number): Cell => cells.get(key(r, c)) ?? { r, c };
  const set = (cell: Cell) => (cell.v || cell.f ? cells.set(key(cell.r, cell.c), cell) : cells.delete(key(cell.r, cell.c)));
  const head = () => Math.max(0, ...history.filter((h) => !h.undone).map((h) => h.seq));
  return mockApi({
    "GET /workbooks/w1": () => ok(WORKBOOK),
    "GET /workbooks/w1/sheets/s1/cells?r0=0&c0=0&rows=100&cols=26": () => ok({ sheet_id: "s1", row0: 0, col0: 0, rows: 100, cols: 26, cells: [...cells.values()] }),
    "GET /documents/w1/history?limit=100": () => ok([...history].reverse().map((h) => entry(h.seq, h.undone))),
    "PATCH /workbooks/w1/sheets/s1/cells": (call) => {
      const body = call.body as { base_seq: number; edits: { r: number; c: number; value?: Cell["v"]; formula?: string }[] };
      if (body.base_seq !== head()) return err(409, "version_conflict");
      const e = body.edits[0]!;
      const before = get(e.r, e.c);
      const after: Cell = { r: e.r, c: e.c, ...(e.value ? { v: e.value } : {}), ...(e.formula ? { f: e.formula } : {}) };
      set(after);
      history.splice(history.findIndex((h) => h.undone) < 0 ? history.length : history.findIndex((h) => h.undone));
      const seq = history.length + 1;
      history.push({ seq, undone: false, before, after });
      return ok({ history_entry: entry(seq), sheet_id: "s1", cells: [after] });
    },
    "POST /documents/w1/undo?base_seq=1": () => {
      const h = history.find((x) => x.seq === 1)!;
      h.undone = true;
      set(h.before);
      return ok({ history_entry: entry(1, true), sheet_id: "s1", cells: [h.before] });
    },
  });
}

function page() {
  usePrefs.setState({ digits: "latin", locale: "en" });
  useUi.setState({ toasts: [] });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><WorkbookPage id="w1" /></QueryClientProvider>);
}
// jsdom has no layout: give elements a size so the grid renders a window of cells
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(764);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(528);
});
afterEach(() => vi.restoreAllMocks());

const ready = () =>
  waitFor(() => {
    expect(document.querySelector("[role=gridcell]")).not.toBeNull();
    expect(document.querySelector("[role=gridcell][aria-busy]")).toBeNull();
  });
const grid = () => screen.getByRole("grid");
const cellText = (r: number, c: number) => document.getElementById(`gv-${r}-${c}`)?.textContent;

describe("WorkbookPage editing", () => {
  it("typing a number saves it, shows what the server returned, and undo takes it back", async () => {
    const api = server();
    const user = userEvent.setup();
    page();
    await ready();
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();

    grid().focus();
    await user.keyboard("۴۲{Enter}"); // Persian digits are sent as a Latin number
    const patch = api.calls.find((c) => c.method === "PATCH")!;
    expect(patch.body).toEqual({ base_seq: 0, edits: [{ r: 0, c: 0, value: { k: "num", n: 42 } }] });
    await waitFor(() => expect(cellText(0, 0)).toBe("42"));
    expect(screen.getByRole("button", { name: "Undo" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Redo" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(cellText(0, 0)).toBe(""));
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Redo" })).toBeEnabled();
  });

  it("the value bar edits the active cell", async () => {
    const api = server();
    const user = userEvent.setup();
    page();
    await ready();
    const bar = screen.getByRole("textbox", { name: "Value bar" });
    await user.click(bar);
    await user.keyboard("=A2+1{Enter}");
    await waitFor(() => expect(api.calls.filter((c) => c.method === "PATCH")).toHaveLength(1));
    expect(api.calls.find((c) => c.method === "PATCH")!.body).toMatchObject({ edits: [{ r: 0, c: 0, formula: "=A2+1" }] });
  });

  it("an error from the server becomes a plain-language message, not server text", async () => {
    mockApi({
      "GET /workbooks/w1": () => ok(WORKBOOK),
      "GET /workbooks/w1/sheets/s1/cells?r0=0&c0=0&rows=100&cols=26": () => ok({ sheet_id: "s1", row0: 0, col0: 0, rows: 100, cols: 26, cells: [] }),
      "GET /documents/w1/history?limit=100": () => ok([]),
      "PATCH /workbooks/w1/sheets/s1/cells": () => err(422, "validation_failed"),
    });
    const user = userEvent.setup();
    page();
    await ready();
    grid().focus();
    await user.keyboard("x{Enter}");
    await waitFor(() => expect(useUi.getState().toasts.map((t) => t.text)).toEqual([catalogs.en["error.validation_failed"]]));
    expect(fa["error.validation_failed"]).toBeTruthy();
  });

  it("a conflict shows a banner (not a toast), reloads, and goes away after the next successful change", async () => {
    let conflict = true;
    const api = mockApi({
      "GET /workbooks/w1": () => ok(WORKBOOK),
      "GET /workbooks/w1/sheets/s1/cells?r0=0&c0=0&rows=100&cols=26": () => ok({ sheet_id: "s1", row0: 0, col0: 0, rows: 100, cols: 26, cells: [] }),
      "GET /documents/w1/history?limit=100": () => ok([]),
      "PATCH /workbooks/w1/sheets/s1/cells": () => (conflict ? err(409, "version_conflict") : ok({ history_entry: entry(1), sheet_id: "s1", cells: [] })),
    });
    const user = userEvent.setup();
    page();
    await ready();
    grid().focus();
    await user.keyboard("x{Enter}");
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(catalogs.en["conflict.title"]);
    expect(useUi.getState().toasts).toEqual([]);
    expect(api.calls.filter((c) => c.path.startsWith("/documents/w1/history"))).toHaveLength(2); // reloaded

    conflict = false;
    grid().focus();
    await user.keyboard("y{Enter}");
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("the banner can be dismissed", async () => {
    mockApi({
      "GET /workbooks/w1": () => ok(WORKBOOK),
      "GET /workbooks/w1/sheets/s1/cells?r0=0&c0=0&rows=100&cols=26": () => ok({ sheet_id: "s1", row0: 0, col0: 0, rows: 100, cols: 26, cells: [] }),
      "GET /documents/w1/history?limit=100": () => ok([]),
      "PATCH /workbooks/w1/sheets/s1/cells": () => err(409, "version_conflict"),
    });
    const user = userEvent.setup();
    page();
    await ready();
    grid().focus();
    await user.keyboard("x{Enter}");
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("pasting several cells is ONE request and one undo step", async () => {
    const api = server();
    page();
    await ready();
    grid().focus();
    fireEvent.paste(grid(), { clipboardData: { getData: () => "1\t2\n3\t4" } });
    await waitFor(() => expect(api.calls.filter((c) => c.method === "PATCH")).toHaveLength(1));
    expect((api.calls.find((c) => c.method === "PATCH")!.body as { edits: unknown[] }).edits).toHaveLength(4);
  });

  it("the history panel lists changes newest first, marks undone ones and speaks the person's language", async () => {
    const withLabel = (seq: number, label: string, undone: boolean, params: unknown = {}) =>
      ({ ...entry(seq, undone), label, operation: { type: "set_cells", params }, created_at: "2026-11-22T10:00:00Z" });
    mockApi({
      "GET /workbooks/w1": () => ok(WORKBOOK),
      "GET /workbooks/w1/sheets/s1/cells?r0=0&c0=0&rows=100&cols=26": () => ok({ sheet_id: "s1", row0: 0, col0: 0, rows: 100, cols: 26, cells: [] }),
      "GET /documents/w1/history?limit=100": () => ok([]),
      "GET /documents/w1/history?limit=50": () => ok([withLabel(3, "Sort A to Z", true), withLabel(2, "history.cell_edit", false, { count: 4 })]),
    });
    const user = userEvent.setup();
    page();
    await ready();
    await user.click(screen.getByRole("button", { name: "History" }));
    const items = await screen.findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Sort A to Z");
    expect(items[0]).toHaveTextContent("undone");
    expect(items[1]).toHaveTextContent("Edited cells (4 cells)");
    await user.click(screen.getAllByRole("button", { name: "Close panel" })[0]!);
    expect(screen.queryByText("Edited cells (4 cells)")).toBeNull();
  });
});
