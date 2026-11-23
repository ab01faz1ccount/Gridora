import type { Operation, OperationDescriptor, PreviewResult } from "@contracts";
import { useQuery } from "@tanstack/react-query";
import { api } from "./client";

/** The operation catalog drives every form; it only changes with a server release. */
export function useOperationDescriptors() {
  return useQuery({
    queryKey: ["operations"],
    queryFn: () => api.get<OperationDescriptor[]>("/operations"),
    staleTime: Infinity,
  });
}

/** Flat key -> text for operation labels, descriptions, parameter titles and validation messages. */
export function useOperationCatalog(locale: string) {
  return useQuery({
    queryKey: ["operations", "i18n", locale],
    queryFn: () => api.get<Record<string, string>>("/operations/i18n", { query: { locale } }),
    staleTime: Infinity,
  });
}

export function previewOperation(documentId: string, op: Operation, signal?: AbortSignal): Promise<PreviewResult> {
  return api.post<PreviewResult>(`/documents/${documentId}/operations/preview`, op, { signal });
}
