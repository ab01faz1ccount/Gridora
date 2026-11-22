import type { Cell, CellsChangedResult, HistoryEntry } from "@contracts";
import { describe, expect, it, vi } from "vitest";
import { err, mockApi, ok, type Call } from "@/test/mockApi";
import { WorkbookEditor } from "./editing";
import type { DataSource } from "./datasource";

const entry = (seq: number, undone = false, kind = "cell_patch"): HistoryEntry =>
  ({ id: `h${seq}`, document_id: "w1", seq, operation: { type: "set_cells" }, delta: { kind, sheet_id: "s1", before: [], after: [] },
    label: "", created_at: "", undone }) as unknown as HistoryEntry;

const result = (seq: number, cells: Cell[], extra: Partial<CellsChangedResult> = {}, undone = false): CellsChangedResult =>
  ({ history_entry: entry(seq, undone), sheet_id: "s1", cells, ...extra });

const num = (r: number, c: number, n: number): Cell => ({ r, c, v: { k: "num", n } });
const source: DataSource = { rowCount: 100, colCount: 10, fetchBlock: async () => [] };

const HISTORY = "GET /documents/w1/history?limit=100";
const PATCH = "PATCH /workbooks/w1/sheets/s1/cells";

describe("WorkbookEditor", () => {
  it("sends base_seq = newest applied entry and applies cells and others to their sheets' caches", async () => {
    const api = mockApi({
      [HISTORY]: () => ok([entry(3), entry(2), entry(1)]),
      [PATCH]: () => ok(result(4, [num(0, 0, 5)], { others: [{ sheet_id: "s2", cells: [num(1, 1, 9)] }] })),
    });
    const ed = new WorkbookEditor("w1");
    const c1 = ed.caches.get("s1", source);
    const c2 = ed.caches.get("s2", source);
    const p1 = vi.spyOn(c1, "patch");
    const p2 = vi.spyOn(c2, "patch");
    await ed.edit("s1", [{ r: 0, c: 0, value: { k: "num", n: 5 } }]);
    expect((api.calls.find((c) => c.method === "PATCH")!.body as { base_seq: number }).base_seq).toBe(3);
    expect(p1).toHaveBeenCalledWith([num(0, 0, 5)]);
    expect(p2).toHaveBeenCalledWith([num(1, 1, 9)]);
    expect(ed.getSnapshot()).toMatchObject({ canUndo: true, canRedo: false, pending: 0 });
  });

  it("starts undo/redo from the real history: undone entries can be redone", async () => {
    mockApi({ [HISTORY]: () => ok([entry(3, true), entry(2, true), entry(1)]) });
    const ed = new WorkbookEditor("w1");
    await ed.load();
    expect(ed.getSnapshot()).toMatchObject({ canUndo: true, canRedo: true });
  });

  it("an empty history can neither undo nor redo, and undo then does not call the server", async () => {
    const api = mockApi({ [HISTORY]: () => ok([]) });
    const ed = new WorkbookEditor("w1");
    await ed.undo();
    expect(api.calls.map((c) => c.method + " " + c.path)).toEqual([HISTORY.slice(4)].map((p) => "GET " + p));
    expect(ed.getSnapshot()).toMatchObject({ canUndo: false, canRedo: false });
  });

  it("undo and redo move the head, pass base_seq, and apply the returned cells", async () => {
    const api = mockApi({
      [HISTORY]: () => ok([entry(2), entry(1)]),
      "POST /documents/w1/undo?base_seq=2": () => ok(result(2, [num(0, 0, 1)], {}, true)),
      "POST /documents/w1/redo?base_seq=1": () => ok(result(2, [num(0, 0, 5)])),
    });
    const ed = new WorkbookEditor("w1");
    const cache = ed.caches.get("s1", source);
    const patch = vi.spyOn(cache, "patch");
    await ed.undo();
    expect(ed.getSnapshot()).toMatchObject({ canUndo: true, canRedo: true });
    await ed.redo();
    expect(ed.getSnapshot()).toMatchObject({ canUndo: true, canRedo: false });
    expect(patch.mock.calls.map((c) => c[0])).toEqual([[num(0, 0, 1)], [num(0, 0, 5)]]);
    expect(api.calls.filter((c) => c.method === "POST")).toHaveLength(2);
  });

  it("a new edit after an undo ends redo", async () => {
    mockApi({
      [HISTORY]: () => ok([entry(2, true), entry(1)]),
      [PATCH]: () => ok(result(3, [])),
    });
    const ed = new WorkbookEditor("w1");
    await ed.edit("s1", [{ r: 0, c: 0 }]);
    expect(ed.getSnapshot()).toMatchObject({ canUndo: true, canRedo: false });
  });

  it("requests run one at a time, each with the previous one's seq", async () => {
    let seq = 1;
    const seen: number[] = [];
    mockApi({
      [HISTORY]: () => ok([entry(1)]),
      [PATCH]: (call: Call) => {
        seen.push((call.body as { base_seq: number }).base_seq);
        return ok(result(++seq, []));
      },
    });
    const ed = new WorkbookEditor("w1");
    await Promise.all([
      ed.edit("s1", [{ r: 0, c: 0 }]),
      ed.edit("s1", [{ r: 1, c: 0 }]),
      ed.edit("s1", [{ r: 2, c: 0 }]),
    ]);
    expect(seen).toEqual([1, 2, 3]);
  });

  it("a failed edit rejects, keeps the queue alive and sets the failed flag until something works", async () => {
    let fail = true;
    mockApi({
      [HISTORY]: () => ok([]),
      [PATCH]: () => (fail ? err(422, "validation_failed") : ok(result(1, []))),
    });
    const ed = new WorkbookEditor("w1");
    await expect(ed.edit("s1", [{ r: 0, c: 0 }])).rejects.toMatchObject({ code: "validation_failed" });
    expect(ed.getSnapshot().failed).toBe(true);
    fail = false;
    await ed.edit("s1", [{ r: 0, c: 0 }]);
    expect(ed.getSnapshot()).toMatchObject({ failed: false, canUndo: true });
  });

  it("on a version conflict it reloads the history and the caches", async () => {
    let heads = [entry(1)];
    const api = mockApi({
      [HISTORY]: () => ok(heads),
      [PATCH]: () => err(409, "version_conflict"),
    });
    const ed = new WorkbookEditor("w1");
    const refresh = vi.spyOn(ed.caches.get("s1", source), "refresh");
    await ed.load();
    heads = [entry(5), entry(1)]; // someone else changed the document
    await expect(ed.edit("s1", [{ r: 0, c: 0 }])).rejects.toMatchObject({ status: 409 });
    expect(refresh).toHaveBeenCalled();
    expect(api.calls.filter((c) => c.path === HISTORY.slice(4))).toHaveLength(2);
  });

  it("undoing something that is not a plain cell change refreshes every cache", async () => {
    mockApi({
      [HISTORY]: () => ok([entry(1)]),
      "POST /documents/w1/undo?base_seq=1": () => ({ body: { data: { ...result(1, []), history_entry: entry(1, true, "table_version") }, meta: { request_id: "r" } } }),
    });
    const ed = new WorkbookEditor("w1");
    const refresh = vi.spyOn(ed.caches.get("s1", source), "refresh");
    await ed.undo();
    expect(refresh).toHaveBeenCalled();
  });

  it("clear sends one edit per cell of the range, and refuses a range the API would refuse", async () => {
    const api = mockApi({ [HISTORY]: () => ok([]), [PATCH]: () => ok(result(1, [])) });
    const ed = new WorkbookEditor("w1");
    await ed.clear("s1", { r0: 1, r1: 2, c0: 0, c1: 1 });
    const body = api.calls.find((c) => c.method === "PATCH")!.body as { edits: unknown[] };
    expect(body.edits).toEqual([{ r: 1, c: 0 }, { r: 1, c: 1 }, { r: 2, c: 0 }, { r: 2, c: 1 }]);
    await expect(ed.clear("s1", { r0: 0, r1: 99_999, c0: 0, c1: 0 })).rejects.toBeInstanceOf(RangeError);
  });

  it("calls onChanged after every successful change only", async () => {
    mockApi({ [HISTORY]: () => ok([]), [PATCH]: () => ok(result(1, [])) });
    const onChanged = vi.fn();
    const ed = new WorkbookEditor("w1", onChanged);
    await ed.edit("s1", [{ r: 0, c: 0 }]);
    expect(onChanged).toHaveBeenCalledTimes(1);
  });
});
