import type { ChartColumnProfile, ChartSpec, ChartSuggestion } from "@contracts";
import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/client";
import {
  KINDS, capabilities, draftFromSuggestion, draftToSpec, isTime, missing, newDraft, problemOf, specToDraft, switchType, type Ctx,
} from "./builderModel";

const col = (index: number, name: string, extra: Partial<ChartColumnProfile> = {}): ChartColumnProfile =>
  ({ index, name, kind: "number", nulls: 0, distinct: 5, ...extra });
const COLS: ChartColumnProfile[] = [
  col(0, "region", { kind: "text", looks_like: "category" }),
  col(1, "sales", { looks_like: "measure", default_aggregate: "sum" }),
  col(2, "age", { looks_like: "measure", default_aggregate: "avg" }),
  col(3, "id", { looks_like: "identifier", default_aggregate: "count" }),
];
const CTX: Ctx = { documentId: "w", source: { kind: "data_table", table_id: "t" }, columns: COLS };
const DATE_COLS: ChartColumnProfile[] = [
  col(0, "when", { kind: "text", date_text: "jalali", looks_like: "time", distinct: 90 }), col(1, "v", { looks_like: "measure" }),
];

describe("capabilities", () => {
  it("shows each chart type only the controls that mean something for it", () => {
    expect(capabilities("scatter")).toMatchObject({ aggregate: false, sort: false, limit: false, stack: false, splitBy: true, categoryRole: "x" });
    expect(capabilities("pie")).toMatchObject({ multiValues: false, donut: true, stack: false, orientation: false, time: false });
    expect(capabilities("bar")).toMatchObject({ stack: true, orientation: true, labels: true });
    expect(capabilities("line")).toMatchObject({ stack: false, orientation: false });
    expect(capabilities("area").stack).toBe(true);
  });
  it("every kind in the gallery is known", () => {
    for (const k of KINDS) expect(capabilities(k.type)).toBeDefined();
  });
});

describe("newDraft", () => {
  it("fills obvious roles from the profile and leaves identifiers out of the values", () => {
    const d = newDraft("bar", COLS);
    expect([d.category, d.values, d.aggregate]).toEqual([0, [1, 2], "sum"]);
    expect(d.aggregates).toEqual({ 1: "sum", 2: "avg" });
  });
  it("uses the average for a column that is usually averaged, as a hint", () => {
    expect(newDraft("bar", [COLS[0]!, COLS[2]!]).aggregate).toBe("avg");
  });
  it("pie takes one value, scatter takes numbers on both axes and never combines rows", () => {
    expect(newDraft("pie", COLS).values).toEqual([1]);
    const s = newDraft("scatter", COLS);
    expect([s.category, s.values, s.aggregate]).toEqual([1, [2], "none"]);
  });
  it("a date column becomes the axis, with its calendar and a monthly step when there are many dates", () => {
    const d = newDraft("line", DATE_COLS);
    expect([d.category, d.calendar, d.granularity]).toEqual([0, "jalali", "month"]);
    expect(isTime(d, DATE_COLS)).toBe(true);
  });
  it("copes with nothing to go on", () => {
    const d = newDraft("bar", []);
    expect(d.category).toBeNull();
    expect(missing(d)).toEqual(["category", "values"]);
  });
});

