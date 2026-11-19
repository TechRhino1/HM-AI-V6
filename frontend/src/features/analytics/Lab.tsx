import { useState } from "react";
import { api } from "../../lib/api";
import { usePoll } from "../../lib/hooks";
import { useStore } from "../../state/store";
import { useFeedback } from "../../components/feedback";
import { dateTime, fixed, num } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, Field, Loading } from "../../components/ui";

interface Meta { styles: string[]; objectives: string[]; defaults: Record<string, number | string> }
interface Job { id: string; label: string; status: string; created_utc: string; finished_utc?: string; progress: string[]; error?: string; has_result: boolean; spec: Record<string, unknown> }

const statusTone = (s: string) => (s === "DONE" ? "up" : s === "FAILED" ? "down" : s === "RUNNING" || s === "QUEUED" ? "warn" : "flat");

/** Backtest lab: run the exit-geometry optimiser and read the walk-forward verdict per style. */
export function Lab() {
  const { symbols } = useStore();
  const { run } = useFeedback();
  const meta = usePoll<Meta>("/api/backtest/meta", 0);
  const jobs = usePoll<{ jobs: Job[] }>("/api/backtest/jobs", 5000);
  const [label, setLabel] = useState("");
  const [objective, setObjective] = useState("");
  const [modes, setModes] = useState<string[]>([]);
  const [syms, setSyms] = useState<string[]>([]);
  const [minTrades, setMinTrades] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const d = meta.data?.defaults || {};

  const toggle = (list: string[], set: (v: string[]) => void, v: string) => set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  const start = async () => {
    const r = await run(() => api.post<{ job_id: string }>("/api/backtest/run", {
      label: label || `run ${new Date().toLocaleString()}`,
      objective: objective || d.objective,
      modes: modes.length ? modes : undefined,
      symbols: syms.length ? syms : undefined,
      min_trades: minTrades ? Number(minTrades) : d.min_trades,
      max_dd_r: d.max_dd_r, passes: d.passes, max_evaluations: d.max_evaluations, walk_forward_split: d.walk_forward_split,
    }), { success: "Backtest queued" });
    if (r?.job_id) setSelected(r.job_id);
    jobs.reload();
  };

  const list = jobs.data?.jobs || [];
  const current = list.find((j) => j.id === selected) || list[0];

  return (
    <div className="grid cols-2" style={{ alignItems: "start" }}>
      <Card title="New optimiser run" sub="Walk-forward search over exit geometry on cached history">
        <ErrorNote error={meta.error} onRetry={meta.reload} />
        {!meta.data ? <Loading /> : (
          <div className="stack" style={{ gap: 14 }}>
            <Field label="Label"><input className="input" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. crypto swing retest" /></Field>
            <Field label="Objective">
              <select className="select" value={objective || String(d.objective)} onChange={(e) => setObjective(e.target.value)}>
                {meta.data.objectives.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
              </select>
            </Field>
            <Field label="Styles (none = all)">
              <div className="row wrap" style={{ gap: 6 }}>
                {meta.data.styles.map((s) => <button key={s} className={`chip ${modes.includes(s) ? "on" : ""}`} onClick={() => toggle(modes, setModes, s)}>{s.replace("_", " ").toLowerCase()}</button>)}
              </div>
            </Field>
            <Field label="Symbols (none = all enabled)">
              <div className="row wrap" style={{ gap: 6 }}>
                {symbols.filter((s) => s.is_enabled).map((s) => <button key={s.symbol} className={`chip ${syms.includes(s.symbol) ? "on" : ""}`} onClick={() => toggle(syms, setSyms, s.symbol)}>{s.symbol}</button>)}
              </div>
            </Field>
            <Field label={`Minimum trades (default ${d.min_trades})`}><input className="input mono" inputMode="numeric" value={minTrades} onChange={(e) => setMinTrades(e.target.value)} /></Field>
            <div className="faint" style={{ fontSize: 12.5 }}>
              Defaults: {d.days} days · {d.passes} passes · ≤{d.max_evaluations} evaluations · {fixed(Number(d.walk_forward_split) * 100, 0)}% train · slippage {d.slippage_pips} pips · commission {d.commission_per_lot}/lot
            </div>
            <button className="btn primary" onClick={start}>Start run</button>
          </div>
        )}
      </Card>

      <div className="stack" style={{ gap: 18 }}>
        <Card title="Runs" flush>
          <ErrorNote error={jobs.error} onRetry={jobs.reload} />
          {!list.length ? <Empty title="No runs yet" icon="flask" /> : (
            <div className="list">
              {list.map((j) => (
                <div key={j.id} className={`list-item clickable ${current?.id === j.id ? "selected" : ""}`} onClick={() => setSelected(j.id)}>
                  <div className="grow"><b>{j.label || j.id}</b><div className="faint" style={{ fontSize: 12 }}>{dateTime(j.created_utc)}</div></div>
                  <Badge tone={statusTone(j.status)}>{j.status.toLowerCase()}</Badge>
                </div>
              ))}
            </div>
          )}
        </Card>
        {current && <JobDetail job={current} onChange={jobs.reload} />}
      </div>
    </div>
  );
}

function JobDetail({ job, onChange }: { job: Job; onChange: () => void }) {
  const { run } = useFeedback();
  const result = usePoll<{ job: { result: any } }>(job.has_result ? `/api/backtest/jobs/${job.id}/result` : null, 0);
  const p: any = result.data;
  const report = [p?.report, p?.result, p?.job?.result, p?.job?.report, p?.job, p].find((c) => c && typeof c === "object" && c.modes) || null;
  const modes: any[] = report?.modes || [];
  const active = job.status === "RUNNING" || job.status === "QUEUED";

  return (
    <Card title={job.label || job.id} sub={job.status.toLowerCase()}
      actions={active && <button className="btn sm danger" onClick={() => run(() => api.post("/api/backtest/cancel", { job_id: job.id }), { success: "Cancel requested" }).then(onChange)}>Cancel</button>}>
      <div className="stack">
        <ErrorNote error={result.error} onRetry={result.reload} />
        {job.error && <div className="alert down">{job.error}</div>}
        {modes.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Style</th><th className="r">IS trades</th><th className="r">IS exp</th><th className="r">OOS trades</th><th className="r">OOS exp</th><th>Verdict</th></tr></thead>
              <tbody>
                {modes.map((m) => {
                  const verdict = m.feasible && m.walk_forward?.generalises ? ["generalises", "up"] : m.feasible ? ["in-sample only", "warn"] : ["no feasible geometry", "down"];
                  return (
                    <tr key={m.style}>
                      <td><b>{m.style}</b></td>
                      <td className="num">{num(m.in_sample?.trades, 0)}</td>
                      <td className="num">{fixed(m.in_sample?.expectancy_r, 3)}</td>
                      <td className="num">{num(m.out_of_sample?.trades, 0)}</td>
                      <td className="num">{fixed(m.out_of_sample?.expectancy_r, 3)}</td>
                      <td><Badge tone={verdict[1] as any}>{verdict[0]}</Badge></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {job.has_result && !modes.length && result.data && <div className="faint">The run finished without a per-style report. See the log below.</div>}
        <pre className="mono" style={{ margin: 0, fontSize: 11.5, maxHeight: 260, overflow: "auto", background: "var(--bg-2)", padding: 10, borderRadius: 8, whiteSpace: "pre-wrap" }}>
          {job.progress.join("\n") || "Waiting for output…"}
        </pre>
      </div>
    </Card>
  );
}
