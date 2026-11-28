// The Chart Builder's logic without any UI: what a chart type needs, how a draft becomes a ChartSpec (and back),
// defaults from the column profile, and how a server error is pointed at the field it is about.
// Rules about data (what is a valid chart) stay on the server; this file only shapes what the person sees.
import {
  SCHEMA_VERSION, type ChartAggregate, type ChartColumnProfile, type ChartFilter, type ChartSpec, type ChartSuggestion,
  type Target,
} from "@contracts";
import type { ErrorDetail } from "@contracts";
import { ApiError } from "@/api/client";
import type { MessageKey } from "@/i18n";

export type Kind = ChartSpec["type"];
export const GROUPS = ["comparison", "trend", "distribution", "relationship", "composition", "specialized"] as const;
export type Group = (typeof GROUPS)[number];
export const KINDS: { type: Kind; group: Group }[] = [
  { type: "bar", group: "comparison" },
  { type: "line", group: "trend" },
  { type: "area", group: "trend" },
  { type: "scatter", group: "relationship" },
  { type: "pie", group: "composition" },
];

export type AggregateChoice = ChartAggregate | "none";
export const AGGREGATES: AggregateChoice[] = ["sum", "avg", "count", "min", "max", "median", "count_distinct", "none"];

export interface DraftFilter { column: number | null; op: ChartFilter["op"]; value: string }
export const FILTER_OPS: ChartFilter["op"][] = ["eq", "ne", "gt", "ge", "lt", "le", "contains", "is_empty", "is_not_empty"];

export interface Draft {
  type: Kind; title: string;
  category: number | null; values: number[]; splitBy: number | null;
  aggregate: AggregateChoice; // for any value column without its own entry in `aggregates`
  aggregates: Record<number, AggregateChoice>; // per value column: sales are summed, ages averaged
  sortBy: "source" | "category" | "value"; sortDir: "asc" | "desc";
  topN: number | null; topEnd: "top" | "bottom"; other: boolean;
  granularity: "day" | "month" | "quarter" | "year" | null; calendar: "gregorian" | "jalali";
  stack: "none" | "stacked" | "percent"; orientation: "vertical" | "horizontal";
  labels: "none" | "value" | "percent"; nulls: "gap" | "zero"; donut: boolean; legend: boolean;
  axisX: string; axisY: string; filters: DraftFilter[];
}

/** Which controls a chart type has. The builder shows only these; everything else would be noise. */
export interface Capabilities {
  multiValues: boolean; splitBy: boolean; aggregate: boolean; sort: boolean; limit: boolean; time: boolean;
  stack: boolean; orientation: boolean; labels: boolean; donut: boolean; nulls: boolean; axisTitles: boolean;
  categoryRole: "category" | "x";
}

export function capabilities(type: Kind): Capabilities {
  const none: Capabilities = {
    multiValues: false, splitBy: false, aggregate: false, sort: false, limit: false, time: false, stack: false,
    orientation: false, labels: false, donut: false, nulls: false, axisTitles: false, categoryRole: "category",
  };
  switch (type) {
    case "bar":
      return { ...none, multiValues: true, splitBy: true, aggregate: true, sort: true, limit: true, time: true, stack: true,
        orientation: true, labels: true, nulls: true, axisTitles: true };
    case "line":
      return { ...none, multiValues: true, splitBy: true, aggregate: true, sort: true, limit: true, time: true, nulls: true, axisTitles: true };
    case "area":
      return { ...none, multiValues: true, splitBy: true, aggregate: true, sort: true, limit: true, time: true, stack: true, nulls: true, axisTitles: true };
    case "pie":
      return { ...none, aggregate: true, sort: true, limit: true, labels: true, donut: true };
    case "scatter":
      return { ...none, multiValues: true, splitBy: true, axisTitles: true, categoryRole: "x" };
  }
}

const isMeasure = (c: ChartColumnProfile) => c.looks_like === "measure";