describe("draftToSpec", () => {
  it("makes a plain, complete spec for the common case", () => {
    const spec = draftToSpec(newDraft("bar", COLS), CTX);
    expect(spec.series).toEqual([
      { name: "sales", value_col: 1, category_col: 0, aggregate: "sum" },
      { name: "age", value_col: 2, category_col: 0, aggregate: "avg" }, // each column keeps its own default
    ]);
    expect(spec.sort).toBeUndefined();
    expect(spec.limit).toBeUndefined();
    expect(spec.filters).toBeUndefined();
    expect(spec.time).toBeUndefined();
  });
  it("writes only settings that belong to the chart type", () => {
    const d = { ...newDraft("line", COLS), stack: "stacked" as const, orientation: "horizontal" as const, labels: "value" as const, donut: true };
    expect(draftToSpec(d, CTX).options).toEqual({ stacked: false, legend: true, nulls: "gap" });
    const pie = { ...newDraft("pie", COLS), donut: true, labels: "percent" as const, nulls: "zero" as const };
    expect(draftToSpec(pie, CTX).options).toEqual({ stacked: false, legend: true, labels: "percent", donut: true });
  });
  it("scatter has no aggregate and can colour by a column when one y is chosen", () => {
    const d = { ...newDraft("scatter", COLS), splitBy: 0 };
    const spec = draftToSpec(d, CTX);
    expect(spec.series).toEqual([{ name: "age", value_col: 2, category_col: 1 }]);
    expect(spec.series_by).toBe(0);
    expect(draftToSpec({ ...d, values: [1, 2], category: 3 }, CTX).series_by).toBeUndefined();
  });
  it("sort, Top N, stack, orientation and titles are written when chosen", () => {
    const d = {
      ...newDraft("bar", COLS), sortBy: "value" as const, sortDir: "desc" as const, topN: 5, other: true,
      stack: "percent" as const, orientation: "horizontal" as const, axisX: "Region", title: " Sales ",
    };
    const spec = draftToSpec(d, CTX, "c1");
    expect(spec).toMatchObject({ id: "c1", title: "Sales", sort: { by: "value", direction: "desc" }, limit: { top_n: 5, end: "top", other: true } });
    expect(spec.options).toMatchObject({ stacked: true, stack: "percent", orientation: "horizontal", axis_titles: { x: "Region" } });
  });
  it("time settings are written only for a date axis", () => {
    expect(draftToSpec(newDraft("line", DATE_COLS), { ...CTX, columns: DATE_COLS }).time).toEqual({ calendar: "jalali", granularity: "month" });
    expect(draftToSpec(newDraft("bar", COLS), CTX).time).toBeUndefined();
  });
  it("filters: numbers stay numbers, incomplete rows are dropped, empty tests need no value", () => {
    const d = { ...newDraft("bar", COLS), filters: [
      { column: 1, op: "gt" as const, value: "100" }, { column: 0, op: "eq" as const, value: "north" },
      { column: 0, op: "eq" as const, value: "  " }, { column: null, op: "eq" as const, value: "x" },
      { column: 2, op: "is_empty" as const, value: "" },
    ] };
    expect(draftToSpec(d, CTX).filters).toEqual([
      { column: 1, op: "gt", value: 100 }, { column: 0, op: "eq", value: "north" }, { column: 2, op: "is_empty" },
    ]);
  });
});

describe("specToDraft", () => {
  it("round-trips what the builder writes", () => {
    const d = { ...newDraft("bar", COLS), sortBy: "category" as const, topN: 3, stack: "stacked" as const, title: "T", filters: [{ column: 1, op: "ge" as const, value: "5" }] };
    const back = specToDraft(draftToSpec(d, CTX, "x"), COLS);
    expect(back).toMatchObject({ type: "bar", title: "T", category: 0, values: [1, 2], aggregate: "sum", sortBy: "category", topN: 3, stack: "stacked" });
    expect(back.aggregates).toEqual({ 1: "sum", 2: "avg" });
    expect(back.filters).toEqual([{ column: 1, op: "ge", value: "5" }]);
  });
  it("opens charts saved before 0.7 (column names, no new fields, no aggregate)", () => {
    const old: ChartSpec = {
      schema_version: 1, document_id: "w", type: "line", source: CTX.source, options: { stacked: true, legend: false },
      series: [{ value_col: "sales", category_col: "region" }],
    };
    const d = specToDraft(old, COLS);
    expect([d.category, d.values, d.aggregate, d.stack, d.legend]).toEqual([0, [1], "none", "stacked", false]);
  });
  it("a column that is gone becomes empty instead of a wrong one", () => {
    const old: ChartSpec = { schema_version: 1, document_id: "w", type: "bar", source: CTX.source, options: { stacked: false, legend: true },
      series: [{ value_col: "deleted", category_col: 99 }] };
    const d = specToDraft(old, COLS);
    expect(d.category).toBeNull();
    expect(d.values).toEqual([]);
  });
});

describe("draftFromSuggestion", () => {
  it("takes the whole mapping of a suggestion", () => {
    const s: ChartSuggestion = { type: "line", reason: "time_and_number", series: [{ name: "v", value_col: 1, category_col: 0, aggregate: "avg" }],
      time: { calendar: "jalali", granularity: "month" } };
    const d = draftFromSuggestion(s, DATE_COLS);
    expect([d.type, d.category, d.values, d.aggregate, d.calendar, d.granularity]).toEqual(["line", 0, [1], "avg", "jalali", "month"]);
    expect(d.aggregates).toEqual({ 1: "avg" });
  });
  it("carries a Top N suggested for many categories", () => {
    const s: ChartSuggestion = { type: "bar", reason: "category_and_number", series: [{ value_col: 1, category_col: 0, aggregate: "sum" }], limit: { top_n: 15, end: "top", other: false } };
    expect(draftFromSuggestion(s, COLS).topN).toBe(15);
  });
});

