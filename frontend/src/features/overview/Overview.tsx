import { useMemo, useState } from "react";
import { useStore } from "../../state/store";
import { usePoll } from "../../lib/hooks";
import { cleanSymbol, isNum, money, num, pct, signedMoney, tone } from "../../lib/format";
import type { ClosedTrade } from "../../lib/types";
import { Badge, Card, CardMenuCtx, Empty, ErrorNote, Loading, Meter, Stat } from "../../components/ui";
import { Icon } from "../../components/Icon";
import { Explain } from "../../components/Explain";
import { Today } from "./Today";
import { loadLayout, move, moveTo, resetLayout, saveLayout, setHidden, toggleSpan, WIDGETS, type WidgetId, type WidgetState } from "./layout";
import { EquityDrill, MarketPulse, PositionsDrill, PositionsWidget, SinceLastLooked, TimelineWidget, TodayTradesDrill, WatchlistWidget } from "./Widgets";

// The server has no definitions for the account guardrails; these are shown when it says so.
const RISK_DEFS = {
  daily_loss: "Loss since the start of the trading day as a share of day-start equity; at the limit the engine blocks new entries for the rest of the day.",
  drawdown: "Fall in equity from its highest recorded value; at the limit the engine stops opening new risk until equity recovers or limits are reset.",
  portfolio_heat: "Combined risk of open positions (size, correlation, distance to stops) on a 0-100 scale; higher heat shrinks new position sizes.",
  size_multiplier: "Factor applied to every new position size from the drawdown and heat rules; below 1 means positions are being scaled down.",
};

export const pnlOf = (t: ClosedTrade) => (isNum(t.realized_pnl) ? t.realized_pnl : isNum(t.profit) ? t.profit : 0);
/** /api/history also lists journal rows of still-open trades; only rows with an exit are closed. */
export const isClosed = (t: ClosedTrade) => !!(t.closed_at || t.exit_time || t.exit_price);
/** Closed trades whose P&L was recorded (older closes lost to deal-history lag have none). */
export const isMeasured = (t: ClosedTrade) => isClosed(t) && (isNum(t.realized_pnl) || isNum(t.profit));

