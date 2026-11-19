import { useMemo, useState } from "react";
import { usePoll } from "../../lib/hooks";
import { fixed, isNum, num, pct, tone } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, Loading, Seg } from "../../components/ui";
import { ProvBadge } from "../../components/ProvBadge";
import { LineChart } from "../../components/Chart";
import { Explain } from "../../components/Explain";
import { QuickAlert } from "../alerts/Alerts";
import { Buildup, lakh } from "./FnoPanels";
import type { Prov } from "./logic";

const MIN = 60000;
const signed = (v: unknown, d = 0) => (isNum(v) ? `${v > 0 ? "+" : ""}${num(v, d)}` : "—");
const Chg = ({ v, d = 0 }: { v: unknown; d?: number }) => (isNum(v) ? <span className={`faint ${tone(v)}`} style={{ fontSize: 11.5 }}> ({signed(v, d)})</span> : null);

/** Institutional view: participant positioning, futures basis/OI, deals, events, delivery, 52-week, most active, ban list, IV term structure. */
export function Inst() {
  return (
    <div className="grid cols-2">
      <Participants />
      <Futures />
      <TermStructure />
      <BanList />
      <Events />
      <Deals />
      <Delivery />
      <FiftyTwo />
      <MostActive />
    </div>
  );
}

/* ---------------- Participant positioning ---------------- */
type PKey = "FII" | "DII" | "Pro" | "Client";
interface PRow {
  net_idx_fut?: number; fut_idx_long_pct?: number; net_stk_fut?: number; idx_call_net?: number; idx_put_net?: number;
  net_idx_fut_chg?: number; fut_idx_long_pct_chg?: number; net_stk_fut_chg?: number; idx_call_net_chg?: number; idx_put_net_chg?: number;
}
interface Participants {
  latest?: { date?: string; previous_date?: string; participants?: Partial<Record<PKey, PRow>> };
  history?: ({ date: string } & Partial<Record<"client" | "dii" | "fii" | "pro", PRow>>)[]; prov?: Prov;
}
const PARTS: PKey[] = ["FII", "DII", "Pro", "Client"];

