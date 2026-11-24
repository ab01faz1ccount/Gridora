// Column names of a sheet range, the way the data operations derive them from the header row
// (packages/dataops targets.py `_header_name_v` + de-duplication), so the pickers offer exactly
// the names the server will look for.
import type { Cell } from "@contracts";

export function headerName(cell: Cell | undefined, index: number): string {
  const v = cell?.v;
  if (v?.k === "str" && v.s.trim() !== "") return v.s.trim();
  if (v?.k === "num") return String(v.n);
  if (v?.k === "bool") return v.b ? "TRUE" : "FALSE";
  return `column_${index + 1}`;
}

export function dedupe(names: string[]): string[] {
  const seen = new Map<string, number>();
  return names.map((n) => {
    const count = (seen.get(n) ?? 0) + 1;
    seen.set(n, count);
    return count === 1 ? n : `${n}_${count}`;
  });
}

/** `cellAt(c)` gives the header-row cell of the c-th column of the range (0-based within the range). */
export function columnNames(width: number, hasHeader: boolean, cellAt: (i: number) => Cell | undefined): string[] {
  const raw = Array.from({ length: width }, (_, i) => (hasHeader ? headerName(cellAt(i), i) : `column_${i + 1}`));
  return dedupe(raw);
}