function pickValues(type: Kind, cols: ChartColumnProfile[], category: number | null): number[] {
  const rest = cols.filter((c) => c.index !== category && c.kind !== "empty");
  const measures = rest.filter(isMeasure);
  const numeric = rest.filter((c) => c.kind === "number");
  const chosen = (measures.length ? measures : numeric).map((c) => c.index);
  return type === "pie" || type === "scatter" ? chosen.slice(0, 1) : chosen.slice(0, 3);
}

/** A first draft for a chart type from the column facts: obvious roles filled, all of them changeable. */
export function newDraft(type: Kind, cols: ChartColumnProfile[]): Draft {
  const scatter = type === "scatter";
  const time = cols.find((c) => c.looks_like === "time");
  const cat = cols.find((c) => c.looks_like === "category");
  const measures = cols.filter(isMeasure);
  const category: number | null = scatter ? (measures[0]?.index ?? cols.find((c) => c.kind === "number")?.index ?? null)
    : type === "pie" ? (cat?.index ?? null)
    : (time ?? cat)?.index ?? null;
  const values = pickValues(type, cols, category);
  const first = cols.find((c) => c.index === values[0]);
  const aggOf = (i: number): AggregateChoice => (scatter ? "none" : (cols.find((c) => c.index === i)?.default_aggregate ?? "sum"));
  const timeCol = cols.find((c) => c.index === category && c.looks_like === "time");
  return {
    type, title: "", category, values, splitBy: null,
    aggregate: scatter ? "none" : (first?.default_aggregate ?? "sum"),
    aggregates: Object.fromEntries(values.map((v) => [v, aggOf(v)])),
    sortBy: "source", sortDir: "asc", topN: null, topEnd: "top", other: false,
    granularity: timeCol && timeCol.distinct > 60 ? "month" : null,
    calendar: timeCol?.date_text === "jalali" ? "jalali" : "gregorian",
    stack: "none", orientation: "vertical", labels: "none", nulls: "gap", donut: false, legend: true,
    axisX: "", axisY: "", filters: [],
  };
}

export function draftFromSuggestion(s: ChartSuggestion, cols: ChartColumnProfile[]): Draft {
  const d = newDraft(s.type, cols);
  const first = s.series[0];
  if (first) {
    d.category = typeof first.category_col === "number" ? first.category_col : d.category;
    d.values = s.series.map((x) => x.value_col).filter((v): v is number => typeof v === "number");
    d.aggregate = first.aggregate ?? (s.type === "scatter" ? "none" : d.aggregate);
    d.aggregates = Object.fromEntries(s.series.flatMap((x) => (typeof x.value_col === "number" ? [[x.value_col, x.aggregate ?? "none"]] : [])));
  }
  if (s.time) { d.calendar = s.time.calendar; d.granularity = s.time.granularity ?? null; }
  if (s.limit) { d.topN = s.limit.top_n; d.topEnd = s.limit.end; d.other = s.limit.other; }
  return d;
}

/** Switch the chart type. Chosen columns and the title stay when they still make sense for the new type; a
 * suggestion for that type (if the profile has one) is the better starting point when the roles change. */
export function switchType(d: Draft, type: Kind, cols: ChartColumnProfile[], suggestions: ChartSuggestion[]): Draft {
  if (type === d.type) return d;
  const fresh = (() => {
    const s = suggestions.find((x) => x.type === type);
    return s ? draftFromSuggestion(s, cols) : newDraft(type, cols);
  })();
  const roleChange = (type === "scatter") !== (d.type === "scatter");
  const keep: Partial<Draft> = { title: d.title, filters: d.filters, legend: d.legend };
  if (!roleChange) {
    const cap = capabilities(type);
    const values = cap.multiValues ? d.values : d.values.slice(0, 1);
    Object.assign(keep, { category: d.category, values, aggregate: d.aggregate, aggregates: d.aggregates, splitBy: cap.splitBy && values.length === 1 ? d.splitBy : null });
  }
  return { ...fresh, ...keep };
}

export interface Ctx { documentId: string; source: Target; columns: ChartColumnProfile[] }

const nameOf = (cols: ChartColumnProfile[], i: number): string => cols.find((c) => c.index === i)?.name ?? `#${i + 1}`;

