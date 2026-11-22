// Spreadsheet clipboard text (tab-separated rows, quotes around cells that need them), the same
// plain-text format Excel and LibreOffice read and write. Pure functions: no DOM, easy to test.
import type { Cell, CellEdit } from "@contracts";
import type { BlockCache } from "./block-cache";
import { MAX_EDITS } from "./editing";
import { parseCellInput } from "./parseInput";
import type { RangeBounds } from "./selection";

/** A cell as plain text for another program: the VALUE (a formula's result), numbers with Latin digits. */
export function valueText(cell: Cell | undefined): string {
  const v = cell?.v;
  if (!v) return "";
  switch (v.k) {
    case "num": return String(v.n);
    case "str": return v.s;
    case "bool": return v.b ? "TRUE" : "FALSE";
    case "err": return v.e;
    case "date": return v.iso;
  }
}

const needsQuotes = (s: string) => /[\t\r\n"]/.test(s);
const quote = (s: string) => (needsQuotes(s) ? `"${s.replace(/"/g, '""')}"` : s);

const EXCEL_MAX_ROWS = 1_048_576;
const EXCEL_MAX_COLS = 16_384;

export type CopyResult = { ok: true; text: string } | { ok: false; reason: "notLoaded" | "tooLarge" };

/** Selection -> text. Refuses (instead of copying blanks that are not really blank) when cells are not loaded. */
export function toTsv(cache: BlockCache, b: RangeBounds): CopyResult {
  if ((b.r1 - b.r0 + 1) * (b.c1 - b.c0 + 1) > MAX_EDITS) return { ok: false, reason: "tooLarge" };
  const lines: string[] = [];
  for (let r = b.r0; r <= b.r1; r++) {
    const cells: string[] = [];
    for (let c = b.c0; c <= b.c1; c++) {
      const look = cache.getCell(r, c);
      if (look.status !== "loaded") return { ok: false, reason: "notLoaded" };
      cells.push(quote(valueText(look.cell)));
    }
    lines.push(cells.join("\t"));
  }
  return { ok: true, text: lines.join("\n") };
}

/** Text -> rows of cells. Handles quoted cells (with tabs, line breaks and "" inside) and \r\n. */
export function parseTsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let i = 0;
  let quoted = false;
  const n = text.length;
  while (i < n) {
    const ch = text[i]!;
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i += 2;
          continue;
        }
        quoted = false;
      } else cell += ch;
      i++;
      continue;
    }
    if (ch === '"' && cell === "") quoted = true;
    else if (ch === "\t") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else cell += ch;
    i++;
  }
  // the last line has no terminator; a trailing line break does not make an extra empty row
  if (cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

export type PasteResult =
  | { ok: true; edits: CellEdit[]; range: RangeBounds }
  | { ok: false; reason: "empty" | "tooLarge" };

/**
 * Where pasted text lands. It starts at the top-left of the selection. One value pasted into a
 * bigger selection fills the whole selection, like Excel. Empty pasted cells clear their target.
 */
export function pasteEdits(text: string, sel: RangeBounds): PasteResult {
  const grid = parseTsv(text);
  const width = Math.max(0, ...grid.map((r) => r.length));
  if (grid.length === 0 || width === 0) return { ok: false, reason: "empty" };
  const single = grid.length === 1 && width === 1;
  const selRows = sel.r1 - sel.r0 + 1;
  const selCols = sel.c1 - sel.c0 + 1;
  const fill = single && (selRows > 1 || selCols > 1);
  const rows = fill ? selRows : grid.length;
  const cols = fill ? selCols : width;
  if (rows * cols > MAX_EDITS) return { ok: false, reason: "tooLarge" };
  const edits: CellEdit[] = [];
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      const r = sel.r0 + i;
      const c = sel.c0 + j;
      if (r >= EXCEL_MAX_ROWS || c >= EXCEL_MAX_COLS) continue; // past the end of any sheet: dropped
      const src = fill ? grid[0]![0]! : (grid[i]?.[j] ?? "");
      edits.push({ r, c, ...parseCellInput(src) });
    }
  }
  return { ok: true, edits, range: { r0: sel.r0, r1: sel.r0 + rows - 1, c0: sel.c0, c1: sel.c0 + cols - 1 } };
}
