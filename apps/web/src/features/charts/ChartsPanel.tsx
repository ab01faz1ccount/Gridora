// Charts of a workbook (docs/UX_SPEC.md F7): make one from the selected range (first row = headers),
// see it, delete it. The server computes the numbers; the browser only draws them.
import { SCHEMA_VERSION, type ChartSpec, type SheetMeta } from "@contracts";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { errorKey } from "@/api/errors";
import { createChart, deleteChart, useChartData, useCharts } from "@/api/panels";
import { Button } from "@/components/Button";
import type { BlockCache } from "@/grid/block-cache";
import { columnLetters } from "@/grid/geometry";
import type { RangeBounds } from "@/grid/selection";
import { cellRaw } from "@/grid/summary";
import { useT } from "@/i18n";
import { ChartView } from "./ChartView";

const TYPES: ChartSpec["type"][] = ["bar", "line", "area", "pie", "scatter"];

export function ChartsPanel({ workbookId, sheet, bounds, cache, onClose }: {
  workbookId: string; sheet: SheetMeta; bounds: RangeBounds; cache: BlockCache; onClose: () => void;
}) {
  const t = useT();
  const charts = useCharts(workbookId);
  const [opened, setOpened] = useState<string>();
  const [making, setMaking] = useState(false);
  const qc = useQueryClient();
  const refresh = () => void qc.invalidateQueries({ queryKey: ["charts", workbookId] });
  return (
    <section className="panel" aria-labelledby="charts-title">
      <header className="panel-head">
        <h2 id="charts-title">{t("charts.title")}</h2>
        <Button onClick={onClose} aria-label={t("shell.panelClose")}>{t("shell.panelClose")}</Button>
      </header>
      {making ? (
        <NewChart workbookId={workbookId} sheet={sheet} bounds={bounds} cache={cache}
          onDone={(id) => { setMaking(false); setOpened(id); refresh(); }} onCancel={() => setMaking(false)} />
      ) : (
        <Button variant="primary" onClick={() => setMaking(true)}>{t("charts.new")}</Button>
      )}
      {charts.isError ? <p role="alert">{t("charts.loadError")}</p> : null}
      {charts.data?.length === 0 && !making ? <p className="muted">{t("charts.none")}</p> : null}
      <ul className="op-list">
        {(charts.data ?? []).map((c) => (
          <li key={c.id} className="op-item">
            <button type="button" className="link-btn" aria-expanded={opened === c.id}
              onClick={() => setOpened(opened === c.id ? undefined : c.id)}>
              <strong>{c.title || t("charts.untitled")}</strong> <span className="muted">{t(`charts.type.${c.type}` as "charts.type.bar")}</span>
            </button>
            {opened === c.id ? <OneChart spec={c} onDeleted={refresh} /> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function OneChart({ spec, onDeleted }: { spec: ChartSpec; onDeleted: () => void }) {
  const t = useT();
  const data = useChartData(spec.id);
  return (
    <div>
      {data.isPending ? <p className="muted">{t("charts.loading")}</p> : null}
      {data.isError ? <p role="alert">{t(errorKey(data.error))}</p> : null}
      {data.data ? <ChartView spec={spec} data={data.data} /> : null}
      <Button variant="danger" onClick={() => spec.id && void deleteChart(spec.id).then(onDeleted)}>{t("charts.delete")}</Button>
    </div>
  );
}

function NewChart({ workbookId, sheet, bounds, cache, onDone, onCancel }: {
  workbookId: string; sheet: SheetMeta; bounds: RangeBounds; cache: BlockCache; onDone: (id: string | undefined) => void; onCancel: () => void;
}) {
  const t = useT();
  const cols = useMemo(
    () => Array.from({ length: bounds.c1 - bounds.c0 + 1 }, (_, i) => {
      const raw = cellRaw(cache.getCell(bounds.r0, bounds.c0 + i).cell).trim();
      return { index: i, name: raw || columnLetters(bounds.c0 + i) };
    }),
    [bounds, cache],
  );
  const usable = bounds.r1 > bounds.r0 && cols.length >= 2;
  const [type, setType] = useState<ChartSpec["type"]>("bar");
  const [title, setTitle] = useState("");
  const [cat, setCat] = useState(0);
  const [vals, setVals] = useState<number[]>(() => cols.slice(1).map((c) => c.index));
  const [stacked, setStacked] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (!usable) {
    return (
      <div>
        <p className="muted">{t("charts.needRange")}</p>
        <Button onClick={onCancel}>{t("common.cancel")}</Button>
      </div>
    );
  }
  const toggle = (i: number) => setVals((v) => (v.includes(i) ? v.filter((x) => x !== i) : [...v, i].sort()));
  const make = () => {
    const spec: ChartSpec = {
      schema_version: SCHEMA_VERSION, document_id: workbookId, type, title: title || undefined,
      source: { kind: "sheet_range", range: { sheet_id: sheet.id, r0: bounds.r0, c0: bounds.c0, r1: bounds.r1, c1: bounds.c1 } },
      series: vals.filter((i) => i !== cat).map((i) => ({ name: cols[i]!.name, value_col: i, category_col: cat })),
      options: { stacked, legend: true },
    };
    createChart(workbookId, spec).then((c) => onDone(c.id), (e: unknown) => setProblem(t(errorKey(e))));
  };
  return (
    <form className="panel" onSubmit={(e) => { e.preventDefault(); make(); }}>
      <label className="field">{t("charts.kind")}
        <select value={type} onChange={(e) => setType(e.target.value as ChartSpec["type"])}>
          {TYPES.map((k) => <option key={k} value={k}>{t(`charts.type.${k}` as "charts.type.bar")}</option>)}
        </select>
      </label>
      <label className="field">{t("charts.titleField")}
        <input value={title} onChange={(e) => setTitle(e.target.value)} dir="auto" />
      </label>
      <label className="field">{t("charts.categories")}
        <select value={cat} onChange={(e) => setCat(Number(e.target.value))}>
          {cols.map((c) => <option key={c.index} value={c.index}>{c.name}</option>)}
        </select>
      </label>
      <fieldset className="field">
        <legend>{t("charts.values")}</legend>
        {cols.filter((c) => c.index !== cat).map((c) => (
          <label key={c.index} className="check">
            <input type="checkbox" checked={vals.includes(c.index)} onChange={() => toggle(c.index)} /> <bdi>{c.name}</bdi>
          </label>
        ))}
      </fieldset>
      {type === "bar" || type === "area" ? (
        <label className="check"><input type="checkbox" checked={stacked} onChange={(e) => setStacked(e.target.checked)} /> {t("charts.stacked")}</label>
      ) : null}
      {problem ? <p role="alert">{problem}</p> : null}
      <div className="panel-actions">
        <Button type="submit" variant="primary" disabled={vals.filter((i) => i !== cat).length === 0}>{t("charts.create")}</Button>
        <Button onClick={onCancel}>{t("common.cancel")}</Button>
      </div>
    </form>
  );
}
