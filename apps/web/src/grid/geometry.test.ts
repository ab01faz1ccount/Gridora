import { describe, expect, it } from "vitest";
import {
  columnLetters, makeScroller, MAX_PROXY_PX, uniformAxis, variableAxis, visibleRange,
} from "./geometry";

describe("uniformAxis", () => {
  const a = uniformAxis(1000, 26);
  it("offsets and indices agree, including at boundaries", () => {
    expect(a.total).toBe(26_000);
    expect(a.offset(0)).toBe(0);
    expect(a.offset(10)).toBe(260);
    expect(a.indexAt(0)).toBe(0);
    expect(a.indexAt(25.9)).toBe(0);
    expect(a.indexAt(26)).toBe(1);
    expect(a.indexAt(-50)).toBe(0); // clamped
    expect(a.indexAt(1e9)).toBe(999);
  });
  it("an empty axis is safe", () => {
    const e = uniformAxis(0, 26);
    expect(e.indexAt(100)).toBe(0);
    expect(visibleRange(e, 0, 500, 3)).toEqual({ first: 0, last: -1 });
  });
});

describe("variableAxis", () => {
  const widths = [100, 50, 200, 80];
  const a = variableAxis(4, (i) => widths[i] ?? 0);
  it("prefix sums", () => {
    expect(a.total).toBe(430);
    expect([0, 1, 2, 3, 4].map((i) => a.offset(i))).toEqual([0, 100, 150, 350, 430]);
    expect([0, 1, 2, 3].map((i) => a.size(i))).toEqual(widths);
  });
  it("indexAt by binary search matches a linear scan for every pixel", () => {
    for (let px = 0; px < 430; px++) {
      let expected = 0;
      while (expected < 3 && a.offset(expected + 1) <= px) expected++;
      expect(a.indexAt(px), `px ${px}`).toBe(expected);
    }
  });
});

describe("visibleRange", () => {
  const rows = uniformAxis(100_000, 26);
  it("covers exactly the viewport plus overscan", () => {
    expect(visibleRange(rows, 0, 520, 0)).toEqual({ first: 0, last: 19 });
    expect(visibleRange(rows, 0, 520, 5)).toEqual({ first: 0, last: 24 });
    expect(visibleRange(rows, 26 * 1000, 520, 5)).toEqual({ first: 995, last: 1024 });
  });
  it("clamps at both ends", () => {
    expect(visibleRange(rows, rows.total - 100, 520, 5).last).toBe(99_999);
  });
  it("renders a small, bounded number of rows however large the sheet is", () => {
    for (const n of [1000, 100_000, 1_048_576]) {
      const r = visibleRange(uniformAxis(n, 26), 12345, 800, 8);
      expect(r.last - r.first + 1).toBeLessThan(60);
    }
  });
});

describe("makeScroller", () => {
  it("is the identity when everything fits under the cap (100k rows)", () => {
    const s = makeScroller(100_000 * 26, 700);
    expect(s.scaled).toBe(false);
    expect(s.proxyPx).toBe(2_600_000);
    expect(s.toContent(12345)).toBe(12345);
  });

  it("caps the proxy and scales at Excel's 1,048,576 rows", () => {
    const content = 1_048_576 * 26; // 27.2M px: would not lay out in Firefox
    const s = makeScroller(content, 700);
    expect(s.scaled).toBe(true);
    expect(s.proxyPx).toBe(MAX_PROXY_PX);
    expect(s.scale).toBeGreaterThan(1);
  });

  it("top shows the first row, the maximum scroll shows the last row exactly", () => {
    const content = 1_048_576 * 26;
    const viewport = 700;
    const s = makeScroller(content, viewport);
    expect(s.toContent(0)).toBe(0);
    const maxScroll = s.proxyPx - viewport;
    expect(s.toContent(maxScroll)).toBeCloseTo(content - viewport, 3);
    // bottom of the viewport is the bottom of the last row
    expect(s.toContent(maxScroll) + viewport).toBeCloseTo(content, 3);
  });

  it("is monotonic and round-trips", () => {
    const s = makeScroller(1_048_576 * 26, 700);
    let prev = -1;
    for (let sc = 0; sc <= s.proxyPx - 700; sc += 123_457) {
      const c = s.toContent(sc);
      expect(c).toBeGreaterThan(prev);
      prev = c;
      expect(s.toScroll(c)).toBeCloseTo(sc, 3);
    }
  });

  it("every row is reachable: step through scroll positions and no row is skipped by more than the viewport", () => {
    const rows = uniformAxis(1_048_576, 26);
    const s = makeScroller(rows.total, 700);
    const seen = new Set<number>();
    for (let sc = 0; sc <= s.proxyPx - 700; sc += 20) {
      const r = visibleRange(rows, s.toContent(sc), 700, 0);
      seen.add(r.first);
      seen.add(r.last);
    }
    // consecutive scroll steps overlap, so the union has no gap bigger than one viewport of rows
    const sorted = [...seen].sort((a, b) => a - b);
    let maxGap = 0;
    for (let i = 1; i < sorted.length; i++) maxGap = Math.max(maxGap, (sorted[i] ?? 0) - (sorted[i - 1] ?? 0));
    expect(sorted[0]).toBe(0);
    expect(sorted[sorted.length - 1]).toBe(1_048_575);
    expect(maxGap).toBeLessThanOrEqual(Math.ceil(700 / 26) + 1);
  });
});

describe("columnLetters", () => {
  it.each([[0, "A"], [25, "Z"], [26, "AA"], [51, "AZ"], [52, "BA"], [701, "ZZ"], [702, "AAA"], [16383, "XFD"]])(
    "%i -> %s", (i, s) => expect(columnLetters(i)).toBe(s));
});
