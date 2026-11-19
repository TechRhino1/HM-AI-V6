import { useState } from "react";
import { usePoll } from "../../lib/hooks";
import { fixed, isNum, pct, price, rMult } from "../../lib/format";
import { useStore } from "../../state/store";
import { Badge, Card, Empty, sideTone } from "../../components/ui";
import { ProvBadge } from "../../components/ProvBadge";
import { Explain } from "../../components/Explain";
import { DEFS } from "../../components/ChartIntel";
import type { Prov } from "../markets/logic";

export interface ThreatStat { flag: string; n: number; win_rate_delta: number; mean_r_delta: number; t_stat?: number | null }
export interface Signal {
  engine: null | {
    decision: string; side: string; strategy: string; entry: number; stop_loss: number; take_profit: number; risk_reward: number;
    win_prob: number | null; regime: string | null; regime_confidence: number | null; checks: Record<string, boolean>;
    failing: string[]; not_evaluated: string[]; rejection_reasons: string[]; waiting_reasons: string[]; gate_chips: string[];
    mtf: Record<string, string>; mtf_confluence: number | null; timestamp: string;
    devil: { penalty: number | null; threshold: number | null; threats: string[]; gate_passed: boolean | null;
      calibrated_loss_prob: number | null; calibration_group: string | null; threat_stats: ThreatStat[] };
  };
  positions: { ticket: number; side: string; volume: number; open_price: number; current_price: number; sl: number | null; tp: number | null;
    profit: number; live_r: number | null; to_sl: number | null; to_tp: number | null }[];
  adverse_flags: { flag: string; detail: string; prov?: Prov }[];
  prov?: Prov;
}

export const useSignal = (symbol: string) => usePoll<Signal>(`/api/markets/chart/signal?symbol=${encodeURIComponent(symbol)}`, 10000);

