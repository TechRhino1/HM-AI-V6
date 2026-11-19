// Small hand-drawn SVG charts for dashboard widgets. Colours come from the theme tokens, so light/dark just work.

export type Level = "good" | "warn" | "danger";
/** Same thresholds as the guardrail meters: 50% of a limit is a warning, 80% is danger. */
export const levelOf = (v: number, max: number): Level => (v >= max * 0.8 ? "danger" : v >= max * 0.5 ? "warn" : "good");
const LEVEL_VAR: Record<Level, string> = { good: "var(--up)", warn: "var(--warn)", danger: "var(--down)" };

/** Point on a 180° arc (radius 40, centre 50,50) for a 0..1 fraction, sweeping left to right. */
export function arcPoint(f: number): [number, number] {
  const a = Math.PI * (1 - Math.max(0, Math.min(1, f)));
  return [50 + 40 * Math.cos(a), 50 - 40 * Math.sin(a)];
}
const arc = (f: number) => { const [x, y] = arcPoint(f); return `M10 50 A40 40 0 0 1 ${x.toFixed(2)} ${y.toFixed(2)}`; };

/** Semicircle gauge with 50% / 80% threshold ticks; `label` is read by screen readers. */
export function Gauge({ value, max, display, label }: { value: number; max: number; display: string; label: string }) {
  const f = max > 0 ? value / max : 0;
  const lvl = levelOf(value, max);
  return (
    <svg className="gauge" viewBox="0 0 100 58" role="img" aria-label={`${label}: ${display}, ${lvl === "good" ? "within limits" : lvl === "warn" ? "over half the limit" : "near the limit"}`}>
      <path d={arc(1)} fill="none" stroke="var(--surface-3)" strokeWidth="8" strokeLinecap="round" />
      {f > 0.005 && <path d={arc(f)} fill="none" stroke={LEVEL_VAR[lvl]} strokeWidth="8" strokeLinecap="round" className="gauge-fill" />}
      {[0.5, 0.8].map((t) => { const [x, y] = arcPoint(t), [x2, y2] = [50 + (x - 50) * 1.25, 50 + (y - 50) * 1.25]; return <line key={t} x1={x} y1={y} x2={x2} y2={y2} stroke="var(--text-3)" strokeWidth="1" />; })}
      <text x="50" y="47" textAnchor="middle" className="gauge-val">{display}</text>
    </svg>
  );
}

export interface Step { label: string; pnl: number; start: number; end: number }
/** Running-total steps for a P&L waterfall, in the order given. */
export function waterfallSteps(items: { label: string; pnl: number }[]): Step[] {
  let run = 0;
  return items.map(({ label, pnl }) => { const start = run; run += pnl; return { label, pnl, start, end: run }; });
}

/** Each bar spans the running total before → after one trade; a dashed line marks zero. */
export function Waterfall({ steps, fmt, onPick, height = 120 }: { steps: Step[]; fmt: (v: number) => string; onPick?: () => void; height?: number }) {
  if (!steps.length) return null;
  const vals = steps.flatMap((s) => [s.start, s.end]);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals), span = hi - lo || 1;
  const W = Math.max(steps.length * 12, 60), bw = W / steps.length;
  const y = (v: number) => 4 + ((hi - v) / span) * (height - 8);
  const net = steps[steps.length - 1].end;
  return (
    <svg className={`waterfall ${onPick ? "clickable" : ""}`} viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" height={height}
      role={onPick ? "button" : "img"} tabIndex={onPick ? 0 : undefined} onClick={onPick}
      onKeyDown={onPick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(); } } : undefined}
      aria-label={`P&L waterfall of ${steps.length} trades, net ${fmt(net)}${onPick ? ". Press to list the trades" : ""}`}>
      <line x1="0" x2={W} y1={y(0)} y2={y(0)} stroke="var(--line-2)" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
      {steps.map((s, i) => (
        <rect key={i} x={i * bw + bw * 0.15} width={bw * 0.7} y={Math.min(y(s.start), y(s.end))} height={Math.max(1, Math.abs(y(s.start) - y(s.end)))}
          fill={s.pnl >= 0 ? "var(--up)" : "var(--down)"} rx="1">
          <title>{`${s.label}: ${fmt(s.pnl)} · running ${fmt(s.end)}`}</title>
        </rect>
      ))}
    </svg>
  );
}

/** Bar growing left (negative) or right (positive) from a centre line; `frac` is -1..1. */
export function CentredBar({ frac, tone }: { frac: number; tone: "up" | "down" }) {
  const w = Math.min(50, Math.abs(frac) * 50);
  return (
    <div className="cbar" aria-hidden="true">
      <i style={{ width: `${w}%`, [frac >= 0 ? "left" : "right"]: "50%", background: `var(--${tone})` }} />
    </div>
  );
}

export interface BarRow { label: string; value: number | null; display: string; title?: string }
/** Labelled bars growing left/right from zero, scaled to the largest magnitude; null values show "unavailable". */
export function DivergingBars({ rows, label }: { rows: BarRow[]; label: string }) {
  const max = Math.max(1e-9, ...rows.map((r) => Math.abs(r.value ?? 0)));
  return (
    <div className="dbars" role="list" aria-label={label}>
      {rows.map((r) => (
        <div key={r.label} className="dbar-row" role="listitem" title={r.title}>
          <span className="dbar-lbl">{r.label}</span>
          {r.value === null ? <span className="faint dbar-na">unavailable</span>
            : <CentredBar frac={r.value / max} tone={r.value >= 0 ? "up" : "down"} />}
          <span className={`mono dbar-val ${r.value === null ? "faint" : r.value > 0 ? "up" : r.value < 0 ? "down" : ""}`}>{r.value === null ? "—" : r.display}</span>
        </div>
      ))}
    </div>
  );
}

/** Rolling buffer of real readings for a session sparkline: skips repeats of the same timestamp, keeps the last `cap`. */
export function pushSample(buf: { t: number; v: number }[], t: number, v: number, cap = 240) {
  if (!Number.isFinite(v) || (buf.length && buf[buf.length - 1].t === t)) return buf;
  buf.push({ t, v });
  if (buf.length > cap) buf.splice(0, buf.length - cap);
  return buf;
}
