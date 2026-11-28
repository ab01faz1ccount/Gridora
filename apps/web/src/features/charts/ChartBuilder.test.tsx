import type { ChartData, ChartProfile, ChartSpec } from "@contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePrefs } from "@/state/prefs";
import { err, mockApi, ok } from "@/test/mockApi";
import { ChartBuilder, type SourceChoice } from "./ChartBuilder";

const SOURCE: ChartSpec["source"] = { kind: "data_table", table_id: "w1" };
const SOURCES: SourceChoice[] = [{ id: "table", label: "This Data Table", source: SOURCE }];
const PROFILE: ChartProfile = {
  rows: 4,
  columns: [
    { index: 0, name: "region", kind: "text", nulls: 0, distinct: 3, looks_like: "category" },
    { index: 1, name: "sales", kind: "number", nulls: 0, distinct: 4, looks_like: "measure", default_aggregate: "sum" },
    { index: 2, name: "age", kind: "number", nulls: 0, distinct: 4, looks_like: "measure", default_aggregate: "avg" },
  ],
  suggestions: [
    { type: "bar", reason: "category_and_number", series: [
      { name: "sales", value_col: 1, category_col: 0, aggregate: "sum" }, { name: "age", value_col: 2, category_col: 0, aggregate: "avg" }] },
    { type: "scatter", reason: "two_numbers", series: [{ name: "age", value_col: 2, category_col: 1 }] },
  ],
};
const DATA: ChartData = { categories: ["north", "south"], series: [{ name: "sales", values: [3, 4] }], categories_kind: "category", notes: [] };
const wrap = (ui: React.ReactNode) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
beforeEach(() => usePrefs.setState({ digits: "latin", locale: "en" }));

function routes(extra: Record<string, () => ReturnType<typeof ok>> = {}) {
  return mockApi({
    "POST /documents/w1/charts/profile": () => ok(PROFILE),
    "POST /documents/w1/charts/preview": () => ok(DATA),
    ...extra,
  });
}
const previews = (api: ReturnType<typeof mockApi>) => api.calls.filter((c) => c.path === "/documents/w1/charts/preview");
const lastPreview = (api: ReturnType<typeof mockApi>) => previews(api).at(-1)?.body as ChartSpec;

