import { usePoll } from "../../lib/hooks";
import { ago, fixed } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, KV, Loading } from "../../components/ui";

type Level = "OK" | "WARN" | "CRITICAL";
interface Check { status: Level; value?: number | null; threshold?: number | number[] | null; detail: string }
interface Advisory { ts: string; recommendations: { area: string; finding: string; recommendation: string; priority: string }[] }
interface MonitorResp {
  monitor: { status?: Level; checked_at?: string; checks?: Record<string, Check> };
  advisory?: Advisory | null;
  config: { verifier: Record<string, unknown>; gates: Record<string, unknown>; forward_tests: Record<string, unknown> };
}
interface VerifierRow { ts: string; symbol: string; side: string; origin: string; outcome: string; ms: number; mode: string;
  reasons: { rule: string; ok: boolean; detail?: string }[] }

const TONE: Record<Level, "up" | "warn" | "down"> = { OK: "up", WARN: "warn", CRITICAL: "down" };
const LABEL: Record<string, string> = {
  loop_heartbeat: "Orchestration loop", no_trade: "Order flow", rejection_spike: "Rejection rate",
  analyst_fallbacks: "Analyst fallbacks", verifier_health: "Pre-send verifier", forward_test_exposure: "Forward-test exposure",
};
const OUTCOME_TONE: Record<string, "up" | "warn" | "down" | "flat"> = {
  APPROVED: "up", REJECTED: "warn", NEEDS_ANALYSIS: "flat", BLOCKED_RISK: "down",
};

/** System health: the watchdog's monitor checks, the pre-send verifier's latest verdicts and the AI advisory. */
export function Health() {
  const mon = usePoll<MonitorResp>("/api/monitor", 15000);
  const ver = usePoll<{ mode: string; rows: VerifierRow[] }>("/api/verifier/recent?limit=25", 15000);
  const m = mon.data?.monitor;
  const checks = Object.entries(m?.checks || {});

  return (
    <>
      <Card title="System health" sub={m?.checked_at ? `checked ${ago(m.checked_at)} · refreshed every minute by the watchdog` : "waiting for the first watchdog pass"}
        actions={m?.status && <Badge tone={TONE[m.status]} dot>{m.status.toLowerCase()}</Badge>}>
        <ErrorNote error={mon.error} onRetry={mon.reload} />
        {mon.loading && !mon.data ? <Loading /> : !checks.length ? <Empty title="No monitor result yet" /> : (
          <table className="table">
            <thead><tr><th>Check</th><th>Status</th><th>Value</th><th>Detail</th></tr></thead>
            <tbody>
              {checks.map(([name, c]) => (
                <tr key={name}>
                  <td>{LABEL[name] || name}</td>
                  <td><Badge tone={TONE[c.status]}>{c.status.toLowerCase()}</Badge></td>
                  <td className="num">{c.value == null ? "—" : fixed(c.value, 2)}</td>
                  <td>{c.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Pre-send verifier" sub={`mode: ${ver.data?.mode || "—"} · shadow records verdicts without blocking; enforce blocks anything not approved`}>
        <ErrorNote error={ver.error} onRetry={ver.reload} />
        {!ver.data?.rows?.length ? <Empty title="No orders verified yet" /> : (
          <table className="table">
            <thead><tr><th>When</th><th>Order</th><th>Origin</th><th>Verdict</th><th>Failed rules</th><th className="num">ms</th></tr></thead>
            <tbody>
              {ver.data.rows.map((r, i) => (
                <tr key={i}>
                  <td>{ago(r.ts)}</td>
                  <td>{r.symbol} {r.side}</td>
                  <td>{r.origin}</td>
                  <td><Badge tone={OUTCOME_TONE[r.outcome] || "flat"}>{r.outcome.toLowerCase().replace("_", " ")}</Badge></td>
                  <td>{r.reasons.filter((x) => !x.ok).map((x) => `${x.rule}: ${x.detail ?? ""}`).join("; ") || "—"}</td>
                  <td className="num">{fixed(r.ms, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="AI operations advisory" sub="Hourly review of the checks and gate statistics. Recommendations only: nothing here changes trading.">
        {!mon.data?.advisory?.recommendations?.length ? <Empty title="No advisory yet" /> : (
          <ul>
            {mon.data.advisory.recommendations.map((r, i) => (
              <li key={i}><Badge tone={r.priority === "HIGH" ? "down" : r.priority === "MEDIUM" ? "warn" : "flat"}>{r.priority.toLowerCase()}</Badge>{" "}
                <b>{r.area}:</b> {r.finding} — {r.recommendation}</li>
            ))}
          </ul>
        )}
      </Card>

      {mon.data?.config && (
        <Card title="Rollout switches" sub="config/settings.json · gates / verifier / forward_tests">
          <KV items={[
            ["Verifier mode", String(mon.data.config.verifier.mode)],
            ["Verifier budget", `${mon.data.config.verifier.budget_ms} ms`],
            ["R:R single-source floor", String(mon.data.config.gates.rr_floor_mode)],
            ["Promotion-hole fix", String(mon.data.config.gates.promotion_hole_mode)],
            ["Elite bypass", mon.data.config.gates.elite_bypass_enabled ? "enabled" : "disabled"],
            ["Forward tests gated", mon.data.config.forward_tests.gated ? "yes" : "no"],
          ]} />
        </Card>
      )}
    </>
  );
}
