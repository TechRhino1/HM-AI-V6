import { usePoll } from "../../lib/hooks";
import { dateTime, fixed, num, price } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, Loading, sideTone } from "../../components/ui";

interface Missed { symbol: string; direction: string; style: string; entry_price: number; current_price: number; sl: number; tp: number; gate: string; reason: string; protected_capital: boolean | null; timestamp: string }
type Profile = Record<string, any> & { symbol: string; asset_class: string };

/** Research: setups the gates refused (and whether that protected capital), and each symbol's tuned profile. */
export function Research() {
  const missed = usePoll<{ missed_trades: Missed[] }>("/api/intelligence/missed-trades", 120000);
  const profiles = usePoll<{ profiles: Record<string, Profile> }>("/api/intelligence/symbol-profiles", 0);
  const regime = usePoll<{ status: string; error?: string; [k: string]: unknown }>("/api/backtest/regime-policy", 0);

  return (
    <>
      <Card title="Refused setups" sub="Signals a gate blocked, and whether price then moved against them" flush>
        <ErrorNote error={missed.error} onRetry={missed.reload} />
        {missed.loading && !missed.data ? <Loading /> : missed.error && !missed.data ? null : !missed.data?.missed_trades?.length ? <Empty title="No refused setups recorded" /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>When</th><th>Symbol</th><th>Side</th><th>Style</th><th className="r">Entry</th><th className="r">Now</th><th>Blocked by</th><th>Outcome so far</th></tr></thead>
              <tbody>
                {missed.data.missed_trades.map((m, i) => (
                  <tr key={i}>
                    <td className="muted">{dateTime(m.timestamp)}</td>
                    <td><b>{m.symbol}</b></td>
                    <td><Badge tone={sideTone(m.direction)}>{m.direction}</Badge></td>
                    <td className="muted">{m.style.replace("_", " ").toLowerCase()}</td>
                    <td className="num">{price(m.entry_price)}</td>
                    <td className="num">{price(m.current_price)}</td>
                    <td className="muted" style={{ whiteSpace: "normal" }}>{m.reason}</td>
                    <td>{m.protected_capital === true ? <Badge tone="up">Refusal saved money</Badge>
                      : m.protected_capital === false ? <Badge tone="warn">Would be in profit</Badge> : <Badge>Unknown</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Symbol profiles" sub="Per-symbol stop, target and spread settings the engine uses" flush>
        <ErrorNote error={profiles.error} onRetry={profiles.reload} />
        {!profiles.data ? <Loading /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Symbol</th><th>Class</th><th className="r">SL × ATR</th><th className="r">Min R:R</th><th className="r">Partial at</th><th className="r">BE at</th><th className="r">Trail × ATR</th><th className="r">Typical / max spread</th><th>Banned strategies</th></tr></thead>
              <tbody>
                {Object.values(profiles.data.profiles).map((p) => (
                  <tr key={p.symbol}>
                    <td><b>{p.symbol}</b></td>
                    <td className="muted">{String(p.asset_class).toLowerCase()}</td>
                    <td className="num">{fixed(p.sl_atr_multiplier, 1)}</td>
                    <td className="num">{fixed(p.min_target_rr, 1)}</td>
                    <td className="num">{fixed(p.fast_cash_r, 1)}R</td>
                    <td className="num">{fixed(p.be_trigger_r, 1)}R</td>
                    <td className="num">{fixed(p.runner_trail_atr, 1)}</td>
                    <td className="num">{num(p.typical_spread_pips, 1)} / {num(p.max_allowed_spread_pips, 1)}</td>
                    <td className="faint" style={{ whiteSpace: "normal", fontSize: 12 }}>{(p.banned_strategies || []).map((s: string) => s.replace(/_/g, " ").toLowerCase()).join(", ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Regime policy" sub="Which regimes each style is allowed to trade (from the optimiser)">
        <ErrorNote error={regime.error} onRetry={regime.reload} />
        {!regime.data ? (regime.error ? null : <Loading />) : regime.data.status !== "OK"
          ? <Empty title="No regime policy report">{regime.data.error}</Empty>
          : <pre className="mono" style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap" }}>{JSON.stringify(regime.data, null, 2)}</pre>}
      </Card>
    </>
  );
}
