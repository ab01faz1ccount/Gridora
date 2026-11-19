// Import cards: one per file the user brings in. Kept in a store so they survive navigating
// inside the app; the job id is remembered in storage so polling resumes after a page reload.
import { MAX_UPLOAD_BYTES } from "@contracts";
import { create } from "zustand";
import { ApiError } from "@/api/client";
import { uploadFile } from "@/api/upload";

export type Phase = "uploading" | "processing" | "done" | "failed";

export interface ImportEntry {
  key: string;
  workspaceId: string;
  name: string;
  size: number;
  phase: Phase;
  loaded: number;
  jobId?: string;
  fileId?: string;
  workbookId?: string;
  attention?: number; // import report items that are not fully supported
  error?: ApiError;
  startedAt: number;
  abort?: AbortController;
}

const STORE_KEY = "gridora.imports";

function persist(entries: ImportEntry[]): void {
  try {
    const slim = entries
      .filter((e) => e.jobId && e.phase === "processing")
      .map((e) => ({ key: e.key, workspaceId: e.workspaceId, name: e.name, size: e.size, jobId: e.jobId, fileId: e.fileId }));
    localStorage.setItem(STORE_KEY, JSON.stringify(slim));
  } catch {
    /* storage unavailable: the card just will not survive a reload */
  }
}

export function restoreImports(): ImportEntry[] {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return [];
    const arr: unknown = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    return arr.flatMap((o): ImportEntry[] => {
      const e = o as Partial<ImportEntry>;
      if (typeof e.key !== "string" || typeof e.jobId !== "string" || typeof e.workspaceId !== "string") return [];
      return [{ key: e.key, workspaceId: e.workspaceId, name: String(e.name ?? ""), size: Number(e.size ?? 0),
        phase: "processing", loaded: Number(e.size ?? 0), jobId: e.jobId, fileId: e.fileId, startedAt: Date.now() }];
    });
  } catch {
    return [];
  }
}

interface ImportsState {
  entries: ImportEntry[];
  start: (workspaceId: string, file: File, onUploaded?: () => void) => void;
  jobFinished: (key: string, ok: boolean, error?: ApiError, info?: { workbookId?: string; attention?: number }) => void;
  cancel: (key: string) => void;
  dismiss: (key: string) => void;
}

let counter = 0;

export const useImports = create<ImportsState>((set, get) => {
  const update = (key: string, patch: Partial<ImportEntry>) => {
    set((s) => ({ entries: s.entries.map((e) => (e.key === key ? { ...e, ...patch } : e)) }));
    persist(get().entries);
  };
  return {
    entries: restoreImports(),

    start: (workspaceId, file, onUploaded) => {
      const key = `imp-${Date.now()}-${counter++}`;
      const abort = new AbortController();
      const base: ImportEntry = { key, workspaceId, name: file.name, size: file.size, phase: "uploading",
        loaded: 0, startedAt: Date.now(), abort };
      set((s) => ({ entries: [base, ...s.entries] }));

      // Refuse what the server would refuse, before sending 100 MB for nothing.
      const lower = file.name.toLowerCase();
      if (lower.endsWith(".xls")) {
        update(key, { phase: "failed", error: new ApiError({ code: "unsupported_workbook", message: "", status: 0,
          details: [{ code: "xlsx.legacy_xls", message: "" }] }) });
        return;
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        update(key, { phase: "failed", error: new ApiError({ code: "file_too_large", message: "", status: 0 }) });
        return;
      }
      uploadFile(workspaceId, file, (loaded) => update(key, { loaded }), abort.signal)
        .then((r) => {
          update(key, { phase: "processing", jobId: r.job_id, fileId: r.file.id, loaded: file.size, abort: undefined });
          onUploaded?.();
        })
        .catch((e: unknown) => {
          if (e instanceof DOMException && e.name === "AbortError") {
            set((s) => ({ entries: s.entries.filter((x) => x.key !== key) }));
            return;
          }
          update(key, { phase: "failed", error: e instanceof ApiError ? e
            : new ApiError({ code: "internal_error", message: "", status: 0 }), abort: undefined });
        });
    },

    jobFinished: (key, ok, error, info) =>
      update(key, ok ? { phase: "done", ...info } : { phase: "failed", error }),
    cancel: (key) => get().entries.find((e) => e.key === key)?.abort?.abort(),
    dismiss: (key) => {
      set((s) => ({ entries: s.entries.filter((e) => e.key !== key) }));
      persist(get().entries);
    },
  };
});
