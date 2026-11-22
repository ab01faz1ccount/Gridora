// Everything that changes cells from the web app: edit, undo, redo. One editor per workbook.
// Requests are strictly serialized (each one needs the previous one's history seq as `base_seq`),
// and what the server returns (`cells` and `others`) is applied to the block caches of the
// sheets it belongs to, so the screen shows exactly what the engine computed.
import type { Cell, CellEdit, CellEditRequest, CellsChangedResult, HistoryEntry } from "@contracts";
import { api, ApiError } from "@/api/client";
import { BlockCache } from "./block-cache";
import type { DataSource } from "./datasource";
import {
  afterEdit,
  afterRedo,
  afterUndo,
  canRedo,
  canUndo,
  emptyHistory,
  fromEntries,
  headOf,
  type HistoryState,
} from "./history";
import type { RangeBounds } from "./selection";

/** The API accepts this many edits in one request (one request = one undo step). */
export const MAX_EDITS = 50_000;
const HISTORY_PAGE = 100;
const HISTORY_MAX_PAGES = 50;

/** One block cache per sheet, kept while the workbook is open so switching tabs does not refetch. */
export class SheetCaches {
  private readonly map = new Map<string, BlockCache>();

  get(sheetId: string, source: DataSource): BlockCache {
    const have = this.map.get(sheetId);
    if (have) {
      have.setSource(source); // the sheet may have grown
      return have;
    }
    const made = new BlockCache(source);
    this.map.set(sheetId, made);
    return made;
  }

  patch(sheetId: string, cells: Cell[]): void {
    this.map.get(sheetId)?.patch(cells); // a sheet nobody has opened has nothing to update
  }

  refreshAll(): void {
    this.map.forEach((c) => c.refresh());
  }

  dispose(): void {
    this.map.forEach((c) => c.invalidate());
  }
}

export interface EditorSnapshot {
  canUndo: boolean;
  canRedo: boolean;
  /** requests that are queued or running */
  pending: number;
  /** the last request failed and nothing has succeeded since */
  failed: boolean;
  /** the document was changed elsewhere: the last change was NOT saved and the screen was reloaded */
  conflict: boolean;
}

const INITIAL: EditorSnapshot = { canUndo: false, canRedo: false, pending: 0, failed: false, conflict: false };

export class WorkbookEditor {
  readonly caches = new SheetCaches();
  private history: HistoryState = emptyHistory;
  private loaded: Promise<void> | null = null;
  private tail: Promise<unknown> = Promise.resolve();
  private pending = 0;
  private failed = false;
  private conflict = false;
  private snap: EditorSnapshot = INITIAL;
  private listeners = new Set<() => void>();

  /** `onChanged` runs after every successful change (the page refetches sheet sizes there). */
  constructor(
    readonly workbookId: string,
    private readonly onChanged: () => void = () => {},
  ) {}

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  getSnapshot = (): EditorSnapshot => this.snap;

  private publish(): void {
    const next: EditorSnapshot = {
      canUndo: canUndo(this.history),
      canRedo: canRedo(this.history),
      pending: this.pending,
      failed: this.failed,
      conflict: this.conflict,
    };
    const s = this.snap;
    if (
      s.canUndo === next.canUndo && s.canRedo === next.canRedo && s.pending === next.pending &&
      s.failed === next.failed && s.conflict === next.conflict
    ) return;
    this.snap = next;
    this.listeners.forEach((l) => l());
  }

  /** Reads the history once so undo/redo start in the right state and `base_seq` is known. */
  load(): Promise<void> {
    this.loaded ??= this.readHistory().catch((e: unknown) => {
      this.loaded = null; // try again on the next request
      throw e;
    });
    return this.loaded;
  }