/** Home: customisable widgets (order, visibility, width saved per browser) over the account, risk, activity and markets. */
export default function Overview({ go }: { sub: string; go: (r: string) => void }) {
  const { telemetry, risk, setSymbol } = useStore();
  const acc = telemetry?.account;
  const ccy = acc?.currency || "USD";
  const today = usePoll<ClosedTrade[]>("/api/history?days=1&limit=500", 60000);
  const [layout, setLayoutState] = useState<WidgetState[]>(() => loadLayout());
  const setLayout = (l: WidgetState[]) => { setLayoutState(l); saveLayout(l); };
  const [drill, setDrill] = useState<"equity" | "pnl" | "today" | null>(null);
  const [dragging, setDragging] = useState<WidgetId | null>(null);

  const dayPnl = acc && risk?.daily_start_equity ? acc.equity - risk.daily_start_equity : undefined;
  const marginUsedPct = acc && acc.equity > 0 ? (acc.margin / acc.equity) * 100 : undefined;
  const nPos = telemetry?.positions.length || 0;

  const body = (id: WidgetId) => {
    if (id === "today") return <Today go={go} />;
    if (!telemetry && id !== "since" && id !== "timeline" && id !== "pulse" && id !== "kpis") return <Card title={WIDGETS[id]}><Loading rows={4} /></Card>;
    switch (id) {
      case "kpis": return !telemetry ? <Loading rows={2} /> : (
        <div className="stack" style={{ gap: 10 }}>
          {!acc && <div className="alert warn">No broker account is synced yet. Check the MT5 connection in System.</div>}
          <div className="grid cols-4">
            <Stat label="Equity" icon="activity" value={money(acc?.equity, ccy)} hint={`Balance ${money(acc?.balance, ccy)} · curve ›`}
              onClick={() => setDrill("equity")} title="Show the equity curve" />
            <Stat label="Open P&L" value={signedMoney(acc?.profit, ccy)} tone={tone(acc?.profit)} onClick={() => setDrill("pnl")} title="Show open positions"
              hint={`${nPos} open position${nPos === 1 ? "" : "s"} ›`} />
            <Stat label="Today" value={signedMoney(dayPnl, ccy)} tone={tone(dayPnl)} onClick={() => setDrill("today")} title="Show today's trades"
              hint={risk ? `From ${money(risk.daily_start_equity, ccy)} at day start ›` : "—"} />
            <Stat label="Free margin" value={money(acc?.free_margin, ccy)} onClick={() => go("portfolio/open")} title="Open Portfolio"
              hint={isNum(marginUsedPct) ? `${pct(marginUsedPct, 2)} of equity used as margin · 1:${acc?.leverage || "—"}` : "—"} />
          </div>
        </div>);
      case "since": return <SinceLastLooked />;
      case "positions": return <PositionsWidget go={go} />;
      case "timeline": return <TimelineWidget go={go} />;
      case "guardrails": return <Guardrails ccy={ccy} />;
      case "exposure": return <Exposure ccy={ccy} go={go} onSymbol={(s) => { setSymbol(s); go("trade"); }} />;
      case "trades": return <TodayActivity trades={today.data} loading={today.loading} error={today.error} ccy={ccy} go={go} />;
      case "pulse": return <MarketPulse go={go} />;
      case "watchlist": return <WatchlistWidget go={go} />;
      case "hours": return <MarketHours />;
    }
  };

  const visible = layout.filter((w) => !w.hidden);
  const hidden = layout.filter((w) => w.hidden);
  return (
    <>
      <div className="row wrap between ov-toolbar">
        <span className="faint" style={{ fontSize: 12.5 }}>Drag a widget by its handle, or use its ⋯ menu to move, resize or hide it. Saved in this browser.</span>
        <span className="row" style={{ gap: 6 }}>
          <details className="menu" onKeyDown={closeOnEsc}>
            <summary className="btn sm" aria-haspopup="menu"><Icon name="plus" size={14} />Add widget{hidden.length ? ` (${hidden.length})` : ""}</summary>
            <div className="menu-pop right" role="menu">
              {!hidden.length ? <span className="faint" style={{ padding: "6px 10px", fontSize: 12.5 }}>All widgets are shown.</span>
                : hidden.map((w) => <button key={w.id} role="menuitem" onClick={(e) => { closeMenu(e); setLayout(setHidden(layout, w.id, false)); }}>{WIDGETS[w.id]}</button>)}
            </div>
          </details>
          <button className="btn sm" onClick={() => setLayoutState(resetLayout())}>Reset layout</button>
        </span>
      </div>
      <div className="widget-grid">
        {visible.map((w, i) => {
          const menu = <WidgetMenu w={w} first={i === 0} last={i === visible.length - 1} layout={layout} setLayout={setLayout} onDrag={setDragging} />;
          return (
            <div key={w.id} className={`widget span-${w.span} ${dragging === w.id ? "dragging" : ""}`} data-widget={w.id}
              onDragOver={(e) => { if (dragging && dragging !== w.id) e.preventDefault(); }}
              onDrop={(e) => { e.preventDefault(); if (dragging) setLayout(moveTo(layout, dragging, w.id)); setDragging(null); }}>
              {w.id === "kpis" ? <><div className="widget-head"><b>{WIDGETS[w.id]}</b>{menu}</div>{body(w.id)}</>
                : <CardMenuCtx.Provider value={menu}>{body(w.id)}</CardMenuCtx.Provider>}
            </div>
          );
        })}
      </div>
      {drill === "equity" && <EquityDrill ccy={ccy} onClose={() => setDrill(null)} go={go} />}
      {drill === "pnl" && <PositionsDrill onClose={() => setDrill(null)} go={go} />}
      {drill === "today" && <TodayTradesDrill trades={Array.isArray(today.data) ? today.data : []} ccy={ccy} onClose={() => setDrill(null)} go={go} />}
    </>
  );
}

const closeMenu = (e: { currentTarget: Element }) => { const d = e.currentTarget.closest("details"); if (d) d.open = false; };
const closeOnEsc = (e: React.KeyboardEvent<HTMLDetailsElement>) => {
  if (e.key === "Escape" && e.currentTarget.open) { e.currentTarget.open = false; e.currentTarget.querySelector("summary")?.focus(); }
};

/** Per-widget controls: drag handle plus a keyboard-reachable menu (move, width, hide). */
function WidgetMenu({ w, first, last, layout, setLayout, onDrag }: {
  w: WidgetState; first: boolean; last: boolean; layout: WidgetState[]; setLayout: (l: WidgetState[]) => void; onDrag: (id: WidgetId | null) => void;
}) {
  const act = (fn: () => WidgetState[]) => (e: React.MouseEvent<HTMLButtonElement>) => { closeMenu(e); setLayout(fn()); };
  return (
    <span className="row widget-ctl" style={{ gap: 2 }}>
      <span className="drag-handle" draggable aria-hidden="true" title="Drag to move"
        onDragStart={(e) => {
          e.dataTransfer.effectAllowed = "move";
          e.dataTransfer.setData("text/plain", w.id);
          const box = (e.currentTarget as HTMLElement).closest(".widget");
          if (box) e.dataTransfer.setDragImage(box, 24, 24);
          onDrag(w.id);
        }}
        onDragEnd={() => onDrag(null)}>⋮⋮</span>
      <details className="menu" onKeyDown={closeOnEsc}>
        <summary className="btn ghost sm icon-btn" aria-label={`${WIDGETS[w.id]} widget options`} aria-haspopup="menu">⋯</summary>
        <div className="menu-pop right" role="menu">
          <button role="menuitem" disabled={first} onClick={act(() => move(layout, w.id, -1))}>Move up</button>
          <button role="menuitem" disabled={last} onClick={act(() => move(layout, w.id, 1))}>Move down</button>
          <button role="menuitem" onClick={act(() => toggleSpan(layout, w.id))}>{w.span === 2 ? "Half width" : "Full width"}</button>
          <button role="menuitem" onClick={act(() => setHidden(layout, w.id, true))}>Hide</button>
        </div>
      </details>
    </span>
  );
}

