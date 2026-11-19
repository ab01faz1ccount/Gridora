import type { Cell } from "@contracts";
import { describe, expect, it } from "vitest";
import { BlockCache } from "./block-cache";
import type { DataSource } from "./datasource";
import { cellRaw, summarize } from "./summary";

async function loaded(cells: Cell[], rows = 50, cols = 5) {
  const src: DataSource = { rowCount: rows, colCount: cols, fetchBlock: async () => cells };
  const cache = new BlockCache(src);
  cache.ensure(0, rows - 1, 0, cols - 1);
  await new Promise((r) => setTimeout(r, 0));
  return cache;
}

describe("summarize", () => {
  const cells: Cell[] = [
    { r: 0, c: 0, v: { k: "num", n: 2 } }, { r: 1, c: 0, v: { k: "num", n: 4 } },
    { r: 2, c: 0, v: { k: "str", s: "x" } }, { r: 3, c: 0, v: { k: "bool", b: true } },
  ];
  it("counts non-empty cells, sums and averages only numbers", async () => {
    const s = summarize(await loaded(cells), { r0: 0, r1: 4, c0: 0, c1: 0 });
    expect(s).toEqual({ count: 4, numeric: 2, sum: 6, average: 3, partial: false });
  });
  it("has no average without numbers", async () => {
    const s = summarize(await loaded([{ r: 0, c: 0, v: { k: "str", s: "a" } }]), { r0: 0, r1: 1, c0: 0, c1: 0 });
    expect(s.average).toBeNull();
    expect(s.sum).toBe(0);
  });
  it("says so when part of the selection is not loaded (never a silent partial total)", async () => {
    const cache = await loaded(cells, 50, 5);
    expect(summarize(cache, { r0: 0, r1: 400, c0: 0, c1: 0 }).partial).toBe(true); // beyond the loaded block
  });
  it("refuses to scan an enormous selection and flags it partial", async () => {
    const s = summarize(await loaded(cells), { r0: 0, r1: 99_999, c0: 0, c1: 19 });
    expect(s.partial).toBe(true);
    expect(s.count).toBe(0);
  });
});

describe("cellRaw (formula bar)", () => {
  it("shows values as typed and formulas with =", () => {
    expect(cellRaw(undefined)).toBe("");
    expect(cellRaw({ r: 0, c: 0, v: { k: "num", n: 1234.5 } })).toBe("1234.5");
    expect(cellRaw({ r: 0, c: 0, v: { k: "str", s: "علی" } })).toBe("علی");
    expect(cellRaw({ r: 0, c: 0, f: "SUM(A1:A3)", v: { k: "num", n: 6 } })).toBe("=SUM(A1:A3)");
    expect(cellRaw({ r: 0, c: 0, f: "=A1", v: { k: "num", n: 1 } })).toBe("=A1");
    expect(cellRaw({ r: 0, c: 0, v: { k: "bool", b: false } })).toBe("FALSE");
    expect(cellRaw({ r: 0, c: 0, v: { k: "err", e: "#DIV/0!" } })).toBe("#DIV/0!");
  });
});
