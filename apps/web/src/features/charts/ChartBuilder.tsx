// The Chart Builder: data -> chart type -> columns -> live preview -> optional settings -> save.
// Simple by default: the profile fills the obvious choices, the preview updates as you change them, and
// everything advanced sits in one collapsed section that shows only what the chosen chart type can use.
import type { ChartColumnProfile, ChartSpec } from "@contracts";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { errorKey } from "@/api/errors";
import { createChart, previewChart, profileChartSource, updateChart } from "@/api/panels";
import { Button } from "@/components/Button";
import { useT, type MessageKey } from "@/i18n";
import { ChartView } from "./ChartView";
import {
  AGGREGATES, FILTER_OPS, GROUPS, KINDS, capabilities, draftFromSuggestion, draftToSpec, isTime, missing, newDraft,
  problemOf, specToDraft, switchType, type Draft, type DraftFilter, type Field, type Kind, type Problem,
} from "./builderModel";

export interface SourceChoice { id: string; label: string; source: ChartSpec["source"] }

interface Props {
  documentId: string;
  sources: SourceChoice[]; // what the chart can read; the first one is used unless a chart is being edited
  initial?: ChartSpec; // editing a saved chart: its own source is kept
  onSaved: (id: string | undefined) => void;
  onCancel: () => void;
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const h = setTimeout(() => setV(value), ms);
    return () => clearTimeout(h);
  }, [value, ms]);
  return v;
}