/** The ChartSpec the server understands. Only settings that belong to the chart type are written. */
export function draftToSpec(d: Draft, ctx: Ctx, id?: string): ChartSpec {
  const cap = capabilities(d.type);
  const values = cap.multiValues ? d.values : d.values.slice(0, 1);
  const series = values.map((v) => {
    const choice = d.aggregates[v] ?? d.aggregate;
    return {
      name: nameOf(ctx.columns, v), value_col: v,
      ...(d.category !== null ? { category_col: d.category } : {}),
      ...(cap.aggregate && choice !== "none" ? { aggregate: choice } : {}),
    };
  });
  const spec: ChartSpec = {
    schema_version: SCHEMA_VERSION, document_id: ctx.documentId, type: d.type, title: d.title.trim() || undefined,
    source: ctx.source, series,
    options: {
      stacked: cap.stack && d.stack !== "none", legend: d.legend,
      ...(cap.stack ? { stack: d.stack } : {}), ...(cap.orientation ? { orientation: d.orientation } : {}),
      ...(cap.labels ? { labels: d.labels } : {}), ...(cap.nulls ? { nulls: d.nulls } : {}),
      ...(cap.donut && d.donut ? { donut: true } : {}),
      ...(cap.axisTitles && (d.axisX || d.axisY) ? { axis_titles: { ...(d.axisX ? { x: d.axisX } : {}), ...(d.axisY ? { y: d.axisY } : {}) } } : {}),
    },
  };
  if (id) spec.id = id;
  if (cap.splitBy && d.splitBy !== null && values.length === 1) spec.series_by = d.splitBy;
  if (cap.sort && d.sortBy !== "source") spec.sort = { by: d.sortBy, direction: d.sortDir };
  if (cap.limit && d.topN) spec.limit = { top_n: d.topN, end: d.topEnd, other: d.other };
  if (cap.time && isTime(d, ctx.columns)) spec.time = { calendar: d.calendar, granularity: d.granularity };
  const filters = d.filters.flatMap((f): ChartFilter[] => {
    if (f.column === null) return [];
    if (f.op === "is_empty" || f.op === "is_not_empty") return [{ column: f.column, op: f.op }];
    if (f.value.trim() === "") return [];
    const num = Number(f.value);
    const numeric = ctx.columns.find((c) => c.index === f.column)?.kind === "number" && Number.isFinite(num);
    return [{ column: f.column, op: f.op, value: numeric ? num : f.value }];
  });
  if (filters.length) spec.filters = filters;
  return spec;
}

/** Is the chosen category column a date axis (a date column, or text that reads as dates)? */
export function isTime(d: Draft, cols: ChartColumnProfile[]): boolean {
  const c = cols.find((x) => x.index === d.category);
  return Boolean(c && (c.kind === "date" || c.date_text));
}

const colIndex = (cols: ChartColumnProfile[], ref: string | number | null | undefined): number | null => {
  if (ref === null || ref === undefined) return null;
  if (typeof ref === "number") return cols.some((c) => c.index === ref) ? ref : null;
  return cols.find((c) => c.name === ref)?.index ?? null;
};

/** A saved chart as a draft, so it can be edited. Specs saved before 0.7 (names, no new fields) load too. */
export function specToDraft(spec: ChartSpec, cols: ChartColumnProfile[]): Draft {
  const d = newDraft(spec.type, cols);
  const first = spec.series[0];
  d.title = spec.title ?? "";
  d.category = colIndex(cols, first?.category_col);
  d.values = spec.series.map((s) => colIndex(cols, s.value_col)).filter((v): v is number => v !== null);
  d.aggregate = first?.aggregate ?? "none";
  d.aggregates = Object.fromEntries(spec.series.flatMap((x) => {
    const i = colIndex(cols, x.value_col);
    return i === null ? [] : [[i, x.aggregate ?? "none"]];
  }));
  d.splitBy = colIndex(cols, spec.series_by);
  d.sortBy = spec.sort?.by ?? "source"; d.sortDir = spec.sort?.direction ?? "asc";
  d.topN = spec.limit?.top_n ?? null; d.topEnd = spec.limit?.end ?? "top"; d.other = spec.limit?.other ?? false;
  d.granularity = spec.time?.granularity ?? null; d.calendar = spec.time?.calendar ?? d.calendar;
  const o = spec.options;
  d.stack = o.stack ?? (o.stacked ? "stacked" : "none"); d.orientation = o.orientation ?? "vertical";
  d.labels = o.labels ?? "none"; d.nulls = o.nulls ?? "gap"; d.donut = o.donut ?? false; d.legend = o.legend;
  d.axisX = o.axis_titles?.x ?? ""; d.axisY = o.axis_titles?.y ?? "";
  d.filters = (spec.filters ?? []).map((f) => ({
    column: colIndex(cols, f.column), op: f.op, value: f.value === null || f.value === undefined ? "" : String(f.value),
  }));
  return d;
}

