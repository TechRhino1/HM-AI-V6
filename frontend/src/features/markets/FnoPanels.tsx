import { useEffect, useMemo, useState } from "react";
import { api, qs } from "../../lib/api";
import { usePoll } from "../../lib/hooks";
import { dateTime, fixed, isNum, num, pct, tone } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, KV, Loading, Meter, Seg, sideTone } from "../../components/ui";
import { ProvBadge } from "../../components/ProvBadge";
import { useFeedback } from "../../components/feedback";
import { MiniStat } from "../overview/Overview";
import { ReasonList } from "../trade/EngineView";
import { Explain } from "../../components/Explain";
import { QuickAlert } from "../alerts/Alerts";
import { aroundAtm, Leg, legsParam, Prov } from "./logic";
import { inr, Payoff } from "./Payoff";
import { getLastScan, setLastScan, takeScanRequest } from "./scanCache";
import { recName } from "./types";
import type { Advice, Analytics, Forecast, ScanOut, Side, Strategy, Wall } from "./types";

const BUILDUP: Record<string, [string, string]> = {
  long_buildup: ["LB", "up"], short_buildup: ["SB", "down"], short_covering: ["SC", "accent"], long_unwinding: ["LU", "warn"],
};
export const Buildup = ({ b }: { b?: string | null }) => {
  const x = b ? BUILDUP[b] : undefined;
  return x ? <span className={`badge ${x[1]} mk-tag`} title={b!.replace("_", " ")}>{x[0]}</span> : null;
};
export const lakh = (v: unknown) => (isNum(v) ? (Math.abs(v) >= 1e5 ? `${fixed(v / 1e5, 2)}L` : num(v, 0)) : "—");

const GenericTable = ({ rows }: { rows: Record<string, unknown>[] }) => {
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))].filter((k) => rows.some((r) => typeof r[k] !== "object" || r[k] === null));
  return (
    <div className="table-wrap"><table className="table">
      <thead><tr>{cols.map((c) => <th key={c}>{c.replace(/_/g, " ")}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={i}>{cols.map((c) => { const x = r[c]; return <td key={c} className={typeof x === "number" ? `num ${/pnl/.test(c) ? tone(x) : ""}` : ""}>{typeof x === "number" ? (/^ts$|_at$|^time$/.test(c) && x > 1e9 ? dateTime(x) : num(x, 2)) : x === null || x === undefined ? "—" : String(x)}</td>; })}</tr>
      ))}</tbody>
    </table></div>
  );
};

