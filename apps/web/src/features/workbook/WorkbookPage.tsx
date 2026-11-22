import type { CellEdit, SheetMeta } from "@contracts";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { ApiError } from "@/api/client";
import { errorKey } from "@/api/errors";
import { useWorkbook } from "@/api/hooks";
import { navigate } from "@/app/router";
import { Button } from "@/components/Button";
import { Grid } from "@/grid/Grid";
import { sheetDataSource } from "@/grid/datasource";
import { WorkbookEditor } from "@/grid/editing";
import { editFor } from "@/grid/parseInput";
import { columnLetters } from "@/grid/geometry";
import { boundsOf, single, type Selection } from "@/grid/selection";
import { cellRaw, summarize } from "@/grid/summary";
import { CompatPanel } from "@/features/import/CompatPanel";
import { HistoryPanel } from "./HistoryPanel";
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
  const qc = useQueryClient();
  // One editor per open workbook: it owns the per-sheet caches, the undo state and the request queue.
  const editor = useMemo(
    () =>
      new WorkbookEditor(id, () => {
        void qc.invalidateQueries({ queryKey: ["workbook", id] });
        void qc.invalidateQueries({ queryKey: ["history", id] });
      }),
    [id, qc],
  );
  useEffect(() => () => editor.dispose(), [editor]);
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
      <WorkbookView key={`${id}:${sheet.id}`} name={wb.data.name} sheet={sheet} source={source} editor={editor}
        hasReport={Boolean(report)} />
      {panel === "report" && report ? (
        <aside className="wbs-panel" aria-label={t("shell.report")}>
          <CompatPanel report={report} onClose={() => setPanel(null)} />
        </aside>
      ) : null}
      {panel === "history" ? (
        <aside className="wbs-panel" aria-label={t("shell.history")}>
          <HistoryPanel id={id} onClose={() => setPanel(null)} />
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
  editor,
  hasReport,
}: {
  name: string;
  sheet: SheetMeta;
  source: ReturnType<typeof sheetDataSource>;
  editor: WorkbookEditor;
  hasReport: boolean;
}) {
  const t = useT();
  const digits = usePrefs((s) => s.digits);
  const panel = useUi((s) => s.panel);
  const setPanel = useUi((s) => s.setPanel);
  const push = useUi((s) => s.pushToast);
  // Same cache object for the life of the sheet; a grown sheet only swaps its dimensions in.
  const cache = useMemo(() => editor.caches.get(sheet.id, source), [editor, sheet.id, source]);
  const ed = useSyncExternalStore(editor.subscribe, editor.getSnapshot);
  const version = useSyncExternalStore(cache.subscribe, cache.getVersion);
  const [sel, setSel] = useState<Selection>(single({ r: 0, c: 0 }));

  const active = sel.active;
  const address = `${columnLetters(active.c)}${active.r + 1}`;
  const raw = (void version, cellRaw(cache.getCell(active.r, active.c).cell));
  const b = boundsOf(sel);
  const multi = b.r0 !== b.r1 || b.c0 !== b.c1;
  const sum = (void version, summarize(cache, b));

  const fail = (e: unknown) => {
    if (e instanceof ApiError && e.code === "version_conflict") return; // the banner says it, in more words
    push("error", e instanceof RangeError ? t("edit.rangeTooLarge") : t(errorKey(e)));
  };
  const paste = (edits: CellEdit[]) => {
    editor.edit(sheet.id, edits).catch(fail);
  };
  const clipboardProblem = (reason: "notLoaded" | "tooLarge") =>
    push("error", t(reason === "notLoaded" ? "clipboard.notLoaded" : "clipboard.tooLarge"));
  const commit = (r: number, c: number, text: string) => {
    editor.edit(sheet.id, [editFor(r, c, text)]).catch(fail);
  };
  const clear = (rb: typeof b) => {
    editor.clear(sheet.id, rb).catch(fail);
  };
  const undo = () => {
    if (ed.canUndo) editor.undo().catch(fail);
  };
  const redo = () => {
    if (ed.canRedo) editor.redo().catch(fail);
  };

  return (
    <>
      <header className="wbs-top">
        <Button onClick={() => navigate("/workspaces")}>{t("workbook.back")}</Button>
        <h1 className="wbs-name"><bdi>{name}</bdi></h1>
        <span className="spacer" />
        <Button disabled={!ed.canUndo} onClick={undo} title={ed.canUndo ? t("shell.undo") : t("shell.undoDisabled")}
          aria-label={t("shell.undo")}>↶</Button>
        <Button disabled={!ed.canRedo} onClick={redo} title={ed.canRedo ? t("shell.redo") : t("shell.redoDisabled")}
          aria-label={t("shell.redo")}>↷</Button>
        <Button onClick={() => setPanel(panel === "history" ? null : "history")} aria-pressed={panel === "history"}>
          {t("shell.history")}
        </Button>
        <Button disabled title={t("shell.findSoon")}>{t("shell.find")}</Button>
        {hasReport ? (
          <Button onClick={() => setPanel(panel === "report" ? null : "report")} aria-pressed={panel === "report"}>
            {t("shell.report")}
          </Button>
        ) : null}
      </header>
      {ed.conflict ? (
        <div className="wbs-conflict" role="alert">
          <div>
            <strong>{t("conflict.title")}</strong>
            <div>{t("conflict.body")}</div>
          </div>
          <Button onClick={() => editor.dismissConflict()}>{t("common.dismiss")}</Button>
        </div>
      ) : null}
      <div className="wbs-formula" role="group" aria-label={t("shell.formulaBar")}>
        <span className="wbs-addr" dir="ltr" aria-label={t("shell.cellAddress")}>{address}</span>
        <ValueBar key={`${active.r}:${active.c}`} raw={raw} label={t("shell.formulaBar")}
          onCommit={(text) => commit(active.r, active.c, text)} />
      </div>
      <div className="wbs-grid gv-host">
        <Grid source={source} cache={cache} rtl={sheet.rtl} onSelectionChange={setSel}
          onEdit={commit} onClear={clear} onUndo={undo} onRedo={redo}
          onPaste={paste} onClipboardProblem={clipboardProblem} />
      </div>
      <div className="wbs-status" role="status" aria-label={t("shell.statusBar")}>
        <span className="muted">
          {ed.pending > 0 ? t("shell.saveSaving") : ed.failed ? t("shell.saveError") : ed.canUndo ? t("shell.saveSaved") : ""}
        </span>
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

/**
 * The value bar above the grid: shows the active cell as typed (formula text if it has one) and
 * edits it. Enter saves, Escape puts the old text back, leaving the box saves too. It is keyed by
 * the active cell, so moving the cursor always starts from that cell's content.
 */
function ValueBar({ raw, label, onCommit }: { raw: string; label: string; onCommit: (text: string) => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  const cancelled = useRef(false);
  return (
    <input className="wbs-value" value={draft ?? raw} dir="auto" aria-label={label}
      onFocus={() => {
        cancelled.current = false;
        setDraft(raw);
      }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        // every way of leaving the box ends here, so a change is saved exactly once
        if (!cancelled.current && draft !== null && draft !== raw) onCommit(draft);
        setDraft(null);
      }}
      onKeyDown={(e) => {
        if (e.nativeEvent.isComposing) return;
        if (e.key === "Enter") {
          e.preventDefault();
          e.currentTarget.blur();
        } else if (e.key === "Escape") {
          e.preventDefault();
          cancelled.current = true;
          e.currentTarget.blur();
        }
      }} />
  );
}