/** What is still missing before the chart can be drawn (shown quietly; the preview waits). */
export type Missing = "category" | "values";
export function missing(d: Draft): Missing[] {
  const out: Missing[] = [];
  if (d.category === null) out.push("category");
  if (d.values.filter((v) => v !== d.category).length === 0) out.push("values");
  return out;
}

// ------------------------------------------------------------------------------------------- server problems
export type Field = "source" | "category" | "values" | "splitBy" | "aggregate" | "limit" | "time" | "filters" | "other";
export interface Problem { field: Field; key?: MessageKey; params?: Record<string, string>; message?: string; hint?: string }

function fieldOf(path: string | null | undefined): Field {
  if (!path) return "other";
  if (path.startsWith("/series_by")) return "splitBy";
  if (path.startsWith("/limit")) return "limit";
  if (path.startsWith("/filters")) return "filters";
  if (path.startsWith("/time")) return "time";
  if (path.startsWith("/source")) return "source";
  const m = /^\/series\/\d+\/(\w+)/.exec(path);
  if (m?.[1] === "value_col") return "values";
  if (m?.[1] === "category_col") return "category";
  if (m?.[1] === "aggregate") return "aggregate";
  return "other";
}

/** The server's reason for refusing a chart, as a message about one field. Unknown reasons keep the server's text. */
export function problemOf(e: unknown, d: Draft, cols: ChartColumnProfile[]): Problem | null {
  if (!(e instanceof ApiError)) return null;
  const detail: ErrorDetail | undefined = e.details.find((x) => x.path) ?? e.details[0];
  if (!detail) return null;
  const field = fieldOf(detail.path);
  const p: Problem = { field, hint: detail.hint ?? undefined };
  const idx = /^\/series\/(\d+)/.exec(detail.path ?? "")?.[1];
  const col = idx !== undefined ? nameOf(cols, d.values[Number(idx)] ?? -1) : "";
  const code = detail.code;
  if (code === "type_mismatch" && field === "values") return { ...p, key: "charts.problem.valueNotNumber", params: { column: col } };
  if (code === "type_mismatch" && field === "category") return { ...p, key: "charts.problem.xNotNumber" };
  if (code === "chart_too_many_categories") return { ...p, key: "charts.problem.tooManyCategories" };
  if (code === "chart_too_many_series") return { ...p, key: "charts.problem.tooManySeries" };
  if (code === "chart_series_mismatch") return { ...p, key: "charts.problem.seriesMismatch" };
  if (code === "unknown_column") return { ...p, key: "charts.problem.unknownColumn" };
  if (code === "invalid_param") {
    if (detail.path === "/limit/other") return { ...p, key: "charts.problem.otherNeedsSum" };
    if (field === "limit") return { ...p, key: "charts.problem.topNTime" };
    if (field === "aggregate") return { ...p, key: "charts.problem.scatterAggregate" };
    if (field === "values") return { ...p, key: "charts.problem.pieNeedsPositive" };
    if (field === "splitBy") return { ...p, key: "charts.problem.splitByNeeds" };
    if (field === "category") return { ...p, key: "charts.problem.needsCategory" };
  }
  return { ...p, message: detail.message };
}
