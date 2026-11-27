import { useMemo, useState } from "react";
import { usePoll } from "../../lib/hooks";
import { useStore } from "../../state/store";
import { fixed, isNum, money, parseTime, pct, signedMoney, tone } from "../../lib/format";
import type { ClosedTrade } from "../../lib/types";
import { LineChart } from "../../components/Chart";
import { Card, Empty, ErrorNote, Loading, Stat } from "../../components/ui";
import { isMeasured, pnlOf } from "../overview/Overview";

interface Group {
  total_trades: number; wins: number; net_profit: number; win_rate_pct: number; profit_factor: number;
  expectancy_dollars: number; avg_r: number; max_drawdown_dollars: number; max_consecutive_losses: number;
  /** Measured at fill since 2026-11-27 (older trades have none). Slippage is adverse, in R. */
  execution?: { avg_slippage_r?: number; avg_fill_latency_ms?: number; avg_spread_at_fill?: number; measured_fills?: number };
}
const BY = [["symbol", "Symbol"], ["symbol_style", "Symbol × style"], ["strategy", "Strategy"], ["trade_style", "Style"], ["exit_reason", "Exit reason"], ["account_login", "Account"]];
type SortKey = keyof Group | "key";

/** Cumulative realised P&L and drawdown from closed journal trades (also the Overview equity drill-down). */
export function equityCurve(data: ClosedTrade[] | undefined) {
  const trades = (Array.isArray(data) ? data : [])
    .filter(isMeasured)
    .map((t) => ({ t: parseTime(t.closed_at || t.exit_time || t.timestamp), p: pnlOf(t) }))
    .filter((x): x is { t: Date; p: number } => !!x.t)
    .sort((a, b) => a.t.getTime() - b.t.getTime());
  let cum = 0, peak = 0, maxDd = 0;
  const eq: { time: number; value: number }[] = [], dd: { time: number; value: number }[] = [];
  for (const x of trades) {
    cum += x.p;
    peak = Math.max(peak, cum);
    maxDd = Math.min(maxDd, cum - peak);
    const time = Math.floor(x.t.getTime() / 1000);
    eq.push({ time, value: Number(cum.toFixed(2)) });
    dd.push({ time, value: Number((cum - peak).toFixed(2)) });
  }
  return { eq, dd, net: cum, maxDd, n: trades.length };
}

