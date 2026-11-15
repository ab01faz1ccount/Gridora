// Fixed-size blocks of cells, fetched on demand: de-duplicated, prioritized by distance from the
// viewport, limited in concurrency, cancelled when scrolled away, LRU-bounded.
import type { Cell } from "@contracts";
import type { DataSource } from "./datasource";

export const BLOCK_ROWS = 100;
export const BLOCK_COLS = 26;

export type BlockStatus = "loading" | "loaded" | "error";
interface Block {
  status: BlockStatus;
  cells: (Cell | undefined)[]; // BLOCK_ROWS * BLOCK_COLS, row-major
  abort?: AbortController;
  failedAt?: number;
}

export interface CellLookup {
  status: BlockStatus | "absent";
  cell: Cell | undefined;
}

export interface BlockCacheOptions {
  maxBlocks?: number;
  maxInFlight?: number;
  retryAfterMs?: number;
  now?: () => number;
}

const key = (br: number, bc: number) => `${br}:${bc}`;

export class BlockCache {
  private blocks = new Map<string, Block>(); // insertion order = LRU order (oldest first)
  private listeners = new Set<() => void>();
  private wanted: { br: number; bc: number }[] = [];
  private inFlight = 0;
  private _version = 0;
  readonly maxBlocks: number;
  readonly maxInFlight: number;
  private readonly retryAfterMs: number;
  private readonly now: () => number;
  /** Counters for tests and the benchmark. */
  stats = { requested: 0, aborted: 0, failed: 0, evicted: 0 };

  constructor(
    private readonly source: DataSource,
    opts: BlockCacheOptions = {},
  ) {
    this.maxBlocks = opts.maxBlocks ?? 200;
    this.maxInFlight = opts.maxInFlight ?? 4;
    this.retryAfterMs = opts.retryAfterMs ?? 3000;
    this.now = opts.now ?? (() => Date.now());
  }

  // useSyncExternalStore plumbing
  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  getVersion = (): number => this._version;
  private bump(): void {
    this._version++;
    this.listeners.forEach((l) => l());
  }

  get size(): number {
    return this.blocks.size;
  }

  getCell(r: number, c: number): CellLookup {
    const br = Math.floor(r / BLOCK_ROWS);
    const bc = Math.floor(c / BLOCK_COLS);
    const b = this.blocks.get(key(br, bc));
    if (!b) return { status: "absent", cell: undefined };
    return {
      status: b.status,
      cell: b.status === "loaded" ? b.cells[(r - br * BLOCK_ROWS) * BLOCK_COLS + (c - bc * BLOCK_COLS)] : undefined,
    };
  }

  /**
   * Declare which cells are needed now (inclusive ranges). Blocks outside the declared set that
   * are queued or in flight are cancelled; missing ones are requested nearest-first.
   */
  ensure(r0: number, r1: number, c0: number, c1: number): void {
    const maxBr = Math.max(0, Math.ceil(this.source.rowCount / BLOCK_ROWS) - 1);
    const maxBc = Math.max(0, Math.ceil(this.source.colCount / BLOCK_COLS) - 1);
    const b0 = Math.max(0, Math.floor(r0 / BLOCK_ROWS));
    const b1 = Math.min(maxBr, Math.floor(r1 / BLOCK_ROWS));
    const k0 = Math.max(0, Math.floor(c0 / BLOCK_COLS));
    const k1 = Math.min(maxBc, Math.floor(c1 / BLOCK_COLS));
    const centerBr = (b0 + b1) / 2;
    const centerBc = (k0 + k1) / 2;
    const needed = new Set<string>();
    const wanted: { br: number; bc: number }[] = [];
    for (let br = b0; br <= b1; br++) {
      for (let bc = k0; bc <= k1; bc++) {
        const k = key(br, bc);
        needed.add(k);
        const b = this.blocks.get(k);
        if (b) {
          // touch for LRU
          this.blocks.delete(k);
          this.blocks.set(k, b);
          const retry = b.status === "error" && this.now() - (b.failedAt ?? 0) >= this.retryAfterMs;
          if (!retry) continue;
          this.blocks.delete(k);
        }
        wanted.push({ br, bc });
      }
    }
    wanted.sort(
      (a, b) =>
        Math.hypot(a.br - centerBr, a.bc - centerBc) - Math.hypot(b.br - centerBr, b.bc - centerBc),
    );
    this.wanted = wanted;

    // cancel loads nobody needs anymore
    for (const [k, b] of this.blocks) {
      if (b.status === "loading" && !needed.has(k)) {
        b.abort?.abort();
        this.blocks.delete(k);
        this.stats.aborted++;
        this.inFlight--;
      }
    }
    this.pump();
    this.evict(needed);
  }

