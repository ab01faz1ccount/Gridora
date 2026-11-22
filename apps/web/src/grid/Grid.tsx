// Virtualized grid. DOM-based (apps/PLAN.md 3.3): correct bidi/RTL text, IME and accessibility come
// from the browser. Only the visible window (+ overscan) is rendered; cells arrive in blocks from
// the BlockCache. The sheet's own direction (`rtl`) decides column order and arrow-key meaning,
// independent of the UI language.
import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ClipboardEvent as ReactClipboardEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useT } from "@/i18n";
import { usePrefs } from "@/state/prefs";
import { BlockCache } from "./block-cache";
import { cellDisplay, type DisplayPrefs } from "./cellText";
import type { DataSource } from "./datasource";
import {
  columnLetters,
  makeScroller,
  uniformAxis,
  variableAxis,
  visibleRange,
  type Axis,
} from "./geometry";
import { boundsOf, inRange, navigate, single, type Pos, type RangeBounds, type Selection } from "./selection";
import { cellRaw } from "./summary";
import { pasteEdits, toTsv } from "./clipboard";
import type { CellEdit } from "@contracts";

export const ROW_H = 26;
export const COL_W = 110;
export const HEADER_H = 28;
export const HEADER_W = 64;
const ROW_OVERSCAN = 8;
const COL_OVERSCAN = 2;

export interface GridProps {
  source: DataSource;
  rtl: boolean;
  /** Test/measurement hooks. */
  cache?: BlockCache;
  viewport?: { width: number; height: number };
  colWidth?: (c: number) => number;
  onSelectionChange?: (sel: Selection) => void;
  label?: string;
  /** Editing is on when this is given: the text a person typed into a cell (empty = clear). */
  onEdit?: (r: number, c: number, text: string) => void;
  onClear?: (b: RangeBounds) => void;
  onUndo?: () => void;
  onRedo?: () => void;
  /** Pasted cells, as one change. The grid has already selected the pasted range. */
  onPaste?: (edits: CellEdit[]) => void;
  /** Copy/cut/paste could not be done: not all cells are loaded, or too many cells. */
  onClipboardProblem?: (reason: "notLoaded" | "tooLarge") => void;
}

interface Editing {
  r: number;
  c: number;
  original: string; // what the cell held when editing began; an unchanged commit sends nothing
}

interface CellEditorProps {
  top: number;
  start: number;
  w: number;
  initial: string;
  label: string;
  onKeyDown: (e: ReactKeyboardEvent<HTMLInputElement>, draft: string) => void;
  onBlur: (draft: string) => void;
}

/** The text box over the active cell. It owns the draft, so typing does not re-render the grid. */
function CellEditor(p: CellEditorProps) {
  const [draft, setDraft] = useState(p.initial);
  const ref = useRef<HTMLInputElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus({ preventScroll: true });
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);
  return (
    <input ref={ref} className="gv-editor" dir="auto" value={draft} aria-label={p.label}
      style={{ top: p.top, insetInlineStart: p.start, inlineSize: p.w, blockSize: ROW_H }}
      onChange={(e) => setDraft(e.target.value)}
      onKeyDown={(e) => {
        e.stopPropagation(); // arrows, Home/End and letters belong to the text box, not the grid
        p.onKeyDown(e, draft);
      }}
      onBlur={() => p.onBlur(draft)} />
  );
}

interface CellViewProps {
  id: string;
  r: number;
  c: number;
  top: number;
  start: number;
  w: number;
  text: string;
  kind: string;
  loading: boolean;
  failed: boolean;
  selected: boolean;
  active: boolean;
}

const CellView = memo(function CellView(p: CellViewProps) {
  const cls =
    "gv-cell" +
    ` gv-${p.kind}` +
    (p.loading ? " gv-loading" : "") +
    (p.failed ? " gv-failed" : "") +
    (p.selected ? " gv-selected" : "") +
    (p.active ? " gv-active" : "");
  return (
    <div id={p.id} role="gridcell" aria-colindex={p.c + 1} aria-selected={p.selected || undefined}
      aria-busy={p.loading || undefined} className={cls}
      style={{ top: p.top, insetInlineStart: p.start, inlineSize: p.w, blockSize: ROW_H }}
      data-r={p.r} data-c={p.c}>
      {p.kind === "str" ? <bdi>{p.text}</bdi> : p.text}
    </div>
  );
});

