// Draws the plain `ChartData` the server computes as SVG (bar, line, area, scatter, pie).
// No chart library: the data is small and the output must follow the page's colours, digits and direction.
// All arithmetic lives in chartLayout.ts; this file only turns it into shapes, labels and notes.
import type { ChartData, ChartNote, ChartSpec } from "@contracts";
import type { ReactElement } from "react";
import { formatNumber } from "@/i18n/format";
import { useT, type MessageKey } from "@/i18n";
import { usePrefs, type Digits } from "@/state/prefs";
import {
  buildSegments, compact, linePieces, localizeDigits, niceTicks, pickLabelIndexes, pieSlices, shorten, stackMode,
  valueRange, type Seg,
} from "./chartLayout";

const W = 360;
const COLORS = ["var(--accent)", "#c2410c", "#15803d", "#7e22ce", "#0e7490", "#a16207"];
const color = (k: number): string => COLORS[k % COLORS.length]!;

export function ChartView({ spec, data }: { spec: ChartSpec; data: ChartData }) {
  const digits = usePrefs((s) => s.digits);
  const label = spec.title ?? spec.type;
  const empty = data.categories.length === 0 || data.series.length === 0;
  const body = empty ? null : spec.type === "pie" ? <Pie spec={spec} data={data} label={label} digits={digits} />
    : spec.type === "scatter" ? <Scatter spec={spec} data={data} label={label} digits={digits} />
    : <Cartesian spec={spec} data={data} label={label} digits={digits} />;
  return (
    <figure className="chart">
      {body}
      {!empty && spec.type !== "pie" && spec.options.legend && data.series.length > 1 ? (
        <figcaption className="chart-legend">
          {data.series.map((s, k) => <span key={k}><i style={{ background: color(k) }} /><bdi>{s.name}</bdi></span>)}
        </figcaption>
      ) : null}
      <Notes notes={data.notes ?? []} />
    </figure>
  );
}

interface Props { spec: ChartSpec; data: ChartData; label: string; digits: Digits }

const num = (v: number, digits: Digits): string => formatNumber(v, digits, 2);

function AxisTitle({ text, x, y, rotate }: { text?: string; x: number; y: number; rotate?: boolean }) {
  if (!text) return null;
  return <text x={x} y={y} textAnchor="middle" className="chart-text chart-axis-title" transform={rotate ? `rotate(-90 ${x} ${y})` : undefined}>{text}</text>;
}