function Guardrails({ ccy }: { ccy: string }) {
  const { risk, riskError, reloadRisk } = useStore();
  if (!risk) return <Card title="Risk guardrails">{riskError ? <ErrorNote error={`Risk status unavailable: ${riskError}`} onRetry={reloadRisk} /> : <Loading />}</Card>;
  const dl = Math.max(0, risk.daily_loss_pct), dd = Math.max(0, risk.total_dd_pct);
  const level = (v: number, max: number) => (v >= max * 0.8 ? "danger" : v >= max * 0.5 ? "warn" : "good");
  return (
    <Card title="Risk guardrails" sub="Limits the engine enforces before any new entry"
      actions={risk.allow_new_risk ? <Badge tone="up" dot>Accepting new risk</Badge> : <Badge tone="down" dot>New risk blocked</Badge>}>
      <div className="stack" style={{ gap: 16 }}>
        {risk.circuit_breaker_active && (
          <div className="alert down"><b>Circuit breaker active.</b> {risk.circuit_breaker_reason}
            {risk.circuit_breaker_cooldown_sec > 0 && ` · resumes in ${Math.ceil(risk.circuit_breaker_cooldown_sec / 60)} min`}</div>
        )}
        <div className="stack" style={{ gap: 6 }}>
          <div className="row between"><span>Daily loss<Explain metric="daily_loss" value={dl} fallback={RISK_DEFS.daily_loss} /></span><span className="mono">{pct(dl, 2)} / {pct(risk.max_daily_loss_pct, 0)}</span></div>
          <Meter value={dl} max={risk.max_daily_loss_pct} tone={level(dl, risk.max_daily_loss_pct)} />
        </div>
        <div className="stack" style={{ gap: 6 }}>
          <div className="row between"><span>Drawdown from peak {money(risk.peak_equity, ccy)}<Explain metric="drawdown" value={dd} fallback={RISK_DEFS.drawdown} /></span><span className="mono">{pct(dd, 2)} / {pct(risk.max_drawdown_pct, 0)}</span></div>
          <Meter value={dd} max={risk.max_drawdown_pct} tone={level(dd, risk.max_drawdown_pct)} />
        </div>
        <div className="stack" style={{ gap: 6 }}>
          <div className="row between"><span>Portfolio heat · {risk.portfolio_heat_zone}<Explain metric="portfolio_heat" value={risk.portfolio_heat_score} fallback={RISK_DEFS.portfolio_heat} /></span><span className="mono">{num(risk.portfolio_heat_score, 1)} / 100</span></div>
          <Meter value={risk.portfolio_heat_score} tone={level(risk.portfolio_heat_score, 100)} />
        </div>
        <div className="grid cols-3" style={{ gap: 10 }}>
          <MiniStat label={<>Size multiplier<Explain metric="size_multiplier" value={risk.drawdown_multiplier * risk.heat_risk_multiplier} fallback={RISK_DEFS.size_multiplier} /></>} value={`${num(risk.drawdown_multiplier * risk.heat_risk_multiplier, 2)}×`} />
          <MiniStat label="Losses in a row" value={String(risk.consecutive_losses)} />
          <MiniStat label="Paused symbols" value={risk.paused_symbols?.length ? risk.paused_symbols.join(", ") : "None"} />
        </div>
        {!!risk.heat_reasons?.length && <div className="faint" style={{ fontSize: 12.5 }}>{risk.heat_reasons.join(" · ")}</div>}
      </div>
    </Card>
  );
}

export function MiniStat({ label, value, valueClass = "" }: { label: React.ReactNode; value: string; valueClass?: string }) {
  return (
    <div style={{ background: "var(--surface-2)", borderRadius: 8, padding: "8px 10px", minWidth: 0 }}>
      <div className="faint" style={{ fontSize: 11.5 }}>{label}</div>
      <div className={`mono ${valueClass}`} style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis" }}>{value}</div>
    </div>
  );
}