export function ChartBuilder({ documentId, sources, initial, onSaved, onCancel }: Props) {
  const t = useT();
  const [sourceId, setSourceId] = useState(sources[0]?.id ?? "");
  const choice = sources.find((s) => s.id === sourceId) ?? sources[0];
  const source = initial?.source ?? choice?.source;
  const profile = useQuery({
    queryKey: ["chart-profile", documentId, JSON.stringify(source)], enabled: Boolean(source), retry: false,
    queryFn: () => profileChartSource(documentId, source!),
  });
  const cols = useMemo(() => profile.data?.columns ?? [], [profile.data]);
  const suggestions = useMemo(() => profile.data?.suggestions ?? [], [profile.data]);
  // First draft once the columns are known: the saved chart, else the best suggestion, else a plain bar chart.
  // Edits sit on top of it and are dropped on their own when the data (or the chart being edited) changes.
  const base = useMemo<Draft | null>(() => {
    if (!profile.data) return null;
    if (initial) return specToDraft(initial, cols);
    return suggestions[0] ? draftFromSuggestion(suggestions[0], cols) : newDraft("bar", cols);
  }, [profile.data, initial, cols, suggestions]);
  const [edited, setEdited] = useState<{ from: Draft | null; draft: Draft } | null>(null);
  const draft = edited && edited.from === base ? edited.draft : base;
  const setDraft = (d: Draft) => setEdited({ from: base, draft: d });
  const [saved, setSaved] = useState<{ for: Draft; problem: Problem } | null>(null);
  const saveProblem = saved && saved.for === draft ? saved.problem : null;

  const ctx = useMemo(() => (source ? { documentId, source, columns: cols } : null), [documentId, source, cols]);
  const spec = useMemo(() => (draft && ctx ? draftToSpec(draft, ctx, initial?.id) : null), [draft, ctx, initial?.id]);
  const need = draft ? missing(draft) : [];
  const ready = Boolean(spec) && need.length === 0;
  const debounced = useDebounced(spec, 350);
  const preview = useQuery({
    queryKey: ["chart-preview", documentId, JSON.stringify(debounced)],
    enabled: ready && Boolean(debounced), retry: false, placeholderData: keepPreviousData,
    queryFn: () => previewChart(documentId, debounced!),
  });
  const problem: Problem | null = (preview.isError && draft ? problemOf(preview.error, draft, cols) : null) ?? saveProblem;

  if (!source) return <p className="muted">{t("charts.needRange")}</p>;
  if (profile.isPending) return <p className="muted" role="status">{t("charts.profileLoading")}</p>;
  if (profile.isError) return (
    <div>
      <p role="alert">{t("charts.profileError")}</p>
      <Button onClick={onCancel}>{t("common.cancel")}</Button>
    </div>
  );
  if (!draft || !spec) return null;

  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });
  const cap = capabilities(draft.type);
  const timeAxis = isTime(draft, cols);
  const fieldProblem = (f: Field) => (problem?.field === f ? <ProblemText problem={problem} /> : null);
  const save = () => {
    const run = initial?.id ? updateChart(initial.id, spec) : createChart(documentId, spec);
    run.then((c) => onSaved(c.id), (e: unknown) => {
      setSaved({ for: draft, problem: problemOf(e, draft, cols) ?? { field: "other", message: t(errorKey(e)) } });
    });
  };
  const recommended = [...new Set(suggestions.map((s) => s.type))];

  return (
    <form className="panel cb" onSubmit={(e) => { e.preventDefault(); if (ready) save(); }}>
      {sources.length > 1 && !initial ? (
        <fieldset className="cb-section">
          <legend>{t("charts.step.source")}</legend>
          {sources.map((s) => (
            <label key={s.id} className="check">
              <input type="radio" name="cb-source" checked={sourceId === s.id} onChange={() => setSourceId(s.id)} /> {s.label}
            </label>
          ))}
          <p className="muted">{t("charts.source.headerRow")}</p>
        </fieldset>
      ) : (
        <p className="muted">{initial ? "" : `${choice?.label ?? ""} `}{t("charts.source.headerRow")}</p>
      )}

      <fieldset className="cb-section">
        <legend>{t("charts.step.type")}</legend>
        {recommended.length ? <p className="muted">{t("charts.recommended")}</p> : null}
        {recommended.length ? <Gallery kinds={recommended} current={draft.type} onPick={(k) => setDraft(switchType(draft, k, cols, suggestions))} star /> : null}
        {GROUPS.map((g) => {
          const kinds = KINDS.filter((k) => k.group === g).map((k) => k.type);
          return kinds.length ? (
            <div key={g}>
              <p className="muted cb-group">{t(`charts.group.${g}` as MessageKey)}</p>
              <Gallery kinds={kinds} current={draft.type} onPick={(k) => setDraft(switchType(draft, k, cols, suggestions))} />
            </div>
          ) : null;
        })}
      </fieldset>

      <fieldset className="cb-section">
        <legend>{t("charts.step.fields")}</legend>
        {cap.categoryRole !== "none" ? (
          <ColumnSelect label={t(cap.categoryRole === "x" ? "charts.role.x" : cap.categoryRole === "group" ? "charts.role.group" : timeAxis ? "charts.role.time" : "charts.role.category")}
            cols={cols} value={draft.category} optional={cap.categoryRole === "group"}
            onChange={(v) => set({ category: v, values: draft.values.filter((x) => x !== v) })} />
        ) : null}
        {need.includes("category") ? <p className="muted">{t("charts.needCategory")}</p> : null}
        {fieldProblem("category")}
        {cap.multiValues ? (
          <fieldset className="field">
            <legend>{t(cap.categoryRole === "x" ? "charts.role.y" : "charts.role.values")}</legend>
            {cols.filter((c) => c.index !== draft.category && c.kind !== "empty").map((c) => (
              <label key={c.index} className="check">
                <input type="checkbox" checked={draft.values.includes(c.index)}
                  onChange={() => set(draft.values.includes(c.index)
                    ? { values: draft.values.filter((x) => x !== c.index), splitBy: null }
                    : { values: [...draft.values, c.index].sort((a, b) => a - b), splitBy: null,
                        aggregates: { ...draft.aggregates, [c.index]: draft.aggregates[c.index] ?? (draft.type === "scatter" ? "none" : (c.default_aggregate ?? "sum")) } })} />{" "}
                <bdi>{c.name}</bdi>
              </label>
            ))}
          </fieldset>
        ) : (
          <ColumnSelect label={t(cap.bins || cap.outliers ? "charts.role.distValue" : "charts.role.value")}
            cols={cols.filter((c) => c.index !== draft.category && (!(cap.bins || cap.outliers) || c.kind === "number"))} value={draft.values[0] ?? null}
            onChange={(v) => set({ values: v === null ? [] : [v] })} />
        )}
        {need.includes("values") && !need.includes("category") ? <p className="muted">{t("charts.needValues")}</p> : null}
        {fieldProblem("values")}
      </fieldset>

      <section className="cb-section" aria-label={t("charts.step.preview")} aria-live="polite">
        <h3>{t("charts.step.preview")}</h3>
        {!ready ? <p className="muted">{t("charts.previewEmpty")}</p> : null}
        {ready && preview.isFetching ? <p className="muted" role="status">{t("charts.previewing")}</p> : null}
        {ready && preview.data && !(preview.isError) ? <ChartView spec={spec} data={preview.data} /> : null}
        {problem && (problem.field === "other" || problem.field === "source" || !visibleField(problem.field)) ? <ProblemText problem={problem} /> : null}
      </section>

      <details className="cb-more">
        <summary>{t("charts.step.more")}</summary>
        <label className="field">{t("charts.titleField")}
          <input value={draft.title} onChange={(e) => set({ title: e.target.value })} dir="auto" />
        </label>
        {cap.aggregate ? (
          <fieldset className="field">
            <legend>{t("charts.agg.label")}</legend>
            {draft.values.length > 1 ? draft.values.map((v) => (
              <Select key={v} label={cols.find((c) => c.index === v)?.name ?? `#${v + 1}`} value={draft.aggregates[v] ?? draft.aggregate}
                onChange={(a) => set({ aggregates: { ...draft.aggregates, [v]: a as Draft["aggregate"] } })}
                options={AGGREGATES.map((a) => [a, t(`charts.agg.${a}` as MessageKey)])} />
            )) : (
              <Select label={t("charts.agg.label")} hideLabel value={draft.aggregates[draft.values[0] ?? -1] ?? draft.aggregate}
                onChange={(a) => set({ aggregate: a as Draft["aggregate"], aggregates: draft.values[0] === undefined ? {} : { [draft.values[0]]: a as Draft["aggregate"] } })}
                options={AGGREGATES.map((a) => [a, t(`charts.agg.${a}` as MessageKey)])} problem={fieldProblem("aggregate")} />
            )}
            {draft.values.length > 1 ? fieldProblem("aggregate") : null}
          </fieldset>
        ) : null}
        {cap.splitBy && draft.values.length === 1 ? (
          <ColumnSelect label={t(cap.categoryRole === "x" ? "charts.role.color" : "charts.role.split")} cols={cols.filter((c) => c.index !== draft.category && c.index !== draft.values[0])}
            value={draft.splitBy} onChange={(v) => set({ splitBy: v })} optional problem={fieldProblem("splitBy")} />
        ) : null}
        {timeAxis && cap.time ? (
          <>
            <Select label={t("charts.time.step")} value={draft.granularity ?? ""} onChange={(v) => set({ granularity: (v || null) as Draft["granularity"] })}
              options={[["", t("charts.time.asIs")], ...(["day", "month", "quarter", "year"] as const).map((g): [string, string] => [g, t(`charts.time.${g}` as MessageKey)])]} />
            <Select label={t("charts.time.calendar")} value={draft.calendar} onChange={(v) => set({ calendar: v as Draft["calendar"] })}
              options={[["gregorian", t("charts.time.gregorian")], ["jalali", t("charts.time.jalali")]]} />
            {fieldProblem("time")}
          </>
        ) : null}
        {cap.bins ? (
          <fieldset className="field">
            <Select label={t("charts.bins.label")} value={draft.binMode} onChange={(v) => set({ binMode: v as Draft["binMode"] })}
              options={[["auto", t("charts.bins.auto")], ["count", t("charts.bins.count")], ["width", t("charts.bins.width")]]} />
            {draft.binMode === "count" ? (
              <NumberField label={t("charts.bins.n")} value={draft.bins} min={2} max={200} integer onCommit={(n) => set({ bins: n })} />
            ) : null}
            {draft.binMode === "width" ? (
              <NumberField label={t("charts.bins.w")} value={draft.binWidth} min={Number.MIN_VALUE} onCommit={(n) => set({ binWidth: n })} />
            ) : null}
            {fieldProblem("bins")}
          </fieldset>
        ) : null}
        {cap.percent ? <label className="check"><input type="checkbox" checked={draft.asPercent} onChange={(e) => set({ asPercent: e.target.checked })} /> {t("charts.percent")}</label> : null}
        {cap.outliers ? <label className="check"><input type="checkbox" checked={draft.outliers} onChange={(e) => set({ outliers: e.target.checked })} /> {t("charts.outliers")}</label> : null}
        {cap.sort ? (
          <div className="cb-row">
            <Select label={t("charts.sort.by")} value={draft.sortBy} onChange={(v) => set({ sortBy: v as Draft["sortBy"] })}
              options={[["source", t("charts.sort.source")], ["category", t("charts.sort.category")], ["value", t("charts.sort.value")]]} />
            {draft.sortBy !== "source" ? (
              <Select label={t("charts.sort.dir")} hideLabel value={draft.sortDir} onChange={(v) => set({ sortDir: v as Draft["sortDir"] })}
                options={[["asc", t("charts.sort.asc")], ["desc", t("charts.sort.desc")]]} />
            ) : null}
          </div>
        ) : null}
        {cap.limit && !timeAxis ? (
          <fieldset className="field">
            <label className="check"><input type="checkbox" checked={draft.topN !== null} onChange={(e) => set({ topN: e.target.checked ? 10 : null, other: false })} /> {t("charts.limit.use")}</label>
            {draft.topN !== null ? (
              <div className="cb-row">
                <Select label={t("charts.limit.end")} hideLabel value={draft.topEnd} onChange={(v) => set({ topEnd: v as Draft["topEnd"] })} options={[["top", t("charts.limit.top")], ["bottom", t("charts.limit.bottom")]]} />
                <NumberField label={t("charts.limit.n")} value={draft.topN} min={1} max={500} integer onCommit={(n) => set({ topN: n })} />
                <label className="check"><input type="checkbox" checked={draft.other} onChange={(e) => set({ other: e.target.checked })} /> {t("charts.limit.other")}</label>
              </div>
            ) : null}
            {fieldProblem("limit")}
          </fieldset>
        ) : null}
        {cap.stack && draft.values.length + (draft.splitBy === null ? 0 : 2) > 1 ? (
          <Select label={t("charts.stack.label")} value={draft.stack} onChange={(v) => set({ stack: v as Draft["stack"] })}
            options={[["none", t("charts.stack.none")], ["stacked", t("charts.stack.stacked")], ["percent", t("charts.stack.percent")]]} />
        ) : null}
        {cap.orientation ? (
          <Select label={t("charts.orientation.label")} value={draft.orientation} onChange={(v) => set({ orientation: v as Draft["orientation"] })}
            options={[["vertical", t("charts.orientation.vertical")], ["horizontal", t("charts.orientation.horizontal")]]} />
        ) : null}
        {cap.labels ? (
          <Select label={t("charts.labels.label")} value={draft.labels} onChange={(v) => set({ labels: v as Draft["labels"] })}
            options={[["none", t("charts.labels.none")], ["value", t("charts.labels.value")], ["percent", t("charts.labels.percent")]]} />
        ) : null}
        {cap.nulls ? (
          <Select label={t("charts.nulls.label")} value={draft.nulls} onChange={(v) => set({ nulls: v as Draft["nulls"] })}
            options={[["gap", t("charts.nulls.gap")], ["zero", t("charts.nulls.zero")]]} />
        ) : null}
        {cap.donut ? <label className="check"><input type="checkbox" checked={draft.donut} onChange={(e) => set({ donut: e.target.checked })} /> {t("charts.donut")}</label> : null}
        {cap.axisTitles ? (
          <>
            <label className="field">{t("charts.axisX")}<input value={draft.axisX} onChange={(e) => set({ axisX: e.target.value })} dir="auto" /></label>
            <label className="field">{t("charts.axisY")}<input value={draft.axisY} onChange={(e) => set({ axisY: e.target.value })} dir="auto" /></label>
          </>
        ) : null}
        <label className="check"><input type="checkbox" checked={draft.legend} onChange={(e) => set({ legend: e.target.checked })} /> {t("charts.legend")}</label>
        <Filters draft={draft} cols={cols} onChange={(filters) => set({ filters })} problem={fieldProblem("filters")} />
      </details>

      <div className="panel-actions">
        <Button type="submit" variant="primary" disabled={!ready}>{t(initial ? "charts.saveChanges" : "charts.save")}</Button>
        <Button onClick={onCancel}>{t("common.cancel")}</Button>
      </div>
    </form>
  );
}

