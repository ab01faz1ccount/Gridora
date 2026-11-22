import type { Cell, CellWindow } from "@contracts";
import { api } from "@/api/client";

/** Where the grid gets its cells. One grid serves sheets and (later) Data Table pages. */
export interface DataSource {
  readonly rowCount: number;
  readonly colCount: number;
  /** The part that holds data, when the grid is larger than that (Ctrl+End goes here). Default: all of it. */
  readonly usedRows?: number;
  readonly usedCols?: number;
  fetchBlock(r0: number, c0: number, rows: number, cols: number, signal: AbortSignal): Promise<Cell[]>;
}

/** A sheet is shown at least this big, and always a little bigger than its data, so empty cells can be typed into. */
export const MIN_ROWS = 100;
export const MIN_COLS = 26;
export const PAD_ROWS = 20;
export const PAD_COLS = 5;
const MAX_ROWS = 1_048_576;
const MAX_COLS = 16_384;

/** The size the grid shows for a sheet whose data fills `rows` x `cols`. */
export const paddedSize = (rows: number, cols: number) => ({
  rows: Math.min(MAX_ROWS, Math.max(rows + PAD_ROWS, MIN_ROWS)),
  cols: Math.min(MAX_COLS, Math.max(cols + PAD_COLS, MIN_COLS)),
});

export function sheetDataSource(
  workbookId: string,
  sheetId: string,
  rowCount: number,
  colCount: number,
): DataSource {
  const size = paddedSize(rowCount, colCount);
  return {
    rowCount: size.rows,
    colCount: size.cols,
    usedRows: rowCount,
    usedCols: colCount,
    async fetchBlock(r0, c0, rows, cols, signal) {
      const w = await api.get<CellWindow>(`/workbooks/${workbookId}/sheets/${sheetId}/cells`, {
        query: { r0, c0, rows, cols },
        signal,
      });
      return w.cells;
    },
  };
}
