import { create } from "zustand";
import type { Implementation } from "@/api/client";

export interface Toast {
  id: number;
  kind: "error" | "info";
  text: string;
}

interface UiState {
  implementation: Implementation;
  setImplementation: (i: Implementation) => void;
  toasts: Toast[];
  pushToast: (kind: Toast["kind"], text: string) => void;
  dismissToast: (id: number) => void;
}

let nextId = 1;

export const useUi = create<UiState>((set) => ({
  implementation: {},
  setImplementation: (i) => set({ implementation: i }),
  toasts: [],
  pushToast: (kind, text) => set((s) => ({ toasts: [...s.toasts, { id: nextId++, kind, text }] })),
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