  private pump(): void {
    while (this.inFlight < this.maxInFlight && this.wanted.length > 0) {
      const next = this.wanted.shift();
      if (!next) break;
      const k = key(next.br, next.bc);
      if (this.blocks.has(k)) continue;
      this.load(next.br, next.bc, k);
    }
  }

  private load(br: number, bc: number, k: string): void {
    const abort = new AbortController();
    const block: Block = { status: "loading", cells: [], abort };
    this.blocks.set(k, block);
    this.inFlight++;
    this.stats.requested++;
    const r0 = br * BLOCK_ROWS;
    const c0 = bc * BLOCK_COLS;
    const rows = Math.min(BLOCK_ROWS, Math.max(1, this.source.rowCount - r0));
    const cols = Math.min(BLOCK_COLS, Math.max(1, this.source.colCount - c0));
    this.source
      .fetchBlock(r0, c0, rows, cols, abort.signal)
      .then((cells) => {
        if (this.blocks.get(k) !== block) return; // cancelled or replaced
        const arr: (Cell | undefined)[] = new Array<Cell | undefined>(BLOCK_ROWS * BLOCK_COLS);
        for (const cell of cells) {
          const i = (cell.r - r0) * BLOCK_COLS + (cell.c - c0);
          if (i >= 0 && i < arr.length) arr[i] = cell;
        }
        block.cells = arr;
        block.status = "loaded";
        block.abort = undefined;
        this.inFlight--;
        this.bump();
        this.pump();
      })
      .catch((e: unknown) => {
        if (this.blocks.get(k) !== block) return;
        if (e instanceof DOMException && e.name === "AbortError") return;
        block.status = "error";
        block.failedAt = this.now();
        block.abort = undefined;
        this.stats.failed++;
        this.inFlight--;
        this.bump();
        this.pump();
      });
    this.bump(); // "loading" placeholders become visible
  }

  private evict(keep: Set<string>): void {
    for (const [k, b] of this.blocks) {
      if (this.blocks.size <= this.maxBlocks) break;
      if (keep.has(k) || b.status === "loading") continue;
      this.blocks.delete(k);
      this.stats.evicted++;
    }
  }

  /** Overwrite cells in blocks that are loaded (used for server-returned changes). */
  patch(cells: Cell[]): void {
    let changed = false;
    for (const cell of cells) {
      const br = Math.floor(cell.r / BLOCK_ROWS);
      const bc = Math.floor(cell.c / BLOCK_COLS);
      const b = this.blocks.get(key(br, bc));
      if (!b || b.status !== "loaded") continue;
      const i = (cell.r - br * BLOCK_ROWS) * BLOCK_COLS + (cell.c - bc * BLOCK_COLS);
      b.cells[i] = cell.v === undefined && cell.f === undefined ? undefined : cell;
      changed = true;
    }
    if (changed) this.bump();
  }

  /** Forget everything (e.g. after a structural change); visible blocks reload on next ensure. */
  invalidate(): void {
    for (const b of this.blocks.values()) b.abort?.abort();
    this.blocks.clear();
    this.inFlight = 0;
    this.wanted = [];
    this.bump();
  }

  dispose(): void {
    this.invalidate();
    this.listeners.clear();
  }
}
