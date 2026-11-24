// Data Tables of the workspace (docs/UX_SPEC.md F5): make one from the selected range, look at its
// rows, put it back into a sheet (one undo step), download it as CSV.
import type { DataTable, SheetMeta, TablePreview, TableRows } from "@contracts";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { errorKey } from "@/api/errors";
import { useJob } from "@/api/hooks";
import { createFromRange, downloadUrl, exportTable, previewFromRange, tableRows, useTables } from "@/api/panels";
import { Button } from "@/components/Button";
import type { WorkbookEditor } from "@/grid/editing";
import type { RangeBounds } from "@/grid/selection";
import { useT } from "@/i18n";
import { formatNumber } from "@/i18n/format";
import { usePrefs } from "@/state/prefs";
import { useUi } from "@/state/ui";

const SHOW_ROWS = 20;
const cellText = (v: unknown): string => (v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v));

export function TablesPanel({ workspaceId, workbookId, sheet, bounds, active, editor, onClose }: {
  workspaceId: string | undefined; workbookId: string; sheet: SheetMeta; bounds: RangeBounds;
  active: { r: number; c: number }; editor: WorkbookEditor; onClose: () => void;
}) {
  const t = useT();
  const tables = useTables(workspaceId);
  const [open, setOpen] = useState<string>();
  const [making, setMaking] = useState(false);
  const qc = useQueryClient();
  return (
    <section className="panel" aria-labelledby="tables-title">
      <header className="panel-head">
        <h2 id="tables-title">{t("tables.title")}</h2>
        <Button onClick={onClose} aria-label={t("shell.panelClose")}>{t("shell.panelClose")}</Button>
      </header>
      <p className="muted">{t("tables.help")}</p>
      {making ? (
        <NewTable workbookId={workbookId} sheet={sheet} bounds={bounds} onCancel={() => setMaking(false)}
          onDone={(id) => { setMaking(false); setOpen(id); void qc.invalidateQueries({ queryKey: ["tables", workspaceId] }); }} />
      ) : (
        <Button variant="primary" onClick={() => setMaking(true)}>{t("tables.new")}</Button>
      )}
      {tables.isError ? <p role="alert">{t("tables.loadError")}</p> : null}
      {tables.data?.length === 0 && !making ? <p className="muted">{t("tables.none")}</p> : null}
      <ul className="op-list">
        {(tables.data ?? []).map((tb) => (
          <li key={tb.id} className="op-item">
            <button type="button" className="link-btn" aria-expanded={open === tb.id} onClick={() => setOpen(open === tb.id ? undefined : tb.id)}>
              <strong><bdi>{tb.name}</bdi></strong>{" "}
              <span className="muted">{t("tables.size", { rows: tb.row_count, cols: tb.columns.length })}</span>
            </button>
            {open === tb.id ? <OneTable table={tb} workbookId={workbookId} sheet={sheet} active={active} editor={editor} /> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Grid2({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  return (
    <div className="mini-table-wrap">
      <table className="mini-table">
        <thead><tr>{columns.map((c, i) => <th key={i}><bdi>{c}</bdi></th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}><bdi>{cellText(v)}</bdi></td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function NewTable({ workbookId, sheet, bounds, onDone, onCancel }: {
  workbookId: string; sheet: SheetMeta; bounds: RangeBounds; onDone: (id: string) => void; onCancel: () => void;
}) {
  const t = useT();
  const [header, setHeader] = useState(true);
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const range = { sheet_id: sheet.id, r0: bounds.r0, c0: bounds.c0, r1: bounds.r1, c1: bounds.c1 };
  const multi = bounds.r1 > bounds.r0 || bounds.c1 > bounds.c0;
  const found = useQuery({
    queryKey: ["table-preview", workbookId, sheet.id, bounds.r0, bounds.c0, bounds.r1, bounds.c1, header],
    enabled: multi,
    retry: false,
    queryFn: () => previewFromRange(workbookId, range, header),
  });
  const preview: TablePreview | null = found.data ?? null;
  const loadProblem = found.isError ? t(errorKey(found.error)) : null;
  if (!multi) {
    return (<div><p className="muted">{t("tables.needRange")}</p><Button onClick={onCancel}>{t("common.cancel")}</Button></div>);
  }
  return (
    <form className="panel" onSubmit={(e) => {
      e.preventDefault();
      createFromRange(workbookId, range, header, name.trim() || sheet.name).then((d) => onDone(d.id), (er: unknown) => setProblem(t(errorKey(er))));
    }}>
      <label className="field">{t("tables.name")}<input value={name} onChange={(e) => setName(e.target.value)} dir="auto" placeholder={sheet.name} /></label>
      <label className="check"><input type="checkbox" checked={header} onChange={(e) => setHeader(e.target.checked)} /> {t("tables.firstRowHeader")}</label>
      {preview ? (
        <>
          <p className="muted">{t("tables.previewRows", { rows: preview.row_count, cols: preview.columns.length })}</p>
          <Grid2 columns={preview.columns.map((c) => `${c.name} (${c.dtype})`)} rows={preview.rows.slice(0, 5)} />
          {preview.warnings.map((w, i) => <p key={i} className="muted">{w.message}</p>)}
        </>
      ) : null}
      {problem ?? loadProblem ? <p role="alert">{problem ?? loadProblem}</p> : null}
      <div className="panel-actions">
        <Button type="submit" variant="primary" disabled={!preview}>{t("tables.create")}</Button>
        <Button onClick={onCancel}>{t("common.cancel")}</Button>
      </div>
    </form>
  );
}

function OneTable({ table, workbookId, sheet, active, editor }: {
  table: DataTable; workbookId: string; sheet: SheetMeta; active: { r: number; c: number }; editor: WorkbookEditor;
}) {
  const t = useT();
  const digits = usePrefs((s) => s.digits);
  const push = useUi((s) => s.pushToast);
  const [rows, setRows] = useState<TableRows | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string>();
  const job = useJob(jobId);
  useEffect(() => {
    let live = true;
    tableRows(table.id, 0, SHOW_ROWS).then((r) => live && setRows(r), (e: unknown) => live && setProblem(t(errorKey(e))));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [table.id, table.version]);
  const put = () => {
    setProblem(null);
    editor.write(`/tables/${table.id}/to-sheet`, (base_seq) => ({
      workbook_id: workbookId, sheet_id: sheet.id, row: active.r, col: active.c, base_seq,
    })).then(() => push("info", t("tables.placed")), (e: unknown) => setProblem(t(errorKey(e))));
  };
  return (
    <div>
      {rows ? <Grid2 columns={rows.columns.map((c) => c.name)} rows={rows.rows} /> : null}
      {rows && rows.row_count > SHOW_ROWS ? (
        <p className="muted">{t("tables.firstRows", { shown: formatNumber(SHOW_ROWS, digits, 0), total: formatNumber(rows.row_count, digits, 0) })}</p>
      ) : null}
      {problem ? <p role="alert">{problem}</p> : null}
      <div className="panel-actions">
        <Button onClick={put}>{t("tables.toSheet")}</Button>
        <Button onClick={() => exportTable(table.id).then((j) => setJobId(j.id), (e: unknown) => setProblem(t(errorKey(e))))}>{t("tables.csv")}</Button>
      </div>
      {job.data?.status === "succeeded" && job.data.result_ref ? (
        <a className="btn btn-primary" href={downloadUrl(job.data.result_ref)} download>{t("export.download", { format: "CSV" })}</a>
      ) : null}
    </div>
  );
}
