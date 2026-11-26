import type { Cell } from "@contracts";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { reloadPrefs, usePrefs } from "@/state/prefs";
import type { DataSource } from "./datasource";
import { Grid, HEADER_H, ROW_H } from "./Grid";

const VIEW = { width: 764, height: 528 }; // body = 700 x 500 -> about 19 rows x 6 columns

function source(rows: number, cols: number, over: Partial<DataSource> = {}) {
  const calls: { r0: number; c0: number; rows: number; cols: number; signal: AbortSignal }[] = [];
  const src: DataSource = {
    rowCount: rows,
    colCount: cols,
    async fetchBlock(r0, c0, nr, nc, signal) {
      calls.push({ r0, c0, rows: nr, cols: nc, signal });
      const out: Cell[] = [];
      for (let r = r0; r < r0 + nr; r++)
        for (let c = c0; c < c0 + nc; c++) out.push({ r, c, v: { k: "num", n: r * 1000 + c } });
      return out;
    },
    ...over,
  };
  return { src, calls };
}

const cellEls = () => Array.from(document.querySelectorAll<HTMLElement>("[role=gridcell]"));
const rowsRendered = () => new Set(cellEls().map((e) => Number(e.dataset.r)));
const scroller = () => screen.getByRole("grid");
function scrollTo(el: HTMLElement, top: number, left = 0) {
  act(() => {
    el.scrollTop = top;
    el.scrollLeft = left;
    fireEvent.scroll(el);
  });
}

describe("Grid rendering", () => {
  it("renders a bounded window of a 100,000-row sheet, not the sheet", async () => {
    usePrefs.setState({ digits: "latin" });
    const { src } = source(100_000, 20);
    render(<Grid source={src} rtl={false} viewport={VIEW} />);
    await waitFor(() => expect(screen.getByText("0")).toBeInTheDocument());
    expect(cellEls().length).toBeLessThan(600); // 19+8 rows x 6+2 columns, not 2,000,000
    expect(cellEls().length).toBeGreaterThan(50);
    expect(scroller()).toHaveAttribute("aria-rowcount", "100001");
    expect(scroller()).toHaveAttribute("aria-colcount", "20");
  });

  it("shows the typed values with the chosen digit set", async () => {
    const { src } = source(50, 5);
    usePrefs.setState({ digits: "persian" });
    render(<Grid source={src} rtl={true} viewport={VIEW} />);
    await waitFor(() => expect(cellEls().some((e) => e.textContent === "۱۰۰۰")).toBe(true)); // r=1,c=0
    reloadPrefs();
  });

  it("strings are wrapped for bidi isolation; numbers align to the logical end", async () => {
    const { src } = source(5, 2, {
      async fetchBlock() {
        return [{ r: 0, c: 0, v: { k: "str", s: "علی" } }, { r: 0, c: 1, v: { k: "num", n: 3 } }];
      },
    });
    render(<Grid source={src} rtl={true} viewport={VIEW} />);
    await waitFor(() => expect(screen.getByText("علی").tagName).toBe("BDI"));
    expect(cellEls().find((e) => e.dataset.c === "1")).toHaveClass("gv-num");
  });

  it("renders booleans, errors and dates by kind", async () => {
    usePrefs.setState({ digits: "latin", calendar: "gregorian", locale: "en" });
    const { src } = source(2, 3, {
      async fetchBlock() {
        return [
          { r: 0, c: 0, v: { k: "bool", b: true } },
          { r: 0, c: 1, v: { k: "err", e: "#DIV/0!" } },
          { r: 0, c: 2, v: { k: "date", iso: "2026-11-14T00:00:00Z" } },
        ];
      },
    });
    render(<Grid source={src} rtl={false} viewport={VIEW} />);
    await waitFor(() => expect(screen.getByText("#DIV/0!")).toHaveClass("gv-err"));
    expect(cellEls().find((e) => e.dataset.c === "2")?.textContent).toContain("2026");
    reloadPrefs();
  });

  it("marks cells of blocks that failed, and of blocks that are still loading", async () => {
    // 60 columns -> two column-blocks are in view: the first fails, the second never answers
    const { src } = source(300, 60, {
      fetchBlock: (_r0, c0) =>
        c0 === 0 ? Promise.reject(new Error("boom")) : new Promise(() => undefined),
    });
    render(<Grid source={src} rtl={false} viewport={{ width: 764 + 110 * 24, height: 528 }} />);
    await waitFor(() => expect(document.querySelector(".gv-failed")).not.toBeNull());
    expect(document.querySelector(".gv-loading")).not.toBeNull();
    const failed = document.querySelector<HTMLElement>(".gv-failed")!;
    const loading = document.querySelector<HTMLElement>(".gv-loading")!;
    expect(Number(failed.dataset.c)).toBeLessThan(26);
    expect(Number(loading.dataset.c)).toBeGreaterThanOrEqual(26);
    expect(loading).toHaveAttribute("aria-busy", "true");
  });

  it("column headers are letters (isolated LTR) and rows are numbered", async () => {
    const { src } = source(100, 30);
    render(<Grid source={src} rtl={true} viewport={VIEW} />);
    await waitFor(() => expect(cellEls().length).toBeGreaterThan(0));
    const heads = screen.getAllByRole("columnheader").slice(0, 3).map((h) => h.textContent);
    expect(heads).toEqual(["A", "B", "C"]);
  });
});

