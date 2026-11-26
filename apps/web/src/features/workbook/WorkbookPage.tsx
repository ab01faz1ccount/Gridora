import type { CellEdit, FormatChange, SheetMeta, StyleInfo } from "@contracts";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { api, ApiError } from "@/api/client";
import { errorKey } from "@/api/errors";
import { useWorkbook } from "@/api/hooks";
import { navigate } from "@/app/router";
import { Button } from "@/components/Button";
import { Grid, type GridHandle } from "@/grid/Grid";
import { sheetDataSource } from "@/grid/datasource";
import { WorkbookEditor } from "@/grid/editing";
import { editFor } from "@/grid/parseInput";
import { columnLetters } from "@/grid/geometry";
import { boundsOf, single, type FillPlan, type Selection } from "@/grid/selection";
import { cellRaw, summarize } from "@/grid/summary";
import { CompatPanel } from "@/features/import/CompatPanel";
import { StyleStore } from "@/grid/styles";
import { FindBar } from "./FindBar";
import { FormatBar } from "./FormatBar";
import { OperationPanel } from "@/features/operations/OperationPanel";
import { ChartsPanel } from "@/features/charts/ChartsPanel";
import { ExportPanel } from "@/features/export/ExportPanel";
import { TablesPanel } from "@/features/tables/TablesPanel";
import { ToolsPanel } from "@/features/tools/ToolsPanel";
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
        hasReport={Boolean(report)} workspaceId={wb.data.workspace_id} />
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
  workspaceId,
}: {
  name: string;
  sheet: SheetMeta;
  source: ReturnType<typeof sheetDataSource>;
  editor: WorkbookEditor;
  hasReport: boolean;
  workspaceId: string | undefined;
}) {
  const t = useT();
  const digits = usePrefs((s) => s.digits);
  const panel = useUi((s) => s.panel);
  const setPanel = useUi((s) => s.setPanel);
  const push = useUi((s) => s.pushToast);
  // Same cache object for the life of the sheet; a grown sheet only swaps its dimensions in.
  const cache = useMemo(() => editor.caches.get(sheet.id, source), [editor, sheet.id, source]);
  const ed = useSyncExternalStore(editor.subscribe, editor.getSnapshot);
  // Looks (font, colours ...) behind the format ids that cells carry, fetched once per id.
  const styles = useMemo(
    () => new StyleStore((ids) => api.get<StyleInfo[]>(`/workbooks/${editor.workbookId}/styles`, { query: { ids: ids.join(",") } })),
    [editor],
  );
  useEffect(() => () => styles.dispose(), [styles]);
  useSyncExternalStore(styles.subscribe, styles.getVersion);
  const version = useSyncExternalStore(cache.subscribe, cache.getVersion);
  const [sel, setSel] = useState<Selection>(single({ r: 0, c: 0 }));
  const [taskQuery, setTaskQuery] = useState("");
  const [finding, setFinding] = useState(false);
  const gridRef = useRef<GridHandle>(null);
  // Ctrl+F (by physical key, so also on a Persian layout) opens Find instead of the browser's own
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.code === "KeyF" && !e.shiftKey) {
        e.preventDefault();
        setFinding(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const taskRef = useRef<HTMLInputElement>(null);
  // Ctrl+K (any keyboard layout) jumps to "what do you want to do?"
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.code === "KeyK") {
        e.preventDefault();
        taskRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const active = sel.active;
  const address = `${columnLetters(active.c)}${active.r + 1}`;
  const raw = (void version, cellRaw(cache.getCell(active.r, active.c).cell));
  const b = boundsOf(sel);
  const multi = b.r0 !== b.r1 || b.c0 !== b.c1;
  const sum = (void version, summarize(cache, b));

  const qc = useQueryClient();
  const fr = sheet.frozen?.rows ?? 0;
  const fcols = sheet.frozen?.cols ?? 0;
  const freezeValue = fr === 0 && fcols === 0 ? "none" : fr === 1 && fcols === 0 ? "row"
    : fr === 0 && fcols === 1 ? "col" : fr === 1 && fcols === 1 ? "both" : "custom";
  const freeze = (how: string) => {
    const [rows, cols] = how === "row" ? [1, 0] : how === "col" ? [0, 1] : how === "both" ? [1, 1]
      : how === "here" ? [active.r, active.c] : how === "custom" ? [fr, fcols] : [0, 0];
    api.put(`/workbooks/${editor.workbookId}/sheets/${sheet.id}/frozen`, { rows: Math.min(rows, 100), cols: Math.min(cols, 26) })
      .then(() => qc.invalidateQueries({ queryKey: ["workbook", editor.workbookId] }))
      .catch(fail);
  };
  const restructure = (how: string) => {
    const nr = b.r1 - b.r0 + 1;
    const nc = b.c1 - b.c0 + 1;
    const [axis, op, at, count] = how === "insertRowAbove" ? ["row", "insert", b.r0, nr]
      : how === "insertRowBelow" ? ["row", "insert", b.r1 + 1, nr]
      : how === "deleteRows" ? ["row", "delete", b.r0, nr]
      : how === "insertColLeft" ? ["col", "insert", b.c0, nc]
      : how === "insertColRight" ? ["col", "insert", b.c1 + 1, nc]
      : ["col", "delete", b.c0, nc];
    editor
      .write(`/workbooks/${editor.workbookId}/sheets/${sheet.id}/structure`, (base_seq) => ({ base_seq, axis, op, at, count }))
      .catch(fail);
  };
  const fail = (e: unknown) => {
    if (e instanceof ApiError && e.code === "version_conflict") return; // the banner says it, in more words
    push("error", e instanceof RangeError ? t("edit.rangeTooLarge") : t(errorKey(e)));
  };
  const paste = (edits: CellEdit[]) => {
    editor.edit(sheet.id, edits).catch(fail);
  };
  const fill = (plan: FillPlan) => {
    const range = (x: typeof b) => ({ sheet_id: sheet.id, r0: x.r0, c0: x.c0, r1: x.r1, c1: x.c1 });
    editor
      .write(`/workbooks/${editor.workbookId}/sheets/${sheet.id}/fill`, (base_seq) => ({
        base_seq, source: range(plan.source), target: range(plan.target),
      }))
      .catch(fail);
  };
  const format = (change: FormatChange) => {
    editor
      .write(`/workbooks/${editor.workbookId}/sheets/${sheet.id}/format`, (base_seq) => ({
        base_seq, range: { sheet_id: sheet.id, r0: b.r0, c0: b.c0, r1: b.r1, c1: b.c1 }, change,
      }))
      .catch(fail);
  };
  const activeCell = (void version, cache.getCell(active.r, active.c).cell);
  styles.need(activeCell?.s);
  const look = styles.get(activeCell?.s);
  const formatKey = (k: "bold" | "italic" | "underline" | "strike") => format({ [k]: !look?.[k] });
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
        <Button onClick={() => setFinding(!finding)} aria-pressed={finding}>{t("shell.find")}</Button>
        <select aria-label={t("freeze.label")} value={freezeValue} onChange={(e) => freeze(e.target.value)}>
          <option value="none">{t("freeze.none")}</option>
          <option value="row">{t("freeze.row")}</option>
          <option value="col">{t("freeze.col")}</option>
          <option value="both">{t("freeze.both")}</option>
          <option value="here">{t("freeze.here")}</option>
          {freezeValue === "custom" ? <option value="custom">{t("freeze.custom")}</option> : null}
        </select>
        <select aria-label={t("structure.label")} value="" onChange={(e) => e.target.value && restructure(e.target.value)}>
          <option value="">{t("structure.label")}</option>
          {(["insertRowAbove", "insertRowBelow", "deleteRows", "insertColLeft", "insertColRight", "deleteCols"] as const).map((k) => (
            <option key={k} value={k}>{t(`structure.${k}`)}</option>
          ))}
        </select>
        {(["tables", "charts", "tools", "export"] as const).map((k) => (
          <Button key={k} onClick={() => setPanel(panel === k ? null : k)} aria-pressed={panel === k}>{t(`shell.${k}`)}</Button>
        ))}
        {hasReport ? (
          <Button onClick={() => setPanel(panel === "report" ? null : "report")} aria-pressed={panel === "report"}>
            {t("shell.report")}
          </Button>
        ) : null}
      </header>
      <form className="wbs-task" role="search" onSubmit={(e) => {
        e.preventDefault();
        setPanel("operations");
      }}>
        <input ref={taskRef} type="search" className="wbs-task-input" value={taskQuery}
          aria-label={t("taskbar.label")} placeholder={t("taskbar.placeholder")}
          onChange={(e) => {
            setTaskQuery(e.target.value);
            setPanel("operations");
          }} />
        <Button onClick={() => setPanel(panel === "operations" ? null : "operations")} aria-pressed={panel === "operations"}>
          {t("taskbar.all")}
        </Button>
      </form>
      {panel === "operations" ? (
        <aside className="wbs-panel" aria-label={t("opPanel.title")}>
          <OperationPanel workbookId={editor.workbookId} sheet={sheet} bounds={b} cache={cache} editor={editor}
            query={taskQuery} onClose={() => setPanel(null)} />
        </aside>
      ) : null}
      {panel === "export" ? (
        <aside className="wbs-panel" aria-label={t("export.title")}>
          <ExportPanel workbookId={editor.workbookId} sheet={sheet} onClose={() => setPanel(null)} />
        </aside>
      ) : null}
      {panel === "charts" ? (
        <aside className="wbs-panel" aria-label={t("charts.title")}>
          <ChartsPanel workbookId={editor.workbookId} sheet={sheet} bounds={b} cache={cache} onClose={() => setPanel(null)} />
        </aside>
      ) : null}
      {panel === "tables" ? (
        <aside className="wbs-panel" aria-label={t("tables.title")}>
          <TablesPanel workspaceId={workspaceId} workbookId={editor.workbookId} sheet={sheet} bounds={b} active={active}
            editor={editor} onClose={() => setPanel(null)} />
        </aside>
      ) : null}
      {panel === "tools" ? (
        <aside className="wbs-panel" aria-label={t("tools.title")}>
          <ToolsPanel workbookId={editor.workbookId} sheet={sheet} bounds={b} editor={editor} onClose={() => setPanel(null)} />
        </aside>
      ) : null}
      {ed.conflict ? (
        <div className="wbs-conflict" role="alert">
          <div>
            <strong>{t("conflict.title")}</strong>
            <div>{t("conflict.body")}</div>
          </div>
          <Button onClick={() => editor.dismissConflict()}>{t("common.dismiss")}</Button>
        </div>
      ) : null}
      <FormatBar look={look} onChange={format} />
      {finding ? (
        <FindBar workbookId={editor.workbookId} sheetId={sheet.id} active={sel.active}
          onGo={(r, c) => gridRef.current?.goTo(r, c)}
          onClose={() => { setFinding(false); document.querySelector<HTMLElement>("[role=grid]")?.focus(); }} />
      ) : null}
      <div className="wbs-formula" role="group" aria-label={t("shell.formulaBar")}>
        <span className="wbs-addr" dir="ltr" aria-label={t("shell.cellAddress")}>{address}</span>
        <ValueBar key={`${active.r}:${active.c}`} raw={raw} label={t("shell.formulaBar")}
          onCommit={(text) => commit(active.r, active.c, text)} />
      </div>
      <div className="wbs-grid gv-host">
        <Grid source={source} cache={cache} rtl={sheet.rtl} onSelectionChange={setSel} handleRef={gridRef} onFill={fill} frozen={sheet.frozen} styles={styles} onFormatKey={formatKey}
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