  private async readHistory(): Promise<void> {
    // Newest first. Undone entries are always the newest ones, so the first applied entry ends
    // the search; a document that was never undone costs one request.
    const entries: HistoryEntry[] = [];
    let cursor: string | undefined;
    for (let page = 0; page < HISTORY_MAX_PAGES; page++) {
      const got = await api.get<HistoryEntry[]>(`/documents/${this.workbookId}/history`, {
        query: { limit: HISTORY_PAGE, cursor },
      });
      entries.push(...got);
      const last = got[got.length - 1];
      if (got.length < HISTORY_PAGE || !last) break;
      if (got.some((e) => !e.undone)) break; // found the head
      cursor = String(last.seq);
    }
    this.history = fromEntries(entries);
    this.publish();
  }

  private enqueue<T>(job: () => Promise<T>): Promise<T> {
    this.pending++;
    this.publish();
    const run = this.tail.then(job, job);
    this.tail = run.catch(() => undefined);
    return run.then(
      (v) => {
        this.pending--;
        this.failed = false;
        this.conflict = false;
        this.publish();
        return v;
      },
      (e: unknown) => {
        this.pending--;
        this.failed = true;
        this.publish();
        throw e;
      },
    );
  }

  private apply(res: CellsChangedResult): void {
    this.caches.patch(res.sheet_id, res.cells);
    for (const o of res.others ?? []) this.caches.patch(o.sheet_id, o.cells);
    if (res.history_entry.delta.kind !== "cell_patch") this.caches.refreshAll(); // table/structure change
  }

  /** Something went wrong in a way that may have left the screen out of date: start from the server. */
  private async resync(e: unknown): Promise<void> {
    if (e instanceof ApiError && (e.code === "version_conflict" || e.code === "operation_conflict")) {
      if (e.code === "version_conflict") this.conflict = true; // shown as a banner until dismissed
      this.loaded = null;
      this.caches.refreshAll();
      try {
        await this.load();
      } catch {
        /* the next request tries again */
      }
    }
  }

  /** Several cells, one history entry. */
  edit(sheetId: string, edits: CellEdit[]): Promise<void> {
    if (edits.length === 0) return Promise.resolve();
    if (edits.length > MAX_EDITS) return Promise.reject(new RangeError("too many edits"));
    return this.enqueue(async () => {
      try {
        await this.load();
        const body: CellEditRequest = { base_seq: headOf(this.history), edits };
        const res = await api.patch<CellsChangedResult>(
          `/workbooks/${this.workbookId}/sheets/${sheetId}/cells`,
          body,
        );
        this.history = afterEdit(this.history, res.history_entry.seq);
        this.apply(res);
        this.onChanged();
      } catch (e) {
        await this.resync(e);
        throw e;
      }
    });
  }

  /** Clears every cell of a range (one history entry). */
  clear(sheetId: string, b: RangeBounds): Promise<void> {
    const area = (b.r1 - b.r0 + 1) * (b.c1 - b.c0 + 1);
    if (area > MAX_EDITS) return Promise.reject(new RangeError("range too large"));
    const edits: CellEdit[] = [];
    for (let r = b.r0; r <= b.r1; r++) for (let c = b.c0; c <= b.c1; c++) edits.push({ r, c });
    return this.edit(sheetId, edits);
  }

  undo(): Promise<void> {
    return this.step("undo");
  }
  redo(): Promise<void> {
    return this.step("redo");
  }

  private step(kind: "undo" | "redo"): Promise<void> {
    return this.enqueue(async () => {
      try {
        await this.load();
        if (kind === "undo" ? !canUndo(this.history) : !canRedo(this.history)) return;
        const res = await api.post<CellsChangedResult>(`/documents/${this.workbookId}/${kind}`, undefined, {
          query: { base_seq: headOf(this.history) },
        });
        const seq = res.history_entry.seq;
        this.history = kind === "undo" ? afterUndo(this.history, seq) : afterRedo(this.history, seq);
        this.apply(res);
        this.onChanged();
      } catch (e) {
        await this.resync(e);
        throw e;
      }
    });
  }

  dismissConflict(): void {
    this.conflict = false;
    this.publish();
  }

  dispose(): void {
    this.caches.dispose();
  }
}
