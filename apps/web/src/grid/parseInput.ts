import type { CellEdit } from "@contracts";
import { normalizeNumericInput } from "@/i18n/format";

export type EditPayload = Pick<CellEdit, "value" | "formula">;

const NUMBER = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

/**
 * Turns what the person typed into the value of a cell edit. An empty payload clears the cell.
 *
 * - "" -> clear
 * - "=..." -> formula (the server parses and validates it)
 * - "'text" -> text, with the apostrophe dropped (the usual way to keep "007" as text)
 * - TRUE / FALSE (any case) -> boolean
 * - a number, also in Persian/Arabic digits and separators -> number (wire values are Latin)
 * - anything else -> text
 *
 * Dates, percentages and currencies are NOT guessed yet: they stay text.
 */
export function parseCellInput(text: string): EditPayload {
  if (text === "") return {};
  if (text.startsWith("=")) return { formula: text };
  if (text.startsWith("'")) return { value: { k: "str", s: text.slice(1) } };
  const upper = text.trim().toUpperCase();
  if (upper === "TRUE") return { value: { k: "bool", b: true } };
  if (upper === "FALSE") return { value: { k: "bool", b: false } };
  const s = normalizeNumericInput(text).trim();
  if (NUMBER.test(s)) {
    const n = Number(s);
    if (Number.isFinite(n)) return { value: { k: "num", n } };
  }
  return { value: { k: "str", s: text } };
}

/** One edit for one cell. */
export function editFor(r: number, c: number, text: string): CellEdit {
  return { r, c, ...parseCellInput(text) };
}
