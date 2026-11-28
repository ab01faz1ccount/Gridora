// Charts of a workbook or a Data Table (docs/UX_SPEC.md F7): make one with the Chart Builder (from the selected
// cells when there are some), look at it, edit it, delete it. The server computes the numbers; the browser only draws.
import type { ChartSpec, SheetMeta } from "@contracts";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { errorKey } from "@/api/errors";
import { deleteChart, useChartData, useCharts } from "@/api/panels";
import { Button } from "@/components/Button";
import { columnLetters } from "@/grid/geometry";
import type { RangeBounds } from "@/grid/selection";
import { useT, type MessageKey } from "@/i18n";
import { ChartBuilder, type SourceChoice } from "./ChartBuilder";
import { ChartView } from "./ChartView";

const MAX_SHEET_CELLS = 1_000_000;

/** What a workbook chart can read: the selected cells (when it is more than one cell) and the whole sheet. */
export function workbookSources(sheet: SheetMeta, bounds: RangeBounds, t: (k: MessageKey, p?: Record<string, string>) => string): SourceChoice[] {
  const out: SourceChoice[] = [];
  const range = (b: RangeBounds) => ({ sheet_id: sheet.id, r0: b.r0, c0: b.c0, r1: b.r1, c1: b.c1 });
  if (bounds.r1 > bounds.r0 && bounds.c1 > bounds.c0) {
    const label = `${columnLetters(bounds.c0)}${bounds.r0 + 1}:${columnLetters(bounds.c1)}${bounds.r1 + 1}`;
    out.push({ id: "selection", label: t("charts.source.selection", { range: label }), source: { kind: "sheet_range", range: range(bounds) } });
  }
  if (sheet.row_count >= 2 && sheet.col_count >= 2 && sheet.row_count * sheet.col_count <= MAX_SHEET_CELLS) {
    out.push({ id: "sheet", label: t("charts.source.sheet"), source: { kind: "sheet_range", range: range({ r0: 0, c0: 0, r1: sheet.row_count - 1, c1: sheet.col_count - 1 }) } });
  }
  return out;
}

export function ChartsPanel({ workbookId, sheet, bounds, onClose }: {
  workbookId: string; sheet: SheetMeta; bounds: RangeBounds; onClose: () => void;
}) {
  const t = useT();
  const sources = useMemo(() => workbookSources(sheet, bounds, t), [sheet, bounds, t]);
  return (
    <section className="panel" aria-labelledby="charts-title">
      <header className="panel-head">
        <h2 id="charts-title">{t("charts.title")}</h2>
        <Button onClick={onClose} aria-label={t("shell.panelClose")}>{t("shell.panelClose")}</Button>
      </header>
      <ChartsManager documentId={workbookId} sources={sources} />
    </section>
  );
}

/** The list of a document's charts with make / edit / delete. Used for workbooks and for Data Tables. */
export function ChartsManager({ documentId, sources }: { documentId: string; sources: SourceChoice[] }) {
  const t = useT();
  const charts = useCharts(documentId);
  const [opened, setOpened] = useState<string>();
  const [mode, setMode] = useState<{ kind: "new" } | { kind: "edit"; spec: ChartSpec } | null>(null);
  const qc = useQueryClient();
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["charts", documentId] });
    void qc.invalidateQueries({ queryKey: ["chart-data"] });
  };
  return (
    <div>
      {mode ? (
        <ChartBuilder documentId={documentId} sources={sources} initial={mode.kind === "edit" ? mode.spec : undefined}
          onSaved={(id) => { setMode(null); setOpened(id); refresh(); }} onCancel={() => setMode(null)} />
      ) : sources.length > 0 ? (
        <Button variant="primary" onClick={() => setMode({ kind: "new" })}>{t("charts.new")}</Button>
      ) : (
        <p className="muted">{t("charts.needRange")}</p>
      )}
      {charts.isError ? <p role="alert">{t("charts.loadError")}</p> : null}
      {charts.data?.length === 0 && !mode ? <p className="muted">{t("charts.none")}</p> : null}
      <ul className="op-list">
        {(charts.data ?? []).map((c) => (
          <li key={c.id} className="op-item">
            <button type="button" className="link-btn" aria-expanded={opened === c.id}
              onClick={() => setOpened(opened === c.id ? undefined : c.id)}>
              <strong>{c.title || t("charts.untitled")}</strong> <span className="muted">{t(`charts.type.${c.type}` as MessageKey)}</span>
            </button>
            {opened === c.id && !mode ? <OneChart spec={c} onEdit={() => setMode({ kind: "edit", spec: c })} onDeleted={refresh} /> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function OneChart({ spec, onEdit, onDeleted }: { spec: ChartSpec; onEdit: () => void; onDeleted: () => void }) {
  const t = useT();
  const data = useChartData(spec.id);
  return (
    <div>
      {data.isPending ? <p className="muted">{t("charts.loading")}</p> : null}
      {data.isError ? <p role="alert">{t(errorKey(data.error))}</p> : null}
      {data.data ? <ChartView spec={spec} data={data.data} /> : null}
      <div className="panel-actions">
        <Button onClick={onEdit}>{t("charts.edit")}</Button>
        <Button variant="danger" onClick={() => spec.id && void deleteChart(spec.id).then(onDeleted)}>{t("charts.delete")}</Button>
      </div>
    </div>
  );
}
