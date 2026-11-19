import { useMemo, useState } from "react";
import { useStore } from "../../state/store";
import { api } from "../../lib/api";
import { usePoll } from "../../lib/hooks";
import { useFeedback } from "../../components/feedback";
import { fixed, num, pct, price } from "../../lib/format";
import { STYLES, type Opportunity } from "../../lib/types";
import { Badge, Card, Empty, ErrorNote, Loading, Modal, Seg, sideTone } from "../../components/ui";
import { ReasonList } from "../trade/EngineView";
import { useDeployment } from "../analytics/useDeployment";
import { MiniStat } from "../overview/Overview";

type Sort = "priority" | "win" | "rr" | "symbol";
const ORDER = ["SCALP", "DAY_TRADING", "SWING", "H4_SWING", "D1_SWING"];
const styleLabel = (s: string) => STYLES.find((x) => x.value === s)?.label || s.replace("_", " ").toLowerCase();

/** Signals: the scanner (every symbol × style the engine evaluated) and the AI consensus across styles. */
export default function Signals({ sub, go }: { sub: string; go: (r: string) => void }) {
  const [tab, inspectSym] = sub.startsWith("inspect/") ? ["scanner", sub.slice(8)] : [sub || "scanner", ""];
  return (
    <>
      <Seg value={tab} onChange={(v) => go(`signals/${v}`)} options={[{ value: "scanner", label: "Scanner" }, { value: "consensus", label: "AI consensus" }]} />
      {tab === "consensus" ? <Consensus go={go} /> : <Scanner inspectSym={inspectSym} go={go} />}
    </>
  );
}

