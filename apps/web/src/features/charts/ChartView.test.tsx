import type { ChartData, ChartSpec } from "@contracts";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { usePrefs } from "@/state/prefs";
import { ChartView, noteKey } from "./ChartView";

beforeEach(() => usePrefs.setState({ digits: "latin", locale: "en" }));

const spec = (type: ChartSpec["type"], options: Partial<ChartSpec["options"]> = {}): ChartSpec => ({
  schema_version: 1, document_id: "w", type, title: "T", source: { kind: "data_table", table_id: "t" },
  series: [{ value_col: 1 }], options: { stacked: false, legend: true, ...options },
});
const bars: ChartData = { categories: ["a", "b", "c"], series: [{ name: "s1", values: [4, null, -2] }, { name: "s2", values: [1, 2, 3] }] };
const shapes = (c: HTMLElement, sel: string) => c.querySelectorAll(sel);

describe("ChartView", () => {
  it("draws nothing for empty data (no crash)", () => {
    const { container } = render(<ChartView spec={spec("bar")} data={{ categories: [], series: [] }} />);
    expect(shapes(container, "svg").length).toBe(0);
  });

  it("an empty value is not drawn as a zero-height bar", () => {
    const { container } = render(<ChartView spec={spec("bar")} data={bars} />);
    expect(shapes(container, "rect").length).toBe(5); // 6 cells, one empty
    expect([...shapes(container, "title")].some((t) => t.textContent?.includes("b — s1"))).toBe(false);
  });

  it("a line breaks at an empty value instead of dropping to zero", () => {
    const d: ChartData = { categories: ["a", "b", "c", "d"], series: [{ name: "s", values: [1, 2, null, 4] }] };
    const { container } = render(<ChartView spec={spec("line")} data={d} />);
    expect(shapes(container, "path").length).toBe(1); // 1-2 is a line; the lone 4 is only a marker
    expect(shapes(container, "circle").length).toBe(3);
  });

  it("stacked bars with mixed signs do not overlap", () => {
    const { container } = render(<ChartView spec={spec("bar", { stack: "stacked" })} data={{ categories: ["a"], series: [{ name: "p", values: [3] }, { name: "n", values: [-2] }] }} />);
    const [up, down] = [...shapes(container, "rect")].map((r) => ({ y: Number(r.getAttribute("y")), h: Number(r.getAttribute("height")) }));
    expect(up!.y + up!.h).toBeLessThanOrEqual(down!.y + 0.001); // the negative bar starts where the positive one ends (the zero line)
  });

  it("percent stacks tell the share in the tooltip", () => {
    const d: ChartData = { categories: ["a"], series: [{ name: "x", values: [1] }, { name: "y", values: [3] }] };
    const { container } = render(<ChartView spec={spec("bar", { stack: "percent" })} data={d} />);
    expect([...shapes(container, "title")].map((t) => t.textContent)).toEqual(["a — x: 1 (25%)", "a — y: 3 (75%)"]);
  });

  it("horizontal bars put categories on the vertical axis and grow with their number", () => {
    const many: ChartData = { categories: Array.from({ length: 30 }, (_, i) => `c${i}`), series: [{ name: "s", values: Array.from({ length: 30 }, (_, i) => i + 1) }] };
    const { container } = render(<ChartView spec={spec("bar", { orientation: "horizontal" })} data={many} />);
    const vb = container.querySelector("svg")!.getAttribute("viewBox")!.split(" ").map(Number);
    expect(vb[3]).toBeGreaterThan(220);
    const widths = [...shapes(container, "rect")].map((r) => Number(r.getAttribute("width")));
    expect(widths[29]).toBeGreaterThan(widths[0]!);
  });

  it("uses the server's labels (e.g. Jalali dates) for the category axis and tooltips", () => {
    const d: ChartData = { categories: ["2025-03-21", "2025-04-21"], labels: ["1404/01", "1404/02"], categories_kind: "time", series: [{ name: "s", values: [1, 2] }] };
    const { container } = render(<ChartView spec={spec("line")} data={d} />);
    expect(container.textContent).toContain("1404/01");
    expect(container.textContent).not.toContain("2025-03-21");
  });

  it("shows axis titles and a legend only with several series", () => {
    const { container, rerender } = render(<ChartView spec={spec("bar", { axis_titles: { x: "Month", y: "Sales" } })} data={bars} />);
    expect(container.textContent).toContain("Month");
    expect(container.textContent).toContain("Sales");
    expect(shapes(container, ".chart-legend span").length).toBe(2);
    rerender(<ChartView spec={spec("bar")} data={{ categories: ["a"], series: [{ name: "only", values: [1] }] }} />);
    expect(shapes(container, ".chart-legend").length).toBe(0);
  });

  it("scatter draws one point per non-empty pair on a numeric x axis", () => {
    const d: ChartData = { categories: [1, 2, 10], series: [{ name: "y", values: [5, null, 7] }], categories_kind: "number" };
    const { container } = render(<ChartView spec={spec("scatter")} data={d} />);
    expect(shapes(container, "circle").length).toBe(2);
  });

  it("pie shows shares in the legend, can be a donut, and draws a lone slice as a full circle", () => {
    const d: ChartData = { categories: ["a", "b"], series: [{ name: "s", values: [1, 3] }] };
    const { container } = render(<ChartView spec={spec("pie", { donut: true, labels: "percent" })} data={d} />);
    expect(container.querySelector(".chart-legend")!.textContent).toContain("75.0%");
    expect(container.textContent).toContain("25%");
    expect(shapes(container, "path").length).toBe(2);
    const one = render(<ChartView spec={spec("pie")} data={{ categories: ["a"], series: [{ name: "s", values: [5] }] }} />);
    expect(one.container.querySelectorAll("path").length).toBe(1);
  });

  it("uses the person's digits for numbers", () => {
    usePrefs.setState({ digits: "persian" });
    const { container } = render(<ChartView spec={spec("bar", { labels: "value" })} data={{ categories: ["a"], series: [{ name: "s", values: [12] }] }} />);
    expect(container.textContent).toContain("۱۲");
  });
});

describe("notes", () => {
  const data: ChartData = {
    categories: ["a"], series: [{ name: "s", values: [1] }],
    notes: [
      { code: "rows_excluded", params: { count: 3, reason: "empty_date" } },
      { code: "categories_limited", params: { shown: 5, total: 40 } },
      { code: "from_a_newer_server", params: {} },
    ],
  };
  it("tells what was left out, in words, and skips codes it does not know", () => {
    render(<ChartView spec={spec("bar")} data={data} />);
    const list = screen.getByRole("list");
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "3 rows without a date were left out.", "Showing 5 of 40 categories.",
    ]);
  });
  it("every note code the server can send has a message", () => {
    const codes = [["rows_excluded", { reason: "empty_date" }], ["rows_excluded", { reason: "empty_value" }], ["dates_unreadable", {}],
      ["empty_values", {}], ["negative_values", {}], ["categories_limited", {}], ["other_merged", {}], ["sampled", {}], ["extra_series_ignored", {}]] as const;
    for (const [code, params] of codes) expect(noteKey({ code, params: { ...params } }), code).toBeDefined();
  });
});
