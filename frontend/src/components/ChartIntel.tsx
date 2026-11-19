import { useMemo, useRef, useState } from "react";
import type { SeriesMarker, Time } from "lightweight-charts";
import { api, qs } from "../lib/api";
import { usePoll } from "../lib/hooks";
import { fixed, isNum, price } from "../lib/format";
import { useStore } from "../state/store";
import { QuickAlert } from "../features/alerts/Alerts";
import type { Prov } from "../features/markets/logic";
import type { PriceLevel } from "./Chart";
import { Badge, Card, ErrorNote } from "./ui";
import { ProvBadge } from "./ProvBadge";
import { Explain } from "./Explain";

export type Market = "FX" | "IN" | "US";
export interface Zone {
  price: number; lo: number; hi: number; role: "support" | "resistance"; types: string[]; sources: string[];
  strength: number; touches: number; hold_rate: number | null; n: number; hold_basis: string | null; label: string;
}
export interface LevelsOut {
  zones?: Zone[]; atr?: number; volume?: { used: boolean; kind: string | null; note: string | null };
  volume_profile?: { poc: number; vah: number; val: number; bars: number }; vwap?: number; prov?: Prov;
  options?: { expiry?: string; note?: string };
}
export interface PatternEvent {
  time: number; kind: string; direction: "up" | "down"; price: number; level: number; note: string;
  stats: { n: number; win_rate: number | null; mean_atr: number | null; label: string };
}
export interface PatternsOut { events?: PatternEvent[]; summary?: Record<string, PatternEvent["stats"]>; horizon_bars?: number; prov?: Prov }

export const LAYERS = [
  { key: "levels", label: "Levels" }, { key: "vp", label: "Volume profile" }, { key: "patterns", label: "Patterns" },
  { key: "signal", label: "Engine signal" }, { key: "positions", label: "Positions" },
] as const;
export type LayerKey = (typeof LAYERS)[number]["key"];
export type Layers = Record<LayerKey, boolean>;
export const DEFAULT_LAYERS: Layers = { levels: true, vp: false, patterns: true, signal: true, positions: true };

export const DEFS = {
  hold_rate: "Share of past touches of this level type (on this symbol and timeframe) where price reversed by 1 ATR before closing beyond the level. Measured walk-forward: each past level only on bars after it was known. Shown only with at least 30 resolved touches.",
  strength: "Relative ranking of the zone: touch episodes, +2 per extra confluent source type, +1 if touched in the last 20 bars, plus profile volume share. Not a probability.",
  pattern: "Historical record of this pattern on this symbol and timeframe: share of earlier instances that moved in the pattern's direction over the next bars, measured only on instances that had already played out.",
  devil_penalty: "The Devil's Advocate penalty: a weighted count of reasons against the trade. Above the gate's limit, the Devil Adversarial Guard blocks the trade.",
  calibrated_loss_prob: "Probability of a losing trade given the Devil's Advocate threat flags, from a walk-forward logistic calibration; used by the gate only when the calibration is published.",
  live_r: "Open profit or loss in units of the initial risk (entry to stop).",
};

const KIND: Record<string, string> = { bos: "BOS", choch: "CHoCH", breakout: "Breakout", false_breakout: "False breakout", liquidity_sweep: "Sweep" };
const SHORT: Record<string, string> = { bos: "BOS", choch: "CH", breakout: "BO", false_breakout: "FB", liquidity_sweep: "SW" };
const kindName = (k: string) => KIND[k] || k.replace(/_/g, " ");
const pctOf = (v: number | null | undefined) => (isNum(v) ? `${Math.round(v * 100)}%` : null);

/** Keep the previous object while the JSON is unchanged, so charts re-render only on real data changes. */
function useStable<T>(v: T | undefined): T | undefined {
  const ref = useRef<{ key: string; v: T | undefined }>({ key: "", v: undefined });
  const key = v === undefined ? "" : JSON.stringify(v);
  if (key !== ref.current.key) ref.current = { key, v };
  return ref.current.v;
}

export const zoneLabel = (z: Zone) => {
  const hr = pctOf(z.hold_rate);
  return `${z.role === "resistance" ? "R" : "S"} ${hr ? `held ${hr} n${z.n}` : z.label.startsWith("insufficient") ? "n<30" : "ctx"} ★${Math.round(z.strength)}`;
};

