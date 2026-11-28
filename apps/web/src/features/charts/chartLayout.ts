// The arithmetic of drawing a chart (no DOM): stacking, axis ranges, tick marks, label picking, pie slices.
// Pure functions so they can be tested without a browser. ChartView only turns their results into SVG.
import type { ChartSpec } from "@contracts";

export type StackMode = "none" | "stacked" | "percent";
export type Values = (number | null)[];

/** Stacking only makes sense for bars and areas; `stack` wins over the old `stacked` flag. */
export function stackMode(spec: ChartSpec): StackMode {
  if (spec.type !== "bar" && spec.type !== "area") return "none";
  return spec.options.stack ?? (spec.options.stacked ? "stacked" : "none");
}

/** One drawn value: `v` is the real number, [lo, hi] is the interval it covers on the value axis. */
export interface Seg { v: number; lo: number; hi: number }

/**
 * Intervals for every series and category. Empty values stay empty (no segment), they are never turned into 0.
 * Stacked: positives pile up above zero and negatives below it, so mixed signs never overlap.
 * Percent: each category is scaled so its absolute values add up to 100.
 */
export function buildSegments(values: Values[], mode: StackMode): (Seg | null)[][] {
  const n = Math.max(0, ...values.map((s) => s.length));
  const out: (Seg | null)[][] = values.map(() => Array.from({ length: n }, () => null));
  for (let i = 0; i < n; i++) {
    let pos = 0;
    let neg = 0;
    const denom = mode === "percent" ? values.reduce((a, s) => a + Math.abs(s[i] ?? 0), 0) : 1;
    values.forEach((s, k) => {
      const v = s[i];
      if (v === null || v === undefined) return;
      if (mode === "none") {
        out[k]![i] = { v, lo: Math.min(0, v), hi: Math.max(0, v) };
        return;
      }
      const d = mode === "percent" ? (denom ? (v / denom) * 100 : 0) : v;
      if (d >= 0) { out[k]![i] = { v, lo: pos, hi: pos + d }; pos += d; }
      else { out[k]![i] = { v, lo: neg + d, hi: neg }; neg += d; }
    });
  }
  return out;
}

export interface Ticks { ticks: number[]; lo: number; hi: number }

const clean = (v: number): number => Number(v.toPrecision(12));

/** Round tick marks (1, 2, 5 x 10^k) that cover [lo, hi]; the returned range is widened to the first/last tick. */
export function niceTicks(lo: number, hi: number, count = 5): Ticks {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { ticks: [0, 1], lo: 0, hi: 1 };
  if (lo > hi) [lo, hi] = [hi, lo];
  if (lo === hi) {
    const pad = lo === 0 ? 1 : Math.abs(lo) * 0.1;
    lo -= pad;
    hi += pad;
  }
  const rough = (hi - lo) / Math.max(1, count - 1);
  const mag = 10 ** Math.floor(Math.log10(rough));
  const f = rough / mag;
  const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag;
  const first = Math.floor(lo / step + 1e-9) * step;
  const last = Math.ceil(hi / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let v = first; v <= last + step / 2; v += step) ticks.push(clean(v));
  return { ticks, lo: ticks[0]!, hi: ticks[ticks.length - 1]! };
}

/** Value-axis range of the drawn segments. Bars and areas always include zero; lines and points need not. */
export function valueRange(segs: (Seg | null)[][], mode: StackMode, includeZero: boolean): { lo: number; hi: number } {
  let lo = Infinity;
  let hi = -Infinity;
  for (const row of segs) for (const s of row) if (s) { lo = Math.min(lo, s.lo, s.hi); hi = Math.max(hi, s.lo, s.hi); }
  if (!Number.isFinite(lo)) return { lo: 0, hi: 1 };
  if (includeZero || mode !== "none") { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (mode === "percent") { lo = Math.min(lo, 0); hi = Math.max(hi, 100); }
  return { lo, hi };
}

/** Indexes of the category labels to show so they do not overlap (always the first one, evenly spaced). */
export function pickLabelIndexes(count: number, max: number): number[] {
  if (count <= 0) return [];
  const step = Math.max(1, Math.ceil(count / Math.max(1, max)));
  const out: number[] = [];
  for (let i = 0; i < count; i += step) out.push(i);
  return out;
}

export function shorten(text: string, max: number): string {
  const chars = [...text];
  return chars.length <= max ? text : `${chars.slice(0, Math.max(1, max - 1)).join("")}…`;
}

/** Compact axis number: 1500 -> 1.5k, 2,300,000 -> 2.3M; small numbers keep two decimals at most. */
export function compact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e9) return `${clean(v / 1e9)}B`;
  if (a >= 1e6) return `${clean(Math.round(v / 1e5) / 10)}M`;
  if (a >= 1e3) return `${clean(Math.round(v / 100) / 10)}k`;
  return String(clean(Math.round(v * 100) / 100));
}

