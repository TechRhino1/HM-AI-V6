import { usePoll } from "../../lib/hooks";
import { ago } from "../../lib/format";
import { useStore } from "../../state/store";
import { Badge, Card, ErrorNote, Loading } from "../../components/ui";
import { Icon } from "../../components/Icon";
import { ProvBadge } from "../../components/ProvBadge";
import type { Prov } from "../markets/logic";

interface Item { id: string; level: "danger" | "warn" | "info"; title: string; detail: string; route: string; symbol?: string }
interface Insights { items?: Item[]; headline?: string; provider?: string; risk_available?: boolean; prov?: Prov }
const TONE = { danger: "down", warn: "warn", info: "accent" } as const;

/** Ranked "what needs my attention" from live risk/exposure rules; the AI (when configured) only words the headline. */
export function Attention({ go }: { go: (r: string) => void }) {
  const res = usePoll<Insights>("/api/ai/insights", 60000);
  const { askAI, setSymbol } = useStore();
  const d = res.data;
  const items = d?.items || [];
  const open = (i: Item) => { if (i.symbol) setSymbol(i.symbol); go(i.route); };
  return (
    <Card title={<span className="row" style={{ gap: 8 }}><Icon name="activity" size={16} />Needs attention</span>}
      sub={d ? `${d.provider === "template" ? "Rule-based" : `Worded by AI (${d.provider})`} · updated ${ago(d.prov?.as_of)}` : "Live risk and exposure checks"}
      actions={<span className="row" style={{ gap: 6 }}><ProvBadge prov={d?.prov} loading={res.loading && !d} />
        {!!items.length && <button className="btn sm" onClick={() => askAI(`What should I do about these account warnings? ${items.map((i) => i.title).join("; ")}`)}>Ask AI</button>}</span>}>
      {res.error && !d ? <ErrorNote error={`Insights unavailable: ${res.error}`} onRetry={res.reload} /> : !d ? <Loading rows={2} /> : (
        <div className="stack" style={{ gap: 10 }}>
          <div className={`attn-head ${items[0] ? TONE[items[0].level] : "up"}`} role="status">{d.headline}</div>
          {!!items.length && (
            <div className="list">
              {items.map((i) => (
                <button key={i.id} type="button" className="list-item clickable attn-row" onClick={() => open(i)} title={`Open ${i.route}`}>
                  <Badge tone={TONE[i.level]} dot>{i.level === "danger" ? "Act" : i.level === "warn" ? "Watch" : "Info"}</Badge>
                  <span className="grow stack" style={{ gap: 2, minWidth: 0 }}><b>{i.title}</b><span className="faint" style={{ fontSize: 12.5 }}>{i.detail}</span></span>
                  <span className="faint" aria-hidden="true">›</span>
                </button>
              ))}
            </div>
          )}
          {d.risk_available === false && <div className="faint" style={{ fontSize: 12.5 }}>Risk status is unavailable, so limit checks were skipped.</div>}
        </div>
      )}
    </Card>
  );
}