function Scanner({ inspectSym, go }: { inspectSym: string; go: (r: string) => void }) {
  const { telemetry } = useStore();
  const [style, setStyle] = useState<string>("ALL");
  const [actionable, setActionable] = useState(false);
  const [sort, setSort] = useState<Sort>("priority");
  const [open, setOpen] = useState<Opportunity | null>(null);
  const rows = telemetry?.radar_opportunities || [];
  const styles = useMemo(() => [...new Set(rows.map((r) => r.trade_style))].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b)), [rows]);

  const list = useMemo(() => {
    const f = rows.filter((r) => (style === "ALL" || r.trade_style === style) && (!actionable || r.is_actionable || r.decision === "EXECUTE"));
    const key: Record<Sort, (r: Opportunity) => number | string> = {
      priority: (r) => -((r as any).dynamic_priority_score ?? r.score ?? 0),
      win: (r) => -(r.win_prob ?? 0), rr: (r) => -(r.risk_reward_ratio ?? 0), symbol: (r) => r.symbol,
    };
    return [...f].sort((a, b) => (key[sort](a) < key[sort](b) ? -1 : key[sort](a) > key[sort](b) ? 1 : 0));
  }, [rows, style, actionable, sort]);

  // Deep link from Trade › Engine view: open the first opportunity of that symbol.
  const deep = inspectSym ? rows.find((r) => r.symbol === inspectSym) : undefined;
  const shown = open || deep || null;

  return (
    <Card title="Scanner" sub={`${rows.length} setups evaluated · updates with each engine scan`} flush
      actions={
        <div className="row wrap" style={{ gap: 6 }}>
          {["ALL", ...styles].map((s) => (
            <button key={s} className={`chip ${style === s ? "on" : ""}`} onClick={() => setStyle(s)}>{s === "ALL" ? "All" : styleLabel(s)}</button>
          ))}
          <button className={`chip ${actionable ? "on" : ""}`} onClick={() => setActionable(!actionable)}>Actionable only</button>
          <select className="select" style={{ width: 150, height: 30 }} value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort">
            <option value="priority">Sort: priority</option><option value="win">Sort: win prob</option>
            <option value="rr">Sort: reward:risk</option><option value="symbol">Sort: symbol</option>
          </select>
        </div>
      }>
      {!telemetry ? <Loading /> : !list.length ? <Empty title="No setups match" icon="radar" /> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Symbol</th><th>Style</th><th>Signal</th><th>Grade</th><th className="r">Win prob</th><th className="r">R:R</th><th className="r">EV</th><th>Regime</th><th>Status</th></tr></thead>
            <tbody>
              {list.map((r, i) => (
                <tr key={`${r.symbol}-${r.trade_style}-${i}`} className="clickable" onClick={() => setOpen(r)}>
                  <td><b>{r.symbol}</b><div className="faint" style={{ fontSize: 11.5 }}>{r.timeframe}</div></td>
                  <td className="muted">{r.trade_style.replace("_", " ").toLowerCase()}</td>
                  <td><Badge tone={sideTone(r.bias)}>{r.status_label || r.action}</Badge></td>
                  <td>{r.setup_grade?.replace("GRADE ", "") || "—"}</td>
                  <td className="num">{pct(r.win_prob, 0)}</td>
                  <td className="num">{fixed(r.risk_reward_ratio, 2)}</td>
                  <td className="num">{fixed(r.ev, 2)}</td>
                  <td className="muted">{String(r.regime || "").replace(/_/g, " ").toLowerCase()}</td>
                  <td>{r.gate_passed ? <Badge tone="up">Gate passed</Badge> : <span className="faint" style={{ fontSize: 12 }}>{((r.failing_reasons || [])[0] || (r.waiting_reasons || [])[0] || "—").slice(0, 42)}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {shown && <Inspector o={shown} onClose={() => { setOpen(null); if (inspectSym) go("signals/scanner"); }} go={go} />}
    </Card>
  );
}

function Inspector({ o, onClose, go }: { o: Opportunity; onClose: () => void; go: (r: string) => void }) {
  const { setDraft, symbols } = useStore();
  const deploy = useDeployment();
  const gate = deploy.data?.symbols?.find((r) => r.symbol === o.symbol);
  const digits = symbols.find((s) => s.symbol === o.symbol)?.digits;
  const checks = Object.entries(o.checks || {});
  const failed = checks.filter(([, v]) => !v);
  const side = String(o.bias).toUpperCase();

  return (
    <Modal drawer title={<span className="row">{o.symbol} · {o.trade_style.replace("_", " ").toLowerCase()} <Badge tone={sideTone(side)}>{o.status_label}</Badge></span>}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Close</button>
          <button className="btn primary" disabled={side !== "BUY" && side !== "SELL"}
            onClick={() => { setDraft({ symbol: o.symbol, side: side as "BUY" | "SELL", entry: o.entry_price, sl: o.stop_loss, tp: o.take_profit, source: `${o.trade_style.toLowerCase()} scanner` }); go("trade"); }}>
            Load into ticket
          </button>
        </>
      }>
      {gate?.refusal ? <div className="alert warn"><b>Deployment gate:</b>&nbsp;{gate.refusal}</div>
        : gate ? <div className="alert up">Deployment gate passed for {o.symbol}.</div> : null}
      <div className="grid cols-3" style={{ gap: 10 }}>
        <MiniStat label="Entry" value={price(o.entry_price, digits)} />
        <MiniStat label="Stop" value={price(o.stop_loss, digits)} valueClass="down" />
        <MiniStat label="Target" value={price(o.take_profit, digits)} valueClass="up" />
        <MiniStat label="Win prob" value={pct(o.win_prob, 0)} />
        <MiniStat label="Reward : risk" value={fixed(o.risk_reward_ratio, 2)} />
        <MiniStat label="Devil penalty" value={num(o.adversarial_penalty, 0)} />
      </div>
      {o.mtf_alignment && (
        <div className="row wrap" style={{ gap: 6 }}>
          {Object.entries(o.mtf_alignment).map(([tf, b]) => <Badge key={tf} tone={sideTone(b)}>{tf} {String(b).toLowerCase()}</Badge>)}
        </div>
      )}
      <ReasonList title="Failing" items={o.failing_reasons || []} tone="down" empty="Nothing failing." />
      <ReasonList title="Waiting for" items={o.waiting_reasons || []} tone="warn" empty="Not waiting on anything." />
      <ReasonList title="Risk factors" items={o.risk_factors || []} tone="warn" empty="None flagged." />
      <ReasonList title="Invalidation" items={(o.invalidation_levels || []).map(String)} tone="down" empty="—" />
      <div>
        <div className="faint" style={{ fontSize: 12, marginBottom: 8, textTransform: "uppercase", letterSpacing: 0.5 }}>
          Quality gate · {checks.length - failed.length}/{checks.length} checks pass
        </div>
        <div className="check-grid">
          {[...failed, ...checks.filter(([, v]) => v)].map(([k, v]) => (
            <div key={k}><span className={`dot ${v ? "up" : "down"}`} /><span className={v ? "muted" : ""}>{k}</span></div>
          ))}
        </div>
      </div>
    </Modal>
  );
}

interface Vote { trade_style: string; bias: string; win_prob: number; setup_grade: string; expected_value: number; reliability: number }
interface ConsensusRow {
  symbol: string; direction: string; consensus_score: number; confidence_tier: string; is_tradeable: boolean; rationale: string; votes: Vote[];
}

function Consensus({ go }: { go: (r: string) => void }) {
  const res = usePoll<{ status: string; decisions: ConsensusRow[]; universe?: Record<string, number> }>("/api/intelligence/auto-selection", 60000);
  const { run } = useFeedback();
  const { setDraft, telemetry } = useStore();
  const [open, setOpen] = useState<string | null>(null);

  const rescan = () => run(() => api.post("/api/action/auto-select", {}), { success: "Consensus refreshed" }).then(res.reload);

  return (
    <Card title="AI consensus" sub={res.data ? `Every style votes per symbol · ${res.data.universe?.scanned_pairs ?? "—"} pairs scanned · preview only, never places orders` : undefined}
      actions={<button className="btn sm" onClick={rescan}>Rescan now</button>} flush>
      <ErrorNote error={res.error} onRetry={res.reload} />
      {res.loading && !res.data ? <Loading /> : !res.data?.decisions?.length ? <Empty title="No consensus yet" icon="radar" /> : (
        <div className="list">
          {res.data.decisions.map((d) => {
            const plan = telemetry?.radar_opportunities?.find((r) => r.symbol === d.symbol && String(r.bias).toUpperCase() === d.direction);
            return (
              <div key={d.symbol}>
                <div className="list-item clickable" onClick={() => setOpen(open === d.symbol ? null : d.symbol)} aria-expanded={open === d.symbol}>
                  <b style={{ width: 80 }}>{d.symbol}</b>
                  <Badge tone={sideTone(d.direction)}>{d.direction}</Badge>
                  <div className="grow stack" style={{ gap: 4 }}>
                    <div className="faint" style={{ fontSize: 12.5, whiteSpace: "normal" }}>{d.rationale}</div>
                    <div className="meter"><i style={{ width: `${Math.min(100, d.consensus_score)}%` }} /></div>
                  </div>
                  <Badge tone={d.confidence_tier === "HIGH" ? "up" : d.confidence_tier === "MEDIUM" ? "warn" : "flat"}>{d.confidence_tier.toLowerCase()}</Badge>
                  <span className="mono" style={{ width: 40, textAlign: "right" }}>{num(d.consensus_score, 0)}</span>
                </div>
                {open === d.symbol && (
                  <div style={{ padding: "0 14px 14px", background: "var(--surface-2)" }}>
                    <div className="table-wrap">
                      <table className="table">
                        <thead><tr><th>Style</th><th>Vote</th><th>Grade</th><th className="r">Win prob</th><th className="r">EV</th><th className="r">Reliability</th></tr></thead>
                        <tbody>
                          {d.votes.map((v) => (
                            <tr key={v.trade_style}>
                              <td>{v.trade_style.replace("_", " ").toLowerCase()}</td>
                              <td><Badge tone={sideTone(v.bias)}>{v.bias}</Badge></td>
                              <td>{v.setup_grade?.replace("GRADE ", "") || "—"}</td>
                              <td className="num">{pct(v.win_prob, 0)}</td>
                              <td className="num">{fixed(v.expected_value, 2)}</td>
                              <td className="num">{pct(v.reliability * 100, 0)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="row" style={{ justifyContent: "flex-end", paddingTop: 10 }}>
                      <button className="btn sm primary" disabled={!plan}
                        title={plan ? "Load the matching scanner plan" : "No scanner plan in this direction"}
                        onClick={() => { if (plan) { setDraft({ symbol: d.symbol, side: d.direction as "BUY" | "SELL", entry: plan.entry_price, sl: plan.stop_loss, tp: plan.take_profit, source: "AI consensus" }); go("trade"); } }}>
                        Load into ticket
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
