// Selection state and keyboard navigation as pure functions (no DOM): easy to test in LTR and RTL.
export interface Pos {
  r: number;
  c: number;
}
export interface Selection {
  active: Pos; // the cell with the cursor
  anchor: Pos; // other corner of the range (equals active when only one cell)
  focus: Pos; // moving corner when extending with Shift
}

export interface Dims {
  rowCount: number;
  colCount: number;
  /** last row/column that holds data (End goes there); default: the last one of the grid */
  lastRow?: number;
  lastCol?: number;
  pageRows: number;
  rtl: boolean; // sheet direction: ArrowLeft means "next column" in an RTL sheet
}

export const single = (p: Pos): Selection => ({ active: p, anchor: p, focus: p });

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

export function clampPos(p: Pos, d: Dims): Pos {
  return { r: clamp(p.r, 0, Math.max(0, d.rowCount - 1)), c: clamp(p.c, 0, Math.max(0, d.colCount - 1)) };
}

export interface KeyInfo {
  key: string;
  shift?: boolean;
  ctrl?: boolean; // ctrl or meta
}

/** Returns the new selection, or null when the key is not a navigation key. */
export function navigate(sel: Selection, k: KeyInfo, d: Dims): Selection | null {
  const from = k.shift ? sel.focus : sel.active;
  let to: Pos;
  const dc = (visual: -1 | 1) => (d.rtl ? -visual : visual); // visual left/right -> logical column step
  switch (k.key) {
    case "ArrowUp": to = { r: from.r - 1, c: from.c }; break;
    case "ArrowDown": to = { r: from.r + 1, c: from.c }; break;
    case "ArrowLeft": to = { r: from.r, c: from.c + dc(-1) }; break;
    case "ArrowRight": to = { r: from.r, c: from.c + dc(1) }; break;
    case "PageUp": to = { r: from.r - d.pageRows, c: from.c }; break;
    case "PageDown": to = { r: from.r + d.pageRows, c: from.c }; break;
    case "Home": to = k.ctrl ? { r: 0, c: 0 } : { r: from.r, c: 0 }; break;
    case "End": {
      const lastCol = d.lastCol ?? d.colCount - 1;
      to = k.ctrl ? { r: d.lastRow ?? d.rowCount - 1, c: lastCol } : { r: from.r, c: lastCol };
      break;
    }
    case "Tab": to = { r: sel.active.r, c: sel.active.c + (k.shift ? -1 : 1) }; break; // reading order, both directions
    case "Enter": to = { r: sel.active.r + (k.shift ? -1 : 1), c: sel.active.c }; break;
    default: return null;
  }
  const p = clampPos(to, d);
  if (k.key === "Tab" || k.key === "Enter") return single(p); // these never extend
  if (k.shift) return { active: sel.active, anchor: sel.anchor, focus: p };
  return single(p);
}

export interface RangeBounds {
  r0: number;
  r1: number;
  c0: number;
  c1: number;
}
export function boundsOf(sel: Selection): RangeBounds {
  return {
    r0: Math.min(sel.anchor.r, sel.focus.r),
    r1: Math.max(sel.anchor.r, sel.focus.r),
    c0: Math.min(sel.anchor.c, sel.focus.c),
    c1: Math.max(sel.anchor.c, sel.focus.c),
  };
}
export const inRange = (b: RangeBounds, r: number, c: number) =>
  r >= b.r0 && r <= b.r1 && c >= b.c0 && c <= b.c1;