/** Server-computed levels + patterns for a chart, mapped to price lines, markers and hover tips. */
export function useChartIntel(symbol: string, market: Market, interval: string, layers: Pick<Layers, "levels" | "vp" | "patterns">) {
  const base = qs({ symbol, market, interval });
  const ttl = interval === "D1" || interval === "W1" ? 900000 : 60000;
  const lvRes = usePoll<LevelsOut>(layers.levels || layers.vp ? `/api/markets/chart/levels${base}` : null, ttl);
  const ptRes = usePoll<PatternsOut>(layers.patterns ? `/api/markets/chart/patterns${base}` : null, ttl);
  const lv = useStable(lvRes.data);
  const pt = useStable(ptRes.data);

  const lines = useMemo<PriceLevel[]>(() => {
    const out: PriceLevel[] = [];
    // Chart shows the 3 nearest zones each side (the list below the chart has all of them).
    const zs = lv?.zones || [];
    const near = [...zs.filter((z) => z.role === "resistance").sort((a, b) => a.price - b.price).slice(0, 3),
      ...zs.filter((z) => z.role === "support").sort((a, b) => b.price - a.price).slice(0, 3)];
    for (const z of zs) if (!near.includes(z) && z.types.some((t) => t === "oi_wall" || t === "max_pain")) near.push(z);
    if (layers.levels) for (const z of near) out.push({ price: z.price, label: zoneLabel(z), tone: z.role === "resistance" ? "down" : "up", dashed: z.hold_rate === null });
    const vp = lv?.volume_profile;
    if (layers.vp && vp) out.push({ price: vp.poc, label: "POC", tone: "accent" }, { price: vp.vah, label: "VAH", tone: "flat", dashed: true }, { price: vp.val, label: "VAL", tone: "flat", dashed: true });
    if (layers.vp && isNum(lv?.vwap)) out.push({ price: lv!.vwap!, label: "VWAP", tone: "warn", dashed: true });
    return out;
  }, [lv, layers.levels, layers.vp]);

  const { markers, tips } = useMemo(() => {
    const tips = new Map<number, string>();
    const markers: SeriesMarker<Time>[] = [];
    if (!layers.patterns) return { markers, tips };
    for (const e of pt?.events || []) {
      const up = e.direction === "up";
      const st = e.stats;
      const rec = isNum(st.win_rate) ? `history: ${pctOf(st.win_rate)} moved ${e.direction} over ${pt?.horizon_bars} bars (n=${st.n}, mean ${fixed(st.mean_atr, 2)} ATR)` : `history: ${st.label}`;
      const line = `${kindName(e.kind)} ${e.direction} · ${e.note} · ${rec}`;
      tips.set(e.time, tips.has(e.time) ? `${tips.get(e.time)}\n${line}` : line);
      markers.push({ time: e.time as Time, position: up ? "belowBar" : "aboveBar", color: up ? "#22c58b" : "#f2555a", shape: up ? "arrowUp" : "arrowDown", text: SHORT[e.kind] || e.kind });
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number));
    return { markers, tips };
  }, [pt, layers.patterns]);

  return { lv, pt, lines, markers, tips, error: lvRes.error || ptRes.error, prov: lv?.prov || pt?.prov };
}

export function LayerBar({ layers, setLayers, only }: { layers: Layers; setLayers: (l: Layers) => void; only?: LayerKey[] }) {
  return (
    <div className="row wrap layer-bar" role="group" aria-label="Chart layers">
      {LAYERS.filter((l) => !only || only.includes(l.key)).map((l) => (
        <button key={l.key} type="button" className={`chip ${layers[l.key] ? "on" : ""}`} aria-pressed={layers[l.key]}
          title={l.key === "patterns" ? "BOS break of structure · CH change of character · BO breakout · FB false breakout · SW liquidity sweep. Hover a marker for its history on this symbol." : undefined}
          onClick={() => setLayers({ ...layers, [l.key]: !layers[l.key] })}>{l.label}</button>
      ))}
    </div>
  );
}

