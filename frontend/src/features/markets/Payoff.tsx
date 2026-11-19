import { useId, useMemo } from "react";
import { isNum, num } from "../../lib/format";

export const inr = (v: unknown, d = 0) => (isNum(v) ? `${v < 0 ? "−" : ""}₹${num(Math.abs(v), d)}` : "—");

const W = 640, H = 240, PAD = { l: 56, r: 12, t: 12, b: 26 };

/** Expiry payoff per lot from the API's payoff_curve; zero line, breakevens (dashed) and spot (accent) marked. */
export function Payoff({ curve, breakevens = [], spot }: { curve: { s: number; pnl: number }[]; breakevens?: number[]; spot?: number }) {
  const id = useId().replace(/:/g, "");
  const g = useMemo(() => {
    const pts = curve.filter((p) => isNum(p.s) && isNum(p.pnl));
    if (pts.length < 2) return null;
    const xs = pts.map((p) => p.s), ys = pts.map((p) => p.pnl);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = Math.min(0, ...ys), y1 = Math.max(0, ...ys);
    const sx = (v: number) => PAD.l + ((v - x0) / (x1 - x0 || 1)) * (W - PAD.l - PAD.r);
    const sy = (v: number) => PAD.t + (1 - (v - y0) / (y1 - y0 || 1)) * (H - PAD.t - PAD.b);
    const line = pts.map((p, i) => `${i ? "L" : "M"}${sx(p.s).toFixed(1)},${sy(p.pnl).toFixed(1)}`).join("");
    const zero = sy(0);
    const area = `${line}L${sx(x1).toFixed(1)},${zero}L${sx(x0).toFixed(1)},${zero}Z`;
    const yTicks = [y0, (y0 + y1) / 2, y1];
    const xTicks = [x0, (x0 + x1) / 2, x1];
    return { sx, sy, line, area, zero, yTicks, xTicks, x0, x1 };
  }, [curve]);
  if (!g) return <div className="empty">No payoff curve</div>;
  const inRange = (v: unknown): v is number => isNum(v) && v >= g.x0 && v <= g.x1;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="payoff" role="img" aria-label="Payoff at expiry per lot">
      <defs>
        <clipPath id={`${id}u`}><rect x="0" y="0" width={W} height={g.zero} /></clipPath>
        <clipPath id={`${id}d`}><rect x="0" y={g.zero} width={W} height={H - g.zero} /></clipPath>
      </defs>
      {g.yTicks.map((v, i) => (
        <g key={i}>
          <line x1={PAD.l} x2={W - PAD.r} y1={g.sy(v)} y2={g.sy(v)} className="grid-line" />
          <text x={PAD.l - 6} y={g.sy(v) + 4} textAnchor="end" className="axis">{inr(v)}</text>
        </g>
      ))}
      {g.xTicks.map((v, i) => (
        <text key={i} x={g.sx(v)} y={H - 8} textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"} className="axis">{num(v, 0)}</text>
      ))}
      <path d={g.area} className="pay-up" clipPath={`url(#${id}u)`} />
      <path d={g.area} className="pay-down" clipPath={`url(#${id}d)`} />
      <line x1={PAD.l} x2={W - PAD.r} y1={g.zero} y2={g.zero} className="zero-line" />
      <path d={g.line} className="pay-line" />
      {breakevens.filter(inRange).map((b) => (
        <g key={b}>
          <line x1={g.sx(b)} x2={g.sx(b)} y1={PAD.t} y2={H - PAD.b} className="be-line" />
          <text x={g.sx(b) + 4} y={PAD.t + 10} className="axis">BE {num(b, 0)}</text>
        </g>
      ))}
      {inRange(spot) && (
        <g>
          <line x1={g.sx(spot)} x2={g.sx(spot)} y1={PAD.t} y2={H - PAD.b} className="spot-line" />
          <text x={g.sx(spot) + 4} y={H - PAD.b - 6} className="axis accent">spot {num(spot, 0)}</text>
        </g>
      )}
    </svg>
  );
}