/** Live trading indication: the engine's current signal, every gate, the devil's advocate breakdown, adverse flags, open-position R. */
export function SignalPanel() {
  const { symbol, symbols } = useStore();
  const digits = symbols.find((s) => s.symbol === symbol)?.digits;
  const sig = useSignal(symbol);
  const [allGates, setAllGates] = useState(false);
  const e = sig.data?.engine;
  const dv = e?.devil;
  const checks = Object.entries(e?.checks || {});
  const failed = checks.filter(([, ok]) => !ok);
  const passed = checks.filter(([, ok]) => ok);
  const statFor = (t: string) => dv?.threat_stats.find((s) => t.toLowerCase().includes(s.flag.replace(/_/g, " ")));

  return (
    <Card title="Live trading indication" sub={e ? `${symbol} · ${e.timestamp}` : symbol}
      actions={<>{e && <Badge tone={e.decision === "EXECUTE" ? "up" : e.decision === "WAIT" ? "warn" : "flat"}>{e.decision} {e.side}</Badge>}<ProvBadge prov={sig.data?.prov} loading={!sig.data} /></>}>
      {!sig.data ? <div className="faint">Loading…</div> : !e && !sig.data.positions.length ? (
        <Empty title={`No engine signal for ${symbol}`}>The engine has no decision for this symbol yet.</Empty>
      ) : (
        <div className="stack" style={{ gap: 12 }}>
          {e && (
            <>
              <div className="row wrap" style={{ gap: 6 }}>
                {e.gate_chips.length ? e.gate_chips.map((c) => <span key={c} className="badge down">{c}</span>) : <span className="badge up">All evaluated gates pass</span>}
              </div>
              {e.entry > 0 && (
                <div className="kv-inline mono">
                  <span className={sideTone(e.side)}>{e.side}</span> entry {price(e.entry, digits)} · SL <span className="down">{price(e.stop_loss, digits)}</span> · TP <span className="up">{price(e.take_profit, digits)}</span> · {fixed(e.risk_reward, 2)}R
                </div>
              )}
              <div>
                <div className="sec-title">Gates · {failed.length} failing / {checks.length}{e.not_evaluated.length ? ` · ${e.not_evaluated.length} not evaluated` : ""}
                  <button className="link-btn" onClick={() => setAllGates(!allGates)}>{allGates ? "hide passing" : "show all"}</button></div>
                <div className="row wrap" style={{ gap: 4 }}>
                  {failed.map(([g]) => <span key={g} className="badge down">✕ {g}</span>)}
                  {allGates && passed.map(([g]) => <span key={g} className="badge up">✓ {g}</span>)}
                  {allGates && e.not_evaluated.map((g) => <span key={g} className="badge">– {g}</span>)}
                </div>
                {[...e.rejection_reasons, ...e.waiting_reasons].length > 0 && (
                  <ul className="reason-list">{[...e.rejection_reasons, ...e.waiting_reasons].slice(0, 6).map((r, i) => <li key={i}>{r}</li>)}</ul>
                )}
              </div>
              {dv && (
                <div>
                  <div className="sec-title">Devil's advocate</div>
                  <div className="row wrap" style={{ gap: 12, fontSize: 13 }}>
                    <span>Penalty<Explain metric="devil_penalty" value={dv.penalty} fallback={DEFS.devil_penalty} />{" "}
                      <b className={dv.gate_passed === false ? "down" : ""}>{isNum(dv.penalty) ? fixed(dv.penalty, 0) : "—"}</b>
                      {isNum(dv.threshold) && <span className="faint"> / limit {fixed(dv.threshold, 0)}</span>}</span>
                    <span>Calibrated loss prob<Explain metric="calibrated_loss_prob" value={dv.calibrated_loss_prob} fallback={DEFS.calibrated_loss_prob} />{" "}
                      <b>{isNum(dv.calibrated_loss_prob) ? pct(dv.calibrated_loss_prob * 100, 0) : <span className="faint">not published</span>}</b></span>
                    <span>Gate {dv.gate_passed === false ? <b className="down">blocks</b> : dv.gate_passed ? <b className="up">passes</b> : "—"}</span>
                  </div>
                  {dv.threats.length > 0 && (
                    <ul className="reason-list">{dv.threats.map((t, i) => {
                      const s = statFor(t);
                      return <li key={i}>{t}{s && <span className="faint mono"> · hist n={s.n}, win {s.win_rate_delta >= 0 ? "+" : ""}{fixed(s.win_rate_delta * 100, 1)} pts, {s.mean_r_delta >= 0 ? "+" : ""}{fixed(s.mean_r_delta, 2)}R</span>}</li>;
                    })}</ul>
                  )}
                  {dv.threat_stats.length > 0 && (
                    <div className="faint mono" style={{ fontSize: 11.5, marginTop: 4 }}>
                      Per-flag history{dv.calibration_group ? ` (${dv.calibration_group})` : ""}: {dv.threat_stats.map((s) => `${s.flag.replace(/_/g, " ")} n=${s.n} ${s.win_rate_delta >= 0 ? "+" : ""}${fixed(s.win_rate_delta * 100, 1)}pts`).join(" · ")}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
          <div>
            <div className="sec-title">Institutional adverse flags</div>
            {sig.data.adverse_flags.length ? (
              <ul className="reason-list">{sig.data.adverse_flags.map((f) => <li key={f.flag}>{f.detail} {f.prov && <ProvBadge prov={f.prov} loading={false} />}</li>)}</ul>
            ) : <div className="faint" style={{ fontSize: 12.5 }}>{e && (e.side === "BUY" || e.side === "SELL") ? "None against this side (context · not validated)." : "No directional signal to check."}</div>}
          </div>
          {sig.data.positions.length > 0 && (
            <div>
              <div className="sec-title">Open positions · live R<Explain metric="live_r" fallback={DEFS.live_r} /></div>
              {sig.data.positions.map((p) => (
                <div key={p.ticket} className="level-row mono">
                  <span className={sideTone(p.side)}>{p.side} {p.volume}</span>
                  <span>@ {price(p.open_price, digits)}</span>
                  <b className={isNum(p.live_r) ? (p.live_r >= 0 ? "up" : "down") : ""}>{rMult(p.live_r)}</b>
                  <span className="faint grow">to SL {price(p.to_sl, digits)} · to TP {price(p.to_tp, digits)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
