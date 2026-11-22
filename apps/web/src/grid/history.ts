import type { HistoryEntry } from "@contracts";

/**
 * What the client knows about the document's history: the seqs that are applied (oldest first)
 * and the ones that were undone (next redo first). `head` is what the server wants as `base_seq`.
 */
export interface HistoryState {
  applied: number[];
  undone: number[];
}

export const emptyHistory: HistoryState = { applied: [], undone: [] };

export const headOf = (h: HistoryState): number => h.applied[h.applied.length - 1] ?? 0;
export const canUndo = (h: HistoryState): boolean => h.applied.length > 0;
export const canRedo = (h: HistoryState): boolean => h.undone.length > 0;

/** Entries come newest first (as the API lists them), undone ones included. */
export function fromEntries(entries: HistoryEntry[]): HistoryState {
  const asc = [...entries].sort((a, b) => a.seq - b.seq);
  return {
    applied: asc.filter((e) => !e.undone).map((e) => e.seq),
    // redo goes from the oldest undone entry forward
    undone: asc.filter((e) => e.undone).map((e) => e.seq),
  };
}

/** A new edit becomes the head and drops everything that could have been redone. */
export const afterEdit = (h: HistoryState, seq: number): HistoryState => ({
  applied: [...h.applied, seq],
  undone: [],
});

export const afterUndo = (h: HistoryState, seq: number): HistoryState => ({
  applied: h.applied.filter((s) => s !== seq),
  undone: [seq, ...h.undone.filter((s) => s !== seq)],
});

export const afterRedo = (h: HistoryState, seq: number): HistoryState => ({
  applied: [...h.applied.filter((s) => s !== seq), seq].sort((a, b) => a - b),
  undone: h.undone.filter((s) => s !== seq),
});
