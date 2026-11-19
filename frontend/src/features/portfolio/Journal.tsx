import { useMemo, useState } from "react";
import { usePoll } from "../../lib/hooks";
import { useStore } from "../../state/store";
import { cleanSymbol, dateTime, isNum, pct, price, signedMoney, tone } from "../../lib/format";
import type { ClosedTrade } from "../../lib/types";
import { Badge, Card, Empty, ErrorNote, KV, Loading, Modal, sideTone } from "../../components/ui";
import { isClosed, isMeasured, MiniStat, pnlOf } from "../overview/Overview";
import { toCsv } from "./csv";

const WINDOWS = [{ v: 7, l: "7 days" }, { v: 30, l: "30 days" }, { v: 90, l: "90 days" }, { v: 365, l: "1 year" }];
const PAGE = 25;
const sideOf = (t: ClosedTrade) => String(t.action || t.type || "").toUpperCase();
const closedAt = (t: ClosedTrade) => t.closed_at || t.exit_time || t.timestamp;

/** The single closed-trade history: filters, totals, paging, CSV export and a detail view. */
export function Journal() {
  const { telemetry } = useStore();
  const ccy = telemetry?.account?.currency || "USD";
  const [days, setDays] = useState(30);
  const res = usePoll<ClosedTrade[]>(`/api/history?days=${days}&limit=2000`, 60000);
  const [sym, setSym] = useState("ALL");
  const [side, setSide] = useState("ALL");
  const [outcome, setOutcome] = useState("ALL");
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<ClosedTrade | null>(null);

  const all = useMemo(() => (Array.isArray(res.data) ? res.data : []).filter(isClosed), [res.data]);
  const symbolsInData = useMemo(() => [...new Set(all.map((t) => cleanSymbol(t.symbol)))].sort(), [all]);
  const rows = useMemo(() => all.filter((t) =>
    (sym === "ALL" || cleanSymbol(t.symbol) === sym) &&
    (side === "ALL" || sideOf(t).includes(side)) &&
    (outcome === "ALL" || (isMeasured(t) && (outcome === "WIN" ? pnlOf(t) > 0 : pnlOf(t) <= 0))),
  ), [all, sym, side, outcome]);

  const stats = useMemo(() => {
    const p = rows.filter(isMeasured).map(pnlOf);
    const wins = p.filter((x) => x > 0), losses = p.filter((x) => x <= 0);
    const gw = wins.reduce((a, b) => a + b, 0), gl = -losses.reduce((a, b) => a + b, 0);
    return { n: p.length, unmeasured: rows.length - p.length, net: gw - gl, wr: p.length ? (wins.length / p.length) * 100 : undefined, pf: gl > 0 ? gw / gl : undefined,
      avgWin: wins.length ? gw / wins.length : undefined, avgLoss: losses.length ? -gl / losses.length : undefined };
  }, [rows]);

  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const view = rows.slice(page * PAGE, page * PAGE + PAGE);

  const exportCsv = () => {
    const blob = new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `trade-journal-${days}d-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const filterSel = (label: string, value: string, set: (v: string) => void, opts: [string, string][]) => (
    <select className="select" style={{ height: 30, width: "auto" }} aria-label={label} value={value} onChange={(e) => { set(e.target.value); setPage(0); }}>
      {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );

  return (
    <>
      <div className="grid cols-4">
        <MiniStat label={stats.unmeasured ? `Trades (+${stats.unmeasured} without P&L)` : "Trades"} value={String(stats.n)} />
        <MiniStat label="Net P&L" value={signedMoney(stats.net, ccy)} valueClass={tone(stats.net)} />
        <MiniStat label="Win rate · profit factor" value={`${pct(stats.wr, 1)} · ${isNum(stats.pf) ? stats.pf.toFixed(2) : "—"}`} />
        <MiniStat label="Avg win / avg loss" value={`${signedMoney(stats.avgWin, ccy)} / ${signedMoney(stats.avgLoss, ccy)}`} />
      </div>
      <Card title="Trade journal" sub={`${rows.length} of ${all.length} closed trades`} flush
        actions={
          <div className="row wrap" style={{ gap: 6 }}>
            {filterSel("Window", String(days), (v) => setDays(Number(v)), WINDOWS.map((w) => [String(w.v), w.l]))}
            {filterSel("Symbol", sym, setSym, [["ALL", "All symbols"], ...symbolsInData.map((s) => [s, s] as [string, string])])}
            {filterSel("Side", side, setSide, [["ALL", "Buy & sell"], ["BUY", "Buys"], ["SELL", "Sells"]])}
            {filterSel("Outcome", outcome, setOutcome, [["ALL", "Wins & losses"], ["WIN", "Wins"], ["LOSS", "Losses"]])}
            <button className="btn sm" onClick={exportCsv} disabled={!rows.length}>Export CSV</button>
          </div>
        }>
        <ErrorNote error={res.error} onRetry={res.reload} />
        {res.loading && !res.data ? <Loading rows={6} /> : !rows.length ? <Empty title="No closed trades in this view" icon="briefcase" /> : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Closed</th><th>Symbol</th><th>Side</th><th className="r">Lots</th><th className="r">Entry</th><th className="r">Exit</th><th>Strategy</th><th>Exit reason</th><th className="r">P&L</th></tr></thead>
                <tbody>
                  {view.map((t, i) => (
                    <tr key={`${t.ticket}-${i}`} className="clickable" onClick={() => setOpen(t)}>
                      <td className="muted">{dateTime(closedAt(t))}</td>
                      <td><b>{cleanSymbol(t.symbol)}</b></td>
                      <td><Badge tone={sideTone(sideOf(t))}>{sideOf(t) || "—"}</Badge></td>
                      <td className="num">{t.volume}</td>
                      <td className="num">{price(t.entry_price)}</td>
                      <td className="num">{price(t.exit_price)}</td>
                      <td className="muted">{String(t.strategy || "—").replace(/_/g, " ").toLowerCase()}</td>
                      <td className="muted">{String(t.exit_reason || "—").replace(/_/g, " ").toLowerCase()}</td>
                      <td className={`num ${tone(pnlOf(t))}`} title={isMeasured(t) ? undefined : "P&L was not recorded for this close"}>
                        <b>{isMeasured(t) ? signedMoney(pnlOf(t), ccy) : "—"}</b></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="row between" style={{ padding: "10px 14px", borderTop: "1px solid var(--line)" }}>
              <span className="faint">Page {page + 1} of {pages}</span>
              <div className="row" style={{ gap: 6 }}>
                <button className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
                <button className="btn sm" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Next</button>
              </div>
            </div>
          </>
        )}
      </Card>
      {open && (
        <Modal drawer title={`${cleanSymbol(open.symbol)} · #${open.ticket}`} onClose={() => setOpen(null)}>
          <KV items={Object.entries(open)
            .filter(([, v]) => v !== null && v !== undefined && v !== "" && typeof v !== "object")
            .map(([k, v]) => [k.replace(/_/g, " "), String(v)])} />
        </Modal>
      )}
    </>
  );
}