// Fields whose problem is shown right next to the control (inside "More options" or the columns); the rest go below the preview.
function visibleField(f: Field): boolean {
  return ["category", "values", "splitBy", "aggregate", "limit", "time", "filters", "bins"].includes(f);
}

function ProblemText({ problem }: { problem: Problem }) {
  const t = useT();
  const text = problem.key ? t(problem.key, problem.params ?? {}) : problem.message ?? t("error.generic");
  return <p role="alert" className="field-error">{text}{problem.hint && !problem.key ? ` ${problem.hint}` : ""}</p>;
}

function Gallery({ kinds, current, onPick, star }: { kinds: Kind[]; current: Kind; onPick: (k: Kind) => void; star?: boolean }) {
  const t = useT();
  return (
    <div className="cb-gallery" role="radiogroup" aria-label={t("charts.step.type")}>
      {kinds.map((k) => (
        <button key={k} type="button" role="radio" aria-checked={current === k} className="cb-kind" onClick={() => onPick(k)}
          title={t(`charts.kindHint.${k}` as MessageKey)}>
          {star ? "★ " : ""}{t(`charts.type.${k}` as MessageKey)}
        </button>
      ))}
    </div>
  );
}

/** A number box you can clear and retype: only a valid number is passed on, and the box shows the real value again on blur. */
function NumberField({ label, value, min, max, integer, onCommit }: {
  label: string; value: number; min: number; max?: number; integer?: boolean; onCommit: (n: number) => void;
}) {
  const [text, setText] = useState<string | null>(null);
  return (
    <label className="field">{label}
      <input type="number" step={integer ? 1 : "any"} min={integer ? min : undefined} max={max} value={text ?? String(value)}
        onChange={(e) => {
          setText(e.target.value);
          const n = Number(e.target.value);
          if (e.target.value.trim() !== "" && Number.isFinite(n) && n >= min && (max === undefined || n <= max) && (!integer || Number.isInteger(n))) onCommit(n);
        }}
        onBlur={() => setText(null)} />
    </label>
  );
}

