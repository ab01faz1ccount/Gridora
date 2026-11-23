// The "do something with this data" side panel (docs/UX_SPEC.md 3.1, 4 F3, 5): find an operation by
// what the person wants to do, fill in a generated form, see a preview, apply, undo with one click.
import { SCHEMA_VERSION, type Operation, type PreviewResult, type SheetMeta, type Target } from "@contracts";
import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { ApiError } from "@/api/client";
import { errorKey } from "@/api/errors";
import { previewOperation, useOperationCatalog, useOperationDescriptors } from "@/api/operations";
import { Button } from "@/components/Button";
import type { BlockCache } from "@/grid/block-cache";
import type { WorkbookEditor } from "@/grid/editing";
import { columnLetters } from "@/grid/geometry";
import type { RangeBounds } from "@/grid/selection";
import { useT } from "@/i18n";
import { formatNumber } from "@/i18n/format";
import { usePrefs } from "@/state/prefs";
import { useUi } from "@/state/ui";
import { columnNames } from "./columns";
import { SchemaForm, type FormCtx } from "./SchemaForm";
import { cleanValue, defaultFor, fieldPath, type Schema, type Value } from "./schemaForm";
import { opEntries, searchOps, type OpEntry } from "./searchOps";

const PREVIEW_ROWS = 8;
const MAX_PICKER_COLUMNS = 200;

export interface PanelProps {
  workbookId: string;
  sheet: SheetMeta;
  bounds: RangeBounds;
  cache: BlockCache;
  editor: WorkbookEditor;
  query: string;
  onClose: () => void;
}

/** One cell selected means "this whole table": the operation works on the used area of the sheet. */
export function targetRange(sheet: SheetMeta, b: RangeBounds) {
  const single = b.r0 === b.r1 && b.c0 === b.c1;
  const r1 = Math.max(0, sheet.row_count - 1);
  const c1 = Math.max(0, sheet.col_count - 1);
  return single
    ? { whole: true, r0: 0, c0: 0, r1, c1 }
    : { whole: false, r0: b.r0, c0: b.c0, r1: b.r1, c1: b.c1 };
}

export function OperationPanel(props: PanelProps) {
  const t = useT();
  const locale = usePrefs((s) => s.locale);
  const descriptors = useOperationDescriptors();
  const catalog = useOperationCatalog(locale);
  const [chosen, setChosen] = useState<string | null>(null);
  const entries = useMemo(
    () =>
      descriptors.data && catalog.data
        ? opEntries(descriptors.data.filter((d) => d.targets.includes("sheet_range")), catalog.data)
        : [],
    [descriptors.data, catalog.data],
  );
  const entry = entries.find((e) => e.type === chosen);

  return (
    <section className="panel" aria-labelledby="ops-title">
      <header className="panel-head">
        <h2 id="ops-title">{t("opPanel.title")}</h2>
        <Button onClick={props.onClose} aria-label={t("shell.panelClose")}>{t("shell.panelClose")}</Button>
      </header>
      {descriptors.isPending || catalog.isPending ? <p className="muted">{t("opPanel.loading")}</p> : null}
      {descriptors.isError || catalog.isError ? <p role="alert">{t("opPanel.loadError")}</p> : null}
      {entry && catalog.data ? (
        <OperationForm key={entry.type} {...props} entry={entry} catalog={catalog.data} onBack={() => setChosen(null)} />
      ) : (
        <OperationList entries={entries} query={props.query} onPick={setChosen} />
      )}
    </section>
  );
}

