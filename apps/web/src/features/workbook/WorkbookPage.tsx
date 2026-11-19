import type { SheetMeta } from "@contracts";
import { useMemo, useState, useSyncExternalStore } from "react";
import { ApiError } from "@/api/client";
import { errorKey } from "@/api/errors";
import { useWorkbook } from "@/api/hooks";
import { navigate } from "@/app/router";
import { Button } from "@/components/Button";
import { Grid } from "@/grid/Grid";
import { BlockCache } from "@/grid/block-cache";
import { sheetDataSource } from "@/grid/datasource";
import { columnLetters } from "@/grid/geometry";
import { boundsOf, single, type Selection } from "@/grid/selection";
import { cellRaw, summarize } from "@/grid/summary";
import { CompatPanel } from "@/features/import/CompatPanel";
import { useT } from "@/i18n";
import { formatNumber } from "@/i18n/format";
import { usePrefs } from "@/state/prefs";
import { useUi } from "@/state/ui";

export function WorkbookPage({ id }: { id: string }) {
  const t = useT();
  const digits = usePrefs((s) => s.digits);
  const panel = useUi((s) => s.panel);
  const setPanel = useUi((s) => s.setPanel);
  const wb = useWorkbook(id);
  const [sheetId, setSheetId] = useState<string | null>(null);

  const visible: SheetMeta[] = useMemo(
    () => (wb.data?.sheets ?? []).filter((s) => s.visible === "visible"),
    [wb.data],
  );
  const sheet = visible.find((s) => s.id === sheetId) ?? visible[0];
  const source = useMemo(
    () => (sheet ? sheetDataSource(id, sheet.id, sheet.row_count, sheet.col_count) : null),
    [id, sheet],
  );

  if (wb.isPending) return <p>{t("workbook.loading")}</p>;
  if (wb.isError) {
    const notFound = wb.error instanceof ApiError && wb.error.code === "not_found";
    return (
      <div role="alert">
        <p>{notFound ? t("workbook.notFound") : t(errorKey(wb.error))}</p>
        <Button onClick={() => navigate("/workspaces")}>{t("workbook.back")}</Button>
      </div>
    );
  }
  if (!sheet || !source) return <p>{t("workbook.noSheets")}</p>;

  const report = wb.data.compat;
  return (
    <section className="wbs" aria-label={wb.data.name}>
      <WorkbookView key={`${id}:${sheet.id}`} name={wb.data.name} sheet={sheet} source={source}
        hasReport={Boolean(report)} />
      {panel === "report" && report ? (
        <aside className="wbs-panel" aria-label={t("shell.report")}>
          <CompatPanel report={report} onClose={() => setPanel(null)} />
        </aside>
      ) : null}
      <footer className="wbs-bottom">
        <div role="tablist" aria-label={t("grid.sheetTabs")} className="sheet-tabs">
          {visible.map((s) => (
            <button key={s.id} type="button" role="tab" aria-selected={s.id === sheet.id}
              className={"sheet-tab" + (s.id === sheet.id ? " sheet-tab-active" : "")}
              onClick={() => setSheetId(s.id)}>
              <bdi>{s.name}</bdi>
            </button>
          ))}
        </div>
        <span className="muted">
          {t("workbook.dimensions", {
            rows: formatNumber(sheet.row_count, digits, 0),
            cols: formatNumber(sheet.col_count, digits, 0),
          })}
        </span>
      </footer>
    </section>
  );
}

/** Top bar, formula bar, grid and status bar of one sheet. */
function WorkbookView({
  name,
  sheet,
  source,
  hasReport,
}: {
  name: string;
  sheet: SheetMeta;
  source: ReturnType<typeof sheetDataSource>;
  hasReport: boolean;
}) {
  const t = useT();
  const digits = usePrefs((s) => s.digits);
  const panel = useUi((s) => s.panel);
  const setPanel = useUi((s) => s.setPanel);
  const cache = useMemo(() => new BlockCache(source), [source]);
  const version = useSyncExternalStore(cache.subscribe, cache.getVersion);
  const [sel, setSel] = useState<Selection>(single({ r: 0, c: 0 }));

  const active = sel.active;
  const address = `${columnLetters(active.c)}${active.r + 1}`;
  const raw = (void version, cellRaw(cache.getCell(active.r, active.c).cell));
  const b = boundsOf(sel);
  const multi = b.r0 !== b.r1 || b.c0 !== b.c1;
  const sum = (void version, summarize(cache, b));

  return (
    <>
      <header className="wbs-top">
        <Button onClick={() => navigate("/workspaces")}>{t("workbook.back")}</Button>
        <h1 className="wbs-name"><bdi>{name}</bdi></h1>
        <span className="spacer" />
        <Button disabled title={t("shell.undoDisabled")} aria-label={t("shell.undo")}>↶</Button>
        <Button disabled title={t("shell.redoDisabled")} aria-label={t("shell.redo")}>↷</Button>
        <Button disabled title={t("shell.findSoon")}>{t("shell.find")}</Button>
        {hasReport ? (
          <Button onClick={() => setPanel(panel === "report" ? null : "report")} aria-pressed={panel === "report"}>
            {t("shell.report")}
          </Button>
        ) : null}
      </header>
      <div className="wbs-formula" role="group" aria-label={t("shell.formulaBar")}>
        <span className="wbs-addr" dir="ltr" aria-label={t("shell.cellAddress")}>{address}</span>
        <input className="wbs-value" readOnly value={raw} dir="auto" aria-label={t("shell.formulaBar")} />
      </div>
      <div className="wbs-grid gv-host">
        <Grid source={source} cache={cache} rtl={sheet.rtl} onSelectionChange={setSel} />
      </div>
      <div className="wbs-status" role="status" aria-label={t("shell.statusBar")}>
        {multi && sum.count > 0 ? (
          <span>
            {t("status.summary", {
              count: formatNumber(sum.count, digits, 0),
              sum: formatNumber(sum.sum, digits, 6),
              avg: sum.average === null ? "—" : formatNumber(sum.average, digits, 6),
            })}
            {sum.partial ? ` · ${t("status.partial")}` : ""}
          </span>
        ) : null}
      </div>
    </>
  );
}
