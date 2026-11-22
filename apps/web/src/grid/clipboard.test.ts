import type { Cell } from "@contracts";
import { describe, expect, it } from "vitest";
import { BlockCache } from "./block-cache";
import { parseTsv, pasteEdits, toTsv, valueText } from "./clipboard";

const tick = () => new Promise((r) => setTimeout(r, 0));
async function cacheWith(cells: Cell[]) {
  const cache = new BlockCache({ rowCount: 10, colCount: 5, fetchBlock: async () => cells });
  cache.ensure(0, 9, 0, 4);
  await tick();
  return cache;
}

describe("parseTsv", () => {
  it("splits rows and cells, with \\n, \\r\\n or \\r", () => {
    expect(parseTsv("a\tb\nc\td")).toEqual([["a", "b"], ["c", "d"]]);
    expect(parseTsv("a\tb\r\nc\td\r\n")).toEqual([["a", "b"], ["c", "d"]]);
    expect(parseTsv("a\rb")).toEqual([["a"], ["b"]]);
  });
  it("keeps empty cells, including at the ends", () => {
    expect(parseTsv("\ta\t")).toEqual([["", "a", ""]]);
    expect(parseTsv("a\n\nb")).toEqual([["a"], [""], ["b"]]);
  });
  it("reads quoted cells with tabs, line breaks and doubled quotes", () => {
    expect(parseTsv('"a\tb"\t"line1\nline2"\t"say ""hi"""')).toEqual([["a\tb", "line1\nline2", 'say "hi"']]);
  });
  it("a quote in the middle of a cell is just a character", () => {
    expect(parseTsv('5" pipe\tx')).toEqual([['5" pipe', "x"]]);
  });
  it("nothing gives no rows", () => {
    expect(parseTsv("")).toEqual([]);
  });
});

describe("toTsv", () => {
  it("writes values (a formula's result), Latin digits, quoting only where needed", async () => {
    const cache = await cacheWith([
      { r: 0, c: 0, v: { k: "num", n: 1.5 } },
      { r: 0, c: 1, v: { k: "str", s: "a\tb" } },
      { r: 1, c: 0, v: { k: "bool", b: true }, f: "=1=1" },
      { r: 1, c: 1, v: { k: "str", s: 'say "hi"' } },
    ]);
    expect(toTsv(cache, { r0: 0, r1: 1, c0: 0, c1: 2 })).toEqual({
      ok: true,
      text: '1.5\t"a\tb"\t\nTRUE\t"say ""hi"""\t',
    });
  });
  it("round-trips through parseTsv", async () => {
    const cache = await cacheWith([{ r: 0, c: 0, v: { k: "str", s: "x\ny" } }, { r: 0, c: 1, v: { k: "num", n: 2 } }]);
    const res = toTsv(cache, { r0: 0, r1: 0, c0: 0, c1: 1 });
    expect(res.ok && parseTsv(res.text)).toEqual([["x\ny", "2"]]);
  });
  it("refuses cells that are not loaded instead of copying blanks", () => {
    const cache = new BlockCache({ rowCount: 10, colCount: 5, fetchBlock: () => new Promise(() => {}) });
    expect(toTsv(cache, { r0: 0, r1: 0, c0: 0, c1: 0 })).toEqual({ ok: false, reason: "notLoaded" });
  });
  it("refuses a range the API could not take back in one step", async () => {
    const cache = await cacheWith([]);
    expect(toTsv(cache, { r0: 0, r1: 99_999, c0: 0, c1: 0 })).toEqual({ ok: false, reason: "tooLarge" });
  });
  it("valueText of errors and dates", () => {
    expect(valueText({ r: 0, c: 0, v: { k: "err", e: "#DIV/0!" } })).toBe("#DIV/0!");
    expect(valueText({ r: 0, c: 0, v: { k: "date", iso: "2026-01-02" } })).toBe("2026-01-02");
    expect(valueText(undefined)).toBe("");
  });
});

describe("pasteEdits", () => {
  const at = (r: number, c: number) => ({ r0: r, r1: r, c0: c, c1: c });
  it("lands at the top-left of the selection and types each cell like typing would", () => {
    const res = pasteEdits("1\t۲\nabc\t=A1+1", at(2, 1));
    expect(res).toEqual({
      ok: true,
      range: { r0: 2, r1: 3, c0: 1, c1: 2 },
      edits: [
        { r: 2, c: 1, value: { k: "num", n: 1 } },
        { r: 2, c: 2, value: { k: "num", n: 2 } },
        { r: 3, c: 1, value: { k: "str", s: "abc" } },
        { r: 3, c: 2, formula: "=A1+1" },
      ],
    });
  });
  it("empty pasted cells clear their target; short rows are padded", () => {
    const res = pasteEdits("a\t\nb", at(0, 0));
    expect(res.ok && res.edits).toEqual([
      { r: 0, c: 0, value: { k: "str", s: "a" } }, { r: 0, c: 1 }, { r: 1, c: 0, value: { k: "str", s: "b" } }, { r: 1, c: 1 },
    ]);
  });
  it("one value fills a bigger selection", () => {
    const res = pasteEdits("7", { r0: 0, r1: 1, c0: 0, c1: 2 });
    expect(res.ok && res.edits).toHaveLength(6);
    expect(res.ok && res.range).toEqual({ r0: 0, r1: 1, c0: 0, c1: 2 });
  });
  it("cells past the last row or column of any sheet are dropped", () => {
    const res = pasteEdits("1\n2", at(1_048_575, 0));
    expect(res.ok && res.edits).toEqual([{ r: 1_048_575, c: 0, value: { k: "num", n: 1 } }]);
  });
  it("empty text and huge pastes are refused", () => {
    expect(pasteEdits("", at(0, 0))).toEqual({ ok: false, reason: "empty" });
    expect(pasteEdits("x", { r0: 0, r1: 99_999, c0: 0, c1: 0 })).toEqual({ ok: false, reason: "tooLarge" });
  });
});
