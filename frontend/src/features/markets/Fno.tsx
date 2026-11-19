import { useEffect, useState } from "react";
import { useStore } from "../../state/store";
import { useFeedback } from "../../components/feedback";
import { Explain } from "../../components/Explain";
import { Icon } from "../../components/Icon";
import { basketText, buildBasket } from "./basket";
import { qs } from "../../lib/api";
import { useLocalStorage, usePoll } from "../../lib/hooks";
import { fixed, isNum, num, pct } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, Loading, Seg, sideTone } from "../../components/ui";
import { ProvBadge } from "../../components/ProvBadge";
import { MiniStat } from "../overview/Overview";
import { ReasonList } from "../trade/EngineView";
import { addLeg, Leg } from "./logic";
import { inr, Payoff } from "./Payoff";
import type { Advice, Analytics, Strategy } from "./types";
import { CandleChart, Candle } from "../../components/Chart";
import { DEFAULT_LAYERS, LayerBar, Layers, LevelList, useChartIntel } from "../../components/ChartIntel";
import { Builder, Chain, ExpiryDesk, Flows, Scanner, Structure, TrackRecord, Volatility } from "./FnoPanels";

const UNDERLYINGS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];
const TABS = [
  { value: "chain", label: "Chain" }, { value: "structure", label: "Structure" }, { value: "vol", label: "Volatility" },
  { value: "expiry", label: "Expiry" }, { value: "flows", label: "Flows" }, { value: "builder", label: "Builder" },
  { value: "scanner", label: "Scanner" }, { value: "record", label: "Track record" },
] as const;
type Tab = (typeof TABS)[number]["value"];