function Participants() {
  const r = usePoll<Participants>("/api/markets/inst/participants?days=60", 30 * MIN);
  const [who, setWho] = useState<PKey>("FII");
  const [metric, setMetric] = useState<"fut_idx_long_pct" | "net_idx_fut">("fut_idx_long_pct");
  const series = useMemo(() => (r.data?.history || []).map((h) => {
    const v = h[who.toLowerCase() as "fii"]?.[metric];
    return isNum(v) ? { time: Date.parse(`${h.date}T00:00:00Z`) / 1000, value: v } : null;
  }).filter((x): x is { time: number; value: number } => !!x), [r.data, who, metric]);
  const p = r.data?.latest?.participants;
  return (
    <Card title="Participant positioning · F&O open interest" className="span-2"
      sub={r.data?.latest?.date ? `NSCCL participant-wise OI for ${r.data.latest.date} vs ${r.data.latest.previous_date || "previous"} · contracts` : "NSCCL participant-wise OI"}
      actions={<ProvBadge prov={r.data?.prov} loading={r.loading && !r.data} />}>
      <ErrorNote error={r.error} onRetry={r.reload} />
      {r.loading && !r.data ? <Loading rows={5} /> : !p ? <Empty title="Participant data unavailable">{r.data?.prov?.note}</Empty> : (
        <div className="stack" style={{ gap: 14 }}>
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Participant</th><th className="r">Index fut net</th>
              <th className="r">Index fut long %<Explain metric="fii_long_pct" value={p.FII?.fut_idx_long_pct} /></th>
              <th className="r">Index calls net</th><th className="r">Index puts net</th><th className="r">Stock fut net</th></tr></thead>
            <tbody>{PARTS.map((k) => { const x = p[k]; return (
              <tr key={k} className={`clickable ${who === k ? "selected" : ""}`} onClick={() => setWho(k)}>
                <td><b>{k}</b>{k === "FII" && <> <span className="badge warn mk-tag" title="The FII long-% signal did not pass walk-forward validation">context · not validated</span>
                  <QuickAlert rule={{ type: "fii_flip", category: "FII", participant: true }} title="Alert when FII index-futures net flips sign" /></>}
                  {k === "DII" && <QuickAlert rule={{ type: "fii_flip", category: "DII", participant: true }} title="Alert when DII index-futures net flips sign" />}</td>
                <td className={`num ${tone(x?.net_idx_fut)}`}>{signed(x?.net_idx_fut)}<Chg v={x?.net_idx_fut_chg} /></td>
                <td className="num">{pct(x?.fut_idx_long_pct, 2)}<Chg v={x?.fut_idx_long_pct_chg} d={2} /></td>
                <td className={`num ${tone(x?.idx_call_net)}`}>{signed(x?.idx_call_net)}<Chg v={x?.idx_call_net_chg} /></td>
                <td className={`num ${tone(x?.idx_put_net)}`}>{signed(x?.idx_put_net)}<Chg v={x?.idx_put_net_chg} /></td>
                <td className={`num ${tone(x?.net_stk_fut)}`}>{signed(x?.net_stk_fut)}<Chg v={x?.net_stk_fut_chg} /></td>
              </tr>); })}</tbody>
          </table></div>
          <div className="row wrap between" style={{ gap: 8 }}>
            <span className="faint" style={{ fontSize: 12 }}>{who} · {metric === "fut_idx_long_pct" ? "index-futures long %" : "index-futures net contracts"} · {series.length} sessions (click a row to switch)</span>
            <Seg value={metric} onChange={setMetric} options={[{ value: "fut_idx_long_pct", label: "Long %" }, { value: "net_idx_fut", label: "Net contracts" }]} />
          </div>
          {series.length > 1 ? <LineChart data={series} tone="accent" height={200} baseline={metric === "net_idx_fut"} />
            : <div className="faint" style={{ fontSize: 13 }}>Not enough stored sessions for a history chart yet.</div>}
          <div className="faint" style={{ fontSize: 12 }}>Positioning is shown as context. The FII long-% signal did not pass walk-forward validation, so the adviser never trades on it.</div>
        </div>
      )}
    </Card>
  );
}

/* ---------------- Futures ---------------- */
interface Contract {
  expiry?: string; ltp?: number; spot?: number; change_pct?: number; oi?: number; volume?: number; basis?: number; basis_pct?: number;
  basis_ann_pct?: number; days_to_expiry?: number; oi_change?: number; buildup?: string | null;
}
interface FutRow { underlying: string; spot?: number; near?: Contract; next?: Contract; rollover_pct?: number | null; total_oi?: number; prov?: Prov }

