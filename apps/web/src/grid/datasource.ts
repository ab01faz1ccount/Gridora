import type { Cell, CellWindow } from "@contracts";
import { api } from "@/api/client";

/** Where the grid gets its cells. One grid serves sheets and (later) Data Table pages. */
export interface DataSource {
  readonly rowCount: number;
  readonly colCount: number;
  fetchBlock(r0: number, c0: number, rows: number, cols: number, signal: AbortSignal): Promise<Cell[]>;
}

export function sheetDataSource(
  workbookId: string,
  sheetId: string,
  rowCount: number,
  colCount: number,
): DataSource {
  return {
    rowCount,
    colCount,
    async fetchBlock(r0, c0, rows, cols, signal) {
      const w = await api.get<CellWindow>(`/workbooks/${workbookId}/sheets/${sheetId}/cells`, {
        query: { r0, c0, rows, cols },
        signal,
      });
      return w.cells;
    },
  };
}