describe("problemOf", () => {
  const err = (code: string, path: string, message = "x", hint?: string) =>
    new ApiError({ code: "validation_failed", message, status: 400, details: [{ code, path, message, hint }] });
  const d = newDraft("bar", COLS);
  it("points a type error at the values field and names the column", () => {
    expect(problemOf(err("type_mismatch", "/series/1/value_col"), d, COLS)).toMatchObject({
      field: "values", key: "charts.problem.valueNotNumber", params: { column: "age" },
    });
  });
  it("knows the chart-specific reasons", () => {
    expect(problemOf(err("invalid_param", "/limit/other"), d, COLS)).toMatchObject({ field: "limit", key: "charts.problem.otherNeedsSum" });
    expect(problemOf(err("invalid_param", "/limit"), d, COLS)).toMatchObject({ field: "limit", key: "charts.problem.topNTime" });
    expect(problemOf(err("chart_too_many_categories", "/series/0/category_col"), d, COLS)).toMatchObject({ field: "category", key: "charts.problem.tooManyCategories" });
    expect(problemOf(err("invalid_param", "/series/0/aggregate"), d, COLS)).toMatchObject({ field: "aggregate", key: "charts.problem.scatterAggregate" });
    expect(problemOf(err("invalid_param", "/series_by"), d, COLS)).toMatchObject({ field: "splitBy" });
    expect(problemOf(err("unknown_column", "/filters/0/column"), d, COLS)).toMatchObject({ field: "filters", key: "charts.problem.unknownColumn" });
  });
  it("keeps the server's text and hint for a reason it does not know", () => {
    expect(problemOf(err("something_new", "/series/0/x", "Odd thing", "do this"), d, COLS)).toMatchObject({ field: "other", message: "Odd thing", hint: "do this" });
  });
  it("is not about errors that are not the chart's (network, other types)", () => {
    expect(problemOf(new Error("boom"), d, COLS)).toBeNull();
    expect(problemOf(new ApiError({ code: "network", message: "n", status: 0 }), d, COLS)).toBeNull();
  });
});

describe("switchType", () => {
  it("keeps the title, the filters and the chosen columns when they still fit", () => {
    const d = { ...newDraft("bar", COLS), title: "T", values: [2], filters: [{ column: 1, op: "gt" as const, value: "1" }] };
    const line = switchType(d, "line", COLS, []);
    expect([line.type, line.title, line.category, line.values, line.filters.length]).toEqual(["line", "T", 0, [2], 1]);
  });
  it("drops what the new type cannot use (several values for a pie, bar-only settings)", () => {
    const d = { ...newDraft("bar", COLS), stack: "stacked" as const, values: [1, 2] };
    const pie = switchType(d, "pie", COLS, []);
    expect([pie.values, pie.stack]).toEqual([[1], "none"]);
  });
  it("moving to or from scatter starts from the suggestion or fresh defaults, not from mismatched roles", () => {
    const d = { ...newDraft("bar", COLS), title: "T" };
    const sc = switchType(d, "scatter", COLS, []);
    expect([sc.category, sc.aggregate, sc.title]).toEqual([1, "none", "T"]);
    const sug: ChartSuggestion = { type: "scatter", reason: "two_numbers", series: [{ value_col: 2, category_col: 1 }] };
    expect(switchType(d, "scatter", COLS, [sug]).values).toEqual([2]);
    expect(switchType(sc, "bar", COLS, []).aggregate).toBe("sum");
  });
  it("keeps a per-column choice of how rows are combined", () => {
    const d = { ...newDraft("bar", COLS), aggregates: { 1: "max" as const, 2: "avg" as const } };
    const area = draftToSpec(switchType(d, "area", COLS, []), CTX);
    expect(area.series.map((x) => x.aggregate)).toEqual(["max", "avg"]);
  });
  it("is a no-op for the same type", () => {
    const d = newDraft("bar", COLS);
    expect(switchType(d, "bar", COLS, [])).toBe(d);
  });
});