/** India F&O: the adviser's verdict first, then chain / structure / volatility / flows behind tabs. */
export function Fno() {
  const [symbol, setSymbol] = useLocalStorage("hm.mk.fno.symbol", "NIFTY");
  const [expiry, setExpiry] = useState("");
  const [custom, setCustom] = useState("");
  const [tab, setTab] = useLocalStorage<Tab>("hm.mk.fno.tab", "chain");
  const [legs, setLegs] = useState<Leg[]>([]);
  const [picked, setPicked] = useState<string | null>(null);
  useEffect(() => { setExpiry(""); setLegs([]); setPicked(null); }, [symbol]);
  const { setPageCtx } = useStore();

  const q = qs({ symbol, expiry });
  const adv = usePoll<Advice>(`/api/markets/fno/advise${q}`, 60000);
  const chain = usePoll<Analytics>(`/api/markets/fno/analytics${q}`, 60000);
  const a = adv.data?.analytics || chain.data;
  const prov = adv.data?.prov || chain.data?.prov;
  const expiries = chain.data?.expiries || [];

  const strategies = adv.data?.strategies || [];
  const rec = adv.data?.recommendation;
  const shown: Strategy | undefined = (picked && strategies.find((s) => s.name === picked)) || rec;

  const shownExpiry = expiry || a?.expiry || "";
  useEffect(() => { setPageCtx({ symbol, market: "IN", expiry: shownExpiry || undefined }); return () => setPageCtx({}); }, [symbol, shownExpiry, setPageCtx]);

  const submitCustom = () => { const s = custom.trim().toUpperCase(); if (s) { setSymbol(s); setCustom(""); } };

  return (
    <>
      <Card title={<span className="row" style={{ gap: 8 }}>{symbol}<span className="faint" style={{ fontWeight: 400 }}>{adv.data?.kind || ""}</span></span>}
        sub={a?.expiry ? `Expiry ${a.expiry}` : "Select an underlying"} actions={<ProvBadge prov={prov} label="chain" loading={!adv.data && !chain.data} />}>
        <div className="stack mk-head">
          <div className="row wrap" style={{ gap: 8 }}>
            <Seg value={UNDERLYINGS.includes(symbol) ? symbol : ""} onChange={setSymbol} options={UNDERLYINGS.map((u) => ({ value: u, label: u }))} />
            <form className="row" style={{ gap: 6 }} onSubmit={(e) => { e.preventDefault(); submitCustom(); }}>
              <input className="input mono" style={{ width: 150, height: 32 }} placeholder="F&O stock, e.g. TCS" value={custom}
                onChange={(e) => setCustom(e.target.value)} aria-label="F&O stock symbol" />
              <button className="btn sm" type="submit">Load</button>
            </form>
            <select className="select" style={{ width: 150, height: 32 }} value={expiry || a?.expiry || ""} onChange={(e) => setExpiry(e.target.value)} aria-label="Expiry">
              {!expiries.length && <option value="">{a?.expiry || "Expiry"}</option>}
              {expiries.map((x) => <option key={x} value={x}>{x}</option>)}
            </select>
          </div>
          <div className="grid mk-stats">
            <MiniStat label="Spot" value={num(a?.spot, 2)} />
            <MiniStat label="Forward" value={num(a?.forward, 2)} />
            <MiniStat label="Days to expiry" value={fixed(a?.days_to_expiry, 1)} />
            <MiniStat label="Lot size" value={num(a?.lot_size, 0)} />
            <MiniStat label="ATM strike / IV" value={`${num(a?.atm_strike, 0)} · ${pct(a?.atm_iv, 1)}`} />
            <MiniStat label="ATM straddle" value={num(a?.atm_straddle, 2)} />
          </div>
        </div>
      </Card>

      <UnderlyingChart symbol={symbol} />

      <ErrorNote error={adv.error} onRetry={adv.reload} />
      {adv.data?.status === "UNAVAILABLE" && (
        <div className="alert warn">Option chain unavailable for {symbol}: {adv.data.reason || "no data"}. Nothing is shown rather than guessed.</div>
      )}

      <div className="grid cols-2">
        <Verdict adv={adv.data} loading={adv.loading && !adv.data} picked={shown?.name} onPick={setPicked}
          symbol={symbol} expiry={a?.expiry || ""} expiries={expiries} lotSize={a?.lot_size} />
        <Card title="Payoff at expiry" sub={shown ? `${shown.name}${shown === rec ? " · recommended" : " · not recommended"} · per lot` : "per lot"}
          actions={picked && <button className="btn ghost sm" onClick={() => setPicked(null)}>Back to recommendation</button>}>
          {shown?.payoff_curve?.length ? (
            <div className="stack">
              <Payoff curve={shown.payoff_curve} breakevens={shown.breakevens} spot={a?.spot} />
              <div className="grid mk-stats">
                <MiniStat label="Max loss / lot" value={shown.unlimited_loss ? "unlimited" : inr(shown.max_loss_per_lot)} valueClass="down" />
                <MiniStat label="Max gain / lot" value={shown.unlimited_gain ? "unlimited" : inr(shown.max_gain_per_lot)} valueClass="up" />
                <MiniStat label="Breakevens" value={(shown.breakevens || []).map((b) => num(b, 0)).join(" / ") || "—"} />
              </div>
            </div>
          ) : (
            <Empty title="No strategy recommended" icon="layers">
              Pick any row under “All strategies compared” to see its payoff, or build your own in the Builder tab.
            </Empty>
          )}
        </Card>
      </div>

      <Seg value={tab} onChange={setTab}
        options={TABS.map((t) => ({ value: t.value, label: t.value === "builder" && legs.length ? `Builder (${legs.length})` : t.label }))} />
      {tab === "chain" && <Chain data={chain.data} error={chain.error} loading={chain.loading} reload={chain.reload}
        onLeg={(l) => setLegs((x) => addLeg(x, l))} />}
      {tab === "structure" && <Structure a={a} prov={prov} />}
      {tab === "vol" && <Volatility adv={adv.data} />}
      {tab === "expiry" && <ExpiryDesk adv={adv.data} />}
      {tab === "flows" && <Flows />}
      {tab === "builder" && <Builder symbol={symbol} expiry={expiry || a?.expiry || ""} spot={a?.spot} legs={legs} setLegs={setLegs} />}
      {tab === "scanner" && <Scanner onOpen={(s) => { setSymbol(s); window.scrollTo({ top: 0, behavior: "smooth" }); }} />}
      {tab === "record" && <TrackRecord />}
    </>
  );
}