/** Net exposure by symbol: direction, lots and floating P&L (a summary; the trade list lives in Portfolio). */
function Exposure({ ccy, go, onSymbol }: { ccy: string; go: (r: string) => void; onSymbol: (s: string) => void }) {
  const { telemetry } = useStore();
  const rows = useMemo(() => {
    const m = new Map<string, { symbol: string; long: number; short: number; pnl: number; n: number }>();
    for (const p of telemetry?.positions || []) {
      const s = cleanSymbol(p.symbol);
      const r = m.get(s) || { symbol: s, long: 0, short: 0, pnl: 0, n: 0 };
      if (String(p.type).toUpperCase().includes("BUY")) r.long += p.volume; else r.short += p.volume;
      r.pnl += (p.profit || 0) + (p.swap || 0) + (p.commission || 0);
      r.n += 1;
      m.set(s, r);
    }
    return [...m.values()].sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl));
  }, [telemetry?.positions]);
  const maxLots = Math.max(0.01, ...rows.map((r) => Math.abs(r.long - r.short)));

  return (
    <Card title="Exposure" sub="Net lots and floating P&L per symbol" flush
      actions={<button className="btn sm" onClick={() => go("portfolio/open")}>Manage positions</button>}>
      {!rows.length ? <Empty title="Flat" icon="briefcase">No open positions.</Empty> : (
        <div className="list">
          {rows.map((r) => {
            const net = r.long - r.short;
            return (
              <div key={r.symbol} className="list-item clickable" role="button" tabIndex={0} title={`Open ${r.symbol} on Trade`}
                onClick={() => onSymbol(r.symbol)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSymbol(r.symbol); } }}>
                <b style={{ width: 80 }}>{r.symbol}</b>
                <div className="grow stack" style={{ gap: 4 }}>
                  <div className="row wrap" style={{ gap: 6, fontSize: 12 }}>
                    <Badge tone={net > 0 ? "up" : net < 0 ? "down" : "flat"}>{net > 0 ? "Net long" : net < 0 ? "Net short" : "Hedged"}</Badge>
                    <span className="faint">{num(r.long, 2)} long · {num(r.short, 2)} short · {r.n} trade{r.n > 1 ? "s" : ""}</span>
                  </div>
                  <div className="meter"><i style={{ width: `${(Math.abs(net) / maxLots) * 100}%`, background: net >= 0 ? "var(--up)" : "var(--down)" }} /></div>
                </div>
                <span className={`mono ${tone(r.pnl)}`} style={{ width: 90, textAlign: "right" }}>{signedMoney(r.pnl, ccy)}</span>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function TodayActivity({ trades, loading, error, ccy, go }: { trades?: ClosedTrade[]; loading: boolean; error: string | null; ccy: string; go: (r: string) => void }) {
  const s = useMemo(() => {
    const list = (Array.isArray(trades) ? trades : []).filter(isMeasured);
    const pnls = list.map(pnlOf);
    const wins = pnls.filter((p) => p > 0).length;
    const net = pnls.reduce((a, b) => a + b, 0);
    return { n: list.length, wins, net, best: pnls.length ? Math.max(...pnls) : undefined, worst: pnls.length ? Math.min(...pnls) : undefined };
  }, [trades]);
  return (
    <Card title="Today's closed trades" sub="Last 24 hours, from the trade journal"
      actions={<button className="btn sm" onClick={() => go("portfolio/history")}>Open journal</button>}>
      {error && !trades ? <ErrorNote error={error} /> : loading && !trades ? <Loading /> : !s.n ? <Empty title="No trades closed today" icon="clock" /> : (
        <div className="grid cols-2" style={{ gap: 10 }}>
          <MiniStat label="Trades" value={`${s.n} (${s.wins} won)`} />
          <MiniStat label="Win rate" value={pct((s.wins / s.n) * 100, 0)} />
          <MiniStat label="Net realised" value={signedMoney(s.net, ccy)} valueClass={tone(s.net)} />
          <MiniStat label="Best / worst" value={`${signedMoney(s.best, ccy)} / ${signedMoney(s.worst, ccy)}`} />
        </div>
      )}
    </Card>
  );
}

/** Market hours board for the configured symbols (open/closed, countdown to the next session event). */
function MarketHours() {
  const { telemetry } = useStore();
  const rows = Object.entries(telemetry?.market_statuses || {});
  return (
    <Card title="Market hours" sub="Session state for the traded symbols" flush>
      {!rows.length ? <Empty title="No session data" /> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Symbol</th><th>State</th><th>Next</th><th className="r">In</th></tr></thead>
            <tbody>
              {rows.map(([sym, m]) => (
                <tr key={sym}>
                  <td><b>{sym}</b></td>
                  <td><Badge tone={m.is_open ? "up" : "flat"} dot>{m.is_open ? "Open" : "Closed"}</Badge></td>
                  <td className="muted" style={{ whiteSpace: "normal", minWidth: 160 }}>{m.next_event || m.status_text || "—"}</td>
                  <td className="num">{m.countdown_formatted || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
