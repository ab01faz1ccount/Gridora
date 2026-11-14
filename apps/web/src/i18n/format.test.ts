import { describe, expect, it } from "vitest";
import { formatDate, formatNumber, normalizeNumericInput } from "./format";

describe("normalizeNumericInput", () => {
  it.each([
    ["۱۲۳", "123"],
    ["٤٥٦", "456"],
    ["۱٬۲۳۴٫۵", "1234.5"],
    ["1,234,567.5", "1234567.5"],
    ["-۷", "-7"],
    ["−7", "-7"],
    ["۱e۳", "1e3"],
    [" 42 ", "42"],
  ])("%s -> %s", (input, out) => {
    expect(normalizeNumericInput(input)).toBe(out);
  });

  it.each([
    "=SUM(۱+۲)", // formulas are never rewritten
    "علی۱۲", // digits inside words stay
    "1,5", // ambiguous: left for the server to judge, not guessed
    "۱۲ ۳۴",
    "abc",
    "",
    "1.2.3",
  ])("leaves %j unchanged", (input) => {
    expect(normalizeNumericInput(input)).toBe(input);
  });
});

describe("formatNumber", () => {
  it("uses the chosen digit set and keeps the value", () => {
    expect(formatNumber(1234.5, "latin")).toBe("1,234.5");
    expect(formatNumber(1234.5, "persian")).toMatch(/^[۰-۹٬٫]+$/);
    expect(formatNumber(1234.5, "persian")).toContain("۱");
    expect(formatNumber(12, "arabic")).toBe("١٢");
  });
});

describe("formatDate", () => {
  const iso = "2026-11-14T10:00:00Z";
  it("gregorian vs jalali are different calendars of the same day", () => {
    const g = formatDate(iso, { calendar: "gregorian", digits: "latin", locale: "en" });
    const j = formatDate(iso, { calendar: "jalali", digits: "latin", locale: "fa" });
    expect(g).toContain("2026");
    expect(j).toContain("1405");
    expect(j).not.toContain("2026");
  });
  it("persian digits", () => {
    const j = formatDate(iso, { calendar: "jalali", digits: "persian", locale: "fa" });
    expect(j).toContain("۱۴۰۵");
  });
  it("an unparsable date is returned as is", () => {
    expect(formatDate("nope", { calendar: "jalali", digits: "latin", locale: "fa" })).toBe("nope");
  });
});