/* ---------------- Option chain ---------------- */
export function Chain({ data, error, loading, reload, onLeg }: {
  data?: Analytics; error: string | null; loading: boolean; reload: () => void; onLeg: (l: Leg) => void;
}) {
  const { toast } = useFeedback();
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const rows = useMemo(() => aroundAtm(data?.strikes || [], data?.atm_strike ?? data?.spot, 15), [data]);
  const maxOi = Math.max(1, ...rows.flatMap((r) => [r.call?.oi || 0, r.put?.oi || 0]));
  const res = new Set((data?.walls?.resistance || []).map((w) => w.strike));
  const sup = new Set((data?.walls?.support || []).map((w) => w.strike));
  const res1 = data?.walls?.resistance?.[0]?.strike, sup1 = data?.walls?.support?.[0]?.strike;
  const sym = data?.symbol;
  const add = (strike: number, type: "CE" | "PE", s: Side | null) => {
    if (!s || !isNum(s.ltp ?? s.mid)) return;
    onLeg({ strike, type, side, lots: 1 });
    toast("info", `Added ${side} ${num(strike, 0)} ${type}`, "Open the Builder tab to evaluate");
  };
  const cells = (s: Side | null, type: "CE" | "PE", strike: number) => {
    const oi = (
      <td className="num mk-oi" key="oi"><i className={type === "CE" ? "ce" : "pe"} style={{ width: `${((s?.oi || 0) / maxOi) * 100}%` }} />{lakh(s?.oi)}</td>
    );
    const c = [
      oi,
      <td key="chg" className={`num ${tone(s?.oi_change)}`}>{lakh(s?.oi_change)} <Buildup b={s?.buildup} /></td>,
      <td key="iv" className="num" title={s?.iv_source || ""}>{isNum(s?.iv) ? fixed(s!.iv, 1) : "—"}</td>,
      <td key="d" className="num">{isNum(s?.delta) ? fixed(s!.delta, 2) : "—"}</td>,
      <td key="ba" className="num faint">{isNum(s?.bid) ? `${fixed(s!.bid, 2)} / ${fixed(s!.ask, 2)}` : "—"}</td>,
      <td key="ltp" className="num mk-pick" onClick={() => add(strike, type, s)} title={`Add ${side} ${strike} ${type} to the builder`}>
        <b>{isNum(s?.ltp) ? fixed(s!.ltp, 2) : "—"}</b>
      </td>,
    ];
    return type === "CE" ? c : c.reverse();
  };
  return (
    <Card title="Option chain" sub={<>ATM ±15 strikes · click a price to add a {side} leg · bell = alert on the wall / max pain · LB long build-up<Explain metric="long_buildup" />, SB short build-up<Explain metric="short_buildup" />, SC short covering<Explain metric="short_covering" />, LU long unwinding<Explain metric="long_unwinding" /></>} flush
      actions={<><Seg value={side} onChange={setSide} options={[{ value: "BUY", label: "Buy" }, { value: "SELL", label: "Sell" }]} /><ProvBadge prov={data?.prov} /></>}>
      <ErrorNote error={error} onRetry={reload} />
      {loading && !data ? <Loading rows={8} /> : !rows.length ? <Empty title="No chain data" /> : (
        <div className="table-wrap mk-chain">
          <table className="table">
            <thead>
              <tr><th colSpan={6} className="r">Calls</th><th className="mk-strike">Strike</th><th colSpan={6}>Puts</th></tr>
              <tr><th className="r">OI</th><th className="r">OI chg</th><th className="r">IV</th><th className="r">Δ</th><th className="r">Bid / ask</th><th className="r">LTP</th>
                <th className="mk-strike" /><th className="r">LTP</th><th className="r">Bid / ask</th><th className="r">Δ</th><th className="r">IV</th><th className="r">OI chg</th><th className="r">OI</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const atm = r.strike === data?.atm_strike;
                return (
                  <tr key={r.strike} className={atm ? "selected" : ""}>
                    {cells(r.call, "CE", r.strike)}
                    <td className="mk-strike mono">
                      <b>{num(r.strike, 2)}</b>
                      {atm && <span className="badge accent mk-tag">ATM</span>}
                      {r.strike === data?.max_pain && <><span className="badge mk-tag" title="Max pain">MP</span>
                        {sym && <QuickAlert rule={{ type: "max_pain_distance", symbol: sym, pct: 0.5 }} title={`Alert when ${sym} spot is within 0.5% of max pain`} />}</>}
                      {res.has(r.strike) && <><span className="badge down mk-tag" title="Call OI wall (resistance)">R</span>
                        {sym && r.strike === res1 && <QuickAlert rule={{ type: "oi_wall_cross", symbol: sym, side: "call", nth: 1 }} title={`Alert when ${sym} spot crosses the largest call OI wall`} />}</>}
                      {sup.has(r.strike) && <><span className="badge up mk-tag" title="Put OI wall (support)">S</span>
                        {sym && r.strike === sup1 && <QuickAlert rule={{ type: "oi_wall_cross", symbol: sym, side: "put", nth: 1 }} title={`Alert when ${sym} spot crosses the largest put OI wall`} />}</>}
                    </td>
                    {cells(r.put, "PE", r.strike)}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/* ---------------- Market structure ---------------- */
const WallList = ({ title, rows, tone: t }: { title: string; rows?: Wall[]; tone: "up" | "down" }) => (
  <div>
    <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}>{title}</div>
    {rows?.length ? rows.map((w) => (
      <div key={w.strike} className="row between mono" style={{ fontSize: 13 }}>
        <b className={t}>{num(w.strike, 0)}</b><span>{lakh(w.oi)} <span className={`faint ${tone(w.oi_change)}`}>({w.oi_change > 0 ? "+" : ""}{lakh(w.oi_change)})</span></span>
      </div>
    )) : <div className="faint">—</div>}
  </div>
);

export function Structure({ a, prov }: { a?: Analytics; prov?: Prov }) {
  if (!a) return <Card title="Market structure"><Empty title="No chain loaded" /></Card>;
  const em = a.expected_move, p = a.pcr, g = a.gex, sk = a.skew;
  return (
    <div className="grid cols-2">
      <Card title="Positioning" actions={<ProvBadge prov={prov} />}>
        <div className="grid mk-stats">
          <MiniStat label={<>PCR (OI)<Explain metric="pcr" value={p?.oi} symbol={a.symbol} /></>} value={fixed(p?.oi, 2)} />
          <MiniStat label="PCR (volume)" value={fixed(p?.volume, 2)} />
          <MiniStat label="PCR (OI change)" value={fixed(p?.oi_change, 2)} />
          <MiniStat label={<>Max pain<Explain metric="max_pain" value={a.max_pain} symbol={a.symbol} /></>} value={num(a.max_pain, 0)} />
        </div>
        <KV items={[
          ["Call OI / change", `${lakh(p?.call_oi)} / ${lakh(p?.call_oi_change)}`],
          ["Put OI / change", `${lakh(p?.put_oi)} / ${lakh(p?.put_oi_change)}`],
          ["Writers' bias", <span className={sideTone(a.positioning?.bias)}>{a.positioning?.bias || "—"}</span>],
        ]} />
      </Card>
      <Card title="Expected move to expiry" sub="1σ from ATM IV" actions={<ProvBadge prov={prov} />}>
        <div className="grid mk-stats">
          <MiniStat label={<>±1σ<Explain metric="expected_move" value={em?.one_sd} symbol={a.symbol} /></>} value={`±${num(em?.one_sd, 0)}`} />
          <MiniStat label="±1σ %" value={pct(em?.one_sd_pct, 2)} />
          <MiniStat label="Upper 1σ" value={num(em?.upper_1sd, 0)} valueClass="up" />
          <MiniStat label="Lower 1σ" value={num(em?.lower_1sd, 0)} valueClass="down" />
        </div>
        <KV items={[
          ["25Δ call IV / put IV", `${fixed(sk?.call25_iv, 2)} / ${fixed(sk?.put25_iv, 2)}`],
          [<>Risk reversal (25Δ)<Explain metric="rr25" value={sk?.rr25} symbol={a.symbol} /></>, <span className={tone(sk?.rr25)}>{fixed(sk?.rr25, 2)}</span>],
          [<>Net GEX<Explain metric="gex" value={g?.net_gex_cr} symbol={a.symbol} /></>, isNum(g?.net_gex_cr) ? `₹${num(g!.net_gex_cr, 0)} cr` : "—"],
          ["Gamma regime", g?.regime || "—"],
          ["Gamma flip", num(g?.gamma_flip_strike, 0)],
        ]} />
        {g?.assumption && <div className="faint" style={{ fontSize: 12, marginTop: 8 }}>GEX assumes {g.assumption}.</div>}
      </Card>
      <Card title="OI walls" sub="Largest open interest and today's fresh writing" className="span-2" actions={<ProvBadge prov={prov} />}>
        <div className="grid cols-4">
          <WallList title="Resistance (call OI)" rows={a.walls?.resistance} tone="down" />
          <WallList title="Support (put OI)" rows={a.walls?.support} tone="up" />
          <WallList title="Fresh call writing" rows={a.walls?.fresh_call_writing} tone="down" />
          <WallList title="Fresh put writing" rows={a.walls?.fresh_put_writing} tone="up" />
        </div>
      </Card>
    </div>
  );
}

/* ---------------- Volatility ---------------- */
interface Vix { value?: number; change_pct?: number; year_low?: number; year_high?: number; range_position?: number; prov?: Prov }

export function Volatility({ adv }: { adv?: Advice }) {
  const vix = usePoll<Vix>("/api/markets/vix", 60000);
  const v = adv?.volatility, vrp = adv?.vrp_history;
  const bars: [string, number | undefined][] = [["ATM IV", v?.atm_iv], ["RV10", v?.rv10], ["RV20", v?.rv20], ["RV60", v?.rv60]];
  const max = Math.max(1, ...bars.map(([, x]) => (isNum(x) ? x : 0)));
  return (
    <div className="grid cols-2">
      <Card title="Implied vs realised" sub={v?.vol_view || ""} actions={<ProvBadge prov={v?.bars_prov} label="bars" loading={!adv} />}>
        {!v?.available ? <Empty title="Volatility unavailable">Not enough real price history for this underlying.</Empty> : (
          <div className="stack">
            {bars.map(([l, x]) => (
              <div key={l} className="row" style={{ gap: 10 }}>
                <span className="faint" style={{ width: 56, fontSize: 12 }}>{l}</span>
                <div className="grow"><Meter value={isNum(x) ? x : 0} max={max} tone={l === "ATM IV" ? undefined : "good"} /></div>
                <span className="mono" style={{ width: 54, textAlign: "right" }}>{pct(x, 1)}</span>
              </div>
            ))}
            <KV items={[
              [<>IV − RV20<Explain metric="iv_minus_rv" value={v?.iv_minus_rv20} symbol={adv?.symbol} /></>, <span className={tone(v?.iv_minus_rv20)}>{isNum(v?.iv_minus_rv20) ? `${fixed(v!.iv_minus_rv20, 2)} pts` : "—"}</span>],
              [<>IV percentile<Explain metric="iv_percentile" value={v?.iv_percentile} symbol={adv?.symbol} /></>, isNum(v?.iv_percentile) ? pct(v!.iv_percentile, 0) : `collecting history: ${v?.iv_history_days ?? 0} days`],
              ["Forecast vol", isNum(v?.forecast_vol) ? pct(v!.forecast_vol * 100, 1) : "—"],
              ["Daily trend", v?.trend?.label || "—"],
            ]} />
          </div>
        )}
      </Card>
      <Card title="India VIX" sub="with its real 52-week range" actions={<ProvBadge prov={vix.data?.prov} />}>
        <ErrorNote error={vix.error} onRetry={vix.reload} />
        {vix.loading && !vix.data ? <Loading /> : !isNum(vix.data?.value) ? <Empty title="VIX unavailable">{vix.data?.prov?.note}</Empty> : (
          <div className="stack">
            <div className="row" style={{ gap: 10, alignItems: "baseline" }}>
              <span className="mono" style={{ fontSize: 28, fontWeight: 600 }}>{fixed(vix.data!.value, 2)}</span>
              <span className={tone(vix.data!.change_pct)}>{isNum(vix.data!.change_pct) ? `${vix.data!.change_pct > 0 ? "+" : ""}${fixed(vix.data!.change_pct, 2)}%` : ""}</span>
            </div>
            <Meter value={(vix.data!.range_position ?? 0) * 100} max={100} tone="warn" />
            <div className="row between faint mono" style={{ fontSize: 12 }}>
              <span>52w low {fixed(vix.data!.year_low, 2)}</span><span>{pct((vix.data!.range_position ?? 0) * 100, 0)} of range</span><span>52w high {fixed(vix.data!.year_high, 2)}</span>
            </div>
          </div>
        )}
      </Card>
      <Card title="Volatility risk premium · history" className="span-2" sub="How often implied vol (VIX) exceeded the next month's realised NIFTY vol">
        {!vrp?.available ? <Empty title="No VRP history" /> : (
          <div className="grid mk-stats">
            <MiniStat label="IV above RV" value={pct(vrp.iv_above_rv_pct, 1)} />
            <MiniStat label="Mean IV − RV" value={`${fixed(vrp.mean_iv_minus_rv, 2)} pts`} />
            <MiniStat label="Worst 5%" value={`${fixed(vrp.worst_5pct, 2)} pts`} valueClass="down" />
            <MiniStat label="Sample" value={`${num(vrp.days, 0)} days since ${vrp.from || "—"}`} />
          </div>
        )}
      </Card>
    </div>
  );
}

/* ---------------- Expiry desk ---------------- */
export function ExpiryDesk({ adv }: { adv?: Advice }) {
  const e = adv?.expiry_desk;
  if (!e?.available) return <Card title="Expiry desk"><Empty title="Expiry desk unavailable" /></Card>;
  const shift = e.oi_shift_today;
  return (
    <div className="grid cols-2">
      <Card title="Expiry desk" sub={e.is_expiry_day ? "Expiry day" : e.is_expiry_week ? "Expiry week" : `${fixed(e.days_to_expiry, 1)} days to expiry`}
        actions={<ProvBadge prov={adv?.prov} />}>
        <div className="stack">
          <div className="grid mk-stats">
            <MiniStat label="To max pain" value={pct(e.distance_to_max_pain_pct, 2)} />
            <MiniStat label="ATM gamma / lot" value={fixed(e.atm_gamma_per_lot, 4)} />
            <MiniStat label="Pin candidates" value={(e.pin_candidates || []).map((p) => num(p, 0)).join(", ") || "—"} />
          </div>
          <ReasonList title="Guidance" items={e.guidance || []} tone="warn" empty="No expiry-specific guidance" />
          <div>
            <div className="faint" style={{ fontSize: 12, marginBottom: 6 }}>OI shift today</div>
            {shift?.available ? (
              <GenericTable rows={shift.largest || []} />
            ) : <div className="faint" style={{ fontSize: 13 }}>{shift?.reason || "Not available"}</div>}
          </div>
        </div>
      </Card>
      <Card title="Straddle decay" sub="ATM straddle if spot and IV stay unchanged" flush>
        <table className="table">
          <thead><tr><th>After</th><th className="r">ATM straddle</th></tr></thead>
          <tbody>
            {(e.straddle_decay_if_spot_and_iv_unchanged || []).map((r) => (
              <tr key={r.after_hours}><td>{r.after_hours ? `${r.after_hours}h` : "now"}</td><td className="num">{fixed(r.atm_straddle, 2)}</td></tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

/* ---------------- Institutional flow ---------------- */
interface FiiRow { category: string; date: string; buy_cr: number; sell_cr: number; net_cr: number }
interface Spurt { symbol: string; latestOI?: number; prevOI?: number; changeInOI?: number; avgInOI?: number; volume?: number; underlyingValue?: number }

export function Flows() {
  const fii = usePoll<{ rows?: FiiRow[]; history?: FiiRow[]; prov?: Prov }>("/api/markets/fii-dii", 600000);
  const sp = usePoll<{ rows?: Spurt[]; prov?: Prov }>("/api/markets/oi-spurts", 180000);
  const hist = fii.data?.history || [];
  const hmax = Math.max(1, ...hist.map((h) => Math.abs(h.net_cr || 0)));
  return (
    <div className="grid cols-2">
      <Card title="FII / DII cash flow" sub="₹ crore, NSE provisional" actions={<ProvBadge prov={fii.data?.prov} />}>
        <ErrorNote error={fii.error} onRetry={fii.reload} />
        {fii.loading && !fii.data ? <Loading /> : !fii.data?.rows?.length ? <Empty title="No FII/DII figures">{fii.data?.prov?.note}</Empty> : (
          <div className="stack">
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Category</th><th>Date</th><th className="r">Buy</th><th className="r">Sell</th><th className="r">Net</th></tr></thead>
              <tbody>{fii.data.rows.map((r) => (
                <tr key={r.category}><td><b>{r.category}</b></td><td>{r.date}</td><td className="num">{num(r.buy_cr, 0)}</td><td className="num">{num(r.sell_cr, 0)}</td>
                  <td className={`num ${tone(r.net_cr)}`}><b>{r.net_cr > 0 ? "+" : ""}{num(r.net_cr, 0)}</b></td></tr>
              ))}</tbody>
            </table></div>
            <div className="faint" style={{ fontSize: 12 }}>History</div>
            {hist.length ? (
              <div className="mk-hbars">
                {hist.map((h, i) => (
                  <div key={i} className="row" style={{ gap: 8, fontSize: 12 }}>
                    <span className="faint" style={{ width: 120 }}>{h.date} {h.category}</span>
                    <div className="grow mk-hbar"><i className={h.net_cr >= 0 ? "up" : "down"} style={{ width: `${(Math.abs(h.net_cr) / hmax) * 50}%`, [h.net_cr >= 0 ? "left" : "right"]: "50%" } as React.CSSProperties} /></div>
                    <span className={`mono ${tone(h.net_cr)}`} style={{ width: 64, textAlign: "right" }}>{num(h.net_cr, 0)}</span>
                  </div>
                ))}
              </div>
            ) : <div className="faint" style={{ fontSize: 13 }}>No history recorded yet; it builds up one session at a time.</div>}
          </div>
        )}
      </Card>
      <Card title="OI spurts" sub="Top 10 by OI change, F&O stocks and indices" flush actions={<ProvBadge prov={sp.data?.prov} />}>
        <ErrorNote error={sp.error} onRetry={sp.reload} />
        {sp.loading && !sp.data ? <Loading /> : !sp.data?.rows?.length ? <Empty title="No OI spurts">{sp.data?.prov?.note}</Empty> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Symbol</th><th className="r">OI</th><th className="r">Δ OI</th><th className="r">Δ %</th><th className="r">Underlying</th></tr></thead>
            <tbody>{[...sp.data.rows].sort((a, b) => (b.changeInOI || 0) - (a.changeInOI || 0)).slice(0, 10).map((r) => (
              <tr key={r.symbol}><td><b>{r.symbol}</b></td><td className="num">{lakh(r.latestOI)}</td><td className={`num ${tone(r.changeInOI)}`}>{lakh(r.changeInOI)}</td>
                <td className="num">{pct(r.avgInOI, 1)}</td><td className="num">{num(r.underlyingValue, 2)}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>
    </div>
  );
}

/* ---------------- Strategy builder ---------------- */
export function Builder({ symbol, expiry, spot, legs, setLegs }: {
  symbol: string; expiry: string; spot?: number; legs: Leg[]; setLegs: (l: Leg[]) => void;
}) {
  const [res, setRes] = useState<Strategy | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState(0);
  const evaluate = async () => {
    setBusy(true); setErr(null);
    try { setRes(await api.get<Strategy>(`/api/markets/fno/evaluate${qs({ symbol, expiry, legs: legsParam(legs) })}`)); }
    catch (e: any) { setErr(e?.message || "Evaluation failed"); setRes(null); }
    finally { setBusy(false); }
  };
  const upd = (i: number, p: Partial<Leg>) => { setLegs(legs.map((l, j) => (j === i ? { ...l, ...p } : l))); setRes(null); };
  const leg = legs[Math.min(sel, legs.length - 1)];
  return (
    <div className="grid cols-2">
      <Card title="Strategy builder" sub={`${symbol} · ${expiry || "nearest expiry"} · add legs by clicking prices in the chain`}
        actions={legs.length ? <button className="btn ghost sm" onClick={() => { setLegs([]); setRes(null); }}>Clear</button> : null}>
        {!legs.length ? <Empty title="No legs yet" icon="layers">Open the Chain tab and click a call or put price.</Empty> : (
          <div className="stack">
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Side</th><th>Contract</th><th className="r">Lots</th><th /></tr></thead>
              <tbody>{legs.map((l, i) => (
                <tr key={i} className={`clickable ${leg === l ? "selected" : ""}`} onClick={() => setSel(i)}>
                  <td><button className={`btn sm ${l.side === "BUY" ? "buy" : "sell"}`} onClick={(e) => { e.stopPropagation(); upd(i, { side: l.side === "BUY" ? "SELL" : "BUY" }); }}>{l.side}</button></td>
                  <td className="mono">{num(l.strike, 2)} {l.type}</td>
                  <td className="num"><div className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
                    <button className="btn ghost sm icon-btn" aria-label="Fewer lots" onClick={(e) => { e.stopPropagation(); upd(i, { lots: Math.max(1, l.lots - 1) }); }}>−</button>
                    {l.lots}
                    <button className="btn ghost sm icon-btn" aria-label="More lots" onClick={(e) => { e.stopPropagation(); upd(i, { lots: l.lots + 1 }); }}>+</button>
                  </div></td>
                  <td><button className="btn ghost sm" onClick={(e) => { e.stopPropagation(); setLegs(legs.filter((_, j) => j !== i)); setRes(null); }}>Remove</button></td>
                </tr>
              ))}</tbody>
            </table></div>
            <button className="btn primary" disabled={busy} onClick={evaluate}>{busy ? "Evaluating…" : "Evaluate on live chain"}</button>
            <ErrorNote error={err} />
            {res && (
              <div className="grid mk-stats">
                <MiniStat label="Net debit" value={fixed(res.net_debit, 2)} />
                <MiniStat label="Edge after costs / lot" value={inr(res.edge_per_lot)} valueClass={tone(res.edge_per_lot)} />
                <MiniStat label="POP view / market" value={`${pct(res.view?.pop, 1)} / ${pct(res.market?.pop, 1)}`} />
                <MiniStat label="Max loss / lot" value={res.unlimited_loss ? "unlimited" : inr(res.max_loss_per_lot)} valueClass="down" />
                <MiniStat label="Max gain / lot" value={res.unlimited_gain ? "unlimited" : inr(res.max_gain_per_lot)} valueClass="up" />
                <MiniStat label="Costs / lot" value={inr(res.cost_per_lot)} />
              </div>
            )}
          </div>
        )}
      </Card>
      <Card title="Builder payoff" actions={res && <ProvBadge prov={res.prov} loading={false} />}>
        {res?.payoff_curve?.length ? <Payoff curve={res.payoff_curve} breakevens={res.breakevens} spot={spot} />
          : <Empty title="Evaluate the legs to see the payoff" />}
      </Card>
      {leg && <PremiumForecast symbol={symbol} expiry={expiry} strike={leg.strike} type={leg.type} />}
    </div>
  );
}

export function ForecastGrid({ f }: { f: Forecast }) {
  const keys = Object.keys(f.grid?.[0] || {}).filter((k) => k.startsWith("iv"));
  return (
    <div className="stack">
      <div className="grid mk-stats">
        <MiniStat label="Premium now" value={fixed(f.premium_now, 2)} />
        <MiniStat label="1σ spot move" value={`±${fixed(f.move_1sd, 2)}`} />
        <MiniStat label="Time decay" value={fixed(f.time_decay, 2)} valueClass="down" />
        <MiniStat label="If nothing moves" value={fixed(f.unchanged_spot_and_iv, 2)} />
      </div>
      <div className="table-wrap"><table className="table">
        <thead><tr><th>Spot move</th><th className="r">Spot</th>{keys.map((k) => <th key={k} className="r">IV {k.slice(2)} pts</th>)}</tr></thead>
        <tbody>{(f.grid || []).map((g) => (
          <tr key={g.spot_sigma} className={g.spot_sigma === 0 ? "selected" : ""}>
            <td>{g.spot_sigma > 0 ? "+" : ""}{g.spot_sigma}σ</td><td className="num">{num(g.spot, 0)}</td>
            {keys.map((k) => { const c = g[k] as { premium: number; pct: number }; return (
              <td key={k} className="num">{fixed(c?.premium, 2)} <span className={tone(c?.pct)}>({c?.pct > 0 ? "+" : ""}{fixed(c?.pct, 0)}%)</span></td>); })}
          </tr>
        ))}</tbody>
      </table></div>
    </div>
  );
}

function PremiumForecast({ symbol, expiry, strike, type }: { symbol: string; expiry: string; strike: number; type: "CE" | "PE" }) {
  const [h, setH] = useState("1");
  const f = usePoll<Forecast>(`/api/markets/fno/premium-forecast${qs({ symbol, expiry, strike, type, horizon_days: h })}`);
  return (
    <Card title={`Premium forecast · ${num(strike, 2)} ${type}`} sub="Black-Scholes reprice across spot (σ) and IV shifts" className="span-2"
      actions={<><Seg value={h} onChange={setH} options={[{ value: "1", label: "1 day" }, { value: "3", label: "3 days" }]} /><ProvBadge prov={f.data?.prov} /></>}>
      <ErrorNote error={f.error} onRetry={f.reload} />
      {f.loading && !f.data ? <Loading /> : f.data?.grid?.length ? <ForecastGrid f={f.data} /> : <Empty title="No forecast for this contract" />}
    </Card>
  );
}

/* ---------------- Opportunity scanner ---------------- */
const SCAN_GAP = 5 * 60 * 1000;

export function Scanner({ onOpen }: { onOpen: (symbol: string) => void }) {
  const [scan, setScan] = useState(getLastScan);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const wait = scan ? Math.max(0, SCAN_GAP - (Date.now() - scan.at)) : 0;
  const run = async () => {
    setBusy(true); setErr(null);
    try { const v = { at: Date.now(), data: await api.get<ScanOut>("/api/markets/fno/scan") }; setLastScan(v); setScan(v); }
    catch (e: any) { setErr(e?.message || "Scan failed"); }
    finally { setBusy(false); }
  };
  useEffect(() => {
    if (takeScanRequest() && !busy && !wait) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const rows = [...(scan?.data.summary || [])].sort((a, b) => (b.status === "RECOMMEND" ? 1 : 0) - (a.status === "RECOMMEND" ? 1 : 0) || (b.edge_per_lot ?? -1e9) - (a.edge_per_lot ?? -1e9));
  return (
    <Card title="Opportunity scanner" flush
      sub={scan ? `${scan.data.scanned ?? rows.length} underlyings in ${fixed(scan.data.seconds, 1)}s · ${dateTime(scan.at / 1000)} · click a row to open it` : "Runs the adviser over the indices and today's most active F&O stocks"}
      actions={<>
        {scan && <ProvBadge prov={scan.data.prov} loading={false} />}
        <button className="btn primary sm" disabled={busy || wait > 0} onClick={run}
          title={wait ? "Scans are limited to one every 5 minutes" : ""}>{busy ? "Scanning…" : wait ? `Next scan in ${Math.ceil(wait / 60000)}m` : "Run scan"}</button>
      </>}>
      <ErrorNote error={err} onRetry={run} />
      {busy ? <div className="stack" style={{ padding: 16 }}><div className="muted">Scanning live chains; this can take one to three minutes…</div><Loading rows={5} /></div>
        : !scan ? <Empty title="No scan yet" icon="radar">Press “Run scan”.</Empty> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Symbol</th><th>Verdict</th><th>Strategy</th><th className="r">Edge / lot</th><th>Lean</th><th>Data</th><th>Reason</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.symbol} className="clickable" onClick={() => onOpen(r.symbol)}>
                <td><b>{r.symbol}</b></td>
                <td><Badge tone={r.status === "RECOMMEND" ? "up" : r.status === "NO_TRADE" ? "warn" : undefined}>{r.status.replace("_", " ")}</Badge></td>
                <td>{recName(r.recommendation) || "—"}</td>
                <td className={`num ${tone(r.edge_per_lot)}`}>{inr(r.edge_per_lot)}</td>
                <td><span className={sideTone(r.lean)}>{r.lean || "—"}</span></td>
                <td><ProvBadge prov={r.prov} loading={false} /></td>
                <td className="faint wrap-cell">{r.reason || ""}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
    </Card>
  );
}

/* ---------------- Track record ---------------- */
interface Ledger {
  recorded?: number; open?: number; closed?: number; win_rate?: number | null; avg_pnl_per_lot?: number | null;
  by_strategy?: Record<string, unknown>[]; items?: Record<string, unknown>[]; prov?: Prov;
}
export function TrackRecord() {
  const l = usePoll<Ledger>("/api/markets/ledger", 300000);
  const d = l.data;
  return (
    <Card title="Adviser track record" sub="Every recommendation is recorded, marked to live chain mids and settled on real closes" actions={<ProvBadge prov={d?.prov} />}>
      <ErrorNote error={l.error} onRetry={l.reload} />
      {l.loading && !d ? <Loading /> : (
        <div className="stack">
          <WeeklyReview />
          <div className="grid mk-stats">
            <MiniStat label="Recorded" value={num(d?.recorded, 0)} />
            <MiniStat label="Open" value={num(d?.open, 0)} />
            <MiniStat label="Closed" value={num(d?.closed, 0)} />
            <MiniStat label={<>Win rate<Explain metric="win_rate" value={d?.win_rate} /></>} value={isNum(d?.win_rate) ? pct(d!.win_rate!, 1) /* server sends a percentage (0–100) */ : "—"} />
            <MiniStat label="Avg P&L / lot" value={inr(d?.avg_pnl_per_lot)} valueClass={tone(d?.avg_pnl_per_lot)} />
          </div>
          {d?.by_strategy?.length ? <><div className="faint" style={{ fontSize: 12 }}>By strategy</div><GenericTable rows={d.by_strategy} /></> : null}
          {d?.items?.length ? <><div className="faint" style={{ fontSize: 12 }}>Recommendations</div><GenericTable rows={d.items.slice(0, 50)} /></>
            : <Empty title="No recommendations recorded yet">The record starts with the first RECOMMEND verdict; nothing is back-filled.</Empty>}
        </div>
      )}
    </Card>
  );
}

/** Weekly AI review of the adviser ledger: loaded on demand. */
function WeeklyReview() {
  const [r, setR] = useState<{ text?: string; provider?: string; prov?: Prov; stats?: { window_days?: number } } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const load = async () => {
    setBusy(true); setErr(null);
    try { setR(await api.get("/api/ai/review")); } catch (e: any) { setErr(e?.message || "Review unavailable"); } finally { setBusy(false); }
  };
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row wrap" style={{ gap: 8 }}>
        <button className="btn sm" disabled={busy} onClick={load}>{busy ? "Reviewing…" : r ? "Refresh weekly review" : "Weekly AI review"}</button>
        {r && <><ProvBadge prov={r.prov} loading={false} /><span className="faint" style={{ fontSize: 12 }}>{r.provider === "template" ? "rule-based summary" : `by ${r.provider}`} · last {r.stats?.window_days ?? 7} days</span></>}
      </div>
      <ErrorNote error={err} onRetry={load} />
      {r?.text && <div className="alert brief">{r.text}</div>}
    </div>
  );
}
