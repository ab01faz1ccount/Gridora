import type { StyleInfo } from "@contracts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cellDisplay, localizeDigits, type DisplayPrefs } from "./cellText";
import { StyleStore, styleCss } from "./styles";

const info = (id: number, extra: Partial<StyleInfo> = {}): StyleInfo => ({ id, bold: false, italic: false, underline: false, wrap: false, ...extra });

describe("StyleStore", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("fetches each id once, in one batch, and tells subscribers", async () => {
    const fetch = vi.fn(async (ids: number[]) => ids.map((i) => info(i, { bold: true })));
    const s = new StyleStore(fetch);
    const seen = vi.fn();
    s.subscribe(seen);
    s.need(3); s.need(3); s.need(5); s.need(0); s.need(undefined);
    await vi.advanceTimersByTimeAsync(50);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith([3, 5]);
    expect(s.get(3)?.bold).toBe(true);
    expect(seen).toHaveBeenCalled();
    s.need(3);
    await vi.advanceTimersByTimeAsync(50);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("retries a failed id only after the pause", async () => {
    let t = 0;
    const fetch = vi.fn().mockRejectedValueOnce(new Error("x")).mockResolvedValue([info(2)]);
    const s = new StyleStore(fetch, 1000, () => t);
    s.need(2);
    await vi.advanceTimersByTimeAsync(50);
    s.need(2);
    await vi.advanceTimersByTimeAsync(50);
    expect(fetch).toHaveBeenCalledTimes(1);
    t = 2000;
    s.need(2);
    await vi.advanceTimersByTimeAsync(50);
    expect(s.get(2)).toBeDefined();
  });
});

describe("styleCss", () => {
  it("maps the look to CSS, points to pixels", () => {
    const css = styleCss(info(1, { bold: true, italic: true, underline: true, font_name: 'Ta"homa', font_size: 12, font_color: "#FF0000", fill_color: "#00FF00", halign: "center", wrap: true }));
    expect(css).toMatchObject({ fontWeight: 700, fontStyle: "italic", textDecoration: "underline", fontSize: 16, color: "#FF0000", backgroundColor: "#00FF00", textAlign: "center", whiteSpace: "normal" });
    expect(String(css?.fontFamily)).toContain('"Tahoma"');
    expect(styleCss(info(1))).toBeUndefined();
    expect(styleCss(undefined)).toBeUndefined();
  });
});

describe("number-format text", () => {
  const prefs = (digits: DisplayPrefs["digits"]): DisplayPrefs => ({ digits, calendar: "gregorian", locale: "en", trueText: "TRUE", falseText: "FALSE" });
  it("shows the server's text with the chosen digits", () => {
    const cell = { r: 0, c: 0, v: { k: "num" as const, n: 1234.5 }, d: "1,234.50" };
    expect(cellDisplay(cell, prefs("latin")).text).toBe("1,234.50");
    expect(cellDisplay(cell, prefs("persian")).text).toBe("۱٬۲۳۴٫۵۰");
    expect(cellDisplay({ r: 0, c: 0, v: { k: "num" as const, n: 7 } }, prefs("latin")).text).toBe("7");
  });
  it("leaves words alone", () => {
    expect(localizeDigits("Total 5%", "persian")).toBe("Total ۵%");
  });
});