function Cartesian({ spec, data, label, digits }: Props) {
  const horizontal = spec.type === "bar" && spec.options.orientation === "horizontal";
  const mode = stackMode(spec);
  const n = data.categories.length;
  const values = data.series.map((s) => s.values);
  const names = data.labels ?? data.categories.map(String);
  const segs = buildSegments(values, mode);
  const { lo, hi } = valueRange(segs, mode, spec.type !== "line");
  const axis = niceTicks(lo, hi);
  const titles = spec.options.axis_titles ?? {};
  const k = data.series.length;
  const H = horizontal ? Math.min(900, Math.max(220, 56 + n * Math.max(14, k * 10 + 6))) : 220;
  const pad = {
    l: horizontal ? 84 : 44 + (titles.y ? 14 : 0), r: 12, t: 12,
    b: (horizontal ? 24 : 32) + (titles.x ? 14 : 0),
  };
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;
  const span = axis.hi - axis.lo || 1;
  const vpos = (v: number) => (horizontal ? pad.l + ((v - axis.lo) / span) * plotW : pad.t + (1 - (v - axis.lo) / span) * plotH);
  const band = (horizontal ? plotH : plotW) / n;
  const cpos = (i: number) => (horizontal ? pad.t : pad.l) + (i + 0.5) * band;
  const pct = mode === "percent";
  const tickText = (v: number) => localizeDigits(compact(v), digits) + (pct ? "%" : "");
  const tip = (i: number, s: number, seg: Seg) => {
    const share = pct ? ` (${num(seg.hi - seg.lo, digits)}%)` : "";
    return `${names[i]} — ${data.series[s]!.name}: ${num(seg.v, digits)}${share}`;
  };
  const showLabels = spec.options.labels !== undefined && spec.options.labels !== "none" && n * k <= 24;
  const absTotals = values.map((s) => s.reduce<number>((a, v) => a + Math.abs(v ?? 0), 0));
  const labelText = (seg: Seg, si: number) => {
    if (pct) return `${localizeDigits(compact(seg.hi - seg.lo), digits)}%`;
    if (spec.options.labels === "percent") return `${localizeDigits(((Math.abs(seg.v) / (absTotals[si] || 1)) * 100).toFixed(0), digits)}%`;
    return localizeDigits(compact(seg.v), digits);
  };
  const cats = pickLabelIndexes(n, Math.max(1, Math.floor((horizontal ? plotH / 12 : plotW / 46))));
  const maxChars = horizontal ? 14 : 12;
  const shapes: ReactElement[] = [];

  data.series.forEach((_, si) => {
    const c = color(si);
    if (spec.type === "bar") {
      const grouped = mode === "none";
      const bw = grouped ? (band * 0.8) / k : band * 0.7;
      segs[si]!.forEach((seg, i) => {
        if (!seg) return;
        const off = grouped ? -band * 0.4 + si * bw : -bw / 2;
        const a = vpos(seg.lo);
        const b = vpos(seg.hi);
        const geo = horizontal
          ? { x: Math.min(a, b), y: cpos(i) + off, width: Math.abs(b - a), height: bw }
          : { x: cpos(i) + off, y: Math.min(a, b), width: bw, height: Math.abs(b - a) };
        shapes.push(<rect key={`b${si}-${i}`} {...geo} fill={c}><title>{tip(i, si, seg)}</title></rect>);
        if (showLabels) {
          const mid = grouped ? (seg.v >= 0 ? seg.hi : seg.lo) : (seg.lo + seg.hi) / 2;
          const tx = horizontal ? vpos(mid) + (grouped ? (seg.v >= 0 ? 3 : -3) : 0) : cpos(i) + off + bw / 2;
          const ty = horizontal ? cpos(i) + off + bw / 2 + 3 : vpos(mid) + (grouped ? (seg.v >= 0 ? -3 : 10) : 3);
          const anchor = horizontal ? (grouped ? (seg.v >= 0 ? "start" : "end") : "middle") : "middle";
          shapes.push(<text key={`l${si}-${i}`} x={tx} y={ty} textAnchor={anchor} className="chart-text chart-value">{labelText(seg, si)}</text>);
        }
      });
      return;
    }
    const edge = (seg: Seg) => (seg.v >= 0 ? seg.hi : seg.lo);
    const base = (seg: Seg) => (seg.v >= 0 ? seg.lo : seg.hi);
    const top = segs[si]!.map((seg, i) => (seg ? { x: cpos(i), y: vpos(edge(seg)), by: vpos(base(seg)) } : null));
    for (const piece of linePieces(top)) {
      const line = piece.map((p, i) => `${i ? "L" : "M"}${p.x},${p.y}`).join(" ");
      if (spec.type === "area" && piece.length > 1) {
        const back = [...piece].reverse().map((p) => `L${p.x},${p.by}`).join(" ");
        shapes.push(<path key={`a${si}-${piece[0]!.x}`} d={`${line} ${back} Z`} fill={c} opacity={0.25} />);
      }
      if (piece.length > 1) shapes.push(<path key={`p${si}-${piece[0]!.x}`} d={line} fill="none" stroke={c} strokeWidth={2} />);
    }
    segs[si]!.forEach((seg, i) => {
      if (!seg) return;
      const alone = !segs[si]![i - 1] && !segs[si]![i + 1];
      if (n <= 40 || alone) {
        shapes.push(<circle key={`m${si}-${i}`} cx={cpos(i)} cy={vpos(edge(seg))} r={alone ? 3 : 2.5} fill={c}><title>{tip(i, si, seg)}</title></circle>);
      }
    });
  });

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ direction: "ltr" }} className="chart-svg">
      {axis.ticks.map((tk) => (
        <g key={tk}>
          {horizontal
            ? <line x1={vpos(tk)} x2={vpos(tk)} y1={pad.t} y2={H - pad.b} className="chart-grid" />
            : <line x1={pad.l} x2={W - pad.r} y1={vpos(tk)} y2={vpos(tk)} className="chart-grid" />}
          {horizontal
            ? <text x={vpos(tk)} y={H - pad.b + 12} textAnchor="middle" className="chart-text">{tickText(tk)}</text>
            : <text x={pad.l - 4} y={vpos(tk) + 3} textAnchor="end" className="chart-text">{tickText(tk)}</text>}
        </g>
      ))}
      {axis.lo < 0 && axis.hi > 0 ? (horizontal
        ? <line x1={vpos(0)} x2={vpos(0)} y1={pad.t} y2={H - pad.b} className="chart-axis" />
        : <line x1={pad.l} x2={W - pad.r} y1={vpos(0)} y2={vpos(0)} className="chart-axis" />) : null}
      {shapes}
      {cats.map((i) => horizontal
        ? <text key={i} x={pad.l - 4} y={cpos(i) + 3} textAnchor="end" className="chart-text">{shorten(localizeDigits(names[i]!, digits), maxChars)}</text>
        : <text key={i} x={cpos(i)} y={H - pad.b + 12} textAnchor="middle" className="chart-text">{shorten(localizeDigits(names[i]!, digits), maxChars)}</text>)}
      <AxisTitle text={titles.x} x={pad.l + plotW / 2} y={H - 4} />
      <AxisTitle text={titles.y} x={11} y={pad.t + plotH / 2} rotate />
    </svg>
  );
}

