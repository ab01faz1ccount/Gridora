import type { Cell } from "@contracts";
import type { BlockCache } from "./block-cache";
import type { RangeBounds } from "./selection";

export interface Summary {
  count: number; // non-empty cells
  numeric: number;
  sum: number;
  average: number | null;
  /** true when some selected cells were not loaded (or the range is too big to scan): the figures cover loaded cells only */
  partial: boolean;
}

const SCAN_LIMIT = 50_000;

/** Count/sum/average of the selection, from cells already in the cache (docs/UX_SPEC.md section 3). */
export function summarize(cache: BlockCache, b: RangeBounds): Summary {
  const area = (b.r1 - b.r0 + 1) * (b.c1 - b.c0 + 1);
  let count = 0;
  let numeric = 0;
  let sum = 0;
  let partial = area > SCAN_LIMIT;
  if (!partial) {
    for (let r = b.r0; r <= b.r1; r++) {
      for (let c = b.c0; c <= b.c1; c++) {
        const look = cache.getCell(r, c);
        if (look.status !== "loaded") {
          partial = true;
          continue;
        }
        const v = look.cell?.v;
        if (!v) continue;
        count++;
        if (v.k === "num") {
          numeric++;
          sum += v.n;
        }
      }
    }
  }
  return { count, numeric, sum, average: numeric > 0 ? sum / numeric : null, partial };
}

/** What the formula bar shows: the formula text if there is one, otherwise the value as typed. */
export function cellRaw(cell: Cell | undefined): string {
  if (!cell) return "";
  if (cell.f) return cell.f.startsWith("=") ? cell.f : `=${cell.f}`;
  const v = cell.v;
  if (!v) return "";
  switch (v.k) {
    case "num": return String(v.n);
    case "str": return v.s;
    case "bool": return v.b ? "TRUE" : "FALSE";
    case "err": return v.e;
    case "date": return v.iso;
  }
}
