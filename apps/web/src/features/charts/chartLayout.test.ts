import type { ChartSpec } from "@contracts";
import { describe, expect, it } from "vitest";
import { buildSegments, compact, linePieces, niceTicks, pickLabelIndexes, pieSlices, shorten, stackMode, valueRange } from "./chartLayout";

const spec = (type: ChartSpec["type"], options: Partial<ChartSpec["options"]> = {}): ChartSpec => ({
  schema_version: 1, document_id: "d", type, source: { kind: "data_table", table_id: "t" }, series: [{ value_col: 1 }],
  options: { stacked: false, legend: true, ...options },
});

describe("stackMode", () => {
  it("is none for lines, pies and scatter whatever the options say", () => {
    for (const t of ["line", "pie", "scatter"] as const) expect(stackMode(spec(t, { stacked: true, stack: "percent" }))).toBe("none");
  });
  it("uses `stack`, falling back to the old `stacked` flag", () => {
    expect(stackMode(spec("bar", { stacked: true }))).toBe("stacked");
    expect(stackMode(spec("area", { stacked: true, stack: "percent" }))).toBe("percent");
    expect(stackMode(spec("bar", { stacked: true, stack: "none" }))).toBe("none");
    expect(stackMode(spec("bar"))).toBe("none");
  });
});

describe("buildSegments", () => {
  it("plain: each value spans from zero to itself, empty stays empty", () => {
    const s = buildSegments([[3, -2, null]], "none");
    expect(s[0]).toEqual([{ v: 3, lo: 0, hi: 3 }, { v: -2, lo: -2, hi: 0 }, null]);
  });
  it("stacked: positives pile up, negatives pile down, they never overlap", () => {
    const s = buildSegments([[2], [-1], [3], [-4]], "stacked");
    expect(s.map((r) => [r[0]!.lo, r[0]!.hi])).toEqual([[0, 2], [-1, 0], [2, 5], [-5, -1]]);
  });
  it("stacked: an empty value adds nothing and is not drawn", () => {
    const s = buildSegments([[2], [null], [3]], "stacked");
    expect(s[1]![0]).toBeNull();
    expect(s[2]![0]).toEqual({ v: 3, lo: 2, hi: 5 });
  });
  it("percent: every category adds up to 100 and keeps the real value", () => {
    const s = buildSegments([[1, 0], [3, 0]], "percent");
    expect(s[0]![0]).toEqual({ v: 1, lo: 0, hi: 25 });
    expect(s[1]![0]).toEqual({ v: 3, lo: 25, hi: 100 });
    expect(s[1]![1]).toEqual({ v: 0, lo: 0, hi: 0 }); // all zero: no division by zero
  });
  it("handles no data", () => {
    expect(buildSegments([], "none")).toEqual([]);
  });
});

describe("niceTicks", () => {
  it("covers the range with round steps", () => {
    expect(niceTicks(0, 97)).toEqual({ ticks: [0, 20, 40, 60, 80, 100], lo: 0, hi: 100 });
    expect(niceTicks(-3, 7)).toEqual({ ticks: [-4, -2, 0, 2, 4, 6, 8], lo: -4, hi: 8 });
  });
  it("copes with a single value, zero, tiny and non-finite ranges", () => {
    expect(niceTicks(5, 5).ticks).toContain(5);
    expect(niceTicks(0, 0).ticks.length).toBeGreaterThan(1);
    expect(niceTicks(0, 0.0003).ticks.at(-1)).toBeCloseTo(0.0003, 6);
    expect(niceTicks(NaN, 3)).toEqual({ ticks: [0, 1], lo: 0, hi: 1 });
  });
  it("has no floating point noise", () => {
    expect(niceTicks(0, 0.3).ticks).toEqual([0, 0.1, 0.2, 0.3]);
  });
});

describe("valueRange", () => {
  it("bars include zero, lines do not have to", () => {
    const segs = buildSegments([[100, 120]], "none");
    expect(valueRange(segs, "none", true)).toEqual({ lo: 0, hi: 120 });
    expect(valueRange([[{ v: 100, lo: 100, hi: 100 }, { v: 120, lo: 120, hi: 120 }]], "none", false)).toEqual({ lo: 100, hi: 120 });
  });
  it("percent is at least 0..100", () => {
    expect(valueRange(buildSegments([[1], [1]], "percent"), "percent", true)).toEqual({ lo: 0, hi: 100 });
  });
  it("no data gives a harmless range", () => {
    expect(valueRange([[null]], "none", true)).toEqual({ lo: 0, hi: 1 });
  });
});

describe("labels and numbers", () => {
  it("picks evenly spaced labels, always the first", () => {
    expect(pickLabelIndexes(5, 8)).toEqual([0, 1, 2, 3, 4]);
    expect(pickLabelIndexes(20, 8)).toEqual([0, 3, 6, 9, 12, 15, 18]);
    expect(pickLabelIndexes(0, 8)).toEqual([]);
  });
  it("shortens by characters, not bytes", () => {
    expect(shorten("abcdef", 4)).toBe("abc…");
    expect(shorten("خرید", 10)).toBe("خرید");
  });
  it("compacts axis numbers", () => {
    expect([compact(950), compact(1500), compact(2_300_000), compact(-4000), compact(0.125)]).toEqual(["950", "1.5k", "2.3M", "-4k", "0.13"]);
  });
});

describe("pieSlices", () => {
  it("covers the full circle and ignores zero and empty values", () => {
    const s = pieSlices([1, 0, null, 3]);
    expect(s.map((x) => x.index)).toEqual([0, 3]);
    expect(s[0]!.fraction).toBeCloseTo(0.25);
    expect(s[1]!.end - s[0]!.start).toBeCloseTo(Math.PI * 2);
  });
  it("is empty without positive values", () => {
    expect(pieSlices([0, null, -1])).toEqual([]);
  });
});

describe("linePieces", () => {
  it("breaks the line at a gap", () => {
    const p = (x: number) => ({ x, y: x });
    expect(linePieces([p(0), p(1), null, p(3), null, null, p(6)])).toEqual([[p(0), p(1)], [p(3)], [p(6)]]);
    expect(linePieces([null])).toEqual([]);
  });
});

describe("localizeDigits", () => {
  it("changes digits only", async () => {
    const { localizeDigits } = await import("./chartLayout");
    expect(localizeDigits("1.5k 20%", "persian")).toBe("۱.۵k ۲۰%");
    expect(localizeDigits("12", "arabic")).toBe("١٢");
    expect(localizeDigits("12", "latin")).toBe("12");
  });
});