describe("Grid direction", () => {
  it("the sheet's own direction drives the grid, independent of the UI language", async () => {
    const { src } = source(10, 5);
    const { rerender } = render(<Grid source={src} rtl={true} viewport={VIEW} />);
    expect(scroller()).toHaveAttribute("dir", "rtl");
    rerender(<Grid source={src} rtl={false} viewport={VIEW} />);
    expect(scroller()).toHaveAttribute("dir", "ltr");
  });

  it("column A is laid out at the inline start (right edge when the sheet is RTL)", async () => {
    const { src } = source(10, 5);
    render(<Grid source={src} rtl={true} viewport={VIEW} />);
    await waitFor(() => expect(cellEls().length).toBeGreaterThan(0));
    const a1 = cellEls().find((e) => e.dataset.r === "0" && e.dataset.c === "0")!;
    const b1 = cellEls().find((e) => e.dataset.r === "0" && e.dataset.c === "1")!;
    // positions are logical (inset-inline-start): B starts one column width after A
    expect(a1.style.insetInlineStart).toBe("0px");
    expect(b1.style.insetInlineStart).toBe("110px");
  });
});

describe("Grid keyboard", () => {
  async function ready(rtl: boolean) {
    const { src } = source(1000, 10);
    const onSel = vi.fn();
    render(<Grid source={src} rtl={rtl} viewport={VIEW} onSelectionChange={onSel} />);
    await waitFor(() => expect(cellEls().length).toBeGreaterThan(0));
    scroller().focus();
    return { user: userEvent.setup(), onSel };
  }
  const active = () => document.querySelector<HTMLElement>(".gv-active")!;
  const pos = () => [active().dataset.r, active().dataset.c];

  it("starts on A1 and exposes the active cell for assistive technology", async () => {
    await ready(false);
    expect(pos()).toEqual(["0", "0"]);
    expect(scroller()).toHaveAttribute("aria-activedescendant", "gv-0-0");
  });

  it("LTR: ArrowRight goes to the next column, ArrowDown to the next row", async () => {
    const { user } = await ready(false);
    await user.keyboard("{ArrowRight}{ArrowDown}");
    expect(pos()).toEqual(["1", "1"]);
  });

  it("RTL: ArrowLeft goes to the NEXT column, ArrowRight to the previous", async () => {
    const { user } = await ready(true);
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(pos()).toEqual(["0", "2"]);
    await user.keyboard("{ArrowRight}");
    expect(pos()).toEqual(["0", "1"]);
  });

  it("Tab and Enter move through the sheet and are not left to the browser", async () => {
    const { user } = await ready(true);
    await user.keyboard("{Tab}");
    expect(pos()).toEqual(["0", "1"]);
    await user.keyboard("{Enter}");
    expect(pos()).toEqual(["1", "1"]);
  });

  it("Shift+arrows select a range; the callback reports it", async () => {
    const { user, onSel } = await ready(false);
    await user.keyboard("{Shift>}{ArrowDown}{ArrowRight}{/Shift}");
    expect(document.querySelectorAll(".gv-selected").length).toBeGreaterThanOrEqual(4);
    expect(onSel).toHaveBeenLastCalledWith(
      expect.objectContaining({ anchor: { r: 0, c: 0 }, focus: { r: 1, c: 1 } }),
    );
  });

  it("Ctrl+End jumps to the last cell and scrolls it into view", async () => {
    const { user } = await ready(false);
    await user.keyboard("{Control>}{End}{/Control}");
    expect(scroller().scrollTop).toBeGreaterThan(0);
    // jsdom does not fire scroll events by itself; a real browser does after scrollTop changes
    fireEvent.scroll(scroller());
    await waitFor(() => expect(pos()).toEqual(["999", "9"]));
    expect(rowsRendered().has(999)).toBe(true);
  });

  it("clicking a cell selects it; Shift+click extends", async () => {
    const { user } = await ready(false);
    const cell = (r: number, c: number) =>
      cellEls().find((e) => e.dataset.r === String(r) && e.dataset.c === String(c))!;
    await user.click(cell(3, 2));
    expect(pos()).toEqual(["3", "2"]);
    await user.keyboard("{Shift>}");
    await user.click(cell(5, 4));
    await user.keyboard("{/Shift}");
    expect(document.querySelectorAll(".gv-selected").length).toBe(9); // 3 x 3
  });
});