function Scatter({ spec, data, label, digits }: Props) {
  const xs = data.categories.map(Number);
  const titles = spec.options.axis_titles ?? {};
  const H = 220;
  const pad = { l: 44 + (titles.y ? 14 : 0), r: 12, t: 12, b: 32 + (titles.x ? 14 : 0) };
  const ys = data.series.flatMap((s) => s.values).filter((v): v is number => v !== null);
  const fin = xs.filter(Number.isFinite);
  const xa = niceTicks(Math.min(...fin), Math.max(...fin));
  const ya = niceTicks(ys.length ? Math.min(...ys) : 0, ys.length ? Math.max(...ys) : 1);
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;
  const px = (x: number) => pad.l + ((x - xa.lo) / (xa.hi - xa.lo || 1)) * plotW;
  const py = (y: number) => pad.t + (1 - (y - ya.lo) / (ya.hi - ya.lo || 1)) * plotH;
  const small = xs.length <= 300;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ direction: "ltr" }} className="chart-svg">
      {ya.ticks.map((tk) => (
        <g key={`y${tk}`}>
          <line x1={pad.l} x2={W - pad.r} y1={py(tk)} y2={py(tk)} className="chart-grid" />
          <text x={pad.l - 4} y={py(tk) + 3} textAnchor="end" className="chart-text">{localizeDigits(compact(tk), digits)}</text>
        </g>
      ))}
      {xa.ticks.map((tk) => (
        <text key={`x${tk}`} x={px(tk)} y={H - pad.b + 12} textAnchor="middle" className="chart-text">{localizeDigits(compact(tk), digits)}</text>
      ))}
      {data.series.map((s, si) => s.values.map((v, i) => v === null || !Number.isFinite(xs[i]!) ? null : (
        <circle key={`${si}-${i}`} cx={px(xs[i]!)} cy={py(v)} r={small ? 3 : 2} fill={color(si)} fillOpacity={small ? 1 : 0.6}>
          <title>{`${s.name}: (${num(xs[i]!, digits)}, ${num(v, digits)})`}</title>
        </circle>
      )))}
      <AxisTitle text={titles.x} x={pad.l + plotW / 2} y={H - 4} />
      <AxisTitle text={titles.y} x={11} y={pad.t + plotH / 2} rotate />
    </svg>
  );
}

