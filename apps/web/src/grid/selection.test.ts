import { describe, expect, it } from "vitest";
import { boundsOf, inRange, navigate, single, type Dims } from "./selection";

const ltr: Dims = { rowCount: 100, colCount: 10, pageRows: 20, rtl: false };
const rtl: Dims = { ...ltr, rtl: true };
const at = (r: number, c: number) => single({ r, c });

describe("navigation (LTR sheet)", () => {
  it("arrows move one cell and clamp at the edges", () => {
    expect(navigate(at(5, 5), { key: "ArrowRight" }, ltr)?.active).toEqual({ r: 5, c: 6 });
    expect(navigate(at(5, 5), { key: "ArrowLeft" }, ltr)?.active).toEqual({ r: 5, c: 4 });
    expect(navigate(at(0, 0), { key: "ArrowUp" }, ltr)?.active).toEqual({ r: 0, c: 0 });
    expect(navigate(at(0, 0), { key: "ArrowLeft" }, ltr)?.active).toEqual({ r: 0, c: 0 });
    expect(navigate(at(99, 9), { key: "ArrowDown" }, ltr)?.active).toEqual({ r: 99, c: 9 });
    expect(navigate(at(99, 9), { key: "ArrowRight" }, ltr)?.active).toEqual({ r: 99, c: 9 });
  });
});

describe("navigation (RTL sheet): arrow keys follow what the user SEES", () => {
  it("ArrowLeft goes to the next column, ArrowRight to the previous one", () => {
    expect(navigate(at(5, 5), { key: "ArrowLeft" }, rtl)?.active).toEqual({ r: 5, c: 6 });
    expect(navigate(at(5, 5), { key: "ArrowRight" }, rtl)?.active).toEqual({ r: 5, c: 4 });
  });
  it("up/down are unchanged", () => {
    expect(navigate(at(5, 5), { key: "ArrowDown" }, rtl)?.active).toEqual({ r: 6, c: 5 });
  });
  it("Tab follows reading order in both directions (next column)", () => {
    expect(navigate(at(5, 5), { key: "Tab" }, rtl)?.active).toEqual({ r: 5, c: 6 });
    expect(navigate(at(5, 5), { key: "Tab", shift: true }, rtl)?.active).toEqual({ r: 5, c: 4 });
    expect(navigate(at(5, 5), { key: "Tab" }, ltr)?.active).toEqual({ r: 5, c: 6 });
  });
  it("Home goes to column A (the right-most column of an RTL sheet)", () => {
    expect(navigate(at(5, 5), { key: "Home" }, rtl)?.active).toEqual({ r: 5, c: 0 });
  });
});

describe("other keys", () => {
  it("page, home/end, ctrl+home/end", () => {
    expect(navigate(at(50, 3), { key: "PageDown" }, ltr)?.active).toEqual({ r: 70, c: 3 });
    expect(navigate(at(5, 3), { key: "PageUp" }, ltr)?.active).toEqual({ r: 0, c: 3 });
    expect(navigate(at(50, 3), { key: "End" }, ltr)?.active).toEqual({ r: 50, c: 9 });
    expect(navigate(at(50, 3), { key: "Home", ctrl: true }, ltr)?.active).toEqual({ r: 0, c: 0 });
    expect(navigate(at(50, 3), { key: "End", ctrl: true }, ltr)?.active).toEqual({ r: 99, c: 9 });
  });
  it("Enter moves down, Shift+Enter up", () => {
    expect(navigate(at(5, 5), { key: "Enter" }, ltr)?.active).toEqual({ r: 6, c: 5 });
    expect(navigate(at(5, 5), { key: "Enter", shift: true }, ltr)?.active).toEqual({ r: 4, c: 5 });
  });
  it("non-navigation keys are ignored", () => {
    expect(navigate(at(5, 5), { key: "a" }, ltr)).toBeNull();
    expect(navigate(at(5, 5), { key: "F2" }, ltr)).toBeNull();
  });
});

describe("range selection", () => {
  it("Shift+arrow extends from the anchor and keeps the active cell", () => {
    let s = at(5, 5);
    s = navigate(s, { key: "ArrowDown", shift: true }, ltr)!;
    s = navigate(s, { key: "ArrowRight", shift: true }, ltr)!;
    expect(s.active).toEqual({ r: 5, c: 5 });
    expect(boundsOf(s)).toEqual({ r0: 5, r1: 6, c0: 5, c1: 6 });
  });
  it("Shift+arrow in an RTL sheet extends toward what you see", () => {
    let s = at(5, 5);
    s = navigate(s, { key: "ArrowLeft", shift: true }, rtl)!;
    expect(boundsOf(s)).toEqual({ r0: 5, r1: 5, c0: 5, c1: 6 });
  });
  it("extending backwards gives normalized bounds", () => {
    let s = at(5, 5);
    s = navigate(s, { key: "ArrowUp", shift: true }, ltr)!;
    s = navigate(s, { key: "ArrowLeft", shift: true }, ltr)!;
    expect(boundsOf(s)).toEqual({ r0: 4, r1: 5, c0: 4, c1: 5 });
    expect(inRange(boundsOf(s), 4, 4)).toBe(true);
    expect(inRange(boundsOf(s), 6, 5)).toBe(false);
  });
  it("a plain arrow collapses the range", () => {
    let s = navigate(at(5, 5), { key: "ArrowDown", shift: true }, ltr)!;
    s = navigate(s, { key: "ArrowRight" }, ltr)!;
    expect(s.anchor).toEqual(s.active);
  });
  it("an empty sheet cannot be navigated out of bounds", () => {
    const empty: Dims = { rowCount: 0, colCount: 0, pageRows: 1, rtl: false };
    expect(navigate(at(0, 0), { key: "ArrowDown" }, empty)?.active).toEqual({ r: 0, c: 0 });
  });
});
