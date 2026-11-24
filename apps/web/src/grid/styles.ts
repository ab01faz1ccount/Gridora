// Look of cells (font, colours, alignment ...): cells carry only a format id (`Cell.s`); the details
// are fetched once per id, in batches, and kept here. Ids never change meaning within a workbook.
import type { StyleInfo } from "@contracts";
import type { CSSProperties } from "react";

export class StyleStore {
  private known = new Map<number, StyleInfo>();
  private wanted = new Set<number>();
  private inFlight = new Set<number>();
  private failedAt = new Map<number, number>();
  private listeners = new Set<() => void>();
  private _version = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private fetchStyles: (ids: number[]) => Promise<StyleInfo[]>,
    private retryAfterMs = 3000,
    private now: () => number = () => Date.now(),
  ) {}

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  getVersion = (): number => this._version;

  get(id: number | undefined): StyleInfo | undefined {
    return id ? this.known.get(id) : undefined;
  }

  /** Ask for a format id that a rendered cell uses; the answer arrives through `subscribe`. Safe in render. */
  need(id: number | undefined): void {
    if (!id || this.known.has(id) || this.inFlight.has(id)) return;
    const failed = this.failedAt.get(id);
    if (failed !== undefined && this.now() - failed < this.retryAfterMs) return;
    this.wanted.add(id);
    this.timer ??= setTimeout(() => void this.flush(), 20);
  }

  /** Formats the server just made (a format request's result carries only ids): forget nothing, fetch what is new. */
  private async flush(): Promise<void> {
    this.timer = null;
    const ids = [...this.wanted].slice(0, 400);
    ids.forEach((i) => {
      this.wanted.delete(i);
      this.inFlight.add(i);
    });
    if (!ids.length) return;
    try {
      const got = await this.fetchStyles(ids);
      for (const s of got) this.known.set(s.id, s);
      ids.forEach((i) => this.failedAt.delete(i));
    } catch {
      ids.forEach((i) => this.failedAt.set(i, this.now()));
    } finally {
      ids.forEach((i) => this.inFlight.delete(i));
      this._version++;
      this.listeners.forEach((l) => l());
      if (this.wanted.size) this.timer ??= setTimeout(() => void this.flush(), 20);
    }
  }

  /** Stop the pending fetch (the store stays usable: a remounted view in StrictMode keeps working). */
  dispose(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }
}

/** Excel font sizes are points; the grid works in CSS pixels. */
const PT = 4 / 3;

export function styleCss(s: StyleInfo | undefined): CSSProperties | undefined {
  if (!s) return undefined;
  const css: CSSProperties = {};
  if (s.bold) css.fontWeight = 700;
  if (s.italic) css.fontStyle = "italic";
  if (s.underline) css.textDecoration = "underline";
  if (s.font_name) css.fontFamily = `"${s.font_name.replace(/["\\]/g, "")}", var(--font, inherit)`;
  if (s.font_size) css.fontSize = Math.round(s.font_size * PT * 10) / 10;
  if (s.font_color) css.color = s.font_color;
  if (s.fill_color) css.backgroundColor = s.fill_color;
  if (s.halign) css.textAlign = s.halign;
  if (s.wrap) css.whiteSpace = "normal";
  return Object.keys(css).length ? css : undefined;
}
