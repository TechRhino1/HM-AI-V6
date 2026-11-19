import { useEffect, useMemo, useState } from "react";
import { useStore } from "../../state/store";
import { api } from "../../lib/api";
import { useFeedback } from "../../components/feedback";
import { isNum, money, pct, price } from "../../lib/format";
import { Card, Field, Seg } from "../../components/ui";
import { riskPreview, sizeForRisk } from "./risk";

type Kind = "MARKET" | "LIMIT" | "STOP";
const QUICK_LOTS = [0.01, 0.05, 0.1, 0.5, 1];

const n = (s: string) => {
  const v = parseFloat(s);
  return Number.isFinite(v) ? v : 0;
};

/** One order ticket: market or pending, with the money at risk shown before you send. */
export function OrderTicket() {
  const { symbol, setSymbol, symbols, telemetry, draft, setDraft, refresh } = useStore();
  const { run, toast } = useFeedback();
  const spec = symbols.find((s) => s.symbol === symbol);
  const acc = telemetry?.account;
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [kind, setKind] = useState<Kind>("MARKET");
  const [lots, setLots] = useState("0.01");
  // Price levels belong to one symbol; switching symbol shows a blank set instead of stale levels.
  const [lv, setLv] = useState({ sym: "", entry: "", sl: "", tp: "", source: "manual" });
  const cur = lv.sym === symbol ? lv : { sym: symbol, entry: "", sl: "", tp: "", source: "manual" };
  const { entry, sl, tp, source } = cur;
  const setLevel = (k: "entry" | "sl" | "tp", v: string) => setLv({ ...cur, [k]: v });
  const [riskPct, setRiskPct] = useState("0.5");
  const [busy, setBusy] = useState(false);

  // "Load into ticket" from anywhere in the app.
  useEffect(() => {
    if (!draft) return;
    if (draft.side) setSide(draft.side);
    setKind("MARKET");
    setLv({ sym: draft.symbol, entry: draft.entry ? String(draft.entry) : "", sl: draft.sl ? String(draft.sl) : "",
      tp: draft.tp ? String(draft.tp) : "", source: draft.source || "plan" });
    if (draft.symbol !== symbol) setSymbol(draft.symbol);
    setDraft(null);
  }, [draft, symbol, setSymbol, setDraft]);

  const live = spec ? (side === "BUY" ? spec.ask : spec.bid) : 0;
  const refEntry = kind === "MARKET" ? live : n(entry);
  const preview = useMemo(() => riskPreview({
    side, entry: refEntry, sl: n(sl), tp: n(tp), lots: n(lots), tickSize: spec?.tick_size, tickValue: spec?.tick_value, equity: acc?.equity,
  }), [side, refEntry, sl, tp, lots, spec, acc?.equity]);

  const sizeIt = () => {
    const v = sizeForRisk({ entry: refEntry, sl: n(sl), riskMoney: ((acc?.equity || 0) * n(riskPct)) / 100,
      tickSize: spec?.tick_size, tickValue: spec?.tick_value, step: spec?.volume_step, min: spec?.volume_min, max: spec?.volume_max });
    if (v.ok) setLots(String(v.lots));
    else if (v.reason === "below_min")
      toast("down", "Stop too wide for this risk", `Even the minimum ${v.minLots} lot risks ${money(v.minLotRisk, acc?.currency)} (${pct(acc?.equity ? (v.minLotRisk / acc.equity) * 100 : undefined, 2)} of equity). Tighten the stop or skip the trade.`);
  };

  const pendingType = `${side}_${kind}`;
  const invalid =
    n(lots) <= 0 ? "Enter a volume"
      : kind !== "MARKET" && n(entry) <= 0 ? "A pending order needs a price"
        : kind !== "MARKET" && n(sl) <= 0 ? "A pending order needs a stop-loss"
          : preview.slWrongSide ? "Stop-loss is on the wrong side of the entry"
            : preview.tpWrongSide ? "Take-profit is on the wrong side of the entry"
              : null;

  const submit = async () => {
    setBusy(true);
    const isLive = telemetry?.execution_mode === "LIVE";
    const what = kind === "MARKET" ? `${side} ${lots} ${symbol} at market` : `${pendingType.replace("_", " ")} ${lots} ${symbol} @ ${entry}`;
    await run(
      () => kind === "MARKET"
        ? api.post("/api/action/manual_trade", { symbol, side, volume: n(lots), price: live || undefined, sl: n(sl) || 0, tp: n(tp) || 0 })
        : api.post("/api/action/place_pending_order", { symbol, order_type: pendingType, price: n(entry), volume: n(lots), sl: n(sl), tp: n(tp) || undefined }),
      {
        success: kind === "MARKET" ? "Order sent" : "Pending order placed",
        confirm: {
          title: isLive ? "Send a LIVE order?" : "Send order?",
          danger: isLive,
          confirmLabel: side === "BUY" ? "Buy" : "Sell",
          body: (
            <div className="stack">
              <div><b>{what}</b></div>
              <div>Stop {sl || "set by the engine"} · Target {tp || "set by the engine"}</div>
              {isNum(preview.riskMoney) && <div>Risk {money(preview.riskMoney, acc?.currency)} ({pct(preview.riskPct, 2)} of equity)</div>}
              <div className="faint">Account mode: {telemetry?.execution_mode || "—"}</div>
            </div>
          ),
        },
      },
    );
    setBusy(false);
    refresh();
  };

  return (
    <Card title="Order ticket" sub={source === "manual" ? "Manual entry" : `Prefilled from ${source}`}>
      <div className="stack" style={{ gap: 14 }}>
        <Field label="Symbol">
          <select className="select" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {symbols.map((s) => <option key={s.symbol} value={s.symbol}>{s.symbol}</option>)}
            {!symbols.some((s) => s.symbol === symbol) && <option value={symbol}>{symbol}</option>}
          </select>
        </Field>
        <div className="grid cols-2" style={{ gap: 8 }}>
          <button className={`btn lg ${side === "BUY" ? "buy" : ""}`} onClick={() => setSide("BUY")} aria-pressed={side === "BUY"}>
            Buy <span className="mono" style={{ fontSize: 12 }}>{spec?.ask ? price(spec.ask, spec.digits) : ""}</span>
          </button>
          <button className={`btn lg ${side === "SELL" ? "sell" : ""}`} onClick={() => setSide("SELL")} aria-pressed={side === "SELL"}>
            Sell <span className="mono" style={{ fontSize: 12 }}>{spec?.bid ? price(spec.bid, spec.digits) : ""}</span>
          </button>
        </div>
        <Seg full value={kind} onChange={setKind} options={[{ value: "MARKET", label: "Market" }, { value: "LIMIT", label: "Limit" }, { value: "STOP", label: "Stop" }]} />
        {kind !== "MARKET" && (
          <Field label={`${kind === "LIMIT" ? "Limit" : "Stop"} price`}>
            <input className="input mono" inputMode="decimal" value={entry} onChange={(e) => setLevel("entry", e.target.value)} placeholder={live ? price(live, spec?.digits) : ""} />
          </Field>
        )}
        <div className="grid cols-2" style={{ gap: 8 }}>
          <Field label="Stop-loss">
            <input className="input mono" inputMode="decimal" value={sl} onChange={(e) => setLevel("sl", e.target.value)} placeholder={kind === "MARKET" ? "Engine sets" : "Required"} />
          </Field>
          <Field label="Take-profit">
            <input className="input mono" inputMode="decimal" value={tp} onChange={(e) => setLevel("tp", e.target.value)} placeholder={kind === "MARKET" ? "Engine sets" : "Optional"} />
          </Field>
        </div>
        <Field label="Volume (lots)">
          <input className="input mono" inputMode="decimal" value={lots} onChange={(e) => setLots(e.target.value)} />
        </Field>
        <div className="row wrap" style={{ gap: 6 }}>
          {QUICK_LOTS.map((v) => <button key={v} className={`chip ${n(lots) === v ? "on" : ""}`} onClick={() => setLots(String(v))}>{v}</button>)}
        </div>
        <div className="row" style={{ gap: 8 }}>
          <Field label="Size by risk % of equity">
            <input className="input mono" inputMode="decimal" value={riskPct} onChange={(e) => setRiskPct(e.target.value)} />
          </Field>
          <button className="btn" style={{ alignSelf: "end" }} onClick={sizeIt} disabled={!n(sl) || !refEntry || !spec?.tick_value}
            title={!n(sl) ? "Set a stop-loss first" : "Compute lots from the risk %"}>Size</button>
        </div>

        <div style={{ background: "var(--surface-2)", borderRadius: 10, padding: 12 }} className="stack">
          <div className="row between"><span className="faint">Money at risk</span>
            <b className={`mono ${isNum(preview.riskMoney) ? "down" : "faint"}`}>{isNum(preview.riskMoney) ? `${money(preview.riskMoney, acc?.currency)} · ${pct(preview.riskPct, 2)}` : n(sl) ? "—" : "Set a stop to see it"}</b></div>
          <div className="row between"><span className="faint">Potential reward</span>
            <b className="mono up">{isNum(preview.rewardMoney) ? money(preview.rewardMoney, acc?.currency) : "—"}</b></div>
          <div className="row between"><span className="faint">Reward : risk</span>
            <b className="mono">{isNum(preview.rr) ? `${preview.rr.toFixed(2)} : 1` : "—"}</b></div>
          {spec?.tick_value === undefined && <div className="faint" style={{ fontSize: 12 }}>Contract data not available for this symbol.</div>}
        </div>

        {invalid && <div className="faint" style={{ fontSize: 12.5 }}>{invalid}</div>}
        <button className={`btn lg block ${side === "BUY" ? "buy" : "sell"}`} disabled={!!invalid || busy} onClick={submit}>
          {busy ? "Sending…" : kind === "MARKET" ? `${side === "BUY" ? "Buy" : "Sell"} ${lots} at market` : `Place ${side.toLowerCase()} ${kind.toLowerCase()}`}
        </button>
      </div>
    </Card>
  );
}
