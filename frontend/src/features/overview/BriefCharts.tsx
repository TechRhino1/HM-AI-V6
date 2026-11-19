import { isNum, num } from "../../lib/format";
import { ProvBadge } from "../../components/ProvBadge";
import { DivergingBars, type BarRow } from "../../components/viz";
import type { Prov } from "../markets/logic";

// Shapes of the brief's stored fact sheet (jarvis/ai/briefs.py fact_sheet). Loose: any section may be missing or errored.
type Rec = Record<string, any>;
export interface Strikes { name: string; expiry?: string; spot: number; maxPain?: number; lo1sd?: number; hi1sd?: number; pcr?: number;
  resistance: number[]; support: number[]; prov?: Prov }
export interface BriefModel {
  global: BarRow[]; indices: BarRow[]; flows: BarRow[]; strikes: (Strikes | { name: string; unavailable: true })[];
  vix?: { value: number; lo: number; hi: number; change?: number; prov?: Prov };
  prov: { global?: Prov; indices?: Prov; flows?: Prov };
}

const n = (v: unknown) => (isNum(v) ? v : typeof v === "string" && v.trim() !== "" && Number.isFinite(+v) ? +v : null);
const sgn = (v: number, d = 2) => `${v > 0 ? "+" : ""}${num(v, d)}`;

/** Normalise the fact sheet into chart rows. Missing figures stay null (shown as unavailable), never filled in. */
export function briefModel(f: Rec | null | undefined): BriefModel | null {
  if (!f || typeof f !== "object") return null;
  const global = (Array.isArray(f.global_cues) ? f.global_cues : []).map((g: Rec): BarRow => {
    const v = n(g?.change_pct);
    return { label: String(g?.name ?? g?.ticker ?? "?"), value: v, display: v === null ? "" : `${sgn(v)}%`, title: isNum(g?.price) ? `Last ${num(g.price, 2)}` : undefined };
  });
  const indices = (Array.isArray(f.indices?.rows) ? f.indices.rows : []).slice(0, 6).map((r: Rec): BarRow => {
    const v = n(r?.change_pct);
    return { label: String(r?.name ?? "?"), value: v, display: v === null ? "" : `${sgn(v)}%`,
      title: isNum(r?.last) ? `${r.name}: ${num(r.last, 2)}` : undefined };
  });
  const flows = (Array.isArray(f.fii_dii?.rows) ? f.fii_dii.rows : []).map((r: Rec): BarRow => {
    const v = n(r?.net_cr);
    return { label: String(r?.category ?? "?"), value: v, display: v === null ? "" : `₹${sgn(v, 0)} cr`, title: r?.date ? `Net cash-market flow on ${r.date}` : undefined };
  });
  const strikes = Object.keys(f).filter((k) => k.startsWith("options_")).map((k) => {
    const o: Rec = f[k] || {};
    const name = k.slice(8);
    const spot = n(o.spot);
    if (o.error || spot === null) return { name, unavailable: true as const };
    const ws = (side: string) => (Array.isArray(o.walls?.[side]) ? o.walls[side] : []).map((w: Rec) => n(w?.strike)).filter((x: number | null): x is number => x !== null).slice(0, 3);
    return { name, expiry: o.expiry, spot, maxPain: n(o.max_pain) ?? undefined, lo1sd: n(o.expected_move?.lower_1sd) ?? undefined,
      hi1sd: n(o.expected_move?.upper_1sd) ?? undefined, pcr: n(o.pcr?.oi) ?? undefined, resistance: ws("resistance"), support: ws("support"), prov: o.prov };
  });
  const v = f.vix || {};
  const vix = n(v.value) !== null && n(v.year_low) !== null && n(v.year_high) !== null
    ? { value: n(v.value)!, lo: n(v.year_low)!, hi: n(v.year_high)!, change: n(v.change_pct) ?? undefined, prov: v.prov } : undefined;
  const firstProv = (a: unknown) => (Array.isArray(a) ? a.find((g: Rec) => g?.prov)?.prov : undefined);
  return { global, indices, flows, strikes, vix, prov: { global: firstProv(f.global_cues), indices: f.indices?.prov, flows: f.fii_dii?.prov } };
}

