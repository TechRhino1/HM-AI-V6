import { useMemo, useState } from "react";
import { qs } from "../../lib/api";
import { useLocalStorage, usePoll } from "../../lib/hooks";
import { fixed, isNum, num, parseTime, pct, tone } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, Field, KV, Loading, Modal, sideTone } from "../../components/ui";
import { CandleChart, Candle, PriceLevel } from "../../components/Chart";
import { ProvBadge } from "../../components/ProvBadge";
import { MiniStat } from "../overview/Overview";
import { QuickAlert } from "../alerts/Alerts";
import { isMissingEndpoint, Prov, sortRows } from "./logic";
import { ChartRead, DEFAULT_LAYERS, LayerBar, Layers, LevelList, useChartIntel } from "../../components/ChartIntel";

type Market = "IN" | "US";
interface Row {
  symbol: string; name?: string; sector?: string; price?: number; change_pct?: number; price_prov?: Prov; volume?: number; rvol?: number;
  rsi?: number; atr_pct?: number; vwap?: number; perf_w?: number; perf_1m?: number; perf_3m?: number; market_cap?: number;
  earnings_date?: string | null; tech_prov?: Prov; momentum_rank?: number; momentum_percentile?: number; trend?: string;
}
interface Scan {
  rows?: Row[]; sectors?: { sector: string; avg_change_pct: number; count: number; leader?: string }[];
  momentum?: { validated?: boolean; stats?: Record<string, unknown>; recommended?: (string | Row)[]; reason?: string }; prov?: Prov;
}

const ccyOf = (m: Market) => (m === "IN" ? "₹" : "$");
const big = (v: unknown) => (!isNum(v) ? "—" : v >= 1e12 ? `${fixed(v / 1e12, 2)}T` : v >= 1e9 ? `${fixed(v / 1e9, 2)}B` : v >= 1e6 ? `${fixed(v / 1e6, 1)}M` : v >= 1e3 ? `${fixed(v / 1e3, 1)}K` : num(v, 0));
const signedPct = (v: unknown, d = 2) => (isNum(v) ? `${v > 0 ? "+" : ""}${fixed(v, d)}%` : "—");
const MissingEndpoint = ({ what }: { what: string }) => (
  <Empty title="Endpoint not available yet" icon="info">{what} is still being built on the server; this panel fills in once it is deployed.</Empty>
);

const COLS: [keyof Row, string][] = [
  ["price", "Price"], ["change_pct", "Chg %"], ["volume", "Volume"], ["rvol", "RVOL"], ["rsi", "RSI"], ["atr_pct", "ATR %"],
  ["perf_w", "1W"], ["perf_1m", "1M"], ["perf_3m", "3M"], ["market_cap", "Mcap"], ["momentum_percentile", "Mom. pct"], ["earnings_date", "Earnings"],
];

