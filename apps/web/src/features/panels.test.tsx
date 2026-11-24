import type { ChartData, ChartSpec } from "@contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePrefs } from "@/state/prefs";
import { useUi } from "@/state/ui";
import { mockApi, ok } from "@/test/mockApi";
import { ChartView } from "./charts/ChartView";
import { ExportPanel } from "./export/ExportPanel";
import { TablesPanel } from "./tables/TablesPanel";
import { ToolsPanel } from "./tools/ToolsPanel";

const SHEET = { id: "s1", name: "Sales", index: 0, visible: "visible" as const, row_count: 10, col_count: 3, rtl: false };
const wrap = (ui: React.ReactNode) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
beforeEach(() => {
  usePrefs.setState({ digits: "latin", locale: "en" });
  useUi.setState({ toasts: [] });
});

describe("export panel", () => {
  it("exports, offers the download and shows what the file does not keep", async () => {
    const api = mockApi({
      "POST /workbooks/w1/export": () => ({ status: 202, body: { data: { id: "j1", kind: "export", status: "queued" }, meta: { request_id: "r" } } }),
      "GET /jobs/j1": () => ok({ id: "j1", kind: "export", status: "succeeded", result_ref: "file9" }),
      "GET /jobs/j1/compatibility": () => ok({
        source: "export", generated_at: "", summary: { supported: 3, partial: 1, unsupported: 0 },
        items: [{ code: "x", status: "partial", preserved: false, editable: false, message: "Charts are not written yet." }],
      }),
    });
    wrap(<ExportPanel workbookId="w1" sheet={SHEET} onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /Export as Excel/ }));
    const link = await screen.findByRole("link", { name: /Download XLSX/ });
    expect(link).toHaveAttribute("href", "/api/v1/files/file9/download");
    expect(await screen.findByText("Charts are not written yet.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "/workbooks/w1/export")?.body).toEqual({ format: "xlsx" });
  });

  it("csv exports the current sheet", async () => {
    const api = mockApi({
      "POST /workbooks/w1/export": () => ({ status: 202, body: { data: { id: "j2", kind: "export", status: "queued" }, meta: { request_id: "r" } } }),
      "GET /jobs/j2": () => ok({ id: "j2", kind: "export", status: "failed" }),
    });
    wrap(<ExportPanel workbookId="w1" sheet={SHEET} onClose={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /CSV/ }));
    expect(await screen.findByText("The export failed.")).toBeInTheDocument();
    expect(api.calls[0]!.body).toEqual({ format: "csv", sheet_id: "s1" });
  });
});

describe("chart view", () => {
  const spec = (type: ChartSpec["type"]): ChartSpec => ({
    schema_version: 1, document_id: "w1", type, title: "Sales", source: { kind: "data_table", table_id: "t" },
    series: [{ value_col: 1 }], options: { stacked: false, legend: true },
  });
  const data: ChartData = { categories: ["a", "b", "c"], series: [{ name: "n", values: [1, 3, null] }, { name: "m", values: [2, 2, 2] }] };
  it.each(["bar", "line", "area", "scatter", "pie"] as const)("draws a %s chart with a text label", (type) => {
    const d = type === "scatter" ? { ...data, categories: [1, 2, 3] } : data;
    const { container } = render(<ChartView spec={spec(type)} data={d} />);
    expect(screen.getByRole("img", { name: "Sales" })).toBeInTheDocument();
    expect(container.querySelectorAll("rect, path, circle").length).toBeGreaterThan(0);
  });
});

describe("tools panel", () => {
  it("runs a tool on the selection through the editor's queue", async () => {
    mockApi({
      "GET /tools": () => ok([{ id: "t1", name: "Clean names", description: "trim", pipeline: { name: "p", input_kind: "sheet_range", steps: [] },
        inputs: [{ name: "col", kind: "value", label: "Column", required: true }] }]),
    });
    const write = vi.fn((_path: string, body: (n: number) => unknown) => { void body; return Promise.resolve(); });
    const editor = { write } as never;
    wrap(<ToolsPanel workbookId="w1" sheet={SHEET} bounds={{ r0: 0, c0: 0, r1: 4, c1: 1 }} editor={editor} onClose={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: /Clean names/ }));
    const run = screen.getByRole("button", { name: "Run the tool" });
    expect(run).toBeDisabled(); // a required input is empty
    await userEvent.type(screen.getByLabelText(/Column/), "B");
    await userEvent.click(run);
    await waitFor(() => expect(write).toHaveBeenCalled());
    expect(write.mock.calls[0]![0]).toBe("/tools/t1/run");
    expect(write.mock.calls[0]![1](7)).toEqual({
      workbook_id: "w1", target: { kind: "sheet_range", range: { sheet_id: "s1", r0: 0, c0: 0, r1: 4, c1: 1 } },
      inputs: { col: "B" }, base_seq: 7, confirm_destructive: false,
    });
  });
});

describe("tables panel", () => {
  it("previews the selection, creates the table and lists it", async () => {
    const tables: unknown[] = [];
    const api = mockApi({
      "GET /workspaces/ws1/tables": () => ok(tables),
      "POST /tables/from-range": (call) => {
        const b = call.body as { preview?: boolean };
        if (b.preview) return ok({ columns: [{ name: "name", dtype: "string", nullable: true }], rows: [["Ali"], ["Sara"]], row_count: 2, warnings: [] });
        tables.push({ id: "tb1", name: "People", version: 1, columns: [{ name: "name", dtype: "string", nullable: true }], row_count: 2 });
        return ok(tables[0]);
      },
      "GET /tables/tb1/rows?offset=0&limit=20": () => ok({ table_id: "tb1", version: 1, columns: [{ name: "name", dtype: "string", nullable: true }], row_count: 2, offset: 0, rows: [["Ali"], ["Sara"]] }),
    });
    wrap(<TablesPanel workspaceId="ws1" workbookId="w1" sheet={SHEET} bounds={{ r0: 0, c0: 0, r1: 2, c1: 0 }} active={{ r: 0, c: 0 }}
      editor={{ write: vi.fn() } as never} onClose={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Make a table from the selection" }));
    expect(await screen.findByText(/2 rows, 1 columns found/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Table name"), "People");
    await userEvent.click(screen.getByRole("button", { name: "Create the table" }));
    expect(await screen.findByText("Ali")).toBeInTheDocument(); // the new table opens with its rows
    const created = api.calls.find((c) => c.method === "POST" && !(c.body as { preview?: boolean }).preview);
    expect(created?.body).toMatchObject({ workbook_id: "w1", header_row: true, name: "People", range: { r0: 0, r1: 2 } });
  });

  it("asks for a range when only one cell is selected", async () => {
    mockApi({ "GET /workspaces/ws1/tables": () => ok([]) });
    wrap(<TablesPanel workspaceId="ws1" workbookId="w1" sheet={SHEET} bounds={{ r0: 0, c0: 0, r1: 0, c1: 0 }} active={{ r: 0, c: 0 }}
      editor={{ write: vi.fn() } as never} onClose={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Make a table from the selection" }));
    expect(screen.getByText(/Select a range with a header row/)).toBeInTheDocument();
  });
});
