import { Fragment, useState } from "react";
import { usePoll } from "../../lib/hooks";
import { ago } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, Loading, Seg, Stat } from "../../components/ui";

interface GateStep { gate: string; verdict: string; reason?: string; value?: unknown; threshold?: unknown; ms?: number }
interface Attempt { ts: string; symbol: string; style: string; bias: string; origin: string; blocked_by: string | null;
  status?: string | null; gates?: GateStep[] }
interface Stats { window_hours: number; attempts: number; sent: number; blocked_by: Record<string, number>;
  shadow_rejects: Record<string, number> }

const VERDICT_TONE: Record<string, "up" | "down" | "warn" | "flat" | "accent"> = {
  PASS: "up", REJECT: "down", SCALE: "accent", SKIP: "flat", SHADOW_REJECT: "warn",
};
const WINDOWS = [{ value: "6", label: "6h" }, { value: "24", label: "24h" }, { value: "168", label: "7d" }];

function Bars({ counts, tone }: { counts: Record<string, number>; tone: "down" | "warn" }) {
  const rows = Object.entries(counts);
  const max = Math.max(1, ...rows.map(([, n]) => n));
  if (!rows.length) return <Empty title="Nothing recorded in this window" />;
  return (
    <div>
      {rows.map(([gate, n]) => (
        <div key={gate} style={{ display: "grid", gridTemplateColumns: "minmax(110px, 34%) 1fr 44px", gap: 8, alignItems: "center", margin: "4px 0" }}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={gate}>{gate}</span>
          <span style={{ height: 10, borderRadius: 5, width: `${(n / max) * 100}%`, background: `var(--${tone})` }} />
          <span className="num">{n}</span>
        </div>
      ))}
    </div>
  );
}

/** Gate analytics: which gate decides order attempts, and a browsable trace of each attempt's gate path. */
export function Gates() {
  const [hours, setHours] = useState("24");
  const [open, setOpen] = useState<number | null>(null);
  const stats = usePoll<Stats>(`/api/gates/stats?hours=${hours}`, 30000);
  const dec = usePoll<{ rows: Attempt[] }>(`/api/decisions?hours=${hours}&limit=100`, 30000);
  const s = stats.data;

  return (
    <>
      <Card title="Gate analytics" sub="Order attempts on the live dispatch path, the forward tests and manual orders"
        actions={<Seg value={hours} onChange={setHours} options={WINDOWS} />}>
        <ErrorNote error={stats.error} onRetry={stats.reload} />
        {stats.loading && !s ? <Loading /> : !s ? <Empty title="Gate statistics unavailable" /> : (
          <>
            <div className="grid cols-3">
              <Stat label="Attempts journaled" value={`${s.attempts}`} hint="one row per changed verdict" />
              <Stat label="Orders sent" value={`${s.sent}`} tone={s.sent ? undefined : "warn"} />
              <Stat label="Top blocker" value={Object.keys(s.blocked_by)[0] || "—"} />
            </div>
            <h4>Blocked by</h4>
            <Bars counts={s.blocked_by} tone="down" />
            <h4>Would block (shadow mode)</h4>
            <Bars counts={s.shadow_rejects} tone="warn" />
          </>
        )}
      </Card>

      <Card title="Decision trace" sub="Newest first. Open a row to see every gate it passed through, in order.">
        <ErrorNote error={dec.error} onRetry={dec.reload} />
        {!dec.data?.rows?.length ? <Empty title="No attempts in this window" /> : (
          <table className="table">
            <thead><tr><th>When</th><th>Attempt</th><th>Origin</th><th>Outcome</th></tr></thead>
            <tbody>
              {dec.data.rows.map((r, i) => (
                <Fragment key={`${r.ts}-${i}`}>
                  <tr onClick={() => setOpen(open === i ? null : i)} style={{ cursor: "pointer" }}
                    aria-expanded={open === i}>
                    <td>{ago(r.ts)}</td>
                    <td>{r.symbol} {r.style} {r.bias}</td>
                    <td>{r.origin}</td>
                    <td>{r.blocked_by ? <Badge tone="down">{r.blocked_by}</Badge> : <Badge tone="up">{(r.status || "sent").toLowerCase()}</Badge>}</td>
                  </tr>
                  {open === i && (
                    <tr><td colSpan={4}>
                      {(r.gates || []).map((g, j) => (
                        <div key={j} style={{ margin: "2px 0" }}>
                          <Badge tone={VERDICT_TONE[g.verdict] || "flat"}>{g.verdict.toLowerCase()}</Badge>{" "}
                          <b>{g.gate}</b>{g.reason ? ` — ${g.reason}` : ""}
                          {g.value != null ? ` (value ${String(g.value)}${g.threshold != null ? ` vs ${String(g.threshold)}` : ""})` : ""}
                        </div>
                      ))}
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