function Futures() {
  const [scope, setScope] = useState<"index" | "stock">("index");
  const r = usePoll<{ rows?: FutRow[]; prov?: Prov }>(`/api/markets/inst/futures?scope=${scope}`, MIN);
  const rows = r.data?.rows || [];
  const expiryWeek = rows.some((x) => isNum(x.near?.days_to_expiry) && x.near!.days_to_expiry! <= 7);
  return (
    <Card title="Futures · basis, OI and buildup" className="span-2" flush
      sub={<>Near-month vs spot · basis<Explain metric="basis" value={rows[0]?.near?.basis} symbol={rows[0]?.underlying} /> annualised · rollover<Explain metric="rollover" value={rows[0]?.rollover_pct} symbol={rows[0]?.underlying} />{expiryWeek ? " · expiry week: rollover is live" : ""} · bell = alert on buildup change</>}
      actions={<><Seg value={scope} onChange={setScope} options={[{ value: "index", label: "Index" }, { value: "stock", label: "Stock" }]} />
        <ProvBadge prov={r.data?.prov} loading={r.loading && !r.data} /></>}>
      <ErrorNote error={r.error} onRetry={r.reload} />
      {r.loading && !r.data ? <Loading rows={5} /> : !rows.length ? <Empty title="No futures data">{r.data?.prov?.note}</Empty> : (
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Underlying</th><th className="r">Spot</th><th>Near</th><th className="r">Fut LTP</th><th className="r">Chg %</th>
            <th className="r">Basis</th><th className="r">Ann. basis</th><th className="r">OI</th><th className="r">OI chg</th><th>Buildup</th>
            <th className="r">Next basis</th><th className="r">Rollover</th><th>Data</th></tr></thead>
          <tbody>{rows.map((x) => { const n = x.near; return (
            <tr key={x.underlying}>
              <td><b>{x.underlying}</b><QuickAlert rule={{ type: "futures_buildup_change", symbol: x.underlying }} title={`Alert when ${x.underlying} futures buildup changes`} /></td>
              <td className="num">{num(x.spot, 2)}</td>
              <td className="faint">{n?.expiry || "—"}{isNum(n?.days_to_expiry) ? ` · ${fixed(n!.days_to_expiry, 1)}d` : ""}</td>
              <td className="num">{num(n?.ltp, 2)}</td>
              <td className={`num ${tone(n?.change_pct)}`}>{isNum(n?.change_pct) ? `${signed(n!.change_pct, 2)}%` : "—"}</td>
              <td className={`num ${tone(n?.basis)}`}>{signed(n?.basis, 2)}</td>
              <td className="num">{pct(n?.basis_ann_pct, 2)}</td>
              <td className="num">{lakh(n?.oi)}</td>
              <td className={`num ${tone(n?.oi_change)}`}>{isNum(n?.oi_change) ? signed(n!.oi_change) : "—"}</td>
              <td>{n?.buildup ? <><Buildup b={n.buildup} /><Explain metric={n.buildup} symbol={x.underlying} /></> : <span className="faint">—</span>}</td>
              <td className="num">{isNum(x.next?.basis) ? `${signed(x.next!.basis, 2)} (${pct(x.next!.basis_ann_pct, 1)})` : "—"}</td>
              <td className="num">{isNum(x.rollover_pct) ? <span className={isNum(n?.days_to_expiry) && n!.days_to_expiry! <= 7 ? "warn" : ""}>{pct(x.rollover_pct, 1)}</span> : "—"}</td>
              <td><ProvBadge prov={x.prov} loading={false} /></td>
            </tr>); })}</tbody>
        </table></div>
      )}
    </Card>
  );
}

/* ---------------- IV term structure ---------------- */
interface TermRow { symbol: string; spot?: number; near?: { expiry?: string; atm_iv?: number; days_to_expiry?: number }; next?: { expiry?: string; atm_iv?: number; days_to_expiry?: number }; slope_pts?: number; shape?: string; prov?: Prov }

