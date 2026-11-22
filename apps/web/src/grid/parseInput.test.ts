import { describe, expect, it } from "vitest";
import { editFor, parseCellInput } from "./parseInput";

describe("parseCellInput", () => {
  it("empty input clears the cell", () => {
    expect(parseCellInput("")).toEqual({});
  });

  it("numbers, including Persian digits and separators, are sent as Latin numbers", () => {
    expect(parseCellInput("42")).toEqual({ value: { k: "num", n: 42 } });
    expect(parseCellInput(" -3.5 ")).toEqual({ value: { k: "num", n: -3.5 } });
    expect(parseCellInput("۱۲۳٫۵")).toEqual({ value: { k: "num", n: 123.5 } });
    expect(parseCellInput("۱٬۲۳۴")).toEqual({ value: { k: "num", n: 1234 } });
    expect(parseCellInput("1e3")).toEqual({ value: { k: "num", n: 1000 } });
  });

  it("a number too large for a finite value stays text instead of failing on the server", () => {
    expect(parseCellInput("1e999")).toEqual({ value: { k: "str", s: "1e999" } });
  });

  it("booleans are case-insensitive", () => {
    expect(parseCellInput("true")).toEqual({ value: { k: "bool", b: true } });
    expect(parseCellInput("False")).toEqual({ value: { k: "bool", b: false } });
  });

  it("a leading = makes a formula, untouched", () => {
    expect(parseCellInput("=SUM(A1:A3)")).toEqual({ formula: "=SUM(A1:A3)" });
    expect(parseCellInput("=۱+۲")).toEqual({ formula: "=۱+۲" });
  });

  it("a leading apostrophe forces text", () => {
    expect(parseCellInput("'007")).toEqual({ value: { k: "str", s: "007" } });
    expect(parseCellInput("'=A1")).toEqual({ value: { k: "str", s: "=A1" } });
  });

  it("everything else is text, spaces kept", () => {
    expect(parseCellInput("علی")).toEqual({ value: { k: "str", s: "علی" } });
    expect(parseCellInput("  hi ")).toEqual({ value: { k: "str", s: "  hi " } });
    expect(parseCellInput("1,5")).toEqual({ value: { k: "str", s: "1,5" } }); // ambiguous: not guessed
  });

  it("editFor attaches the position", () => {
    expect(editFor(2, 3, "7")).toEqual({ r: 2, c: 3, value: { k: "num", n: 7 } });
    expect(editFor(0, 0, "")).toEqual({ r: 0, c: 0 });
  });
});