describe("Grid scrolling and fetching", () => {
  it("scrolling to row 50,000 renders and fetches that region, and cancels what is no longer needed", async () => {
    const { src, calls } = source(100_000, 20);
    render(<Grid source={src} rtl={false} viewport={VIEW} />);
    await waitFor(() => expect(cellEls().length).toBeGreaterThan(0));
    const first = calls[0]!;
    scrollTo(scroller(), ROW_H * 50_000);
    await waitFor(() => expect(rowsRendered().has(50_000)).toBe(true));
    expect(Math.min(...rowsRendered())).toBeGreaterThan(49_900);
    expect(calls.some((c) => c.r0 === 50_000 || c.r0 === 49_900)).toBe(true);
    expect(cellEls().length).toBeLessThan(600);
    void first;
  });

  it("never asks for more than the window cap in one request", async () => {
    const { src, calls } = source(100_000, 200);
    render(<Grid source={src} rtl={false} viewport={VIEW} />);
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    for (const c of calls) {
      expect(c.rows).toBeLessThanOrEqual(1000);
      expect(c.cols).toBeLessThanOrEqual(100);
    }
  });

  it("an Excel-sized sheet (1,048,576 rows) uses scaled scrolling and still reaches the last row", async () => {
    const rows = 1_048_576;
    const { src } = source(rows, 3);
    render(<Grid source={src} rtl={false} viewport={VIEW} />);
    await waitFor(() => expect(cellEls().length).toBeGreaterThan(0));
    expect(scroller()).toHaveAttribute("data-scaled", "true");
    expect(scroller().firstElementChild).toHaveStyle({ blockSize: `${HEADER_H + 10_000_000}px` });
    const max = 10_000_000 - (VIEW.height - HEADER_H);
    scrollTo(scroller(), max);
    await waitFor(() => expect(rowsRendered().has(rows - 1)).toBe(true));
    expect(cellEls().length).toBeLessThan(600);
  });

  it("a normal sheet is not scaled", async () => {
    const { src } = source(100_000, 3);
    render(<Grid source={src} rtl={false} viewport={VIEW} />);
    expect(scroller()).not.toHaveAttribute("data-scaled");
  });

  it("RTL scrolling uses a negative scrollLeft and still renders the right columns", async () => {
    const { src } = source(100, 200);
    render(<Grid source={src} rtl={true} viewport={VIEW} />);
    await waitFor(() => expect(cellEls().length).toBeGreaterThan(0));
    scrollTo(scroller(), 0, -110 * 100);
    await waitFor(() => expect(cellEls().some((e) => e.dataset.c === "100")).toBe(true));
    expect(cellEls().some((e) => e.dataset.c === "0")).toBe(false);
  });
});