function OperationList({ entries, query, onPick }: { entries: OpEntry[]; query: string; onPick: (type: string) => void }) {
  const t = useT();
  const found = useMemo(() => searchOps(entries, query), [entries, query]);
  if (entries.length === 0) return null;
  if (found.length === 0) return <p className="muted">{t("opPanel.noResults")}</p>;
  return (
    <ul className="op-list">
      {found.map((e) => (
        <li key={e.type}>
          <button type="button" className="op-item" onClick={() => onPick(e.type)}>
            <strong>{e.label}</strong>
            {e.destructive ? <span className="op-tag">{t("opPanel.destructive")}</span> : null}
            <span className="muted">{e.description}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

type PreviewState =
  | { status: "loading" }
  | { status: "ok"; data: PreviewResult }
  | { status: "invalid" }
  | { status: "failed"; message: string }
  | { status: "none" };

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

function OperationForm({
  entry, catalog, workbookId, sheet, bounds, cache, editor, onBack, onClose,
}: PanelProps & { entry: OpEntry; catalog: Record<string, string>; onBack: () => void }) {
  const t = useT();
  const digits = usePrefs((s) => s.digits);
  const push = useUi((s) => s.pushToast);
  const root = entry.descriptor.params_schema as Schema;
  const [value, setValue] = useState<Value>(() => defaultFor(root, root));
  const [touched, setTouched] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [applying, setApplying] = useState(false);
  const [serverErrors, setServerErrors] = useState<{ path: string; message: string }[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [settled, setSettled] = useState<{ wire: string; state: PreviewState } | null>(null);

  const range = targetRange(sheet, bounds);
  const version = useSyncExternalStore(cache.subscribe, cache.getVersion);
  const hasHeader = !(isObj(value) && value["has_header"] === false);
  // `version` changes when the header blocks arrive, so the pickers fill in by themselves
  const columns = (void version, columnNames(Math.min(range.c1 - range.c0 + 1, MAX_PICKER_COLUMNS), hasHeader,
    (i) => cache.getCell(range.r0, range.c0 + i).cell));

  const params = cleanValue(root, root, value);
  const target: Target = {
    kind: "sheet_range",
    range: { sheet_id: sheet.id, r0: range.r0, c0: range.c0, r1: range.r1, c1: range.c1 },
  };
  const operation: Operation = {
    type: entry.type, schema_version: SCHEMA_VERSION, target, extra_targets: [],
    params: isObj(params) ? params : {},
  };

  const issueText = (code: string, message: string): string => catalog[`errors.${code}.message`] ?? message;
  const fromDetails = (e: unknown): { path: string; message: string }[] =>
    e instanceof ApiError ? e.details.map((d) => ({ path: d.path ?? "", message: issueText(d.code, d.message) })) : [];

  // Live preview, a moment after the last change.
  const wire = JSON.stringify(operation);
  const preview: PreviewState = !entry.descriptor.supports_preview
    ? { status: "none" }
    : settled?.wire === wire ? settled.state : { status: "loading" };
  useEffect(() => {
    if (!entry.descriptor.supports_preview) return;
    const ctl = new AbortController();
    const timer = setTimeout(() => {
      previewOperation(workbookId, operation, ctl.signal).then(
        (data) => {
          setSettled({ wire, state: { status: "ok", data } });
          setServerErrors([]);
        },
        (e: unknown) => {
          if (e instanceof DOMException && e.name === "AbortError") return;
          if (e instanceof ApiError && e.code === "validation_failed") {
            setServerErrors(fromDetails(e));
            setSettled({ wire, state: { status: "invalid" } });
          } else {
            setSettled({ wire, state: { status: "failed", message: t(errorKey(e)) } });
          }
        },
      );
    }, 400);
    return () => {
      clearTimeout(timer);
      ctl.abort();
    };
    // `wire` is the serialized operation; the other values are stable for one panel
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wire, workbookId]);

  const errors = new Map<string, string>();
  if (touched) for (const e of serverErrors) {
    const p = fieldPath(e.path);
    if (p && !errors.has(p)) errors.set(p, e.message);
  }
  const loose = touched ? serverErrors.filter((e) => {
    const p = fieldPath(e.path);
    return p === null || p === "/";
  }) : [];

  const ctx: FormCtx = {
    root, t, columns, errors,
    tr: (key) => (typeof key === "string" ? catalog[key] ?? "" : ""),
  };

  const change = (v: Value) => {
    setValue(v);
    setTouched(true);
    setConfirming(false);
    setProblem(null);
  };

  const apply = () => {
    if (entry.destructive && !confirming) {
      setConfirming(true);
      return;
    }
    setApplying(true);
    setProblem(null);
    editor.operate(operation, entry.destructive).then(
      () => {
        push("info", t("opPanel.done"));
        onClose();
      },
      (e: unknown) => {
        setApplying(false);
        setConfirming(false);
        if (e instanceof ApiError && e.code === "validation_failed") {
          setServerErrors(fromDetails(e));
          setTouched(true);
        } else if (e instanceof ApiError && e.code === "version_conflict") {
          // the banner on the sheet explains it
        } else {
          setProblem(t(errorKey(e)));
        }
      },
    );
  };

  const rangeText = `${columnLetters(range.c0)}${range.r0 + 1}:${columnLetters(range.c1)}${range.r1 + 1}`;
  return (
    <div className="op-form">
      <Button onClick={onBack}>{t("opPanel.back")}</Button>
      <h3>{entry.label}</h3>
      <p className="muted">{entry.description}</p>
      <p className="op-where">
        <span dir="ltr">{t(range.whole ? "opPanel.whereWhole" : "opPanel.where", { range: rangeText })}</span>
      </p>
      <SchemaForm ctx={ctx} value={value} onChange={change} />
      {loose.length > 0 ? (
        <ul className="field-error" role="alert">{loose.map((e, i) => <li key={i}>{e.message}</li>)}</ul>
      ) : null}
      <PreviewBox state={preview} digits={digits} />
      {entry.destructive && confirming ? <p className="op-confirm" role="status">{t("opPanel.confirmNote")}</p> : null}
      {problem ? <p className="field-error" role="alert">{problem}</p> : null}
      <Button variant={entry.destructive && confirming ? "danger" : "primary"} onClick={apply} disabled={applying}>
        {applying ? t("opPanel.applying") : entry.destructive && confirming ? t("opPanel.applyConfirm") : t("opPanel.apply")}
      </Button>
    </div>
  );
}

function PreviewBox({ state, digits }: { state: PreviewState; digits: Parameters<typeof formatNumber>[1] }) {
  const t = useT();
  if (state.status === "none") return <p className="muted">{t("opPanel.previewUnavailable")}</p>;
  if (state.status === "loading") return <p className="muted" role="status">{t("opPanel.previewLoading")}</p>;
  if (state.status === "invalid") return <p className="muted">{t("opPanel.previewInvalid")}</p>;
  if (state.status === "failed") return <p role="alert">{state.message}</p>;
  const { columns, rows, total_rows, warnings } = state.data;
  const shown = rows.slice(0, PREVIEW_ROWS);
  return (
    <div className="op-preview">
      <h4>{t("opPanel.preview")}</h4>
      {shown.length === 0 ? <p className="muted">{t("opPanel.previewEmpty")}</p> : (
        <div className="op-table-wrap">
          <table className="op-table">
            <thead><tr>{columns.map((c, i) => <th key={i} scope="col" dir="auto">{c}</th>)}</tr></thead>
            <tbody>
              {shown.map((r, i) => (
                <tr key={i}>{r.map((v, j) => <td key={j} dir="auto">{v === null || v === undefined ? "" : String(v)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted">
        {typeof total_rows === "number"
          ? t("opPanel.previewRows", { shown: formatNumber(shown.length, digits, 0), total: formatNumber(total_rows, digits, 0) })
          : t("opPanel.previewRowsUnknown")}
      </p>
      {warnings.length > 0 ? (
        <ul className="op-warnings">{warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
      ) : null}
    </div>
  );
}