export interface Slice { index: number; value: number; fraction: number; start: number; end: number }

/** Pie slices from the server's values; only positive values get a slice (the server already reports the rest). */
export function pieSlices(values: Values): Slice[] {
  const parts = values.map((v, index) => ({ index, value: v ?? 0 })).filter((p) => p.value > 0);
  const total = parts.reduce((a, p) => a + p.value, 0);
  let angle = -Math.PI / 2;
  return parts.map((p) => {
    const fraction = total ? p.value / total : 0;
    const start = angle;
    angle += fraction * Math.PI * 2;
    return { ...p, fraction, start, end: angle };
  });
}

/** SVG path pieces for a line: a gap (empty value) ends the current piece, so the line is never drawn through it. */
export function linePieces<P extends { x: number; y: number }>(points: (P | null)[]): P[][] {
  const pieces: P[][] = [];
  let cur: P[] = [];
  for (const p of points) {
    if (p) cur.push(p);
    else if (cur.length) { pieces.push(cur); cur = []; }
  }
  if (cur.length) pieces.push(cur);
  return pieces;
}

/** Show Latin digits in the person's chosen digit script (display only; wire values stay Latin). */
export function localizeDigits(text: string, digits: "latin" | "persian" | "arabic"): string {
  if (digits === "latin") return text;
  const set = digits === "persian" ? "۰۱۲۳۴۵۶۷۸۹" : "٠١٢٣٤٥٦٧٨٩";
  return text.replace(/\d/g, (d) => set[Number(d)]!);
}

// ---- the extra payload (ChartData.meta) of the distribution charts; the server writes it, the view reads it here
export interface HistogramMeta { kind: "histogram"; edges: number[]; counts: number[]; total: number; percent: boolean }
export interface Box {
  category: string; n: number; min: number; q1: number; median: number; q3: number; max: number;
  whisker_low: number; whisker_high: number; outliers: number[]; outlier_count: number;
}
export interface BoxMeta { kind: "boxplot"; boxes: Box[] }

const isNumbers = (v: unknown): v is number[] => Array.isArray(v) && v.every((x) => typeof x === "number");

export function asHistogram(meta: Record<string, unknown> | null | undefined): HistogramMeta | null {
  if (!meta || meta.kind !== "histogram" || !isNumbers(meta.edges) || !isNumbers(meta.counts)) return null;
  if (meta.edges.length !== meta.counts.length + 1) return null;
  return { kind: "histogram", edges: meta.edges, counts: meta.counts, total: Number(meta.total ?? 0), percent: meta.percent === true };
}

export function asBoxes(meta: Record<string, unknown> | null | undefined): BoxMeta | null {
  if (!meta || meta.kind !== "boxplot" || !Array.isArray(meta.boxes)) return null;
  const ok = (meta.boxes as Record<string, unknown>[]).every((b) =>
    typeof b.category === "string" && ["n", "min", "q1", "median", "q3", "max", "whisker_low", "whisker_high"].every((k) => typeof b[k] === "number")
    && isNumbers(b.outliers));
  return ok ? { kind: "boxplot", boxes: meta.boxes as Box[] } : null;
}

/** Tick marks that fall inside [lo, hi] (a histogram axis keeps its exact ends). */
export function ticksWithin(lo: number, hi: number, count = 5): number[] {
  return niceTicks(lo, hi, count).ticks.filter((v) => v >= lo - 1e-12 && v <= hi + 1e-12);
}