export function Grid({
  source, rtl, cache: cacheProp, viewport, colWidth, onSelectionChange, label,
  onEdit, onClear, onUndo, onRedo, onPaste, onClipboardProblem,
}: GridProps) {
  const t = useT();
  const prefs = usePrefs();
  const scrollerRef = useRef<HTMLDivElement>(null);
  const bodyLayerRef = useRef<HTMLDivElement>(null);
  const rowHdrLayerRef = useRef<HTMLDivElement>(null);

  // data
  const cache = useMemo(() => cacheProp ?? new BlockCache(source), [cacheProp, source]);
  useEffect(() => () => (cacheProp ? undefined : cache.dispose()), [cache, cacheProp]);
  useSyncExternalStore(cache.subscribe, cache.getVersion);

  // geometry
  const rows = useMemo(() => uniformAxis(source.rowCount, ROW_H), [source.rowCount]);
  const cols: Axis = useMemo(
    () => variableAxis(source.colCount, colWidth ?? (() => COL_W)),
    [source.colCount, colWidth],
  );

  // viewport size (px of the scroller), scroll position
  const [size, setSize] = useState(viewport ?? { width: 800, height: 500 });
  const [scroll, setScroll] = useState({ top: 0, left: 0 });
  useLayoutEffect(() => {
    if (viewport) return;
    const el = scrollerRef.current;
    if (!el) return;
    const measure = () => setSize({ width: el.clientWidth, height: el.clientHeight });
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [viewport]);

  const bodyH = Math.max(0, size.height - HEADER_H);
  const bodyW = Math.max(0, size.width - HEADER_W);
  const scroller = useMemo(() => makeScroller(rows.total, bodyH), [rows.total, bodyH]);
  const contentTop = scroller.toContent(scroll.top);
  const contentLeft = Math.abs(scroll.left); // RTL scrollLeft is <= 0

  const rr = visibleRange(rows, contentTop, bodyH, ROW_OVERSCAN);
  const cr = visibleRange(cols, contentLeft, bodyW, COL_OVERSCAN);

  // ask the cache for what is on screen (+ one block of prefetch in each direction)
  useEffect(() => {
    if (rr.last < rr.first || cr.last < cr.first) return;
    cache.ensure(rr.first - 100, rr.last + 100, cr.first, cr.last);
  }, [cache, rr.first, rr.last, cr.first, cr.last]);

  // position the layers: in scaled mode this changes on EVERY scroll event; it is one style write
  const layerTop = scroll.top + rows.offset(rr.first) - contentTop;
  useLayoutEffect(() => {
    const px = `${layerTop}px`;
    if (bodyLayerRef.current) bodyLayerRef.current.style.top = px;
    if (rowHdrLayerRef.current) rowHdrLayerRef.current.style.top = px;
  });

  const onScroll = useCallback(() => {
    const el = scrollerRef.current;
    if (el) setScroll({ top: el.scrollTop, left: el.scrollLeft });
  }, []);

  // selection
  const [sel, setSel] = useState<Selection>(single({ r: 0, c: 0 }));
  const bounds = boundsOf(sel);
  const update = useCallback(
    (s: Selection) => {
      setSel(s);
      onSelectionChange?.(s);
    },
    [onSelectionChange],
  );

  const dims = { rowCount: source.rowCount, colCount: source.colCount, rtl,
    pageRows: Math.max(1, Math.floor(bodyH / ROW_H) - 1) };

  const scrollIntoView = useCallback(
    (p: Pos) => {
      const el = scrollerRef.current;
      if (!el) return;
      // vertical (through the scroll mapping)
      const rowTop = rows.offset(p.r);
      const rowBottom = rowTop + ROW_H;
      const curTop = scroller.toContent(el.scrollTop);
      if (rowTop < curTop) el.scrollTop = scroller.toScroll(rowTop);
      else if (rowBottom > curTop + bodyH) el.scrollTop = scroller.toScroll(rowBottom - bodyH);
      // horizontal
      const colStart = cols.offset(p.c);
      const colEnd = colStart + cols.size(p.c);
      const curLeft = Math.abs(el.scrollLeft);
      const sign = rtl ? -1 : 1;
      if (colStart < curLeft) el.scrollLeft = sign * colStart;
      else if (colEnd > curLeft + bodyW) el.scrollLeft = sign * (colEnd - bodyW);
    },
    [rows, cols, scroller, bodyH, bodyW, rtl],
  );

  // editing
  const [editing, setEditing] = useState<Editing | null>(null);
  const editingRef = useRef<Editing | null>(null);
  const [initial, setInitial] = useState(""); // text the editor opens with
  const editable = Boolean(onEdit);

  const startEdit = (p: Pos, typed?: string) => {
    if (!onEdit) return;
    const look = cache.getCell(p.r, p.c);
    // Keep the typed text if there is one; otherwise show the cell as it is, which needs it loaded.
    if (typed === undefined && look.status !== "loaded") return;
    const original = cellRaw(look.cell);
    scrollIntoView(p);
    const next = { r: p.r, c: p.c, original };
    editingRef.current = next; // the ref is what handlers read; the state only drives rendering
    setEditing(next);
    setInitial(typed ?? original);
  };

  /** Ends editing. `move` is the key that ended it (Enter/Tab move the cursor like a spreadsheet). */
  const finishEdit = (draft: string, commit: boolean, move?: { key: string; shift: boolean }) => {
    const cur = editingRef.current;
    if (!cur) return;
    editingRef.current = null; // a blur that follows must not commit twice
    setEditing(null);
    if (commit && draft !== cur.original) onEdit?.(cur.r, cur.c, draft);
    if (move) {
      const next = navigate(single({ r: cur.r, c: cur.c }), { key: move.key, shift: move.shift }, dims);
      if (next) {
        update(next);
        scrollIntoView(next.focus);
      }
      scrollerRef.current?.focus({ preventScroll: true });
    } else if (!commit) {
      scrollerRef.current?.focus({ preventScroll: true });
    }
  };

  const onEditorKey = (e: ReactKeyboardEvent<HTMLInputElement>, draft: string) => {
    if (e.nativeEvent.isComposing) return; // an IME candidate is being confirmed, not a command
    if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      finishEdit(draft, true, { key: e.key, shift: e.shiftKey });
    } else if (e.key === "Escape") {
      e.preventDefault();
      finishEdit(draft, false);
    }
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && (e.code === "KeyZ" || e.code === "KeyY")) {
      // by physical key, so it also works on a Persian keyboard layout
      const redo = e.code === "KeyY" || e.shiftKey;
      const fn = redo ? onRedo : onUndo;
      if (fn) {
        e.preventDefault();
        fn();
      }
      return;
    }
    if (editable) {
      if (e.key === "F2") {
        e.preventDefault();
        startEdit(sel.active);
        return;
      }
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        onClear?.(boundsOf(sel));
        return;
      }
      if (e.key.length === 1 && !mod && !e.altKey) {
        e.preventDefault();
        startEdit(sel.active, e.key); // typing replaces the content, like a spreadsheet
        return;
      }
    }
    const next = navigate(sel, { key: e.key, shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey }, dims);
    if (!next) return;
    e.preventDefault();
    update(next);
    scrollIntoView(next.focus);
  };

  // clipboard: events fire on the focused grid; while the cell editor is open they belong to its text box
  const inEditor = (e: ReactClipboardEvent<HTMLDivElement>) => e.target instanceof HTMLInputElement;
  const copySelection = (e: ReactClipboardEvent<HTMLDivElement>): boolean => {
    const res = toTsv(cache, bounds);
    if (!res.ok) {
      e.preventDefault();
      onClipboardProblem?.(res.reason);
      return false;
    }
    e.clipboardData.setData("text/plain", res.text);
    e.preventDefault();
    return true;
  };
  const onCopy = (e: ReactClipboardEvent<HTMLDivElement>) => {
    if (inEditor(e)) return;
    copySelection(e);
  };
  const onCut = (e: ReactClipboardEvent<HTMLDivElement>) => {
    if (inEditor(e) || !editable) return;
    // Cut copies and clears at once (undo brings the cells back); nothing is cleared if the copy failed
    if (copySelection(e)) onClear?.(bounds);
  };
  const onPasteEvent = (e: ReactClipboardEvent<HTMLDivElement>) => {
    if (inEditor(e) || !onPaste) return;
    e.preventDefault();
    const res = pasteEdits(e.clipboardData.getData("text/plain"), bounds);
    if (!res.ok) {
      if (res.reason === "tooLarge") onClipboardProblem?.("tooLarge");
      return;
    }
    const r = res.range;
    update({ active: { r: r.r0, c: r.c0 }, anchor: { r: r.r0, c: r.c0 }, focus: { r: r.r1, c: r.c1 } });
    onPaste(res.edits);
  };

  // pointer selection: cells carry their own coordinates (data-r / data-c)
  const onDoubleClick = (e: ReactMouseEvent<HTMLDivElement>) => {
    const target = (e.target as HTMLElement).closest<HTMLElement>("[data-r]");
    if (target) startEdit({ r: Number(target.dataset.r), c: Number(target.dataset.c) });
  };
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    const target = (e.target as HTMLElement).closest<HTMLElement>("[data-r]");
    if (!target) return;
    const p = { r: Number(target.dataset.r), c: Number(target.dataset.c) };
    scrollerRef.current?.focus({ preventScroll: true });
    if (e.shiftKey) update({ active: sel.active, anchor: sel.anchor, focus: p });
    else update(single(p));
  };
  const onPointerOver = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.buttons !== 1) return; // dragging with the primary button extends the range
    const target = (e.target as HTMLElement).closest<HTMLElement>("[data-r]");
    if (!target) return;
    update({ active: sel.active, anchor: sel.anchor,
      focus: { r: Number(target.dataset.r), c: Number(target.dataset.c) } });
  };

  const display: DisplayPrefs = {
    digits: prefs.digits, calendar: prefs.calendar, locale: prefs.locale,
    trueText: t("grid.true"), falseText: t("grid.false"),
  };

  // build the visible cells
  const cells = [];
  const rowHeaders = [];
  for (let r = rr.first; r <= rr.last; r++) {
    const top = rows.offset(r) - rows.offset(rr.first);
    rowHeaders.push(
      <div key={r} className={"gv-rowhdr-cell" + (r >= bounds.r0 && r <= bounds.r1 ? " gv-hdr-selected" : "")}
        style={{ top, blockSize: ROW_H }} aria-hidden="true">
        {r + 1}
      </div>,
    );
    const rowCells = [];
    for (let c = cr.first; c <= cr.last; c++) {
      const look = cache.getCell(r, c);
      const d = cellDisplay(look.cell, display);
      rowCells.push(
        <CellView key={c} id={`gv-${r}-${c}`} r={r} c={c} top={top}
          start={cols.offset(c) - cols.offset(cr.first)} w={cols.size(c)} text={d.text} kind={d.kind}
          loading={look.status === "loading" || look.status === "absent"} failed={look.status === "error"}
          selected={inRange(bounds, r, c)} active={sel.active.r === r && sel.active.c === c} />,
      );
    }
    cells.push(
      <div key={r} role="row" aria-rowindex={r + 2} style={{ display: "contents" }}>
        {rowCells}
      </div>,
    );
  }
  const colHeaders = [];
  for (let c = cr.first; c <= cr.last; c++) {
    colHeaders.push(
      <div key={c} className={"gv-colhdr-cell" + (c >= bounds.c0 && c <= bounds.c1 ? " gv-hdr-selected" : "")}
        style={{ insetInlineStart: cols.offset(c) - cols.offset(cr.first), inlineSize: cols.size(c), blockSize: HEADER_H }}
        role="columnheader" aria-colindex={c + 1} aria-label={t("grid.colHeader", { name: columnLetters(c) })}>
        <bdi dir="ltr">{columnLetters(c)}</bdi>
      </div>,
    );
  }

  const activeId = `gv-${sel.active.r}-${sel.active.c}`;
  const activeRendered = sel.active.r >= rr.first && sel.active.r <= rr.last &&
    sel.active.c >= cr.first && sel.active.c <= cr.last;

  return (
    <div ref={scrollerRef} className="gv-scroller" dir={rtl ? "rtl" : "ltr"} role="grid" tabIndex={0}
      aria-label={label ?? t("grid.label")} aria-rowcount={source.rowCount + 1} aria-colcount={source.colCount}
      aria-activedescendant={activeRendered ? activeId : undefined} aria-multiselectable="true"
      onScroll={onScroll} onKeyDown={onKeyDown} onDoubleClick={onDoubleClick}
      onCopy={onCopy} onCut={onCut} onPaste={onPasteEvent} onPointerDown={onPointerDown} onPointerOver={onPointerOver}
      data-rows={source.rowCount} data-scaled={scroller.scaled || undefined}>
      <div className="gv-content" style={{ inlineSize: HEADER_W + cols.total, blockSize: HEADER_H + scroller.proxyPx }}>
        <div className="gv-top" style={{ blockSize: HEADER_H }}>
          <div className="gv-corner" style={{ inlineSize: HEADER_W, blockSize: HEADER_H }} />
          <div className="gv-colhdr" style={{ inlineSize: cols.total, blockSize: HEADER_H }}>
            <div className="gv-layer" style={{ insetInlineStart: cols.offset(cr.first) }} role="row" aria-rowindex={1}>
              {colHeaders}
            </div>
          </div>
        </div>
        <div className="gv-main" style={{ blockSize: scroller.proxyPx }}>
          <div className="gv-rowhdr" style={{ inlineSize: HEADER_W, blockSize: scroller.proxyPx }}>
            <div ref={rowHdrLayerRef} className="gv-layer">{rowHeaders}</div>
          </div>
          <div className="gv-body" style={{ inlineSize: cols.total, blockSize: scroller.proxyPx }}>
            <div ref={bodyLayerRef} className="gv-layer" style={{ insetInlineStart: cols.offset(cr.first) }}>
              {cells}
              {editing && editing.r >= rr.first && editing.r <= rr.last && editing.c >= cr.first && editing.c <= cr.last ? (
                <CellEditor key={`${editing.r}:${editing.c}`} initial={initial} label={t("grid.cellEditor")}
                  top={rows.offset(editing.r) - rows.offset(rr.first)}
                  start={cols.offset(editing.c) - cols.offset(cr.first)} w={cols.size(editing.c)}
                  onKeyDown={onEditorKey}
                  onBlur={(draft) => finishEdit(draft, true)} />
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
