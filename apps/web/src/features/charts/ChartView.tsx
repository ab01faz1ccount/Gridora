// A small SVG chart (bar, line, area, scatter, pie) from the plain `ChartData` the server computes.
// No chart library: the data is small and the output must follow the page's colours and direction.
import type { ChartData, ChartSpec } from "@contracts";

const W = 360;
const H = 220;
const PAD = { l: 44, r: 12, t: 12, b: 32 };
const COLORS = ["var(--accent)", "#c2410c", "#15803d", "#7e22ce", "#0e7490", "#a16207"];

const nice = (v: number): string => (Math.abs(v) >= 1000 ? `${Math.round(v / 100) / 10}k` : String(Math.round(v * 100) / 100));

export function ChartView({ spec, data }: { spec: ChartSpec; data: ChartData }) {
  const label = spec.title ?? spec.type;
  if (data.categories.length === 0 || data.series.length === 0) return null;
  if (spec.type === "pie") return <Pie label={label} data={data} />;
  const stacked = spec.options.stacked && (spec.type === "bar" || spec.type === "area");
  const n = data.categories.length;
  const vals = data.series.map((s) => s.values.map((v) => v ?? 0));
  const totals = stacked ? data.categories.map((_, i) => vals.reduce((a, s) => a + (s[i] ?? 0), 0)) : vals.flat();
  const lo = Math.min(0, ...totals);
  const hi = Math.max(0, ...totals) || 1;
  const sy = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  const numericX = spec.type === "scatter" ? data.categories.map(Number) : null;
  const xlo = numericX ? Math.min(...numericX) : 0;
  const xhi = numericX ? Math.max(...numericX) || 1 : 1;
  const plotW = W - PAD.l - PAD.r;
  const sx = (i: number) =>
    numericX ? PAD.l + ((numericX[i]! - xlo) / (xhi - xlo || 1)) * plotW : PAD.l + ((i + 0.5) / n) * plotW;
  const band = plotW / n;
  const ticks = [lo, lo + (hi - lo) / 2, hi];
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ direction: "ltr" }} className="chart-svg">
        {ticks.map((tk) => (
          <g key={tk}>
            <line x1={PAD.l} x2={W - PAD.r} y1={sy(tk)} y2={sy(tk)} className="chart-grid" />
            <text x={PAD.l - 4} y={sy(tk) + 4} textAnchor="end" className="chart-text">{nice(tk)}</text>
          </g>
        ))}
        {data.series.map((s, k) => {
          const color = COLORS[k % COLORS.length];
          if (spec.type === "bar") {
            const bw = stacked ? band * 0.7 : (band * 0.8) / data.series.length;
            return vals[k]!.map((v, i) => {
              const base = stacked ? vals.slice(0, k).reduce((a, x) => a + (x[i] ?? 0), 0) : 0;
              const x = stacked ? sx(i) - bw / 2 : PAD.l + i * band + band * 0.1 + k * bw;
              return <rect key={`${k}-${i}`} x={x} y={Math.min(sy(base + v), sy(base))} width={bw}
                height={Math.abs(sy(base) - sy(base + v))} fill={color}><title>{`${s.name}: ${v}`}</title></rect>;
            });
          }
          if (spec.type === "scatter") {
            return vals[k]!.map((v, i) => <circle key={`${k}-${i}`} cx={sx(i)} cy={sy(v)} r={3} fill={color}><title>{`${s.name}: ${v}`}</title></circle>);
          }
          const pts = vals[k]!.map((v, i) => {
            const base = stacked ? vals.slice(0, k).reduce((a, x) => a + (x[i] ?? 0), 0) : 0;
            return [sx(i), sy(base + v)] as const;
          });
          const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x},${y}`).join(" ");
          return (
            <g key={k}>
              {spec.type === "area" ? <path d={`${line} L${pts[pts.length - 1]![0]},${sy(0)} L${pts[0]![0]},${sy(0)} Z`} fill={color} opacity={0.25} /> : null}
              <path d={line} fill="none" stroke={color} strokeWidth={2} />
            </g>
          );
        })}
        {(numericX ? [0, n - 1] : data.categories.map((_, i) => i).filter((i) => n <= 8 || i % Math.ceil(n / 8) === 0)).map((i) => (
          <text key={i} x={sx(i)} y={H - 10} textAnchor="middle" className="chart-text">{String(data.categories[i]).slice(0, 10)}</text>
        ))}
      </svg>
      {spec.options.legend && data.series.length > 1 ? (
        <figcaption className="chart-legend">
          {data.series.map((s, k) => <span key={k}><i style={{ background: COLORS[k % COLORS.length] }} />{s.name}</span>)}
        </figcaption>
      ) : null}
    </figure>
  );
}

function Pie({ label, data }: { label: string; data: ChartData }) {
  const values = (data.series[0]?.values ?? []).map((v) => Math.max(0, v ?? 0));
  const total = values.reduce((a, b) => a + b, 0) || 1;
  const starts = values.reduce<number[]>((acc, v, i) => [...acc, (acc[i] ?? -Math.PI / 2) + (v / total) * Math.PI * 2], [-Math.PI / 2]);
  const R = 90;
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ direction: "ltr" }} className="chart-svg">
        {values.map((v, i) => {
          const a0 = starts[i]!;
          const angle = starts[i + 1]!;
          const large = angle - a0 > Math.PI ? 1 : 0;
          const p = (a: number) => `${W / 2 + R * Math.cos(a)},${H / 2 + R * Math.sin(a)}`;
          const d = values.length === 1 ? `M${W / 2 - R},${H / 2} a${R},${R} 0 1 0 ${2 * R},0 a${R},${R} 0 1 0 ${-2 * R},0`
            : `M${W / 2},${H / 2} L${p(a0)} A${R},${R} 0 ${large} 1 ${p(angle)} Z`;
          return <path key={i} d={d} fill={COLORS[i % COLORS.length]}><title>{`${String(data.categories[i])}: ${v}`}</title></path>;
        })}
      </svg>
      <figcaption className="chart-legend">
        {data.categories.map((c, i) => <span key={i}><i style={{ background: COLORS[i % COLORS.length] }} />{String(c)}</span>)}
      </figcaption>
    </figure>
  );
}