function Select({ label, value, onChange, options, problem, hideLabel }: {
  label: string; value: string; onChange: (v: string) => void; options: [string, string][]; problem?: ReactNode; hideLabel?: boolean;
}) {
  return (
    <div className="field">
      <label><span className={hideLabel ? "sr-only" : undefined}>{label}</span>
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
        </select>
      </label>
      {problem}
    </div>
  );
}

function ColumnSelect({ label, cols, value, onChange, optional, problem, hideLabel }: {
  label: string; cols: ChartColumnProfile[]; value: number | null; onChange: (v: number | null) => void; optional?: boolean; problem?: ReactNode;
  hideLabel?: boolean;
}) {
  const t = useT();
  return (
    <div className="field">
      <label><span className={hideLabel ? "sr-only" : undefined}>{label}</span>
        <select value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}>
          <option value="">{optional ? t("charts.noColumn") : t("charts.choose")}</option>
          {cols.filter((c) => c.kind !== "empty").map((c) => <option key={c.index} value={c.index}>{c.name}</option>)}
        </select>
      </label>
      {problem}
    </div>
  );
}

function Filters({ draft, cols, onChange, problem }: { draft: Draft; cols: ChartColumnProfile[]; onChange: (f: DraftFilter[]) => void; problem?: ReactNode }) {
  const t = useT();
  const update = (i: number, patch: Partial<DraftFilter>) => onChange(draft.filters.map((f, k) => (k === i ? { ...f, ...patch } : f)));
  return (
    <fieldset className="field">
      <legend>{t("charts.filter.title")}</legend>
      {draft.filters.map((f, i) => (
        <div key={i} className="cb-row">
          <ColumnSelect label={t("charts.filter.column")} hideLabel cols={cols} value={f.column} onChange={(v) => update(i, { column: v })} />
          <Select label={t("charts.filter.cond")} hideLabel value={f.op} onChange={(v) => update(i, { op: v as DraftFilter["op"] })}
            options={FILTER_OPS.map((o): [string, string] => [o, t(`charts.filter.op.${o}` as MessageKey)])} />
          {f.op !== "is_empty" && f.op !== "is_not_empty" ? (
            <label className="field"><span className="sr-only">{t("charts.filter.value")}</span>
              <input value={f.value} onChange={(e) => update(i, { value: e.target.value })} dir="auto" placeholder={t("charts.filter.value")} />
            </label>
          ) : null}
          <Button onClick={() => onChange(draft.filters.filter((_, k) => k !== i))} aria-label={t("charts.filter.remove")}>×</Button>
        </div>
      ))}
      {draft.filters.length < 5 ? <Button onClick={() => onChange([...draft.filters, { column: null, op: "eq", value: "" }])}>{t("charts.filter.add")}</Button> : null}
      {problem}
    </fieldset>
  );
}
