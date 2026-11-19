import { useMemo, useState } from "react";
import { api, qs } from "../../lib/api";
import { usePoll, useLocalStorage } from "../../lib/hooks";
import { ago, cleanSymbol, isNum, money, num, parseTime, pct, price, rMult, signedMoney, tone } from "../../lib/format";
import type { ClosedTrade, Position } from "../../lib/types";
import { useStore } from "../../state/store";
import { useFeedback } from "../../components/feedback";
import { Badge, Card, Empty, ErrorNote, Loading, Modal, sideTone } from "../../components/ui";
import { LineChart } from "../../components/Chart";
import { ProvBadge } from "../../components/ProvBadge";
import { Icon } from "../../components/Icon";
import type { Prov } from "../markets/logic";
import { rOf } from "../portfolio/OpenPositions";
import { equityCurve } from "../analytics/Performance";
import { FILTERS, filterTimeline, type TimelineEvent } from "./layout";

type Market = "FX" | "IN" | "US";
interface Series { times: number[]; closes: number[]; last?: number; change_pct?: number | null; prev_close?: number | null; prov?: Prov }
interface Sparks { series?: Record<string, Series>; unavailable?: string[]; prov?: Prov }

/** Intraday closes for many symbols in one request (refreshed every minute). */
export function useSparks(symbols: string[], market: Market) {
  const list = [...new Set(symbols.filter(Boolean))].sort().join(",");
  return usePoll<Sparks>(list ? `/api/markets/overview/sparklines${qs({ market, symbols: list })}` : null, 60000);
}

