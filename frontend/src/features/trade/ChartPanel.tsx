import { useMemo } from "react";
import type { SeriesMarker, Time } from "lightweight-charts";
import { useStore } from "../../state/store";
import { usePoll, useLocalStorage } from "../../lib/hooks";
import { cleanSymbol, parseTime, price, signedMoney, tone } from "../../lib/format";
import { CandleChart, Candle, PriceLevel } from "../../components/Chart";
import { Badge, Card, ErrorNote, Seg } from "../../components/ui";
import { ChartRead, DEFAULT_LAYERS, LayerBar, Layers, LevelList, useChartIntel } from "../../components/ChartIntel";
import { useSignal } from "./SignalPanel";

const TFS = ["M5", "M15", "H1", "H4", "D1"] as const;
const MTF = ["D1", "H4", "H1", "M15", "M5"];

/** Candles plus real overlays only: measured levels, volume profile, patterns, the engine's plan and your positions. */
export function ChartPanel() {
  const { symbol, symbols, telemetry } = useStore();
  const [tf, setTf] = useLocalStorage<string>("hm.tf", "H1");
  const [layers, setLayers] = useLocalStorage<Layers>("hm.chart.layers", DEFAULT_LAYERS);
  const res = usePoll<{ candles: Candle[] }>(`/api/candles?symbol=${encodeURIComponent(symbol)}&tf=${tf}`, 20000);
  const spec = symbols.find((s) => s.symbol === symbol);
  const intel = useChartIntel(symbol, "FX", tf, layers);
  const sig = useSignal(symbol);
  const eng = sig.data?.engine;

  const mine = useMemo(() => (telemetry?.positions || []).filter((p) => cleanSymbol(p.symbol) === symbol), [telemetry?.positions, symbol]);

  const levels = useMemo<PriceLevel[]>(() => {
    const out: PriceLevel[] = [...intel.lines];
    if (layers.positions) for (const p of mine) {
      const side = String(p.type).toUpperCase().includes("BUY") ? "Buy" : "Sell";
      out.push({ price: p.open_price, label: `${side} ${p.volume}`, tone: "accent" });
      out.push({ price: p.sl, label: p.is_be_locked ? "SL (BE)" : "SL", tone: "down" });
      out.push({ price: p.tp, label: "TP", tone: "up" });
    }
    if (layers.signal && eng && isFinite(eng.entry) && eng.entry > 0) {
      out.push({ price: eng.entry, label: `Engine ${eng.side} entry`, tone: "flat", dashed: true });
      out.push({ price: eng.stop_loss, label: "Engine SL", tone: "down", dashed: true });
      out.push({ price: eng.take_profit, label: "Engine TP", tone: "up", dashed: true });
    }
    return out;
  }, [intel.lines, mine, eng, layers.positions, layers.signal]);

  const markers = useMemo<SeriesMarker<Time>[]>(() => {
    const pos = layers.positions ? mine.map((p) => {
      const t = parseTime(p.open_time);
      const buy = String(p.type).toUpperCase().includes("BUY");
      return t ? { time: Math.floor(t.getTime() / 1000) as Time, position: buy ? "belowBar" : "aboveBar", color: buy ? "#22c58b" : "#f2555a", shape: buy ? "arrowUp" : "arrowDown", text: `${buy ? "Buy" : "Sell"} ${p.volume}` } as SeriesMarker<Time> : null;
    }).filter((m): m is SeriesMarker<Time> => !!m) : [];
    return [...pos, ...intel.markers].sort((a, b) => (a.time as number) - (b.time as number));
  }, [mine, intel.markers, layers.positions]);

  const candles = res.data?.candles || [];
  const last = candles[candles.length - 1];
  const prev = candles[candles.length - 2];
  const chg = last && prev ? ((last.close - prev.close) / prev.close) * 100 : undefined;
  const floating = mine.reduce((a, p) => a + (p.profit || 0), 0);

  const barsProv = (res.data as { prov?: { kind?: string; note?: string } } | undefined)?.prov;
  return (
    <>
    <Card
      title={<span className="row" style={{ gap: 10 }}>{symbol}
        <span className="mono" style={{ fontWeight: 500 }}>{last ? price(last.close, spec?.digits) : ""}</span>
        {chg !== undefined && <span className={`mono ${tone(chg)}`} style={{ fontSize: 12.5 }}>{chg >= 0 ? "+" : ""}{chg.toFixed(2)}%</span>}
      </span>}
      sub={mine.length ? <span>{mine.length} open · <span className={tone(floating)}>{signedMoney(floating)}</span></span> : spec ? `${spec.asset_class.toLowerCase()} · ${spec.session_name}` : undefined}
      actions={<Seg value={tf} onChange={setTf} options={TFS.map((t) => ({ value: t, label: t }))} />}
      flush>
      <div className="chart-strip">
        <LayerBar layers={layers} setLayers={setLayers} />
        {eng && (
          <div className="row wrap" style={{ gap: 6 }}>
            {eng.regime && <Badge tone="accent">{String(eng.regime).replace(/_/g, " ").toLowerCase()}{eng.regime_confidence != null ? ` · ${Math.round(eng.regime_confidence * 100)}%` : ""}</Badge>}
            {MTF.filter((k) => eng.mtf?.[k]).map((k) => {
              const v = String(eng.mtf[k]).toUpperCase();
              return <span key={k} className={`badge ${v.includes("BULL") ? "up" : v.includes("BEAR") ? "down" : ""}`} title={`${k}: ${v}`}>{k} {v.includes("BULL") ? "▲" : v.includes("BEAR") ? "▼" : "•"}</span>;
            })}
            {layers.signal && eng.gate_chips.slice(0, 2).map((c) => <span key={c} className="badge down" title={c}>{c}</span>)}
          </div>
        )}
      </div>
      <ErrorNote error={res.error && !candles.length ? `Chart data unavailable: ${res.error}` : !res.error && res.data && !candles.length ? `Chart data unavailable: ${barsProv?.note || "the broker returned no bars"}` : null} onRetry={res.reload} />
      <CandleChart candles={candles} levels={levels} markers={markers} digits={spec?.digits} tips={intel.tips} />
      {layers.levels && <div className="chart-foot"><LevelList lv={intel.lv} symbol={symbol} market="FX" digits={spec?.digits} /></div>}
    </Card>
    <ChartRead symbol={symbol} market="FX" interval={tf} />
    </>
  );
}