/** Spot, max pain, ±1σ band and the biggest OI walls on one strike axis. */
function StrikeMap({ s }: { s: Strikes }) {
  const pts = [s.spot, s.maxPain, s.lo1sd, s.hi1sd, ...s.resistance, ...s.support].filter(isNum);
  const lo = Math.min(...pts), hi = Math.max(...pts), pad = (hi - lo) * 0.06 || 1;
  const x = (v: number) => ((v - (lo - pad)) / (hi - lo + 2 * pad)) * 100;
  const desc = `${s.name}: spot ${num(s.spot, 0)}` + (s.maxPain ? `, max pain ${num(s.maxPain, 0)}` : "")
    + (s.lo1sd && s.hi1sd ? `, one-sigma range ${num(s.lo1sd, 0)} to ${num(s.hi1sd, 0)}` : "")
    + (s.resistance.length ? `, call walls ${s.resistance.map((r) => num(r, 0)).join(", ")}` : "")
    + (s.support.length ? `, put walls ${s.support.map((r) => num(r, 0)).join(", ")}` : "");
  return (
    <div className="smap">
      <div className="row between" style={{ fontSize: 12 }}>
        <b>{s.name} <span className="faint" style={{ fontWeight: 400 }}>{s.expiry}</span></b>
        <span className="row" style={{ gap: 6 }}>{isNum(s.pcr) && <span className="faint">PCR <span className="mono">{num(s.pcr, 2)}</span></span>}<ProvBadge prov={s.prov} /></span>
      </div>
      <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="smap-svg" role="img" aria-label={desc}>
        {isNum(s.lo1sd) && isNum(s.hi1sd) && <rect x={x(s.lo1sd)} width={x(s.hi1sd) - x(s.lo1sd)} y="9" height="12" fill="var(--accent-soft)" rx="1"><title>{`±1σ expected move: ${num(s.lo1sd, 0)} – ${num(s.hi1sd, 0)}`}</title></rect>}
        <line x1="0" x2="100" y1="15" y2="15" stroke="var(--line-2)" vectorEffect="non-scaling-stroke" />
        {s.support.map((v) => <rect key={`s${v}`} x={x(v) - 0.6} width="1.2" y="4" height="22" fill="var(--up)"><title>{`Put wall (support) ${num(v, 0)}`}</title></rect>)}
        {s.resistance.map((v) => <rect key={`r${v}`} x={x(v) - 0.6} width="1.2" y="4" height="22" fill="var(--down)"><title>{`Call wall (resistance) ${num(v, 0)}`}</title></rect>)}
        {isNum(s.maxPain) && <rect x={x(s.maxPain) - 0.5} width="1" y="2" height="26" fill="var(--warn)"><title>{`Max pain ${num(s.maxPain, 0)}`}</title></rect>}
        <rect x={x(s.spot) - 0.9} width="1.8" y="0" height="30" fill="var(--text)"><title>{`Spot ${num(s.spot, 2)}`}</title></rect>
      </svg>
      <div className="row between faint mono" style={{ fontSize: 10.5 }}><span>{num(lo, 0)}</span><span>spot {num(s.spot, 0)}</span><span>{num(hi, 0)}</span></div>
    </div>
  );
}

const Head = ({ t, prov }: { t: string; prov?: Prov }) => (
  <div className="row between" style={{ fontSize: 12.5 }}><b>{t}</b>{prov && <ProvBadge prov={prov} />}</div>
);

/** The brief's fact sheet as charts; every figure comes from the stored sheet the brief text was written from. */
export function BriefCharts({ m }: { m: BriefModel }) {
  return (
    <div className="stack brief-charts" style={{ gap: 14 }}>
      {!!m.global.length && <div className="stack" style={{ gap: 6 }}><Head t="Global cues · % change" prov={m.prov.global} /><DivergingBars rows={m.global} label="Global index changes" /></div>}
      {!!m.indices.length && <div className="stack" style={{ gap: 6 }}><Head t="India indices · % change" prov={m.prov.indices} /><DivergingBars rows={m.indices} label="India index changes" /></div>}
      {m.vix && (
        <div className="stack" style={{ gap: 6 }}>
          <Head t="India VIX in its 52-week range" prov={m.vix.prov} />
          <div className="vixbar" role="img" aria-label={`India VIX ${num(m.vix.value, 2)}, 52-week range ${num(m.vix.lo, 2)} to ${num(m.vix.hi, 2)}`}>
            <i style={{ left: `${Math.max(0, Math.min(100, ((m.vix.value - m.vix.lo) / (m.vix.hi - m.vix.lo || 1)) * 100))}%` }} />
          </div>
          <div className="row between faint mono" style={{ fontSize: 11 }}>
            <span>{num(m.vix.lo, 2)}</span><span className="mono" style={{ color: "var(--text)" }}>{num(m.vix.value, 2)}{isNum(m.vix.change) && <span className={m.vix.change >= 0 ? "up" : "down"}> ({sgn(m.vix.change)}%)</span>}</span><span>{num(m.vix.hi, 2)}</span>
          </div>
        </div>
      )}
      {!!m.flows.length && <div className="stack" style={{ gap: 6 }}><Head t="Institutional flows · net ₹ cr (context, not validated)" prov={m.prov.flows} /><DivergingBars rows={m.flows} label="FII and DII net flows" /></div>}
      {!!m.strikes.length && (
        <div className="stack" style={{ gap: 8 }}>
          <Head t="Options positioning (context, not validated)" />
          <div className="faint smap-key"><i style={{ background: "var(--text)" }} />spot <i style={{ background: "var(--warn)" }} />max pain <i style={{ background: "var(--up)" }} />put wall <i style={{ background: "var(--down)" }} />call wall <i style={{ background: "var(--accent-soft)" }} />±1σ move</div>
          {m.strikes.map((s) => ("unavailable" in s ? <div key={s.name} className="faint" style={{ fontSize: 12 }}><b>{s.name}</b> unavailable</div> : <StrikeMap key={s.name} s={s} />))}
        </div>
      )}
    </div>
  );
}
