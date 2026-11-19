import { usePoll } from "../../lib/hooks";
import { fixed, num, pct, rMult, tone } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, Loading, Stat } from "../../components/ui";
import { useDeployment } from "./useDeployment";

interface ModelCal {
  brier_score: number; brier_benchmark: number; ece: number; calibration_status: string;
  calibration_bins: { bin: string; predicted: number; empirical: number; count: number }[];
  honest_base_rates: Record<string, { symbol: string; style: string; window_days: number; sample_size: number; measured_winrate: number; profit_factor: number; expectancy_r: number; break_even_wr: number }>;
}
interface Reliability { styles: { style: string; expectancy_r: number; trades: number; profit_factor: number; win_rate_pct: number; weight: number; source: string }[] }

/** Is the system allowed to trade (deployment gate), and can its probabilities be trusted (model calibration)? */
export function Calibration() {
  const dep = useDeployment();
  const cal = usePoll<ModelCal>("/api/intelligence/calibration", 300000);
  const rel = usePoll<Reliability>("/api/intelligence/reliability", 300000);
  const rows = dep.data?.symbols || [];
  const passing = rows.filter((r) => !r.refusal).length;

  return (
    <>
      <Card title="Live deployment gate"
        sub={dep.data ? `A symbol may trade only with out-of-sample expectancy ≥ ${rMult(dep.data.min_oos_expectancy_r)} over ≥ ${dep.data.min_oos_trades} trades` : undefined}
        actions={dep.data && <Badge tone={passing ? "up" : "down"} dot>{passing} of {rows.length} cleared</Badge>} flush>
        <ErrorNote error={dep.error} onRetry={dep.reload} />
        {dep.loading && !dep.data ? <Loading /> : !rows.length ? <Empty title="No calibrated profiles" /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Symbol</th><th>Status</th><th>Exit geometry</th><th className="r">Target</th><th className="r">OOS trades</th><th className="r">OOS win rate</th><th className="r">OOS expectancy</th><th className="r">OOS PF</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.symbol}>
                    <td><b>{r.symbol}</b></td>
                    <td style={{ whiteSpace: "normal", maxWidth: 320 }}>
                      {r.refusal ? <span title={r.refusal}><Badge tone="down">Blocked</Badge> <span className="faint" style={{ fontSize: 12 }}>{r.refusal.replace(/^[A-Z_]+:\s*/, "")}</span></span> : <Badge tone="up">Cleared</Badge>}
                    </td>
                    <td className="muted">{r.geometry_mode || "—"}</td>
                    <td className="num">{r.tp_r ? `${fixed(r.tp_r, 1)}R` : "—"}</td>
                    <td className="num">{num(r.oos_trades, 0)}</td>
                    <td className="num">{r.oos_win_rate !== undefined ? pct(r.oos_win_rate * 100, 1) : "—"}</td>
                    <td className={`num ${tone(r.oos_expectancy_r)}`}>{rMult(r.oos_expectancy_r)}</td>
                    <td className="num">{fixed(r.oos_profit_factor, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <ErrorNote error={cal.error} onRetry={cal.reload} />
      {cal.data && (
        <div className="grid cols-4">
          <Stat label="Probability calibration" value={cal.data.calibration_status.replace(/_/g, " ").toLowerCase()} />
          <Stat label="Brier score" value={fixed(cal.data.brier_score, 3)} hint={`Benchmark ${fixed(cal.data.brier_benchmark, 3)} · lower is better`}
            tone={cal.data.brier_score < cal.data.brier_benchmark ? "up" : "down"} />
          <Stat label="Expected calibration error" value={pct(cal.data.ece * 100, 1)} />
          <Stat label="Samples" value={num(cal.data.calibration_bins.reduce((a, b) => a + b.count, 0), 0)} />
        </div>
      )}

      <div className="grid cols-2">
        <Card title="Predicted vs actual win rate" sub="Each bar pair is one probability bucket" flush>
          {!cal.data ? <Loading /> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Bucket</th><th className="r">Predicted</th><th className="r">Actual</th><th>Gap</th><th className="r">n</th></tr></thead>
                <tbody>
                  {cal.data.calibration_bins.map((b) => {
                    const gap = (b.empirical - b.predicted) * 100;
                    return (
                      <tr key={b.bin}>
                        <td className="muted">{b.bin}</td>
                        <td className="num">{pct(b.predicted * 100, 0)}</td>
                        <td className="num">{pct(b.empirical * 100, 0)}</td>
                        <td style={{ width: 140 }}><div className="meter"><i style={{ width: `${Math.min(100, Math.abs(gap) * 4)}%`, background: Math.abs(gap) < 5 ? "var(--up)" : "var(--warn)" }} /></div></td>
                        <td className="num">{b.count}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card title="Honest base rates" sub="Measured win rate of every signal, before any filtering" flush>
          {!cal.data ? <Loading /> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Symbol</th><th className="r">Sample</th><th className="r">Win rate</th><th className="r">Break-even</th><th className="r">PF</th><th className="r">Expectancy</th></tr></thead>
                <tbody>
                  {Object.values(cal.data.honest_base_rates).map((b) => (
                    <tr key={b.symbol}>
                      <td><b>{b.symbol}</b><div className="faint" style={{ fontSize: 11.5 }}>{b.style} · {b.window_days}d</div></td>
                      <td className="num">{num(b.sample_size, 0)}</td>
                      <td className={`num ${b.measured_winrate >= b.break_even_wr ? "up" : "down"}`}>{pct(b.measured_winrate, 1)}</td>
                      <td className="num">{pct(b.break_even_wr, 0)}</td>
                      <td className="num">{fixed(b.profit_factor, 2)}</td>
                      <td className={`num ${tone(b.expectancy_r)}`}>{rMult(b.expectancy_r)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <Card title="Style reliability" sub="Backtested expectancy per trade style, used to weight AI consensus votes" flush>
        <ErrorNote error={rel.error} onRetry={rel.reload} />
        {!rel.data ? <Loading /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Style</th><th className="r">Trades</th><th className="r">Win rate</th><th className="r">PF</th><th className="r">Expectancy</th><th className="r">Vote weight</th><th>Source</th></tr></thead>
              <tbody>
                {rel.data.styles.map((s) => (
                  <tr key={s.style}>
                    <td><b>{s.style.replace("_", " ").toLowerCase()}</b></td>
                    <td className="num">{num(s.trades, 0)}</td>
                    <td className="num">{pct(s.win_rate_pct, 1)}</td>
                    <td className="num">{fixed(s.profit_factor, 2)}</td>
                    <td className={`num ${tone(s.expectancy_r)}`}>{rMult(s.expectancy_r)}</td>
                    <td className="num">{pct(s.weight * 100, 0)}</td>
                    <td className="faint">{s.source}</td>
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