/** Zones nearest price, each with its measured hold rate and a one-click alert. */
export function LevelList({ lv, symbol, market, digits }: { lv?: LevelsOut; symbol: string; market: Market; digits?: number }) {
  const zones = lv?.zones || [];
  if (!zones.length) return null;
  const sorted = [...zones].sort((a, b) => b.price - a.price);
  return (
    <div className="level-list">
      <div className="row between" style={{ marginBottom: 4 }}>
        <span className="faint" style={{ fontSize: 12 }}>Levels · hold rate<Explain metric="level_hold_rate" fallback={DEFS.hold_rate} /> · strength<Explain metric="zone_strength" fallback={DEFS.strength} />
          {lv?.volume && !lv.volume.used ? ` · ${lv.volume.note}` : lv?.volume?.kind ? ` · volume: ${lv.volume.kind}` : ""}</span>
        <ProvBadge prov={lv?.prov} loading={false} />
      </div>
      {sorted.map((z) => {
        const dir = z.role === "resistance" ? "above" : "below";
        const hr = pctOf(z.hold_rate);
        return (
          <div key={`${z.price}`} className="level-row">
            <span className={`mono ${z.role === "resistance" ? "down" : "up"}`}>{price(z.price, digits)}</span>
            <span className="grow ellipsis" title={z.sources.join(", ")}>{z.sources.slice(0, 3).join(", ")}{z.sources.length > 3 ? ` +${z.sources.length - 3}` : ""}</span>
            <span className="faint mono" title={`${z.label}${z.hold_basis ? ` (basis: ${z.hold_basis.replace(/_/g, " ")})` : ""}`}>
              {hr ? `held ${hr} · n=${z.n}` : z.label}</span>
            <span className="faint mono">★{Math.round(z.strength)}</span>
            <QuickAlert rule={{ type: "level_cross", symbol, market, level: Number(z.price.toFixed(digits ?? 2)), direction: dir }}
              title={`Alert when ${symbol} crosses ${dir} ${price(z.price, digits)}`} />
          </div>
        );
      })}
    </div>
  );
}

interface ReadOut { bullets: string[]; source: string; note?: string; prov?: Prov; sources_prov?: Record<string, Prov | undefined> }

/** "Read this chart": five bullets from the server, built only from the levels, patterns, engine signal and quote. */
export function ChartRead({ symbol, market, interval }: { symbol: string; market: Market; interval: string }) {
  const { askAI, setPageCtx } = useStore();
  const [res, setRes] = useState<ReadOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const key = `${symbol}|${market}|${interval}`;
  const [forKey, setForKey] = useState(key);
  if (forKey !== key) { setForKey(key); setRes(null); setErr(null); }
  const read = async () => {
    setBusy(true); setErr(null);
    try { setRes(await api.get<ReadOut>(`/api/markets/chart/read${qs({ symbol, market, interval })}`)); }
    catch (e: any) { setErr(e?.message || "Chart read failed"); }
    finally { setBusy(false); }
  };
  const ask = () => {
    setPageCtx({ symbol, market: market === "FX" ? undefined : market });
    askAI(`Looking at the ${symbol} ${interval} chart: what are the key support/resistance levels, the latest structure, and what is the engine doing?`);
  };
  return (
    <Card className="chart-read" title="AI chart read" sub={`${symbol} · ${interval} · from measured levels, patterns and the engine's state only`}
      actions={<>
        {res && <Badge tone={res.source === "template" ? "flat" : "accent"}>{res.source === "template" ? "template" : `AI · ${res.source}`}</Badge>}
        {res && <ProvBadge prov={res.prov} loading={false} />}
        <button className="btn sm" onClick={read} disabled={busy}>{busy ? "Reading…" : res ? "Read again" : "Read this chart"}</button>
        <button className="btn sm ghost" onClick={ask}>Ask AI about this chart</button>
      </>}>
      <ErrorNote error={err} onRetry={read} />
      {res ? (
        <div className="stack" style={{ gap: 6 }}>
          <ul className="read-list">{res.bullets.map((b, i) => <li key={i}>{b}</li>)}</ul>
          {res.note && <div className="faint" style={{ fontSize: 12 }}>{res.note}</div>}
        </div>
      ) : !err && <div className="faint" style={{ fontSize: 13 }}>Press “Read this chart” for a five-point read: trend, levels with their hold rates, the engine's stance, risks, and what would change the view.</div>}
    </Card>
  );
}