/** Tiny line of closes; colour follows first → last. Renders "no data" text when the series is empty. */
export function Sparkline({ values, height = 28, label }: { values?: number[]; height?: number; label?: string }) {
  if (!values || values.length < 2) return <span className="faint spark-none">no data</span>;
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const pts = values.map((v, i) => `${((i / (values.length - 1)) * 100).toFixed(2)},${(height - 2 - ((v - lo) / span) * (height - 4)).toFixed(2)}`).join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg className="spark" viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" height={height} role="img"
      aria-label={label || `${values.length} points, ${up ? "up" : "down"} from ${values[0]} to ${values[values.length - 1]}`}>
      <polyline points={pts} fill="none" stroke={`var(--${up ? "up" : "down"})`} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const sideOf = (p: Position) => (String(p.type).toUpperCase().includes("BUY") ? "BUY" : "SELL");
const pnlOfPos = (p: Position) => (p.profit || 0) + (p.swap || 0) + (p.commission || 0);

// ---------------------------------------------------------------- since you last looked

const VISIT_KEY = "hm.overview.lastVisit";
interface Visit { ts: number; equity?: number }
interface Summary { bullets?: string[]; source?: string; note?: string; prov?: Prov; since?: number }

export function SinceLastLooked() {
  const { telemetry } = useStore();
  const [visit, setVisit] = useLocalStorage<Visit | null>(VISIT_KEY, null);
  const path = `/api/markets/overview/changes/summary${qs({ since: visit?.ts, equity_then: visit?.equity })}`;
  const res = usePoll<Summary>(path, 5 * 60000);
  const markRead = () => setVisit({ ts: Math.floor(Date.now() / 1000), equity: telemetry?.account?.equity || undefined });
  const ai = res.data?.source && res.data.source !== "template";
  return (
    <Card title={<span className="row" style={{ gap: 8 }}><Icon name="chat" size={15} />Since you last looked</span>}
      sub={visit ? `Changes since ${ago(visit.ts)}` : "Changes since the start of today (IST)"}
      actions={<>
        {res.data && <Badge tone={ai ? "accent" : "flat"}>{ai ? `AI · ${res.data.source}` : "template"}</Badge>}
        <ProvBadge prov={res.data?.prov} loading={res.loading && !res.data} />
        <button className="btn sm" onClick={markRead} title="Remember now as your last visit">Mark as read</button>
      </>}>
      {res.error && !res.data ? <ErrorNote error={`Summary unavailable: ${res.error}`} onRetry={res.reload} />
        : res.loading && !res.data ? <Loading rows={4} />
        : <div className="stack" style={{ gap: 8 }}>
            <ul className="since-list">{(res.data?.bullets || []).map((b, i) => <li key={i}>{b}</li>)}</ul>
            {res.data?.note && <div className="faint" style={{ fontSize: 12 }}>{res.data.note}.</div>}
            <div className="faint" style={{ fontSize: 11.5 }}>Written only from the fact sheet (account, journal, alerts, engine decisions, index moves); every AI figure is checked against it.</div>
          </div>}
    </Card>
  );
}

// ---------------------------------------------------------------- today timeline

const KIND_TONE: Record<string, "up" | "down" | "warn" | "accent" | "flat"> = { trade: "up", alert: "warn", brief: "accent", recommendation: "accent", signal: "flat" };

export function TimelineWidget({ go }: { go: (r: string) => void }) {
  const { setPanel, setSymbol } = useStore();
  const res = usePoll<{ events?: TimelineEvent[]; total?: number; sources?: Record<string, { ok: boolean; error?: string }>; prov?: Prov; day_basis?: string }>(
    "/api/markets/overview/timeline?limit=400", 60000);
  const [on, setOn] = useLocalStorage<string[]>("hm.overview.tl.filters", FILTERS.map((f) => f.id));
  const [sym, setSym] = useState("");
  const [shown, setShown] = useState(40);
  const rows = useMemo(() => filterTimeline(res.data?.events || [], on, sym), [res.data, on, sym]);
  const failed = Object.entries(res.data?.sources || {}).filter(([, s]) => !s.ok);
  const open = (e: TimelineEvent) => {
    if (e.link === "alerts") return setPanel("alerts");
    if (e.symbol && e.kind === "signal") setSymbol(e.symbol);
    go(e.link);
  };
  return (
    <Card title="Today timeline" sub={res.data?.day_basis || "Trades, alerts, briefs, engine signals"} flush
      actions={<ProvBadge prov={res.data?.prov} loading={res.loading && !res.data} />}>
      <div className="row wrap" style={{ gap: 6, padding: "10px 14px", borderBottom: "1px solid var(--line)" }}>
        {FILTERS.map((f) => (
          <button key={f.id} className={`chip ${on.includes(f.id) ? "on" : ""}`} aria-pressed={on.includes(f.id)}
            onClick={() => setOn(on.includes(f.id) ? on.filter((x) => x !== f.id) : [...on, f.id])}>{f.label}</button>
        ))}
        <input className="input" style={{ width: 110, height: 28 }} placeholder="Symbol" aria-label="Filter timeline by symbol" value={sym} onChange={(e) => setSym(e.target.value)} />
      </div>
      {failed.length > 0 && <div className="alert warn" style={{ margin: 10 }}>Unavailable: {failed.map(([k, s]) => `${k} (${s.error})`).join("; ")}</div>}
      {res.error && !res.data ? <ErrorNote error={res.error} onRetry={res.reload} />
        : res.loading && !res.data ? <Loading rows={5} />
        : !rows.length ? <Empty title="Nothing yet today" icon="clock">No events match these filters.</Empty>
        : <div className="list timeline">
            {rows.slice(0, shown).map((e, i) => (
              <button key={`${e.ts}-${i}`} className="list-item clickable tl-row" onClick={() => open(e)} title={`${e.prov?.source || ""} · open ${e.link}`}>
                <span className="mono faint tl-time">{parseTime(e.ts)?.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                <span className="grow" style={{ minWidth: 0 }}>
                  <span className="row" style={{ gap: 6 }}><Badge tone={KIND_TONE[e.kind]}>{e.kind === "recommendation" ? "adviser" : e.kind}</Badge><b className="ellipsis">{e.title}</b></span>
                  {e.detail && <span className="faint tl-detail">{e.detail}</span>}
                </span>
              </button>
            ))}
            {rows.length > shown && <button className="btn ghost sm" style={{ margin: 10 }} onClick={() => setShown(shown + 60)}>Show more ({rows.length - shown})</button>}
          </div>}
    </Card>
  );
}

// ---------------------------------------------------------------- positions

export function PositionCards({ positions, ccy, go }: { positions: Position[]; ccy: string; go: (r: string) => void }) {
  const { symbols, setSymbol, setPanel, setAlertDraft, askAI, setPageCtx, refresh } = useStore();
  const { run } = useFeedback();
  const sparks = useSparks(positions.map((p) => cleanSymbol(p.symbol)), "FX");
  if (!positions.length) return <Empty title="Flat" icon="briefcase">No open positions.</Empty>;
  const digitsOf = (s: string) => symbols.find((x) => x.symbol === cleanSymbol(s))?.digits;

  const close = (p: Position) => run(() => api.post("/api/action/close_position", { ticket: p.ticket }), {
    success: `Closed ${cleanSymbol(p.symbol)} #${p.ticket}`,
    confirm: { title: `Close ${cleanSymbol(p.symbol)}?`, danger: true, confirmLabel: "Close position",
      body: <>Close {p.type} {p.volume} {cleanSymbol(p.symbol)} (ticket {p.ticket}) at market. Current P&L {signedMoney(p.profit, ccy)}.</> },
  }).then(refresh);
  const alert = (p: Position) => {
    const buy = sideOf(p) === "BUY";
    setAlertDraft(p.sl > 0 ? { type: "level_cross", symbol: cleanSymbol(p.symbol), market: "FX", level: p.sl, direction: buy ? "below" : "above" }
      : { type: "level_cross", symbol: cleanSymbol(p.symbol), market: "FX", level: p.current_price });
    setPanel("alerts-new");
  };
  const ask = (p: Position) => {
    const s = cleanSymbol(p.symbol), d = digitsOf(p.symbol);
    setPageCtx({ symbol: s, market: "FX" });
    askAI(`Review my open ${sideOf(p)} ${p.volume} ${s} position (ticket ${p.ticket}): entry ${price(p.open_price, d)}, stop ${p.sl ? price(p.sl, d) : "none"}, `
      + `target ${p.tp ? price(p.tp, d) : "none"}, now ${price(p.current_price, d)}, P&L ${signedMoney(pnlOfPos(p), ccy)}. `
      + `Use the chart levels, patterns and engine signal tools for ${s} (market FX) and tell me what they say. Do not place or close anything.`);
  };

  return (
    <div className="pos-grid">
      {positions.map((p) => {
        const s = cleanSymbol(p.symbol), d = digitsOf(p.symbol), sr = sparks.data?.series?.[s], pnl = pnlOfPos(p);
        return (
          <div key={p.ticket} className="pos-card">
            <button className="pos-main" onClick={() => { setSymbol(s); go("trade"); }} title={`Open ${s} on the Trade screen`}>
              <span className="row between" style={{ gap: 6 }}>
                <span className="row" style={{ gap: 6 }}><b>{s}</b><Badge tone={sideTone(p.type)}>{sideOf(p).toLowerCase()} {num(p.volume, 2)}</Badge></span>
                <span className={`mono ${tone(pnl)}`}>{signedMoney(pnl, ccy)}</span>
              </span>
              {sparks.loading && !sparks.data ? <div className="skeleton" style={{ height: 28 }} /> : <Sparkline values={sr?.closes} label={`${s} M15 closes, last 24 hours`} />}
              <span className="row between faint" style={{ fontSize: 11.5 }}>
                <span>{price(p.open_price, d)} → {price(p.current_price, d)}</span><span className="mono">{rMult(rOf(p))}</span>
              </span>
            </button>
            <div className="row between pos-actions">
              <ProvBadge prov={sr?.prov} loading={sparks.loading && !sparks.data} />
              <span className="row" style={{ gap: 4 }}>
                <button className="btn ghost sm icon-btn" onClick={() => alert(p)} aria-label={`Add alert for ${s}`} title="Add alert (stop level prefilled)"><Icon name="bell" size={14} /></button>
                <button className="btn ghost sm icon-btn" onClick={() => ask(p)} aria-label={`Ask AI about ${s}`} title="Ask AI about this position"><Icon name="chat" size={14} /></button>
                <button className="btn sm danger" onClick={() => close(p)} aria-label={`Close ${s} position ${p.ticket}`}>Close</button>
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function PositionsWidget({ go }: { go: (r: string) => void }) {
  const { telemetry } = useStore();
  const ccy = telemetry?.account?.currency || "USD";
  return (
    <Card title="Positions" sub="Live P&L, R and 24 h M15 sparkline · click a card to open it on Trade"
      actions={<button className="btn sm" onClick={() => go("portfolio/open")}>Manage</button>}>
      {!telemetry ? <Loading /> : <PositionCards positions={telemetry.positions || []} ccy={ccy} go={go} />}
    </Card>
  );
}

// ---------------------------------------------------------------- watchlist + market pulse

const readList = (k: string): string[] => { try { const v = JSON.parse(localStorage.getItem(k) || "[]"); return Array.isArray(v) ? v : []; } catch { return []; } };

function SparkRow({ sym, s, loading, onClick }: { sym: string; s?: Series; loading: boolean; onClick: () => void }) {
  return (
    <button className="list-item clickable spark-row" onClick={onClick} title={`Open ${sym}`}>
      <b className="ellipsis" style={{ width: 84 }}>{sym}</b>
      <span className="grow" style={{ minWidth: 40 }}>{loading && !s ? <div className="skeleton" style={{ height: 22 }} /> : <Sparkline values={s?.closes} height={22} />}</span>
      <span style={{ textAlign: "right", minWidth: 78 }}>
        <span className="mono" style={{ display: "block" }}>{isNum(s?.last) ? price(s!.last) : "—"}</span>
        <span className={`mono ${tone(s?.change_pct)}`} style={{ fontSize: 11.5 }}>{isNum(s?.change_pct) ? `${s!.change_pct > 0 ? "+" : ""}${pct(s!.change_pct, 2)}` : ""}</span>
      </span>
      <ProvBadge prov={s?.prov} loading={loading && !s} />
    </button>
  );
}

export function WatchlistWidget({ go }: { go: (r: string) => void }) {
  const { symbols, setSymbol } = useStore();
  const fx = symbols.filter((s) => s.is_enabled).map((s) => s.symbol);
  const lists: Record<"IN" | "US", string[]> = { IN: readList("hm.mk.watch.IN"), US: readList("hm.mk.watch.US") };
  const fxS = useSparks(fx, "FX"), inS = useSparks(lists.IN, "IN"), usS = useSparks(lists.US, "US");
  const groups: [string, Market, string[], ReturnType<typeof useSparks>][] = [
    ["Engine symbols · MT5 M15", "FX", fx, fxS], ["India watchlist · Yahoo 5m", "IN", lists.IN, inS], ["US watchlist · Yahoo 5m", "US", lists.US, usS]];
  return (
    <Card title="Watchlist" sub="Engine symbols plus your Markets watchlists" flush>
      {!fx.length && !lists.IN.length && !lists.US.length ? <Empty title="No symbols">Enable symbols in System or star stocks in Markets.</Empty> : (
        <div className="list" style={{ maxHeight: 520, overflowY: "auto" }}>
          {groups.filter(([, , l]) => l.length).map(([title, m, l, r]) => (
            <div key={m}>
              <div className="faint tl-group">{title}</div>
              {r.error && !r.data && <ErrorNote error={r.error} onRetry={r.reload} />}
              {l.map((sym) => <SparkRow key={sym} sym={sym} s={r.data?.series?.[sym]} loading={r.loading}
                onClick={() => (m === "FX" ? (setSymbol(sym), go("trade")) : go(m === "IN" ? "markets/india" : "markets/us"))} />)}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

const PULSE: [string, Market, string][] = [["NIFTY", "IN", "NIFTY 50"], ["BANKNIFTY", "IN", "Bank Nifty"], ["INDIAVIX", "IN", "India VIX"],
  ["^GSPC", "US", "S&P 500"], ["DX-Y.NYB", "US", "Dollar index"], ["^TNX", "US", "US 10Y yield"]];

export function MarketPulse({ go }: { go: (r: string) => void }) {
  const inS = useSparks(PULSE.filter((p) => p[1] === "IN").map((p) => p[0]), "IN");
  const usS = useSparks(PULSE.filter((p) => p[1] === "US").map((p) => p[0]), "US");
  return (
    <Card title="Market pulse" sub="Today, 5-minute closes (Yahoo spark)" flush
      actions={<button className="btn sm" onClick={() => go("markets/fno")}>Markets</button>}>
      <div className="pulse-grid">
        {PULSE.map(([sym, m, label]) => {
          const r = m === "IN" ? inS : usS, s = r.data?.series?.[sym];
          return (
            <div key={sym} className="pulse-tile">
              <div className="row between" style={{ gap: 6 }}><span className="faint" style={{ fontSize: 12 }}>{label}</span><ProvBadge prov={s?.prov} loading={r.loading && !r.data} /></div>
              <div className="row between" style={{ gap: 6 }}>
                <b className="mono">{isNum(s?.last) ? num(s!.last, 2) : r.error ? "unavailable" : "—"}</b>
                <span className={`mono ${tone(s?.change_pct)}`} style={{ fontSize: 12 }}>{isNum(s?.change_pct) ? `${s!.change_pct > 0 ? "+" : ""}${pct(s!.change_pct, 2)}` : ""}</span>
              </div>
              {r.loading && !r.data ? <div className="skeleton" style={{ height: 24 }} /> : <Sparkline values={s?.closes} height={24} label={`${label} today`} />}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- KPI drill-downs

export function EquityDrill({ ccy, onClose, go }: { ccy: string; onClose: () => void; go: (r: string) => void }) {
  const hist = usePoll<ClosedTrade[]>("/api/history?days=90&limit=2000", 0);
  const c = useMemo(() => equityCurve(hist.data), [hist.data]);
  return (
    <Modal wide title="Equity curve · realised P&L, last 90 days" onClose={onClose}
      footer={<button className="btn sm" onClick={() => { onClose(); go("analytics/performance"); }}>Open Analytics</button>}>
      {hist.error && !hist.data ? <ErrorNote error={hist.error} onRetry={hist.reload} /> : hist.loading && !hist.data ? <Loading rows={6} />
        : !c.n ? <Empty title="No closed trades with recorded P&L in 90 days" /> : (
          <div className="stack">
            <div className="faint" style={{ fontSize: 12.5 }}>{c.n} closed trades from the trade journal · net {signedMoney(c.net, ccy)} · max drawdown {money(Math.abs(c.maxDd), ccy)}</div>
            <LineChart data={c.eq} baseline />
            <LineChart data={c.dd} tone="down" height={120} />
          </div>
        )}
    </Modal>
  );
}

export function TodayTradesDrill({ trades, ccy, onClose, go }: { trades: ClosedTrade[]; ccy: string; onClose: () => void; go: (r: string) => void }) {
  return (
    <Modal wide title="Today's trades · trade journal, last 24 h" onClose={onClose}
      footer={<button className="btn sm" onClick={() => { onClose(); go("portfolio/history"); }}>Open journal</button>}>
      {!trades.length ? <Empty title="No trades in the last 24 hours" /> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Symbol</th><th>Side</th><th className="r">Lots</th><th className="r">Entry</th><th className="r">Exit</th><th className="r">P&L</th><th>Reason</th><th>Closed</th></tr></thead>
            <tbody>
              {trades.map((t, i) => {
                const pnl = isNum(t.realized_pnl) ? t.realized_pnl : isNum(t.profit) ? t.profit : undefined;
                return (
                  <tr key={`${t.ticket}-${i}`}>
                    <td><b>{cleanSymbol(t.symbol)}</b></td>
                    <td><Badge tone={sideTone(t.action || t.type)}>{String(t.action || t.type || "—").toLowerCase()}</Badge></td>
                    <td className="num">{num(t.volume, 2)}</td><td className="num">{price(t.entry_price)}</td><td className="num">{price(t.exit_price)}</td>
                    <td className={`num ${tone(pnl)}`}>{pnl === undefined ? (t.closed_at || t.exit_price ? "not recorded" : "open") : signedMoney(pnl, ccy)}</td>
                    <td className="muted">{t.exit_reason || "—"}</td>
                    <td className="muted">{t.closed_at ? ago(t.closed_at) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}

export function PositionsDrill({ onClose, go }: { onClose: () => void; go: (r: string) => void }) {
  const { telemetry } = useStore();
  return (
    <Modal wide title="Open positions" onClose={onClose}
      footer={<button className="btn sm" onClick={() => { onClose(); go("portfolio/open"); }}>Open Portfolio</button>}>
      <PositionCards positions={telemetry?.positions || []} ccy={telemetry?.account?.currency || "USD"} go={(r) => { onClose(); go(r); }} />
    </Modal>
  );
}