describe("Grid editing", () => {
  async function setup(rtl = false) {
    usePrefs.setState({ digits: "latin" });
    const { src } = source(50, 5);
    const onEdit = vi.fn();
    const onClear = vi.fn();
    const onUndo = vi.fn();
    const onRedo = vi.fn();
    const onSel = vi.fn();
    render(<Grid source={src} rtl={rtl} viewport={VIEW} onEdit={onEdit} onClear={onClear} onUndo={onUndo}
      onRedo={onRedo} onSelectionChange={onSel} />);
    await waitFor(() => expect(screen.getByText("1001")).toBeInTheDocument()); // loaded
    const user = userEvent.setup();
    act(() => scroller().focus());
    return { user, onEdit, onClear, onUndo, onRedo, onSel };
  }
  const editor = () => screen.queryByRole("textbox");

  it("typing starts an edit that replaces the content; Enter saves and moves down", async () => {
    const { user, onEdit, onSel } = await setup();
    await user.keyboard("hi");
    expect(editor()).toHaveValue("hi");
    await user.keyboard("{Enter}");
    expect(onEdit).toHaveBeenCalledExactlyOnceWith(0, 0, "hi");
    expect(editor()).toBeNull();
    expect(onSel).toHaveBeenLastCalledWith(expect.objectContaining({ active: { r: 1, c: 0 } }));
    expect(scroller()).toHaveFocus();
  });

  it("Tab saves and moves to the next column", async () => {
    const { user, onEdit, onSel } = await setup();
    await user.keyboard("5{Tab}");
    expect(onEdit).toHaveBeenCalledWith(0, 0, "5");
    expect(onSel).toHaveBeenLastCalledWith(expect.objectContaining({ active: { r: 0, c: 1 } }));
  });

  it("Escape throws the edit away", async () => {
    const { user, onEdit } = await setup();
    await user.keyboard("oops{Escape}");
    expect(onEdit).not.toHaveBeenCalled();
    expect(editor()).toBeNull();
    expect(scroller()).toHaveFocus();
  });

  it("F2 opens the cell as it is, and leaving it unchanged sends nothing", async () => {
    const { user, onEdit } = await setup();
    await user.keyboard("{F2}");
    expect(editor()).toHaveValue("0");
    await user.keyboard("{Enter}");
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("F2 then typing appends to the content", async () => {
    const { user, onEdit } = await setup();
    await user.keyboard("{F2}9{Enter}");
    expect(onEdit).toHaveBeenCalledWith(0, 0, "09");
  });

  it("double click edits that cell", async () => {
    const { user, onEdit } = await setup();
    await user.dblClick(document.getElementById("gv-1-1")!);
    expect(editor()).toHaveValue("1001");
    await user.keyboard("7{Enter}");
    expect(onEdit).toHaveBeenCalledWith(1, 1, "10017");
  });

  it("clicking another cell saves the edit exactly once", async () => {
    const { user, onEdit } = await setup();
    await user.keyboard("abc");
    await user.click(document.getElementById("gv-2-2")!);
    expect(onEdit).toHaveBeenCalledExactlyOnceWith(0, 0, "abc");
    expect(editor()).toBeNull();
  });

  it("arrow keys inside the editor move the caret, not the selection", async () => {
    const { user, onSel } = await setup();
    await user.keyboard("ab{ArrowLeft}{ArrowDown}");
    expect(editor()).toBeInTheDocument();
    expect(onSel).not.toHaveBeenCalled();
  });

  it("Persian text can be typed as the first character", async () => {
    const { user, onEdit } = await setup(true);
    await user.keyboard("سلام{Enter}");
    expect(onEdit).toHaveBeenCalledWith(0, 0, "سلام");
  });

  it("Delete clears the whole selected range", async () => {
    const { user, onClear } = await setup();
    await user.keyboard("{Shift>}{ArrowDown}{ArrowRight}{/Shift}{Delete}");
    expect(onClear).toHaveBeenCalledWith({ r0: 0, r1: 1, c0: 0, c1: 1 });
  });

  it("Ctrl+Z undoes, Ctrl+Y and Ctrl+Shift+Z redo", async () => {
    const { user, onUndo, onRedo } = await setup();
    await user.keyboard("{Control>}z{/Control}");
    expect(onUndo).toHaveBeenCalledTimes(1);
    await user.keyboard("{Control>}y{/Control}");
    await user.keyboard("{Control>}{Shift>}z{/Shift}{/Control}");
    expect(onRedo).toHaveBeenCalledTimes(2);
  });

  it("is read-only without onEdit: typing and Delete do nothing", async () => {
    usePrefs.setState({ digits: "latin" });
    const { src } = source(50, 5);
    render(<Grid source={src} rtl={false} viewport={VIEW} />);
    await waitFor(() => expect(screen.getByText("1001")).toBeInTheDocument());
    act(() => scroller().focus());
    await userEvent.setup().keyboard("x{Delete}");
    expect(editor()).toBeNull();
  });
});

describe("Grid clipboard", () => {
  async function setup(over: Partial<DataSource> = {}) {
    usePrefs.setState({ digits: "latin" });
    const { src } = source(50, 5, over);
    const onPaste = vi.fn();
    const onClear = vi.fn();
    const onEdit = vi.fn();
    const onProblem = vi.fn();
    render(<Grid source={src} rtl={false} viewport={VIEW} onEdit={onEdit} onClear={onClear} onPaste={onPaste}
      onClipboardProblem={onProblem} />);
    await waitFor(() => expect(screen.getByText("1001")).toBeInTheDocument());
    act(() => scroller().focus());
    return { user: userEvent.setup(), onPaste, onClear, onEdit, onProblem };
  }
  const clip = (text = "") => {
    const data: Record<string, string> = { "text/plain": text };
    return { clipboardData: { setData: (k: string, v: string) => (data[k] = v), getData: (k: string) => data[k] ?? "" }, data };
  };

  it("copy puts the selected values on the clipboard as tab-separated text", async () => {
    const { user } = await setup();
    await user.keyboard("{Shift>}{ArrowDown}{ArrowRight}{/Shift}");
    const c = clip();
    fireEvent.copy(scroller(), { clipboardData: c.clipboardData });
    expect(c.data["text/plain"]).toBe("0\t1\n1000\t1001");
  });

  it("cut copies, then clears the range", async () => {
    const { user, onClear } = await setup();
    await user.keyboard("{Shift>}{ArrowRight}{/Shift}");
    const c = clip();
    fireEvent.cut(scroller(), { clipboardData: c.clipboardData });
    expect(c.data["text/plain"]).toBe("0\t1");
    expect(onClear).toHaveBeenCalledWith({ r0: 0, r1: 0, c0: 0, c1: 1 });
  });

  it("paste sends one change for all cells and selects what was pasted", async () => {
    const { user, onPaste } = await setup();
    await user.keyboard("{ArrowDown}");
    fireEvent.paste(scroller(), { clipboardData: clip("1\t2\n3\t4").clipboardData });
    expect(onPaste).toHaveBeenCalledTimes(1);
    expect(onPaste.mock.calls[0]![0]).toEqual([
      { r: 1, c: 0, value: { k: "num", n: 1 } }, { r: 1, c: 1, value: { k: "num", n: 2 } },
      { r: 2, c: 0, value: { k: "num", n: 3 } }, { r: 2, c: 1, value: { k: "num", n: 4 } },
    ]);
    expect(document.querySelectorAll(".gv-selected, .gv-active").length).toBe(4);
  });

  it("while the cell editor is open, paste and copy are the text box's own", async () => {
    const { user, onPaste } = await setup();
    await user.keyboard("a");
    const c = clip("1\t2");
    fireEvent.paste(screen.getByRole("textbox"), { clipboardData: c.clipboardData });
    expect(onPaste).not.toHaveBeenCalled();
  });

  it("copying cells that are not loaded says so and copies nothing", async () => {
    usePrefs.setState({ digits: "latin" });
    const { src } = source(5000, 5);
    const onProblem = vi.fn();
    render(<Grid source={src} rtl={false} viewport={VIEW} onEdit={vi.fn()} onClipboardProblem={onProblem} />);
    await waitFor(() => expect(screen.getByText("1001")).toBeInTheDocument());
    act(() => scroller().focus());
    const c = clip();
    // select from A1 to the last row at once: the far blocks were never asked for
    fireEvent.keyDown(scroller(), { key: "End", ctrlKey: true, shiftKey: true });
    fireEvent.copy(scroller(), { clipboardData: c.clipboardData });
    expect(onProblem).toHaveBeenCalledWith("notLoaded");
    expect(c.data["text/plain"]).toBe("");
  });
});

describe("Grid column resize", () => {
  const widthOf = (c: number) => Number(document.querySelector<HTMLElement>(`[role=columnheader][aria-colindex="${c + 1}"]`)?.style.inlineSize.replace("px", ""));

  it("dragging a column border changes that column's width; a double click restores it", async () => {
    const { src } = source(50, 5);
    render(<Grid source={src} rtl={false} viewport={VIEW} />);
    await waitFor(() => expect(cellEls().length).toBeGreaterThan(0));
    const before = widthOf(1);
    const grip = document.querySelector<HTMLElement>('[data-grip="1"]')!;
    fireEvent.pointerDown(grip, { clientX: 200 });
    fireEvent.pointerMove(window, { clientX: 260 });
    fireEvent.pointerUp(window);
    await waitFor(() => expect(widthOf(1)).toBe(before + 60));
    expect(widthOf(0)).toBe(before);
    fireEvent.doubleClick(grip);
    await waitFor(() => expect(widthOf(1)).toBe(before));
  });
});

describe("Grid frozen panes", () => {
  it("keeps the frozen rows and columns rendered while the body scrolls", async () => {
    usePrefs.setState({ digits: "latin" });
    const { src } = source(10_000, 20);
    render(<Grid source={src} rtl={false} viewport={VIEW} frozen={{ rows: 2, cols: 1 }} />);
    await waitFor(() => expect(cellEls().length).toBeGreaterThan(20));
    scrollTo(scroller(), 5000, 300);
    await waitFor(() => expect(rowsRendered().has(200)).toBe(true));
    const rs = rowsRendered();
    expect(rs.has(0) && rs.has(1)).toBe(true);
    const cs = new Set(cellEls().map((e) => Number(e.dataset.c)));
    expect(cs.has(0)).toBe(true);
  });
});

describe("Grid header selection", () => {
  it("clicking a column header selects the whole column; a row number selects the whole row", async () => {
    const { src } = source(50, 5);
    const seen: { active: { r: number; c: number }; anchor: { r: number; c: number }; focus: { r: number; c: number } }[] = [];
    render(<Grid source={src} rtl={false} viewport={VIEW} onSelectionChange={(s) => seen.push(s)} />);
    await waitFor(() => expect(cellEls().length).toBeGreaterThan(0));
    fireEvent.pointerDown(document.querySelector('[data-hdr-c="2"]')!);
    expect(seen.at(-1)).toMatchObject({ anchor: { r: 0, c: 2 }, focus: { r: 49, c: 2 } });
    fireEvent.pointerDown(document.querySelector('[data-hdr-r="3"]')!);
    expect(seen.at(-1)).toMatchObject({ anchor: { r: 3, c: 0 }, focus: { r: 3, c: 4 } });
  });
});
