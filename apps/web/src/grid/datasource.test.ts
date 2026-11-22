import { describe, expect, it } from "vitest";
import { MIN_COLS, MIN_ROWS, paddedSize, sheetDataSource } from "./datasource";
import { navigate, single } from "./selection";

describe("paddedSize", () => {
  it("a small sheet is shown at the minimum size", () => {
    expect(paddedSize(4, 2)).toEqual({ rows: MIN_ROWS, cols: MIN_COLS });
    expect(paddedSize(0, 0)).toEqual({ rows: MIN_ROWS, cols: MIN_COLS });
  });
  it("a bigger sheet gets room below and to the right, so the next cell can be typed into", () => {
    expect(paddedSize(500, 30)).toEqual({ rows: 520, cols: 35 });
  });
  it("never goes past the last row or column of any sheet", () => {
    expect(paddedSize(1_048_576, 16_384)).toEqual({ rows: 1_048_576, cols: 16_384 });
  });
});

describe("sheetDataSource", () => {
  it("shows the padded size but remembers where the data ends", () => {
    const s = sheetDataSource("w", "s", 4, 2);
    expect([s.rowCount, s.colCount, s.usedRows, s.usedCols]).toEqual([MIN_ROWS, MIN_COLS, 4, 2]);
  });
});

describe("End goes to the last cell with data, not to the padding", () => {
  const dims = { rowCount: 100, colCount: 26, lastRow: 3, lastCol: 1, rtl: false, pageRows: 10 };
  it("Ctrl+End", () => {
    expect(navigate(single({ r: 0, c: 0 }), { key: "End", ctrl: true }, dims)?.active).toEqual({ r: 3, c: 1 });
  });
  it("End stays in the row", () => {
    expect(navigate(single({ r: 2, c: 0 }), { key: "End" }, dims)?.active).toEqual({ r: 2, c: 1 });
  });
  it("without lastRow/lastCol it goes to the corner as before", () => {
    const d = { rowCount: 50, colCount: 5, rtl: false, pageRows: 10 };
    expect(navigate(single({ r: 0, c: 0 }), { key: "End", ctrl: true }, d)?.active).toEqual({ r: 49, c: 4 });
  });
});
