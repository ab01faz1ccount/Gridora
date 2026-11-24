// Calls behind the Save/Export, Data Table, chart and saved-tool panels.
import type {
  ChartData, ChartSpec, CompatibilityReport, DataTable, FileRecord, FindResult, Job, Range, TablePreview, TableRows, Tool,
} from "@contracts";
import { useQuery } from "@tanstack/react-query";
import { api } from "./client";

export const downloadUrl = (fileId: string): string => `/api/v1/files/${fileId}/download`;

export const saveWorkbook = (id: string) => api.post<FileRecord>(`/workbooks/${id}/save`);
export const startExport = (id: string, format: "xlsx" | "csv", sheetId?: string) =>
  api.post<Job>(`/workbooks/${id}/export`, { format, sheet_id: sheetId });
export const exportReport = (jobId: string) => api.get<CompatibilityReport>(`/jobs/${jobId}/compatibility`);

// ---- Data Tables
export function useTables(workspaceId: string | undefined) {
  return useQuery({
    queryKey: ["tables", workspaceId],
    enabled: Boolean(workspaceId),
    queryFn: () => api.get<DataTable[]>(`/workspaces/${workspaceId}/tables`),
    retry: false,
  });
}
export const previewFromRange = (workbookId: string, range: Range, headerRow: boolean) =>
  api.post<TablePreview>("/tables/from-range", { workbook_id: workbookId, range, header_row: headerRow, preview: true });
export const createFromRange = (workbookId: string, range: Range, headerRow: boolean, name: string) =>
  api.post<DataTable>("/tables/from-range", { workbook_id: workbookId, range, header_row: headerRow, name });
export const tableRows = (id: string, offset: number, limit: number) =>
  api.get<TableRows>(`/tables/${id}/rows`, { query: { offset, limit } });
export const exportTable = (id: string) => api.post<Job>(`/tables/${id}/export`, {});
// ---- charts
export function useCharts(documentId: string) {
  return useQuery({ queryKey: ["charts", documentId], queryFn: () => api.get<ChartSpec[]>(`/documents/${documentId}/charts`), retry: false });
}
export function useChartData(chartId: string | undefined) {
  return useQuery({ queryKey: ["chart-data", chartId], enabled: Boolean(chartId), retry: false,
    queryFn: () => api.get<ChartData>(`/charts/${chartId}/data`) });
}
export const createChart = (documentId: string, spec: ChartSpec) => api.post<ChartSpec>(`/documents/${documentId}/charts`, spec);
export const deleteChart = (id: string) => api.delete<void>(`/charts/${id}`);

// ---- saved tools
export function useTools() {
  return useQuery({ queryKey: ["tools"], queryFn: () => api.get<Tool[]>("/tools"), retry: false });
}
export const deleteTool = (id: string) => api.delete<void>(`/tools/${id}`);

// ---- find in a sheet
export interface FindOptions { matchCase: boolean; wholeCell: boolean; inFormulas: boolean }
export function findInSheet(
  workbookId: string, sheetId: string, q: string, o: FindOptions,
  after: { r: number; c: number } | undefined, limit: number,
) {
  return api.get<FindResult>(`/workbooks/${workbookId}/sheets/${sheetId}/find`, {
    query: {
      q, limit, match_case: o.matchCase || undefined, whole_cell: o.wholeCell || undefined,
      in_formulas: o.inFormulas || undefined, after_row: after?.r, after_col: after?.c,
    },
  });
}
