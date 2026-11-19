import { usePoll } from "../../lib/hooks";
import { num } from "../../lib/format";
import { useStore } from "../../state/store";
import { ProvBadge } from "../../components/ProvBadge";
import { Badge, Card, Empty, ErrorNote, Loading, sideTone } from "../../components/ui";
import type { Prov } from "../markets/logic";

// Shape of GET /api/intelligence/auto-style (jarvis/api/intelligence_api.py _get_auto_style).
export interface AutoRow {
  symbol: string; action: "TRADE" | "VETO" | "SKIP"; live: boolean; updated?: number;
  pick: { style?: string; strategy?: string; score?: number; n?: number; expectancy_r?: number; source?: string; bias?: string; reason?: string };
  news: { state: "CLEAR" | "CAUTION" | "BLOCK"; size_mult: number; blocked_directions: string[]; bias?: string; ai_used?: boolean;
    ai?: { bias: string; confidence: number; reason: string } | null; reasons: string[]; prov?: Prov };
}
export interface AutoResp { active: boolean; trade_style: string | null; live: boolean; orchestrator_attached: boolean; symbols: AutoRow[] }

type Tone = "up" | "down" | "warn" | "flat";
/** Display model for one row: what AUTO will do with the symbol and why, in plain words. */
export function autoRow(r: AutoRow) {
  const newsTone: Tone = r.news.state === "BLOCK" ? "down" : r.news.state === "CAUTION" ? "warn" : "up";
  const actionTone: Tone = r.action === "TRADE" ? "up" : r.action === "VETO" ? "down" : "flat";
  const actionLabel = r.action === "TRADE" ? (r.live ? "Trade" : "Would trade") : r.action === "VETO" ? "Vetoed by news" : "No pick";
  const style = r.pick.style ? r.pick.style.replace("_", " ").toLowerCase() : null;
  const record = r.pick.n ? `${r.pick.n} live trades, ${num(r.pick.expectancy_r ?? 0, 2)}R avg` : r.pick.style ? "backtest record only" : r.pick.reason ?? "";
  const size = r.news.size_mult < 1 && r.news.state !== "BLOCK" ? `${Math.round(r.news.size_mult * 100)}% size` : null;
  return { newsTone, actionTone, actionLabel, style, record, size, reason: r.news.reasons[0] ?? "" };
}

export function AutoPicks({ go }: { go: (r: string) => void }) {
  const res = usePoll<AutoResp>("/api/intelligence/auto-style", 30000);
  const { setSymbol } = useStore();
  const d = res.data;
  const sub = !d ? undefined : !d.active ? "Trade style is not Auto; switch it in System › Controls"
    : d.live ? "Live: only these picks can trade, at the shown size" : "Shadow: picks and news checks are logged; trading runs as All";

  return (
    <Card title="Auto picks" sub={sub} flush
      actions={d?.active ? <Badge tone={d.live ? "up" : "warn"} dot>{d.live ? "Live" : "Shadow — not trading"}</Badge> : undefined}>
      <ErrorNote error={res.error} onRetry={res.reload} />
      {res.loading && !d ? <Loading /> : !d?.symbols?.length ? (
        <Empty title={d?.active ? "Waiting for the next scan" : "Auto is off"} icon="radar">
          {d?.active ? "Picks appear after the engine finishes a sweep." : <button className="btn sm" onClick={() => go("system/controls")}>Open Controls</button>}
        </Empty>
      ) : (
        <div className="list">
          {d.symbols.map((r) => {
            const m = autoRow(r);
            return (
              <div key={r.symbol} className="list-item clickable" onClick={() => setSymbol(r.symbol)} title={r.news.reasons.join("\n")}>
                <b style={{ width: 80 }}>{r.symbol}</b>
                <Badge tone={m.actionTone}>{m.actionLabel}</Badge>
                {r.pick.bias && <Badge tone={sideTone(r.pick.bias)}>{r.pick.bias}</Badge>}
                <span className="stack" style={{ gap: 2, flex: 1, minWidth: 0 }}>
                  <span style={{ fontSize: 13 }}>{m.style ? <>{m.style} · {String(r.pick.strategy ?? "").replace(/_/g, " ").toLowerCase()}</> : <span className="faint">—</span>}</span>
                  <span className="faint" style={{ fontSize: 12 }}>{m.record}</span>
                </span>
                <span className="stack" style={{ gap: 2, alignItems: "flex-end", maxWidth: "45%" }}>
                  <span className="row" style={{ gap: 6 }}>
                    {r.news.ai_used && <Badge tone="accent">AI</Badge>}
                    {m.size && <span className="mono faint" style={{ fontSize: 12 }}>{m.size}</span>}
                    <Badge tone={m.newsTone} dot>News {r.news.state.toLowerCase()}</Badge>
                    <ProvBadge prov={r.news.prov} />
                  </span>
                  <span className="faint" style={{ fontSize: 12, textAlign: "right" }}>{m.reason}</span>
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