function TermStructure() {
  const r = usePoll<{ rows?: TermRow[]; prov?: Prov }>("/api/markets/inst/term-structure", 2 * MIN);
  return (
    <Card title="IV term structure" sub="ATM IV, near vs next expiry" flush actions={<ProvBadge prov={r.data?.prov} loading={r.loading && !r.data} />}>
      <ErrorNote error={r.error} onRetry={r.reload} />
      {r.loading && !r.data ? <Loading /> : !r.data?.rows?.length ? <Empty title="No term structure">{r.data?.prov?.note}</Empty> : (
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Symbol</th><th className="r">Near IV<Explain metric="atm_iv" value={r.data.rows[0]?.near?.atm_iv} /></th><th className="r">Next IV</th><th className="r">Slope</th><th>Shape</th></tr></thead>
          <tbody>{r.data.rows.map((x) => (
            <tr key={x.symbol}>
              <td><b>{x.symbol}</b></td>
              <td className="num" title={x.near?.expiry}>{pct(x.near?.atm_iv, 2)} <span className="faint">{isNum(x.near?.days_to_expiry) ? `${fixed(x.near!.days_to_expiry, 0)}d` : ""}</span></td>
              <td className="num" title={x.next?.expiry}>{pct(x.next?.atm_iv, 2)} <span className="faint">{isNum(x.next?.days_to_expiry) ? `${fixed(x.next!.days_to_expiry, 0)}d` : ""}</span></td>
              <td className={`num ${tone(x.slope_pts)}`}>{isNum(x.slope_pts) ? `${signed(x.slope_pts, 2)} pts` : "—"}</td>
              <td className="faint">{x.shape || "—"}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </Card>
  );
}

/* ---------------- Ban list ---------------- */
function BanList() {
  const r = usePoll<{ trade_date?: string; symbols?: string[]; prov?: Prov }>("/api/markets/inst/ban", 30 * MIN);
  return (
    <Card title="F&O ban list" sub={r.data?.trade_date ? `Trade date ${r.data.trade_date} · no fresh positions in these` : "Securities over 95% of market-wide position limit"}
      actions={<ProvBadge prov={r.data?.prov} loading={r.loading && !r.data} />}>
      <ErrorNote error={r.error} onRetry={r.reload} />
      {r.loading && !r.data ? <Loading /> : !r.data?.symbols ? <Empty title="Ban list unavailable">{r.data?.prov?.note}</Empty>
        : !r.data.symbols.length ? <Empty title="No securities in ban" icon="check" />
          : <div className="row wrap" style={{ gap: 6 }}>{r.data.symbols.map((s) => <Badge key={s} tone="down">{s}</Badge>)}</div>}
    </Card>
  );
}

/* ---------------- Events ---------------- */
interface Ev { symbol: string; company?: string; purpose?: string; description?: string; date?: string; is_results?: boolean }

function Events() {
  const r = usePoll<{ upcoming?: Ev[]; recent?: Ev[]; prov?: Prov }>("/api/markets/inst/events", 10 * MIN);
  const [which, setWhich] = useState<"upcoming" | "recent">("upcoming");
  const rows = r.data?.[which] || [];
  return (
    <Card title="Results & corporate events" flush sub="NSE event calendar · bell = alert a day before"
      actions={<><Seg value={which} onChange={setWhich} options={[{ value: "upcoming", label: `Upcoming${r.data?.upcoming ? ` (${r.data.upcoming.length})` : ""}` }, { value: "recent", label: "Recent" }]} />
        <ProvBadge prov={r.data?.prov} loading={r.loading && !r.data} /></>}>
      <ErrorNote error={r.error} onRetry={r.reload} />
      {r.loading && !r.data ? <Loading /> : !rows.length ? <Empty title={`No ${which} events`}>{r.data?.prov?.note}</Empty> : (
        <div className="table-wrap" style={{ maxHeight: 360 }}><table className="table">
          <thead><tr><th>Date</th><th>Symbol</th><th>Purpose</th></tr></thead>
          <tbody>{rows.map((e, i) => (
            <tr key={`${e.symbol}-${e.date}-${i}`}>
              <td className="mono">{e.date || "—"}</td>
              <td title={e.company}><b>{e.symbol}</b>{which === "upcoming" && <QuickAlert rule={{ type: "event_upcoming", symbol: e.symbol, days: 1 }} title={`Alert a day before ${e.symbol}'s ${e.purpose || "event"}`} />}</td>
              <td className="wrap-cell" title={e.description}>{e.is_results && <Badge tone="accent">results</Badge>} {e.purpose || "—"}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </Card>
  );
}

/* ---------------- Deals ---------------- */
interface Deal { symbol: string; name?: string; client?: string | null; side?: string | null; qty?: number | null; price?: number | null; date?: string }

function Deals() {
  const r = usePoll<{ bulk?: Deal[]; block?: Deal[]; short?: Deal[]; as_on_date?: string; prov?: Prov }>("/api/markets/inst/deals", 30 * MIN);
  const [kind, setKind] = useState<"bulk" | "block" | "short">("block");
  const [q, setQ] = useState("");
  const all = r.data?.[kind] || [];
  const rows = all.filter((d) => !q || `${d.symbol} ${d.name} ${d.client}`.toLowerCase().includes(q.toLowerCase())).slice(0, 80);
  return (
    <Card title="Bulk, block & short deals" flush sub={r.data?.as_on_date ? `As on ${r.data.as_on_date}` : "NSE large deals"}
      actions={<><Seg value={kind} onChange={setKind} options={(["block", "bulk", "short"] as const).map((k) => ({ value: k, label: `${k[0].toUpperCase()}${k.slice(1)}${r.data?.[k] ? ` (${r.data[k]!.length})` : ""}` }))} />
        <ProvBadge prov={r.data?.prov} loading={r.loading && !r.data} /></>}>
      <ErrorNote error={r.error} onRetry={r.reload} />
      {r.loading && !r.data ? <Loading /> : !all.length ? <Empty title={`No ${kind} deals`}>{r.data?.prov?.note}</Empty> : (
        <>
          <div style={{ padding: "10px 14px 0" }}><input className="input" style={{ height: 32 }} placeholder="Filter symbol or client" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter deals" /></div>
          <div className="table-wrap" style={{ maxHeight: 360 }}><table className="table">
            <thead><tr><th>Symbol</th><th>Client</th><th>Side</th><th className="r">Qty</th><th className="r">Price</th><th className="r">Value ₹ cr</th></tr></thead>
            <tbody>{rows.map((d, i) => (
              <tr key={i}>
                <td title={d.name}><b>{d.symbol}</b></td>
                <td className="wrap-cell" style={{ minWidth: 160 }}>{d.client || "—"}</td>
                <td>{d.side ? <Badge tone={d.side === "BUY" ? "up" : d.side === "SELL" ? "down" : undefined}>{d.side}</Badge> : "—"}</td>
                <td className="num">{num(d.qty, 0)}</td>
                <td className="num">{num(d.price, 2)}</td>
                <td className="num">{isNum(d.qty) && isNum(d.price) ? num((d.qty * d.price) / 1e7, 2) : "—"}</td>
              </tr>
            ))}</tbody>
          </table></div>
        </>
      )}
    </Card>
  );
}

/* ---------------- Delivery accumulation ---------------- */
interface Deliv { symbol: string; close?: number; volume?: number; deliv_pct?: number; avg_deliv_pct_20d?: number; volume_x?: number; deliv_x?: number; accumulation?: boolean; history_days?: number }

function Delivery() {
  const r = usePoll<{ date?: string; rows?: Deliv[]; matches?: number; rule?: string; prov?: Prov }>("/api/markets/inst/delivery", 30 * MIN);
  const rows = r.data?.rows || [];
  return (
    <Card title="Delivery accumulation screen" flush
      sub={r.data?.rule ? `${r.data.rule} · ${r.data.matches ?? rows.length} matches on ${r.data.date}` : "High delivery on high volume vs own 20-session average"}
      actions={<ProvBadge prov={r.data?.prov} loading={r.loading && !r.data} />}>
      <ErrorNote error={r.error} onRetry={r.reload} />
      {r.loading && !r.data ? <Loading /> : !rows.length ? <Empty title="No accumulation matches">{r.data?.prov?.note}</Empty> : (
        <div className="table-wrap" style={{ maxHeight: 360 }}><table className="table">
          <thead><tr><th>Symbol</th><th className="r">Close</th><th className="r">Deliv %<Explain metric="delivery_pct" value={rows[0]?.deliv_pct} symbol={rows[0]?.symbol} /></th>
            <th className="r">20d avg</th><th className="r">Deliv ×</th><th className="r">Volume ×</th><th /></tr></thead>
          <tbody>{rows.map((d) => (
            <tr key={d.symbol}>
              <td><b>{d.symbol}</b></td>
              <td className="num">{num(d.close, 2)}</td>
              <td className="num">{pct(d.deliv_pct, 1)}</td>
              <td className="num faint">{pct(d.avg_deliv_pct_20d, 1)}</td>
              <td className="num">{isNum(d.deliv_x) ? `${fixed(d.deliv_x, 2)}×` : "—"}</td>
              <td className="num">{isNum(d.volume_x) ? `${fixed(d.volume_x, 1)}×` : "—"}</td>
              <td>{d.accumulation && <Badge tone="up">accumulation</Badge>}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </Card>
  );
}

/* ---------------- 52-week highs / lows ---------------- */
interface Wk { symbol: string; company?: string; ltp?: number; change_pct?: number; new_52w?: number; prev_52w?: number; prev_52w_date?: string }

function FiftyTwo() {
  const r = usePoll<{ highs?: { rows?: Wk[]; prov?: Prov }; lows?: { rows?: Wk[]; prov?: Prov } }>("/api/markets/inst/52week", 5 * MIN);
  const [side, setSide] = useState<"highs" | "lows">("highs");
  const d = r.data?.[side];
  return (
    <Card title="New 52-week highs & lows" flush
      actions={<><Seg value={side} onChange={setSide} options={[{ value: "highs", label: `Highs${r.data?.highs?.rows ? ` (${r.data.highs.rows.length})` : ""}` }, { value: "lows", label: `Lows${r.data?.lows?.rows ? ` (${r.data.lows.rows.length})` : ""}` }]} />
        <ProvBadge prov={d?.prov} loading={r.loading && !r.data} /></>}>
      <ErrorNote error={r.error} onRetry={r.reload} />
      {r.loading && !r.data ? <Loading /> : !d?.rows?.length ? <Empty title={`No new 52-week ${side}`}>{d?.prov?.note}</Empty> : (
        <div className="table-wrap" style={{ maxHeight: 360 }}><table className="table">
          <thead><tr><th>Symbol</th><th className="r">LTP</th><th className="r">Chg %</th><th className="r">New 52w</th><th className="r">Previous</th></tr></thead>
          <tbody>{d.rows.map((x) => (
            <tr key={x.symbol}>
              <td title={x.company}><b>{x.symbol}</b></td>
              <td className="num">{num(x.ltp, 2)}</td>
              <td className={`num ${tone(x.change_pct)}`}>{isNum(x.change_pct) ? `${signed(x.change_pct, 2)}%` : "—"}</td>
              <td className={`num ${side === "highs" ? "up" : "down"}`}>{num(x.new_52w, 2)}</td>
              <td className="num faint" title={x.prev_52w_date}>{num(x.prev_52w, 2)}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </Card>
  );
}

/* ---------------- Most active contracts ---------------- */
interface Active { contract?: string; underlying?: string; expiry?: string; option_type?: string; strike?: number; ltp?: number; change_pct?: number; contracts?: number; turnover_lakh?: number; oi?: number }

function MostActive() {
  const r = usePoll<{ by_volume?: Active[]; by_value?: Active[]; volume_timestamp?: string; prov?: Prov }>("/api/markets/inst/most-active", 2 * MIN);
  const [by, setBy] = useState<"by_volume" | "by_value">("by_volume");
  const rows = r.data?.[by] || [];
  const label = (a: Active) => `${a.underlying || ""} ${a.expiry || ""} ${a.option_type && a.option_type !== "-" ? `${num(a.strike, 2)} ${a.option_type === "Call" ? "CE" : a.option_type === "Put" ? "PE" : a.option_type}` : "FUT"}`;
  return (
    <Card title="Most active F&O contracts" flush sub={r.data?.volume_timestamp ? `NSE snapshot ${r.data.volume_timestamp}` : ""}
      actions={<><Seg value={by} onChange={setBy} options={[{ value: "by_volume", label: "Volume" }, { value: "by_value", label: "Value" }]} />
        <ProvBadge prov={r.data?.prov} loading={r.loading && !r.data} /></>}>
      <ErrorNote error={r.error} onRetry={r.reload} />
      {r.loading && !r.data ? <Loading /> : !rows.length ? <Empty title="No contract data">{r.data?.prov?.note}</Empty> : (
        <div className="table-wrap" style={{ maxHeight: 360 }}><table className="table">
          <thead><tr><th>Contract</th><th className="r">LTP</th><th className="r">Chg %</th><th className="r">Contracts</th><th className="r">Turnover ₹ cr</th><th className="r">OI</th></tr></thead>
          <tbody>{rows.map((a, i) => (
            <tr key={a.contract || i}>
              <td className="mono" title={a.contract}>{label(a)}</td>
              <td className="num">{num(a.ltp, 2)}</td>
              <td className={`num ${tone(a.change_pct)}`}>{isNum(a.change_pct) ? `${signed(a.change_pct, 1)}%` : "—"}</td>
              <td className="num">{lakh(a.contracts)}</td>
              <td className="num">{isNum(a.turnover_lakh) ? num(a.turnover_lakh / 100, 0) : "—"}</td>
              <td className="num">{lakh(a.oi)}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </Card>
  );
}