function Pie({ spec, data, label, digits }: Props) {
  const values = data.series[0]?.values ?? [];
  const names = data.labels ?? data.categories.map(String);
  const slices = pieSlices(values);
  const H = 220;
  const R = 90;
  const r0 = spec.options.donut ? R * 0.55 : 0;
  const at = (a: number, r: number) => `${W / 2 + r * Math.cos(a)},${H / 2 + r * Math.sin(a)}`;
  const show = spec.options.labels ?? "none";
  const text = (sl: { value: number; fraction: number }) =>
    show === "percent" ? `${localizeDigits((sl.fraction * 100).toFixed(sl.fraction < 0.1 ? 1 : 0), digits)}%` : localizeDigits(compact(sl.value), digits);
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ direction: "ltr" }} className="chart-svg">
        {slices.map((sl) => {
          const whole = slices.length === 1;
          const large = sl.end - sl.start > Math.PI ? 1 : 0;
          const d = whole
            ? `M${W / 2 - R},${H / 2} a${R},${R} 0 1 0 ${2 * R},0 a${R},${R} 0 1 0 ${-2 * R},0${r0 ? ` M${W / 2 - r0},${H / 2} a${r0},${r0} 0 1 1 ${2 * r0},0 a${r0},${r0} 0 1 1 ${-2 * r0},0` : ""}`
            : r0
              ? `M${at(sl.start, R)} A${R},${R} 0 ${large} 1 ${at(sl.end, R)} L${at(sl.end, r0)} A${r0},${r0} 0 ${large} 0 ${at(sl.start, r0)} Z`
              : `M${W / 2},${H / 2} L${at(sl.start, R)} A${R},${R} 0 ${large} 1 ${at(sl.end, R)} Z`;
          const mid = (sl.start + sl.end) / 2;
          const [lx, ly] = at(mid, (R + r0) / 2).split(",").map(Number) as [number, number];
          return (
            <g key={sl.index}>
              <path d={d} fill={color(sl.index)} fillRule="evenodd"><title>{`${names[sl.index]}: ${num(sl.value, digits)} (${num(sl.fraction * 100, digits)}%)`}</title></path>
              {show !== "none" && sl.fraction >= 0.06 ? <text x={lx} y={ly + 3} textAnchor="middle" className="chart-text chart-pie-label">{text(sl)}</text> : null}
            </g>
          );
        })}
      </svg>
      <figcaption className="chart-legend">
        {slices.map((sl) => (
          <span key={sl.index}><i style={{ background: color(sl.index) }} /><bdi>{names[sl.index]}</bdi> <span className="muted">{localizeDigits((sl.fraction * 100).toFixed(1), digits)}%</span></span>
        ))}
      </figcaption>
    </>
  );
}

const NOTE_KEYS: Record<string, MessageKey> = {
  rows_excluded_empty_date: "charts.note.rowsEmptyDate",
  rows_excluded_empty_value: "charts.note.rowsEmptyValue",
  dates_unreadable: "charts.note.datesUnreadable",
  empty_values: "charts.note.emptyValues",
  negative_values: "charts.note.negativeValues",
  categories_limited: "charts.note.categoriesLimited",
  other_merged: "charts.note.otherMerged",
  sampled: "charts.note.sampled",
  extra_series_ignored: "charts.note.extraSeries",
};

/** What the chart left out or summarised, in plain words. Unknown codes from a newer server are skipped. */
export function noteKey(n: ChartNote): MessageKey | undefined {
  return NOTE_KEYS[n.code === "rows_excluded" ? `rows_excluded_${String(n.params.reason)}` : n.code];
}

function Notes({ notes }: { notes: ChartNote[] }) {
  const t = useT();
  const digits = usePrefs((s) => s.digits);
  const lines = notes.flatMap((n) => {
    const key = noteKey(n);
    if (!key) return [];
    const params: Record<string, string | number> = {};
    for (const [name, v] of Object.entries(n.params)) {
      params[name] = typeof v === "number" ? formatNumber(v, digits, 0) : Array.isArray(v) ? v.join("، ") : String(v);
    }
    return [t(key, params)];
  });
  if (lines.length === 0) return null;
  return <ul className="chart-notes muted">{lines.map((l) => <li key={l}>{l}</li>)}</ul>;
}
