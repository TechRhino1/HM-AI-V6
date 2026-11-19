import { useStore } from "../../state/store";
import { useDeployment } from "../analytics/useDeployment";
import { fixed, pct, price } from "../../lib/format";
import { Badge, Card, Empty, sideTone } from "../../components/ui";
import { MiniStat } from "../overview/Overview";

/** What the engine currently thinks about the selected symbol, and whether it is allowed to act on it. */
export function EngineView({ go }: { go: (r: string) => void }) {
  const { symbol, telemetry, symbols, setDraft } = useStore();
  const d = telemetry?.latest_decisions?.[symbol];
  const spec = symbols.find((s) => s.symbol === symbol);
  const deploy = useDeployment();
  const gate = deploy.data?.symbols?.find((r) => r.symbol === symbol);

  if (!d) return <Card title="Engine view"><Empty title={`No engine decision for ${symbol}`}>The engine has not scanned this symbol yet, or it is not enabled.</Empty></Card>;

  const reasons: string[] = [...(d.rejection_reasons || []), ...(d.waiting_reasons || [])];
  const dec = String(d.decision || "—");
  const side = String(d.bias || "").toUpperCase();
  const canLoad = (side === "BUY" || side === "SELL") && d.entry_price > 0;

  return (
    <Card title="Engine view" sub={`${String(d.strategy || "").replace(/_/g, " ").toLowerCase()} · ${String(d.trade_style || "").replace("_", " ").toLowerCase()} · ${d.timestamp || ""}`}
      actions={
        <>
          <Badge tone={dec === "EXECUTE" ? "up" : dec === "WAIT" ? "warn" : "flat"}>{dec}</Badge>
          <button className="btn sm" disabled={!canLoad}
            onClick={() => setDraft({ symbol, side: side as "BUY" | "SELL", entry: d.entry_price, sl: d.stop_loss, tp: d.take_profit, source: "engine plan" })}>
            Load plan into ticket
          </button>
          <button className="btn sm ghost" onClick={() => go(`signals/inspect/${symbol}`)}>Full analysis</button>
        </>
      }>
      <div className="stack" style={{ gap: 14 }}>
        {gate?.refusal && (
          <div className="alert warn"><b>Live deployment gate:</b>&nbsp;{gate.refusal}</div>
        )}
        <div className="grid cols-4" style={{ gap: 10 }}>
          <MiniStat label="Bias" value={side || "—"} valueClass={sideTone(side)} />
          <MiniStat label="Win probability" value={pct((d.model_confidence ?? 0) * 100, 0)} />
          <MiniStat label="Reward : risk" value={`${fixed(d.risk_reward_ratio, 2)} : 1`} />
          <MiniStat label="Confluence" value={`${d.master_confluence_score ?? "—"} · ${String(d.master_confluence_tier || "").toLowerCase()}`} />
        </div>
        {d.entry_price > 0 && (
          <div className="grid cols-4" style={{ gap: 10 }}>
            <MiniStat label="Entry" value={price(d.entry_price, spec?.digits)} />
            <MiniStat label="Stop" value={price(d.stop_loss, spec?.digits)} valueClass="down" />
            <MiniStat label="Target" value={price(d.take_profit, spec?.digits)} valueClass="up" />
            <MiniStat label="Regime" value={String(d.regime?.primary || d.regime || "—").replace(/_/g, " ").toLowerCase()} />
          </div>
        )}
        {d.honest_base_rate?.win_rate !== undefined && (
          <div className="faint" style={{ fontSize: 12.5 }}>
            Honest base rate ({d.honest_base_rate.symbol}, {d.honest_base_rate.window_days}d, n={d.honest_base_rate.n}):
            win {pct(d.honest_base_rate.win_rate * 100, 1)}, PF {fixed(d.honest_base_rate.profit_factor, 2)}
          </div>
        )}
        <div className="grid cols-2" style={{ gap: 14 }}>
          <ReasonList title="Why it is not trading" items={reasons} tone="down" empty="Nothing is blocking this setup." />
          <ReasonList title="Risk factors" items={d.risk_factors || []} tone="warn" empty="No risk factors flagged." />
          <ReasonList title="Bull case" items={d.bull_case || []} tone="up" empty="—" />
          <ReasonList title="Bear case" items={d.bear_case || []} tone="down" empty="—" />
        </div>
      </div>
    </Card>
  );
}

export function ReasonList({ title, items, tone, empty }: { title: string; items: string[]; tone: "up" | "down" | "warn"; empty: string }) {
  return (
    <div>
      <div className="faint" style={{ fontSize: 12, marginBottom: 6, textTransform: "uppercase", letterSpacing: 0.5 }}>{title}</div>
      {items.length ? (
        <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4, fontSize: 13 }}>
          {items.map((r, i) => <li key={i} className={tone === "warn" ? "" : ""} style={{ color: "var(--text-2)" }}>{r}</li>)}
        </ul>
      ) : <div className="faint" style={{ fontSize: 13 }}>{empty}</div>}
    </div>
  );
}