describe("ChartBuilder", () => {
  it("starts from the best suggestion: a chart is on screen without choosing anything", async () => {
    const api = routes();
    wrap(<ChartBuilder documentId="w1" sources={SOURCES} onSaved={() => {}} onCancel={() => {}} />);
    expect(await screen.findByRole("img", { name: "bar" })).toBeInTheDocument();
    expect(lastPreview(api).series).toEqual([
      { name: "sales", value_col: 1, category_col: 0, aggregate: "sum" }, { name: "age", value_col: 2, category_col: 0, aggregate: "avg" },
    ]);
    expect(screen.getByRole("radio", { name: /★ Bars/ })).toBeChecked();
  });

  it("each chosen column gets its own way of combining rows, with the sensible default", async () => {
    const api = routes();
    wrap(<ChartBuilder documentId="w1" sources={SOURCES} onSaved={() => {}} onCancel={() => {}} />);
    await screen.findByRole("img", { name: "bar" });
    const sales = screen.getByRole("combobox", { name: "sales" });
    expect(sales).toHaveValue("sum");
    expect(screen.getByRole("combobox", { name: "age" })).toHaveValue("avg");
    await userEvent.selectOptions(sales, "max");
    await waitFor(() => expect(lastPreview(api).series.map((x) => x.aggregate)).toEqual(["max", "avg"]));
  });

  it("lists recommended types first but keeps every type reachable", async () => {
    routes();
    wrap(<ChartBuilder documentId="w1" sources={SOURCES} onSaved={() => {}} onCancel={() => {}} />);
    await screen.findByRole("img", { name: "bar" });
    expect(screen.getByRole("radio", { name: /★ Scatter/ })).toBeInTheDocument();
    for (const name of ["Line", "Area", "Pie"]) expect(screen.getAllByRole("radio", { name: new RegExp(`^${name}$`) }).length).toBeGreaterThan(0);
  });

  it("a changed setting updates the preview", async () => {
    const api = routes();
    wrap(<ChartBuilder documentId="w1" sources={SOURCES} onSaved={() => {}} onCancel={() => {}} />);
    await screen.findByRole("img", { name: "bar" });
    await userEvent.click(screen.getByRole("checkbox", { name: /Show only some of the categories/ }));
    await waitFor(() => expect(lastPreview(api).limit).toEqual({ top_n: 10, end: "top", other: false }));
    await userEvent.selectOptions(screen.getByLabelText("Order"), "value");
    await waitFor(() => expect(lastPreview(api).sort).toEqual({ by: "value", direction: "asc" }));
  });

  it("shows only the options the chosen type can use", async () => {
    routes();
    wrap(<ChartBuilder documentId="w1" sources={SOURCES} onSaved={() => {}} onCancel={() => {}} />);
    await screen.findByRole("img", { name: "bar" });
    expect(screen.getByLabelText("Direction")).toBeInTheDocument();
    expect(screen.getByLabelText("Several values")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("radio", { name: /^Pie$/ })[0]!);
    expect(screen.queryByLabelText("Direction")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Several values")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Doughnut/ })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("radio", { name: /Scatter/ })[0]!);
    expect(screen.queryByLabelText("Combine rows with")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /Show only some of the categories/ })).not.toBeInTheDocument();
  });

  it("explains a refused chart next to the field, in plain words", async () => {
    mockApi({
      "POST /documents/w1/charts/profile": () => ok(PROFILE),
      "POST /documents/w1/charts/preview": () => err(400, "validation_failed", undefined, [
        { code: "type_mismatch", path: "/series/0/value_col", message: "series values 'region' must be numeric" }]),
    });
    wrap(<ChartBuilder documentId="w1" sources={SOURCES} onSaved={() => {}} onCancel={() => {}} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("“sales” is not a column of numbers");
    expect(alert).not.toHaveTextContent("must be numeric"); // the server's technical text is not shown
    expect(screen.getByRole("button", { name: "Save the chart" })).toBeEnabled();
  });

  it("waits for the missing choices instead of failing", async () => {
    const api = mockApi({
      "POST /documents/w1/charts/profile": () => ok({ ...PROFILE, columns: [PROFILE.columns[0]!], suggestions: [] }),
      "POST /documents/w1/charts/preview": () => ok(DATA),
    });
    wrap(<ChartBuilder documentId="w1" sources={SOURCES} onSaved={() => {}} onCancel={() => {}} />);
    expect(await screen.findByText("Choose at least one column of numbers.")).toBeInTheDocument();
    expect(screen.getByText("Choose the columns to see the chart.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save the chart" })).toBeDisabled();
    expect(previews(api)).toHaveLength(0);
  });

  it("saves a new chart with the mapping, title and settings chosen", async () => {
    const saved = vi.fn();
    const api = routes({ "POST /documents/w1/charts": () => ok({ id: "c9" }) as never });
    wrap(<ChartBuilder documentId="w1" sources={SOURCES} onSaved={saved} onCancel={() => {}} />);
    await screen.findByRole("img", { name: "bar" });
    await userEvent.type(screen.getByLabelText("Title"), "Sales by region");
    await userEvent.selectOptions(screen.getByLabelText("Direction"), "horizontal");
    await userEvent.click(screen.getByRole("button", { name: "Save the chart" }));
    await waitFor(() => expect(saved).toHaveBeenCalledWith("c9"));
    const body = api.calls.find((c) => c.method === "POST" && c.path === "/documents/w1/charts")!.body as ChartSpec;
    expect(body).toMatchObject({ type: "bar", title: "Sales by region", options: { orientation: "horizontal" }, source: SOURCE });
    expect(body.series[0]).toMatchObject({ value_col: 1, category_col: 0, aggregate: "sum" });
  });

  it("opens a saved chart for editing and saves it in place", async () => {
    const saved = vi.fn();
    const old: ChartSpec = { schema_version: 1, id: "c1", document_id: "w1", type: "line", title: "Old", source: SOURCE, options: { stacked: false, legend: true },
      series: [{ value_col: "sales", category_col: "region" }] };
    const api = routes({ "PUT /charts/c1": () => ok({ ...old, title: "New" }) as never });
    wrap(<ChartBuilder documentId="w1" sources={SOURCES} initial={old} onSaved={saved} onCancel={() => {}} />);
    await screen.findByRole("img", { name: "Old" });
    expect(screen.getByRole("radio", { name: /^Line$/ })).toBeChecked();
    const title = screen.getByLabelText("Title");
    await userEvent.clear(title);
    await userEvent.type(title, "New");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(saved).toHaveBeenCalledWith("c1"));
    const put = api.calls.find((c) => c.method === "PUT")!.body as ChartSpec;
    expect(put).toMatchObject({ id: "c1", title: "New", type: "line", source: SOURCE });
    expect(api.calls.some((c) => c.method === "POST" && c.path === "/documents/w1/charts")).toBe(false);
  });

  it("a refused save is explained at the field and nothing is lost", async () => {
    routes({ "POST /documents/w1/charts": () => err(400, "validation_failed", undefined, [
      { code: "invalid_param", path: "/limit/other", message: "x" }]) as never });
    wrap(<ChartBuilder documentId="w1" sources={SOURCES} onSaved={() => {}} onCancel={() => {}} />);
    await screen.findByRole("img", { name: "bar" });
    await userEvent.click(screen.getByRole("button", { name: "Save the chart" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("“Other” only works with Sum or Count of rows");
    expect(screen.getByRole("button", { name: "Save the chart" })).toBeEnabled();
  });

  it("says so when the columns cannot be read", async () => {
    mockApi({ "POST /documents/w1/charts/profile": () => err(500, "internal_error") });
    wrap(<ChartBuilder documentId="w1" sources={SOURCES} onSaved={() => {}} onCancel={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The columns could not be read.");
  });

  it("offers the choice of source when there is more than one (selection or whole sheet)", async () => {
    const two: SourceChoice[] = [
      { id: "selection", label: "Selected cells A1:C4", source: { kind: "sheet_range", range: { sheet_id: "s", r0: 0, c0: 0, r1: 3, c1: 2 } } },
      { id: "sheet", label: "The whole sheet", source: { kind: "sheet_range", range: { sheet_id: "s", r0: 0, c0: 0, r1: 99, c1: 4 } } },
    ];
    const api = mockApi({
      "POST /documents/w1/charts/profile": () => ok(PROFILE),
      "POST /documents/w1/charts/preview": () => ok(DATA),
    });
    wrap(<ChartBuilder documentId="w1" sources={two} onSaved={() => {}} onCancel={() => {}} />);
    await screen.findByRole("img", { name: "bar" });
    const group = screen.getByRole("radio", { name: /Selected cells A1:C4/ });
    expect(group).toBeChecked(); // the selection is used first
    await userEvent.click(screen.getByRole("radio", { name: /The whole sheet/ }));
    await waitFor(() => expect(api.calls.filter((c) => c.path.endsWith("/profile")).at(-1)?.body).toEqual({ source: two[1]!.source }));
    expect(within(document.body).getByRole("radio", { name: /The whole sheet/ })).toBeChecked();
  });
});