/** Equity curve (realised P&L) + drawdown, then the breakdown by symbol / strategy / style. */
export function Performance() {
  const { telemetry } = useStore();
  const ccy = telemetry?.account?.currency || "USD";
  const [by, setBy] = useState("symbol");
  const [mode, setMode] = useState("");
  const [days, setDays] = useState(90);
  const [sort, setSort] = useState<{ k: SortKey; desc: boolean }>({ k: "net_profit", desc: false });
  const perf = usePoll<{ closed_trades: number; groups: Record<string, Group> }>(`/api/analytics/performance?by=${by}${mode ? `&mode=${mode}` : ""}`, 120000);
  const hist = usePoll<ClosedTrade[]>(`/api/history?days=${days}&limit=2000`, 120000);

  const curve = useMemo(() => equityCurve(hist.data), [hist.data]);

  const groups = useMemo(() => {
    const rows = Object.entries(perf.data?.groups || {}).map(([key, g]) => ({ key, ...g }));
    const k = sort.k;
    return rows.sort((a: any, b: any) => (a[k] < b[k] ? -1 : a[k] > b[k] ? 1 : 0) * (sort.desc ? -1 : 1));
  }, [perf.data, sort]);

  const totals = useMemo(() => {
    const g = Object.values(perf.data?.groups || {});
    const n = g.reduce((a, x) => a + (x.total_trades || 0), 0);
    const w = g.reduce((a, x) => a + (x.wins || 0), 0);
    return { n, net: g.reduce((a, x) => a + (x.net_profit || 0), 0), wr: n ? (w / n) * 100 : undefined };
  }, [perf.data]);

  const th = (k: SortKey, label: string, right = true) => (
    <th className={`sortable ${right ? "r" : ""}`} onClick={() => setSort({ k, desc: sort.k === k ? !sort.desc : true })}
      aria-sort={sort.k === k ? (sort.desc ? "descending" : "ascending") : undefined}>
      {label}{sort.k === k ? (sort.desc ? " ↓" : " ↑") : ""}
    </th>
  );

  return (
    <>
      <div className="grid cols-4">
        <Stat label="Closed trades" value={String(totals.n)} hint={mode ? `${mode.toLowerCase()} account only` : "all accounts"} />
        <Stat label="Net profit" value={signedMoney(totals.net, ccy)} tone={tone(totals.net)} />
        <Stat label="Win rate" value={pct(totals.wr, 1)} />
        <Stat label={`Max drawdown (${days}d)`} value={money(Math.abs(curve.maxDd), ccy)} tone={curve.maxDd < 0 ? "down" : ""} hint="realised, peak to trough" />
      </div>

      <Card title="Equity curve" sub={`Cumulative realised P&L over ${curve.n} trades · drawdown below`}
        actions={
          <select className="select" style={{ height: 30, width: 120 }} value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Window">
            {[30, 90, 180, 365].map((d) => <option key={d} value={d}>{d} days</option>)}
          </select>
        }>
        <ErrorNote error={hist.error} onRetry={hist.reload} />
        {hist.loading && !hist.data ? <Loading /> : !curve.n ? <Empty title="No closed trades in this window" /> : (
          <div className="stack">
            <LineChart data={curve.eq} baseline />
            <LineChart data={curve.dd} tone="down" height={130} />
          </div>
        )}
      </Card>

      <Card title="Breakdown" sub="Closed trades grouped; click a column to sort" flush
        actions={
          <div className="row wrap" style={{ gap: 6 }}>
            <select className="select" style={{ height: 30, width: "auto" }} value={by} onChange={(e) => setBy(e.target.value)} aria-label="Group by">
              {BY.map(([v, l]) => <option key={v} value={v}>By {l.toLowerCase()}</option>)}
            </select>
            <select className="select" style={{ height: 30, width: "auto" }} value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Account mode">
              <option value="">All modes</option><option value="LIVE">Live</option><option value="DEMO">Demo</option><option value="PAPER">Paper</option>
            </select>
          </div>
        }>
        <ErrorNote error={perf.error} onRetry={perf.reload} />
        {perf.loading && !perf.data ? <Loading /> : !groups.length ? <Empty title="No closed trades" /> : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>{th("key", BY.find((b) => b[0] === by)?.[1] || "Group", false)}{th("total_trades", "Trades")}{th("win_rate_pct", "Win rate")}
                  {th("profit_factor", "PF")}{th("expectancy_dollars", "Expectancy")}{th("avg_r", "Avg R")}{th("net_profit", "Net")}
                  {th("max_drawdown_dollars", "Max DD")}{th("max_consecutive_losses", "Loss streak")}
                  <th className="num" title="Average adverse slippage vs the requested price, in R (fills measured since 2026-11-27)">Slippage R</th>
                  <th className="num" title="Average order round trip">Latency</th></tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <tr key={g.key}>
                    <td><b>{g.key || "unknown"}</b></td>
                    <td className="num">{g.total_trades}</td>
                    <td className="num">{pct(g.win_rate_pct, 1)}</td>
                    <td className={`num ${isNum(g.profit_factor) && g.profit_factor >= 1 ? "up" : "down"}`}>{fixed(g.profit_factor, 2)}</td>
                    <td className={`num ${tone(g.expectancy_dollars)}`}>{signedMoney(g.expectancy_dollars, ccy)}</td>
                    <td className={`num ${tone(g.avg_r)}`}>{fixed(g.avg_r, 2)}</td>
                    <td className={`num ${tone(g.net_profit)}`}><b>{signedMoney(g.net_profit, ccy)}</b></td>
                    <td className="num">{money(g.max_drawdown_dollars, ccy)}</td>
                    <td className="num">{g.max_consecutive_losses}</td>
                    <td className={`num ${isNum(g.execution?.avg_slippage_r) && (g.execution?.avg_slippage_r as number) > 0.05 ? "down" : ""}`}
                      title={`${g.execution?.measured_fills ?? 0} measured fill(s)`}>
                      {isNum(g.execution?.avg_slippage_r) ? fixed(g.execution?.avg_slippage_r as number, 3) : "—"}</td>
                    <td className="num">{isNum(g.execution?.avg_fill_latency_ms) ? `${fixed(g.execution?.avg_fill_latency_ms as number, 0)} ms` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