/** India equities / US stocks: index strip, scanner, sector heatmap, momentum picks, detail drawer, compare. */
export function Equities({ market }: { market: Market }) {
  const scan = usePoll<Scan>(`/api/markets/equities/scan?market=${market}`, 60000);
  const [watch, setWatch] = useLocalStorage<string[]>(`hm.mk.watch.${market}`, []);
  const [sector, setSector] = useState("");
  const [q, setQ] = useState("");
  const [onlyWatch, setOnlyWatch] = useState(false);
  const [sort, setSort] = useState<{ k: keyof Row; desc: boolean }>({ k: "change_pct", desc: true });
  const [open, setOpen] = useState<string | null>(null);
  const [cmp, setCmp] = useState<[string, string] | null>(null);
  const missing = isMissingEndpoint(scan.error);
  const rows = scan.data?.rows || [];

  const list = useMemo(() => {
    const t = q.trim().toLowerCase();
    const f = rows.filter((r) => (!sector || r.sector === sector) && (!onlyWatch || watch.includes(r.symbol))
      && (!t || `${r.symbol} ${r.name || ""}`.toLowerCase().includes(t)));
    return sortRows(f, (r) => r[sort.k], sort.desc);
  }, [rows, sector, q, onlyWatch, watch, sort]);
  const techProv = rows.find((r) => r.tech_prov)?.tech_prov;
  const priceProv = rows.find((r) => r.price_prov)?.price_prov;
  const star = (s: string) => setWatch(watch.includes(s) ? watch.filter((x) => x !== s) : [...watch, s]);

  return (
    <>
      <IndexStrip market={market} />
      <div className="grid cols-2">
        <Card title="Sector heatmap" sub="Average change today · click to filter" actions={<ProvBadge prov={scan.data?.prov} />}>
          {missing ? <MissingEndpoint what="The equities scanner" /> : scan.loading && !scan.data ? <Loading /> : !scan.data?.sectors?.length ? <Empty title="No sector data" /> : (
            <div className="mk-heat">
              {scan.data.sectors.map((s) => (
                <button key={s.sector} className={`mk-tile ${sector === s.sector ? "on" : ""}`} onClick={() => setSector(sector === s.sector ? "" : s.sector)}
                  style={{ background: heat(s.avg_change_pct) }} title={`${s.count} stocks · leader ${s.leader || "—"}`}>
                  <b>{s.sector}</b><span className="mono">{signedPct(s.avg_change_pct)}</span>
                </button>
              ))}
            </div>
          )}
        </Card>
        <Momentum m={scan.data?.momentum} missing={missing} loading={scan.loading && !scan.data} onOpen={setOpen} />
      </div>

      <Card title="Scanner" flush
        sub={<>Prices <ProvBadge prov={priceProv} /> · technicals <ProvBadge prov={techProv} /> · TradingView technicals are 15-minute delayed; prices are live</>}
        actions={
          <div className="row wrap" style={{ gap: 6 }}>
            <input className="input" style={{ width: 160, height: 30 }} placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search symbols" />
            <button className={`chip ${onlyWatch ? "on" : ""}`} onClick={() => setOnlyWatch(!onlyWatch)}>★ Watchlist ({watch.length})</button>
          </div>
        }>
        {!!scan.data?.sectors?.length && (
          <div className="row wrap" style={{ gap: 6, padding: "10px 14px", borderBottom: "1px solid var(--line)" }}>
            <button className={`chip ${!sector ? "on" : ""}`} onClick={() => setSector("")}>All sectors</button>
            {scan.data.sectors.map((s) => <button key={s.sector} className={`chip ${sector === s.sector ? "on" : ""}`} onClick={() => setSector(s.sector)}>{s.sector}</button>)}
          </div>
        )}
        {missing ? <MissingEndpoint what="/api/markets/equities/scan" /> : <ErrorNote error={scan.error} onRetry={scan.reload} />}
        {missing ? null : scan.loading && !scan.data ? <Loading rows={6} /> : !list.length ? <Empty title="No stocks match" /> : (
          <div className="table-wrap" style={{ maxHeight: 560 }}>
            <table className="table">
              <thead><tr>
                <th aria-label="Watchlist" />
                <th className="sortable" onClick={() => setSort({ k: "symbol", desc: sort.k === "symbol" ? !sort.desc : false })}>Symbol{sort.k === "symbol" ? (sort.desc ? " ↓" : " ↑") : ""}</th>
                {COLS.map(([k, l]) => (
                  <th key={k} className="sortable r" onClick={() => setSort({ k, desc: sort.k === k ? !sort.desc : true })}
                    aria-sort={sort.k === k ? (sort.desc ? "descending" : "ascending") : undefined}>{l}{sort.k === k ? (sort.desc ? " ↓" : " ↑") : ""}</th>
                ))}
                <th>Trend</th>
              </tr></thead>
              <tbody>{list.map((r) => (
                <tr key={r.symbol} className="clickable" onClick={() => setOpen(r.symbol)}>
                  <td><button className={`btn ghost sm icon-btn ${watch.includes(r.symbol) ? "warn" : "faint"}`} aria-label={`Watch ${r.symbol}`}
                    onClick={(e) => { e.stopPropagation(); star(r.symbol); }}>{watch.includes(r.symbol) ? "★" : "☆"}</button></td>
                  <td><b>{r.symbol}</b><div className="faint" style={{ fontSize: 11.5, maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis" }}>{r.name || r.sector || ""}</div></td>
                  <td className="num">{isNum(r.price) ? `${ccyOf(market)}${fixed(r.price, 2)}` : "—"}{r.price_prov?.kind && r.price_prov.kind !== "live" && <span className="faint"> ({r.price_prov.kind})</span>}</td>
                  <td className={`num ${tone(r.change_pct)}`}>{signedPct(r.change_pct)}</td>
                  <td className="num">{big(r.volume)}</td>
                  <td className="num">{isNum(r.rvol) ? `${fixed(r.rvol, 2)}×` : "—"}</td>
                  <td className={`num ${isNum(r.rsi) && r.rsi > 70 ? "down" : isNum(r.rsi) && r.rsi < 30 ? "up" : ""}`}>{fixed(r.rsi, 0)}</td>
                  <td className="num">{pct(r.atr_pct, 2)}</td>
                  <td className={`num ${tone(r.perf_w)}`}>{signedPct(r.perf_w, 1)}</td>
                  <td className={`num ${tone(r.perf_1m)}`}>{signedPct(r.perf_1m, 1)}</td>
                  <td className={`num ${tone(r.perf_3m)}`}>{signedPct(r.perf_3m, 1)}</td>
                  <td className="num">{big(r.market_cap)}</td>
                  <td className="num">{isNum(r.momentum_percentile) ? fixed(r.momentum_percentile, 0) : "—"}</td>
                  <td className="num">{r.earnings_date || "—"}</td>
                  <td><span className={sideTone(r.trend)}>{r.trend || "—"}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Card>

      {open && <Detail symbol={open} market={market} others={rows.map((r) => r.symbol)} onClose={() => setOpen(null)}
        onCompare={(b) => { setCmp([open, b]); setOpen(null); }} />}
      {cmp && <Compare a={cmp[0]} b={cmp[1]} market={market} onClose={() => setCmp(null)} />}
    </>
  );
}

const heat = (v: number) => {
  const a = Math.min(1, Math.abs(v || 0) / 3) * 55 + 8; // ±3% saturates
  return `color-mix(in srgb, var(${v >= 0 ? "--up" : "--down"}) ${a.toFixed(0)}%, var(--surface-2))`;
};

function IndexStrip({ market }: { market: Market }) {
  const ind = usePoll<{ rows?: { name: string; last?: number; change_pct?: number }[]; prov?: Prov }>(market === "IN" ? "/api/markets/indices" : null, 60000);
  const us = usePoll<{ quotes?: { symbol: string; price?: number; change_pct?: number; prov?: Prov; extra?: { name?: string } }[] }>(
    market === "US" ? "/api/markets/quote?symbols=SPY,QQQ,DIA,IWM&market=US" : null, 60000);
  const items = market === "IN"
    ? (ind.data?.rows || []).slice(0, 8).map((r) => ({ k: r.name, v: r.last, c: r.change_pct, prov: ind.data?.prov }))
    : (us.data?.quotes || []).map((r) => ({ k: r.symbol, v: r.price, c: r.change_pct, prov: r.prov }));
  const err = ind.error || us.error;
  return (
    <div className="mk-strip">
      {err && <ErrorNote error={err} />}
      {items.map((x) => (
        <div key={x.k} className="mk-strip-item">
          <div className="faint" style={{ fontSize: 11.5, whiteSpace: "nowrap" }}>{x.k}</div>
          <div className="mono" style={{ fontWeight: 600 }}>{num(x.v, 2)} <span className={tone(x.c)} style={{ fontSize: 12 }}>{signedPct(x.c)}</span></div>
          <ProvBadge prov={x.prov} loading={false} />
        </div>
      ))}
      {!items.length && !err && <div className="faint" style={{ padding: 8 }}>Loading indices…</div>}
    </div>
  );
}

function Momentum({ m, missing, loading, onOpen }: { m?: Scan["momentum"]; missing: boolean; loading: boolean; onOpen: (s: string) => void }) {
  const picks = (m?.recommended || []).map((r) => (typeof r === "string" ? r : r.symbol));
  return (
    <Card title="Momentum picks" sub="Shown only when the momentum ranking beats its benchmark out of sample"
      actions={m && <Badge tone={m.validated ? "up" : "warn"}>{m.validated ? "validated" : "not validated"}</Badge>}>
      {missing ? <MissingEndpoint what="The momentum ranking" /> : loading ? <Loading /> : !m ? <Empty title="No momentum data" /> : (
        <div className="stack">
          {m.validated && picks.length ? (
            <div className="row wrap" style={{ gap: 6 }}>{picks.map((s) => <button key={s} className="chip on" onClick={() => onOpen(s)}>{s}</button>)}</div>
          ) : <div className="alert warn">No picks: {m.reason || (m.validated ? "nothing ranks high enough today" : "the ranking has not shown an edge, so nothing is recommended")}.</div>}
          {m.stats && (() => {
            const st = m.stats as Record<string, any>;
            const sg = (v: unknown, d: number) => (isNum(v) ? `${v > 0 ? "+" : ""}${fixed(v, d)}%` : "—");
            return <KV items={[
              ["Signal", "12-1 month momentum, top quintile held one month"],
              ["Test period", `${st.from ?? "—"} → ${st.to ?? "—"} (${st.months ?? "—"} months)`],
              ["Mean monthly excess vs universe", sg(st.mean_excess_pct, 2)],
              ["t-statistic", isNum(st.t_stat) ? fixed(st.t_stat, 2) : "—"],
              ["Months beating the universe", isNum(st.pct_months_positive) ? `${fixed(st.pct_months_positive, 1)}%` : "—"],
              ["Worst drawdown of the excess", sg(st.max_drawdown_excess_pct, 1)],
            ]} />;
          })()}
          {(m as any).survivorship_note && <div className="alert warn" style={{ fontSize: 12.5 }}><b>Caveat:</b> {(m as any).survivorship_note}</div>}
        </div>
      )}
    </Card>
  );
}

interface Detail {
  quote?: { price?: number; change_pct?: number; prov?: Prov; [k: string]: unknown };
  bars?: { bars?: Record<string, unknown>[]; last_bar_forming?: boolean; prov?: Prov };
  technicals?: Record<string, number | null>; pivots?: { P?: number; R1?: number; R2?: number; S1?: number; S2?: number; based_on?: string; prov?: Prov };
  earnings?: Record<string, unknown> | null; momentum?: Record<string, unknown> | null; risk_sizing?: Record<string, unknown> | null; prov?: Prov;
}
const toCandle = (b: Record<string, unknown>): Candle | null => {
  const t = parseTime(b.time ?? b.t ?? b.date ?? b.timestamp);
  const o = Number(b.open ?? b.o), h = Number(b.high ?? b.h), l = Number(b.low ?? b.l), c = Number(b.close ?? b.c);
  if (!t || ![o, h, l, c].every(Number.isFinite)) return null;
  return { time: Math.floor(t.getTime() / 1000), open: o, high: h, low: l, close: c, volume: Number(b.volume ?? b.v) || 0 };
};
const kvOf = (o?: Record<string, unknown> | null) =>
  Object.entries(o || {}).filter(([k, v]) => k !== "prov" && (typeof v !== "object" || v === null))
    .map(([k, v]) => [k.replace(/_/g, " "), isNum(v) ? num(v, 2) : v === null || v === undefined ? "—" : String(v)] as [string, string]);

function Detail({ symbol, market, others, onClose, onCompare }: {
  symbol: string; market: Market; others: string[]; onClose: () => void; onCompare: (b: string) => void;
}) {
  const [risk, setRisk] = useState({ equity: "", risk_pct: "1", atr_mult: "2" });
  const [applied, setApplied] = useState(risk);
  const [b, setB] = useState("");
  const d = usePoll<Detail>(`/api/markets/equities/detail${qs({ symbol, market, ...applied })}`, 60000);
  const news = usePoll<{ items?: { title: string; link?: string; source?: string; published?: string }[]; prov?: Prov }>(`/api/markets/equities/news${qs({ symbol, market })}`, 300000);
  const candles = useMemo(() => (d.data?.bars?.bars || []).map(toCandle).filter((c): c is Candle => !!c).sort((x, y) => x.time - y.time), [d.data]);
  const lv = d.data?.pivots;
  const levels: PriceLevel[] = useMemo(() => [
    ["P", "P", "accent"], ["R1", "R1", "down"], ["R2", "R2", "down"], ["S1", "S1", "up"], ["S2", "S2", "up"],
  ].filter(([k]) => isNum((lv as any)?.[k])).map(([k, label, t]) => ({ price: (lv as any)[k], label, tone: t as PriceLevel["tone"], dashed: true })), [lv]);
  const t = d.data?.technicals;
  const [layers, setLayers] = useLocalStorage<Layers>("hm.eq.layers", DEFAULT_LAYERS);
  const intel = useChartIntel(symbol, market, "D1", layers);
  const lines = useMemo(() => [...levels, ...intel.lines], [levels, intel.lines]);
  return (
    <Modal drawer title={<span className="row" style={{ gap: 8 }}>{symbol}<ProvBadge prov={d.data?.quote?.prov || d.data?.prov} loading={!d.data} /></span>} onClose={onClose}>
      {isMissingEndpoint(d.error) ? <MissingEndpoint what="/api/markets/equities/detail" /> : <ErrorNote error={d.error} onRetry={d.reload} />}
      {d.loading && !d.data ? <Loading rows={6} /> : d.data && (
        <>
          <div className="row" style={{ gap: 10, alignItems: "baseline" }}>
            <span className="mono" style={{ fontSize: 24, fontWeight: 600 }}>{isNum(d.data.quote?.price) ? `${ccyOf(market)}${fixed(d.data.quote!.price, 2)}` : "—"}</span>
            <span className={tone(d.data.quote?.change_pct)}>{signedPct(d.data.quote?.change_pct)}</span>
          </div>
          <div>
            <div className="row between" style={{ marginBottom: 6 }}>
              <span className="faint" style={{ fontSize: 12 }}>Daily bars{d.data.bars?.last_bar_forming ? " · last bar still forming" : ""}</span>
              <ProvBadge prov={d.data.bars?.prov} loading={false} />
            </div>
            <LayerBar layers={layers} setLayers={setLayers} only={["levels", "vp", "patterns"]} />
            {candles.length ? <div className="mk-chart"><CandleChart candles={candles} levels={lines} markers={intel.markers} tips={intel.tips} /></div> : <Empty title="No bars available" />}
            {layers.levels && <LevelList lv={intel.lv} symbol={symbol} market={market} />}
          </div>
          <ChartRead symbol={symbol} market={market} interval="D1" />
          <div className="grid mk-stats">
            <MiniStat label="SMA 20 / 50" value={`${fixed(t?.sma20, 2)} / ${fixed(t?.sma50, 2)}`} />
            <MiniStat label="SMA 200" value={fixed(t?.sma200, 2)} />
            <MiniStat label="RSI 14" value={fixed(t?.rsi14, 1)} />
            <MiniStat label="ATR 14" value={`${fixed(t?.atr14, 2)} (${pct(t?.atr_pct, 2)})`} />
            <MiniStat label="52w range" value={`${fixed(t?.low_52w, 2)} – ${fixed(t?.high_52w, 2)}`} />
            <MiniStat label="From 52w high" value={pct(t?.from_high_52w_pct, 1)} />
          </div>
          <div>
            <div className="row between" style={{ marginBottom: 6 }}><b style={{ fontSize: 13 }}>Pivot levels</b><ProvBadge prov={lv?.prov} loading={false} /></div>
            <KV items={kvOf(lv as Record<string, unknown>)} />
            {isNum(d.data.quote?.price) && levels.length > 0 && (
              <div className="row wrap" style={{ gap: 6, marginTop: 8, fontSize: 12 }}>
                <span className="faint">Alert when price crosses</span>
                {levels.map((l) => {
                  const dir = l.price > d.data!.quote!.price! ? "above" : "below";
                  return <span key={l.label} className="chip" style={{ cursor: "default" }}>{l.label} {fixed(l.price, 2)}
                    <QuickAlert rule={{ type: "level_cross", symbol, market, level: Math.round(l.price * 100) / 100, direction: dir }} title={`Alert when ${symbol} crosses ${dir} ${l.label} ${fixed(l.price, 2)}`} /></span>;
                })}
              </div>
            )}
          </div>
          {d.data.earnings && <div><b style={{ fontSize: 13 }}>Earnings</b><KV items={kvOf(d.data.earnings)} /></div>}
          {d.data.momentum && <div><b style={{ fontSize: 13 }}>Momentum</b><KV items={kvOf(d.data.momentum)} /></div>}
          <div className="stack">
            <b style={{ fontSize: 13 }}>Risk calculator</b>
            <div className="grid cols-3" style={{ gap: 8 }}>
              <Field label="Equity"><input className="input mono" inputMode="decimal" value={risk.equity} onChange={(e) => setRisk({ ...risk, equity: e.target.value })} /></Field>
              <Field label="Risk %"><input className="input mono" inputMode="decimal" value={risk.risk_pct} onChange={(e) => setRisk({ ...risk, risk_pct: e.target.value })} /></Field>
              <Field label="Stop (× ATR)"><input className="input mono" inputMode="decimal" value={risk.atr_mult} onChange={(e) => setRisk({ ...risk, atr_mult: e.target.value })} /></Field>
            </div>
            <button className="btn sm" disabled={!Number(risk.equity)} onClick={() => setApplied(risk)}>Size position</button>
            {d.data.risk_sizing ? <KV items={kvOf(d.data.risk_sizing)} /> : <div className="faint" style={{ fontSize: 12.5 }}>Enter equity to size a position from the ATR stop.</div>}
          </div>
        </>
      )}
      <div className="stack">
        <div className="row between"><b style={{ fontSize: 13 }}>News</b><ProvBadge prov={news.data?.prov} /></div>
        {isMissingEndpoint(news.error) ? <MissingEndpoint what="/api/markets/equities/news" /> : <ErrorNote error={news.error} />}
        {news.data?.items?.length ? news.data.items.slice(0, 10).map((n, i) => (
          <a key={i} href={n.link} target="_blank" rel="noreferrer noopener" className="list-item" style={{ padding: "8px 0" }}>
            <div className="grow"><div>{n.title}</div><div className="faint" style={{ fontSize: 11.5 }}>{n.source} · {n.published}</div></div>
          </a>
        )) : !news.loading && !news.error && <div className="faint">No recent news.</div>}
      </div>
      <div className="row" style={{ gap: 8 }}>
        <select className="select" value={b} onChange={(e) => setB(e.target.value)} aria-label="Compare with">
          <option value="">Compare with…</option>
          {others.filter((s) => s !== symbol).map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <button className="btn" disabled={!b} onClick={() => onCompare(b)}>Compare</button>
      </div>
    </Modal>
  );
}

function Compare({ a, b, market, onClose }: { a: string; b: string; market: Market; onClose: () => void }) {
  const c = usePoll<Record<string, any>>(`/api/markets/equities/compare${qs({ a, b, market })}`);
  const A = c.data?.a ?? c.data?.[a], B = c.data?.b ?? c.data?.[b];
  const keys = A && B ? [...new Set([...Object.keys(A), ...Object.keys(B)])].filter((k) => typeof A[k] !== "object" && typeof B[k] !== "object") : [];
  const cell = (v: unknown) => (isNum(v) ? num(v, 2) : v === null || v === undefined ? "—" : String(v));
  return (
    <Modal wide title={`${a} vs ${b}`} onClose={onClose}>
      {isMissingEndpoint(c.error) ? <MissingEndpoint what="/api/markets/equities/compare" /> : <ErrorNote error={c.error} onRetry={c.reload} />}
      {c.loading && !c.data ? <Loading /> : keys.length ? (
        <div className="table-wrap"><table className="table">
          <thead><tr><th /><th className="r">{a}</th><th className="r">{b}</th></tr></thead>
          <tbody>{keys.map((k) => <tr key={k}><td className="faint">{k.replace(/_/g, " ")}</td><td className="num">{cell(A[k])}</td><td className="num">{cell(B[k])}</td></tr>)}</tbody>
        </table></div>
      ) : c.data && <KV items={kvOf(c.data)} />}
      {c.data?.prov && <ProvBadge prov={c.data.prov} />}
    </Modal>
  );
}
