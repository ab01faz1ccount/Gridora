import type { Cell } from "@contracts";
import { describe, expect, it, vi } from "vitest";
import { BlockCache, BLOCK_COLS, BLOCK_ROWS } from "./block-cache";
import type { DataSource } from "./datasource";

interface Pending {
  r0: number; c0: number; rows: number; cols: number; signal: AbortSignal;
  resolve: (c: Cell[]) => void; reject: (e: unknown) => void;
}

function fakeSource(rowCount = 100_000, colCount = 52) {
  const pending: Pending[] = [];
  const src: DataSource = {
    rowCount, colCount,
    fetchBlock: (r0, c0, rows, cols, signal) =>
      new Promise<Cell[]>((resolve, reject) => {
        const p: Pending = { r0, c0, rows, cols, signal, resolve, reject };
        pending.push(p);
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      }),
  };
  const answer = (p: Pending) =>
    p.resolve([{ r: p.r0, c: p.c0, v: { k: "num", n: p.r0 * 1000 + p.c0 } }]);
  return { src, pending, answer };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

describe("BlockCache", () => {
  it("requests only the blocks that intersect the range, with the right window", async () => {
    const { src, pending } = fakeSource();
    const c = new BlockCache(src, { maxInFlight: 100 });
    c.ensure(0, 150, 0, 30); // rows 0-150 -> blocks 0,1 ; cols 0-30 -> blocks 0,1
    expect(pending.length).toBe(4);
    expect(pending.map((p) => [p.r0, p.c0]).sort()).toEqual([[0, 0], [0, 26], [100, 0], [100, 26]]);
    expect(pending[0]).toMatchObject({ rows: BLOCK_ROWS, cols: BLOCK_COLS });
  });

  it("clips the last blocks to the real sheet size", () => {
    const { src, pending } = fakeSource(250, 30);
    const c = new BlockCache(src, { maxInFlight: 100 });
    c.ensure(200, 249, 26, 29);
    expect(pending).toHaveLength(1);
    expect(pending[0]).toMatchObject({ r0: 200, c0: 26, rows: 50, cols: 4 });
  });

  it("never asks twice for a block (de-duplicates) and serves loaded cells", async () => {
    const { src, pending, answer } = fakeSource();
    const c = new BlockCache(src);
    c.ensure(0, 50, 0, 10);
    c.ensure(0, 50, 0, 10);
    expect(pending).toHaveLength(1);
    expect(c.getCell(0, 0).status).toBe("loading");
    answer(pending[0]!);
    await tick();
    expect(c.getCell(0, 0)).toMatchObject({ status: "loaded", cell: { v: { k: "num", n: 0 } } });
    expect(c.getCell(5, 5)).toMatchObject({ status: "loaded", cell: undefined }); // empty cell
    c.ensure(0, 50, 0, 10);
    expect(pending).toHaveLength(1); // still cached
    expect(c.getCell(5000, 0).status).toBe("absent");
  });

  it("limits concurrency and requests the nearest blocks first", () => {
    const { src, pending } = fakeSource();
    const c = new BlockCache(src, { maxInFlight: 2 });
    c.ensure(0, 499, 0, 25); // 5 row-blocks
    expect(pending).toHaveLength(2);
    // 5 blocks (0..4): the center block 2 goes first, then one of its neighbours (distance 1)
    expect(pending[0]!.r0).toBe(200);
    expect([100, 300]).toContain(pending[1]!.r0);
    expect(pending.map((p) => p.r0)).not.toContain(0);
    expect(pending.map((p) => p.r0)).not.toContain(400);
  });

  it("starts the next request when one finishes", async () => {
    const { src, pending, answer } = fakeSource();
    const c = new BlockCache(src, { maxInFlight: 1 });
    c.ensure(0, 199, 0, 25);
    expect(pending).toHaveLength(1);
    answer(pending[0]!);
    await tick();
    expect(pending).toHaveLength(2);
  });

  it("cancels in-flight loads that scrolled out of view", async () => {
    const { src, pending } = fakeSource();
    const c = new BlockCache(src, { maxInFlight: 100 });
    c.ensure(0, 99, 0, 25);
    const first = pending[0]!;
    c.ensure(50_000, 50_099, 0, 25); // jumped far away
    expect(first.signal.aborted).toBe(true);
    expect(c.stats.aborted).toBe(1);
    expect(c.getCell(0, 0).status).toBe("absent"); // an aborted block is not left as 'loading'
    await tick();
    expect(c.stats.failed).toBe(0); // an abort is not an error
  });

  it("keeps a block that is still needed when the range moves a little", () => {
    const { src, pending } = fakeSource();
    const c = new BlockCache(src, { maxInFlight: 100 });
    c.ensure(0, 99, 0, 25);
    c.ensure(50, 149, 0, 25); // blocks 0 and 1; block 0 stays in flight
    expect(pending).toHaveLength(2);
    expect(pending[0]!.signal.aborted).toBe(false);
  });

  it("marks a failed block, then retries it only after the delay", async () => {
    let now = 0;
    const { src, pending } = fakeSource();
    const c = new BlockCache(src, { retryAfterMs: 3000, now: () => now });
    c.ensure(0, 99, 0, 25);
    pending[0]!.reject(new Error("boom"));
    await tick();
    expect(c.getCell(0, 0).status).toBe("error");
    expect(c.stats.failed).toBe(1);
    c.ensure(0, 99, 0, 25);
    expect(pending).toHaveLength(1); // too early
    now = 3500;
    c.ensure(0, 99, 0, 25);
    expect(pending).toHaveLength(2); // retried
  });

  it("evicts least-recently-used blocks beyond the cap, never the ones in view", async () => {
    const { src, pending, answer } = fakeSource();
    const c = new BlockCache(src, { maxBlocks: 3, maxInFlight: 100 });
    for (let b = 0; b < 6; b++) {
      c.ensure(b * 100, b * 100 + 99, 0, 25);
      answer(pending[b]!);
      await tick();
    }
    expect(c.size).toBeLessThanOrEqual(3);
    expect(c.getCell(500, 0).status).toBe("loaded"); // the newest, in view, is kept
    expect(c.getCell(0, 0).status).toBe("absent"); // the oldest was evicted
    expect(c.stats.evicted).toBeGreaterThanOrEqual(3);
  });

  it("notifies subscribers when data changes (useSyncExternalStore)", async () => {
    const { src, pending, answer } = fakeSource();
    const c = new BlockCache(src);
    const fn = vi.fn();
    c.subscribe(fn);
    const v0 = c.getVersion();
    c.ensure(0, 99, 0, 25);
    answer(pending[0]!);
    await tick();
    expect(fn).toHaveBeenCalled();
    expect(c.getVersion()).toBeGreaterThan(v0);
  });

  it("patch() updates loaded cells only", async () => {
    const { src, pending, answer } = fakeSource();
    const c = new BlockCache(src);
    c.ensure(0, 99, 0, 25);
    answer(pending[0]!);
    await tick();
    c.patch([{ r: 3, c: 3, v: { k: "str", s: "x" } }, { r: 5000, c: 0, v: { k: "num", n: 1 } }]);
    expect(c.getCell(3, 3).cell?.v).toEqual({ k: "str", s: "x" });
    expect(c.getCell(5000, 0).status).toBe("absent");
    c.patch([{ r: 3, c: 3 }]); // an emptied cell
    expect(c.getCell(3, 3).cell).toBeUndefined();
  });

  it("invalidate() drops everything and aborts loads", () => {
    const { src, pending } = fakeSource();
    const c = new BlockCache(src);
    c.ensure(0, 99, 0, 25);
    c.invalidate();
    expect(pending[0]!.signal.aborted).toBe(true);
    expect(c.size).toBe(0);
  });

  it("ignores a late answer for a block that was cancelled", async () => {
    const { src, pending, answer } = fakeSource();
    const c = new BlockCache(src, { maxInFlight: 100 });
    c.ensure(0, 99, 0, 25);
    const first = pending[0]!;
    c.ensure(9000, 9099, 0, 25);
    answer(first); // resolves after the abort was requested
    await tick();
    expect(c.getCell(0, 0).status).toBe("absent");
  });
});

describe("BlockCache: changes from the server", () => {
  it("a change that arrives while a block is loading is applied when the block arrives", async () => {
    const { src, pending } = fakeSource();
    const c = new BlockCache(src);
    c.ensure(0, 5, 0, 5);
    c.patch([{ r: 2, c: 2, v: { k: "num", n: 42 } }]); // the response below was computed before this
    pending[0]!.resolve([{ r: 2, c: 2, v: { k: "num", n: 1 } }]);
    await tick();
    expect(c.getCell(2, 2).cell?.v).toEqual({ k: "num", n: 42 });
  });

  it("a cleared cell (no value, no formula) becomes empty", async () => {
    const { src, pending } = fakeSource();
    const c = new BlockCache(src);
    c.ensure(0, 5, 0, 5);
    pending[0]!.resolve([{ r: 1, c: 1, v: { k: "num", n: 7 } }]);
    await tick();
    c.patch([{ r: 1, c: 1 }]);
    expect(c.getCell(1, 1)).toEqual({ status: "loaded", cell: undefined });
  });

  it("patching notifies subscribers once per call, and not when nothing was cached", async () => {
    const { src, pending } = fakeSource();
    const c = new BlockCache(src);
    const fn = vi.fn();
    c.subscribe(fn);
    c.patch([{ r: 0, c: 0, v: { k: "num", n: 1 } }]); // nothing loaded
    expect(fn).not.toHaveBeenCalled();
    c.ensure(0, 5, 0, 5);
    pending[0]!.resolve([]);
    await tick();
    fn.mockClear();
    c.patch([{ r: 0, c: 0, v: { k: "num", n: 1 } }, { r: 1, c: 0, v: { k: "num", n: 2 } }]);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("setSource keeps loaded blocks and uses the new size for later requests", async () => {
    const { src, pending } = fakeSource(100, 10);
    const c = new BlockCache(src);
    c.ensure(0, 5, 0, 5);
    pending[0]!.resolve([{ r: 0, c: 0, v: { k: "num", n: 9 } }]);
    await tick();
    c.setSource({ ...src, rowCount: 250 });
    expect(c.getCell(0, 0).cell?.v).toEqual({ k: "num", n: 9 });
    c.ensure(200, 210, 0, 5);
    expect(pending.at(-1)).toMatchObject({ r0: 200, rows: 50 });
  });

  it("refresh drops everything and asks again for what was last on screen", async () => {
    const { src, pending } = fakeSource();
    const c = new BlockCache(src);
    c.ensure(0, 5, 0, 5);
    pending[0]!.resolve([{ r: 0, c: 0, v: { k: "num", n: 1 } }]);
    await tick();
    const before = pending.length;
    c.refresh();
    expect(c.getCell(0, 0).status).toBe("loading");
    expect(pending.length).toBe(before + 1);
  });
});