function Verdict({ adv, loading, picked, onPick, symbol, expiry, expiries, lotSize }: {
  adv?: Advice; loading: boolean; picked?: string; onPick: (n: string) => void; symbol: string; expiry: string; expiries: string[]; lotSize?: number;
}) {
  if (loading) return <Card title="AI adviser"><Loading rows={6} /></Card>;
  if (!adv) return <Card title="AI adviser"><Empty title="No advice yet" /></Card>;
  const rec = adv.recommendation, plan = adv.plan, ev = adv.evidence;
  const status = adv.status || "UNAVAILABLE";
  const tone = status === "RECOMMEND" ? "up" : status === "NO_TRADE" ? "warn" : "flat";
  return (
    <Card title="AI adviser" sub="Recommends only when a strategy clears every gate: edge after costs, defined risk, liquidity, evidence fit"
      actions={<ProvBadge prov={adv.prov} loading={false} />}>
      <div className="stack" style={{ gap: 14 }}>
        <div className="row wrap" style={{ gap: 12 }}>
          <span className={`verdict ${tone}`}>{status === "NO_TRADE" ? "NO TRADE" : status}</span>
          {rec && <div><b>{rec.name}</b><div className="faint" style={{ fontSize: 12 }}>{(rec.legs || []).length} legs · net {plan?.entry?.type || ""} {num(plan?.entry?.net, 2)}</div></div>}
        </div>
        {status !== "RECOMMEND" && adv.reason && <div className="muted">{adv.reason}</div>}

        {rec && (
          <>
            <div className="grid mk-stats">
              <MiniStat label={<>Edge after costs / lot<Explain metric="edge_after_costs" value={rec.edge_per_lot} symbol={adv.symbol} /></>} value={inr(rec.edge_per_lot)} valueClass={isNum(rec.edge_per_lot) && rec.edge_per_lot > 0 ? "up" : "down"} />
              <MiniStat label={<>POP · our view<Explain metric="pop" value={rec.view?.pop} symbol={adv.symbol} /></>} value={pct(rec.view?.pop, 1)} />
              <MiniStat label="POP · market-implied" value={pct(rec.market?.pop, 1)} />
              <MiniStat label="Max loss / lot" value={rec.unlimited_loss ? "unlimited" : inr(rec.max_loss_per_lot)} valueClass="down" />
              <MiniStat label="Max gain / lot" value={rec.unlimited_gain ? "unlimited" : inr(rec.max_gain_per_lot)} valueClass="up" />
              <MiniStat label="Reward : risk" value={isNum(rec.reward_risk) ? fixed(rec.reward_risk, 2) : "—"} />
            </div>
            {plan?.entry?.orders?.length ? (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Side</th><th className="r">Lots</th><th>Contract</th><th className="r">Limit</th></tr></thead>
                  <tbody>
                    {plan.entry.orders.map((o, i) => (
                      <tr key={i}><td><Badge tone={sideTone(o.side)}>{o.side}</Badge></td><td className="num">{o.lots}</td>
                        <td className="mono">{o.contract}</td><td className="num">{fixed(o.limit, 2)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            <dl className="kv">
              <dt>Entry zone</dt><dd>{plan?.entry?.zone?.length ? plan.entry.zone.map((z) => fixed(z, 2)).join(" – ") : "—"} ({plan?.entry?.type || "net"})</dd>
              <dt>Target</dt><dd>{isNum(plan?.target?.close_at_net_credit) ? `close at ${fixed(plan!.target!.close_at_net_credit, 2)}` : "—"}</dd>
              <dt>Stop</dt><dd>{isNum(plan?.stop?.close_at_net_credit) ? `close at ${fixed(plan!.stop!.close_at_net_credit, 2)}` : "—"}</dd>
            </dl>
            {status === "RECOMMEND" && <BasketButtons symbol={symbol} expiry={expiry} expiries={expiries} lotSize={lotSize} legs={rec.legs || []} />}
            <ul className="mk-rules">
              {plan?.target?.rule && <li><b>Target:</b> {plan.target.rule}</li>}
              {plan?.stop?.rule && <li><b>Stop:</b> {plan.stop.rule}</li>}
              {plan?.trailing && <li><b>Trailing:</b> {plan.trailing}</li>}
            </ul>
          </>
        )}

        {adv.reasoning?.length ? <ReasonList title="Reasoning" items={adv.reasoning} tone="up" empty="" /> : null}
        <div>
          <div className="row wrap" style={{ gap: 6, marginBottom: 6 }}>
            <span className="faint" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 0.5 }}>Market evidence</span>
            {ev?.lean && <Badge tone={sideTone(ev.lean)}>{ev.lean}</Badge>}
            {isNum(ev?.score) && <Badge>score {ev!.score}</Badge>}
            <Badge tone={ev?.validated ? "up" : "warn"}>{ev?.validated ? "validated" : "context only · not validated"}</Badge>
          </div>
          <ReasonList title="" items={ev?.notes || []} tone="warn" empty="No evidence notes" />
          {adv.direction_model && !adv.direction_model.validated && (
            <div className="faint" style={{ fontSize: 12.5, marginTop: 6 }}>Direction model not used: {adv.direction_model.reason || "not validated"}</div>
          )}
        </div>

        {adv.institutional && <InstContext inst={adv.institutional} />}

        {adv.strategies?.length ? (
          <details className="mk-details">
            <summary>All strategies compared ({adv.strategies.length}) · click a row for its payoff</summary>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Strategy</th><th className="r">Edge / lot</th><th className="r">POP view</th><th className="r">POP mkt</th>
                  <th className="r">Max loss</th><th className="r">R:R</th><th>Verdict</th></tr></thead>
                <tbody>
                  {adv.strategies.map((s, i) => {
                    const chosen = rec?.name === s.name;
                    return (
                      <tr key={i} className={`clickable ${picked === s.name ? "selected" : ""}`} onClick={() => s.name && onPick(s.name)}>
                        <td><b>{s.name}</b></td>
                        <td className={`num ${isNum(s.edge_per_lot) && s.edge_per_lot > 0 ? "up" : "down"}`}>{inr(s.edge_per_lot)}</td>
                        <td className="num">{pct(s.view?.pop, 1)}</td><td className="num">{pct(s.market?.pop, 1)}</td>
                        <td className="num">{s.unlimited_loss ? "unlimited" : inr(s.max_loss_per_lot)}</td>
                        <td className="num">{isNum(s.reward_risk) ? fixed(s.reward_risk, 2) : "—"}</td>
                        <td className="wrap-cell">{chosen ? <Badge tone="up">chosen</Badge> : s.rejected?.length ? <span className="faint">{s.rejected.join("; ")}</span> : <Badge>passed</Badge>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </details>
        ) : null}
      </div>
    </Card>
  );
}

function BasketButtons({ symbol, expiry, expiries, lotSize, legs }: {
  symbol: string; expiry: string; expiries: string[]; lotSize?: number; legs: { strike: number; type: "CE" | "PE"; side: "BUY" | "SELL"; lots: number; price?: number }[];
}) {
  const { toast } = useFeedback();
  const b = expiries.length ? buildBasket(symbol, expiry, expiries, lotSize, legs) : { error: "expiry list unavailable", orders: undefined };
  const copy = async (text: string, what: string) => {
    try { await navigator.clipboard.writeText(text); toast("up", `${what} copied`, "Verify every contract, quantity and price in your broker before placing."); }
    catch { toast("down", "Clipboard unavailable", "Your browser blocked clipboard access; open “Show basket JSON” and copy it from there."); }
  };
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row wrap" style={{ gap: 8 }}>
        <button className="btn sm" disabled={!b.orders} onClick={() => copy(JSON.stringify(b.orders, null, 2), "Basket JSON")}><Icon name="copy" size={14} />Copy basket</button>
        <button className="btn sm ghost" disabled={!b.orders} onClick={() => copy(basketText(b.orders!), "Basket text")}>Copy as text</button>
      </div>
      <div className="faint" style={{ fontSize: 12 }}>
        {b.error ? `Basket unavailable: ${b.error}.` : `${b.orders!.map((o) => o.tradingsymbol).join(", ")} · Kite-style JSON, ${b.orders![0].exchange} · NRML · LIMIT.`}
        {" "}<b className="warn">Verify in your broker before placing.</b> Nothing is sent from here.
      </div>
      {b.orders && (
        <details className="mk-details">
          <summary>Show basket JSON</summary>
          <textarea className="input mono" readOnly style={{ height: 140, padding: 8, fontSize: 12 }} value={JSON.stringify(b.orders, null, 2)}
            onFocus={(e) => e.currentTarget.select()} aria-label="Basket JSON" />
        </details>
      )}
    </div>
  );
}

function InstContext({ inst }: { inst: NonNullable<Advice["institutional"]> }) {
  const f = inst.fii_index_futures;
  return (
    <div>
      <div className="row wrap" style={{ gap: 6, marginBottom: 6 }}>
        <span className="faint" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 0.5 }}>Institutional context</span>
        <Badge tone={inst.validated ? "up" : "warn"}>{inst.validated ? "validated" : "context · not validated"}</Badge>
        {f && <span className="faint" style={{ fontSize: 12 }}>FII long {pct(f.long_pct, 2)}<Explain metric="fii_long_pct" value={f.long_pct} /></span>}
        {f?.prov && <ProvBadge prov={f.prov} label="FII" loading={false} />}
        {inst.futures?.prov && <ProvBadge prov={inst.futures.prov} label="futures" loading={false} />}
      </div>
      {inst.in_ban && <div className="alert down" style={{ marginBottom: 6 }}>In the F&O ban list for {inst.ban_trade_date || "today"}: no new positions allowed.</div>}
      {inst.event_risk ? <div className="alert warn" style={{ marginBottom: 6 }}>Event risk: {typeof inst.event_risk === "string" ? inst.event_risk : (inst.events || []).map((e) => `${e.purpose} ${e.date}`).join(", ") || "corporate event before expiry"}</div> : null}
      <ReasonList title="" items={inst.notes || []} tone="warn" empty="No institutional notes" />
      {inst.validation && <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>Validation: {inst.validation}</div>}
    </div>
  );
}

/** Underlying 15-minute chart with live OI walls, max pain and measured levels/patterns. */
function UnderlyingChart({ symbol }: { symbol: string }) {
  const [layers, setLayers] = useLocalStorage<Layers>("hm.fno.layers", DEFAULT_LAYERS);
  const bars = usePoll<{ bars?: Candle[]; prov?: import("./logic").Prov }>(`/api/markets/bars${qs({ symbol, market: "IN", interval: "15m", range: "5d" })}`, 60000);
  const intel = useChartIntel(symbol, "IN", "M15", layers);
  const candles = bars.data?.bars || [];
  return (
    <Card title={`${symbol} · 15m`} sub="Levels include live OI walls and max pain (context · not validated) plus swing/pivot levels with measured hold rates"
      actions={<ProvBadge prov={bars.data?.prov} label="bars" loading={!bars.data} />}>
      <div className="stack" style={{ gap: 8 }}>
        <LayerBar layers={layers} setLayers={setLayers} only={["levels", "vp", "patterns"]} />
        <ErrorNote error={bars.error} onRetry={bars.reload} />
        {candles.length ? <div className="mk-chart"><CandleChart candles={candles} levels={intel.lines} markers={intel.markers} tips={intel.tips} /></div>
          : !bars.loading && <Empty title="No bars available" />}
        {layers.levels && <LevelList lv={intel.lv} symbol={symbol} market="IN" />}
      </div>
    </Card>
  );
}
