import { usePoll } from "../../lib/hooks";
import { ago, fixed } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, Loading, Stat } from "../../components/ui";

interface GovernorAi {
  provider?: string | null; model?: string | null; enabled?: boolean; refreshing?: boolean;
  calls?: number; failures?: number; last_ok_at?: string | null; last_error?: string | null;
  last_error_at?: string | null; last_latency_ms?: number | null; backoff_until?: string | null;
}
interface Decision {
  ts: string; source: string; posture: string; risk_multiplier: number;
  paused?: string[] | null; throttled?: string[] | null; reasoning?: string | null;
}
interface Governor {
  source?: string | null; risk_posture?: string | null; risk_multiplier?: number | null;
  reasoning?: string | null; updated_at?: string | null; paused: string[]; throttled: string[];
  ai?: GovernorAi | null; activity: Decision[];
}
interface AiStatus { provider?: string | null; model?: string | null; available?: boolean; busy?: boolean; governor?: Governor }

const isAi = (source?: string | null) => source === "LLM";
const list = (xs?: string[] | null) => (xs && xs.length ? xs.join(", ") : "—");

/** What the AI (Gemini) is doing for the engine: the risk governor's live directive and recent decisions.
 *  The governor can only cut risk; an AI "pause" is shown as advisory, only the rule-based governor pauses. */
export function AiGovernor() {
  const st = usePoll<AiStatus>("/api/ai/status", 30000);
  const g = st.data?.governor;
  const ai = g?.ai;
  const backoff = ai?.backoff_until ? new Date(ai.backoff_until).getTime() > Date.now() : false;
  const health = !ai?.enabled ? { tone: "flat" as const, text: "AI off (rule-based)" }
    : backoff ? { tone: "warn" as const, text: "AI backing off" }
    : isAi(g?.source) ? { tone: "up" as const, text: "AI active" }
    : { tone: "accent" as const, text: "rule-based until next AI read" };

  return (
    <>
      <Card title="AI governor"
        sub={st.data?.provider ? `${st.data.provider} · ${st.data.model || "default model"} · reduce-only: it can lower risk, never raise it` : "No AI key configured: the governor runs on its rules"}
        actions={g && <Badge tone={health.tone} dot>{health.text}</Badge>}>
        <ErrorNote error={st.error} onRetry={st.reload} />
        {st.loading && !st.data ? <Loading /> : !g ? <Empty title="Governor state unavailable" /> : (
          <>
            <div className="grid cols-4">
              <Stat label="Directive from" value={isAi(g.source) ? "Gemini" : "Rules"} hint={g.updated_at ? `updated ${ago(g.updated_at)}` : undefined} />
              <Stat label="Risk posture" value={(g.risk_posture || "—").toLowerCase()} hint={g.risk_multiplier != null ? `${fixed(g.risk_multiplier, 2)}× risk per trade` : undefined}
                tone={g.risk_multiplier != null && g.risk_multiplier < 1 ? "warn" : undefined} />
              <Stat label="AI calls" value={`${ai?.calls ?? 0}`} hint={`${ai?.failures ?? 0} failed${ai?.last_latency_ms ? ` · last ${(ai.last_latency_ms / 1000).toFixed(1)}s` : ""}`}
                tone={ai?.failures ? "warn" : undefined} />
              <Stat label="Last AI answer" value={ai?.last_ok_at ? ago(ai.last_ok_at) : "never"}
                hint={backoff && ai?.backoff_until ? `retry after ${new Date(ai.backoff_until).toLocaleTimeString()}` : undefined} />
            </div>
            {g.reasoning && <p className="muted" style={{ marginTop: 12, fontSize: 13 }}>{g.reasoning}</p>}
            <div className="row wrap" style={{ gap: 16, marginTop: 8, fontSize: 13 }}>
              <span><b>Paused (rules):</b> <span className="muted">{list(g.paused)}</span></span>
              <span><b>Throttled / AI advisory:</b> <span className="muted">{list(g.throttled)}</span></span>
            </div>
            {ai?.last_error && (
              <p className="faint" style={{ marginTop: 8, fontSize: 12 }}>Last AI error {ai.last_error_at ? ago(ai.last_error_at) : ""}: {ai.last_error}</p>
            )}
          </>
        )}
      </Card>

      <Card title="Recent governor decisions" sub="Each change of posture, risk or symbol status, newest first" flush>
        {!g?.activity?.length ? <Empty title="No decisions recorded yet" /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>When</th><th>From</th><th>Posture</th><th className="r">Risk</th><th>Paused</th><th>Throttled</th><th>Why</th></tr></thead>
              <tbody>
                {g.activity.map((d, i) => (
                  <tr key={`${d.ts}-${i}`}>
                    <td className="muted" title={d.ts}>{ago(d.ts)}</td>
                    <td>{isAi(d.source) ? <Badge tone="accent">Gemini</Badge> : <Badge tone="flat">Rules</Badge>}</td>
                    <td>{(d.posture || "—").toLowerCase()}</td>
                    <td className="num">{fixed(d.risk_multiplier, 2)}×</td>
                    <td className="muted" style={{ whiteSpace: "normal", maxWidth: 200, fontSize: 12.5 }}>{list(d.paused)}</td>
                    <td className="muted" style={{ whiteSpace: "normal", maxWidth: 200, fontSize: 12.5 }}>{list(d.throttled)}</td>
                    <td className="muted" style={{ whiteSpace: "normal", maxWidth: 360, fontSize: 12.5 }}>{d.reasoning || "—"}</td>
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
