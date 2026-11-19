import { usePoll } from "../../lib/hooks";
import { ago, num } from "../../lib/format";
import { Badge, Card, Empty, ErrorNote, Loading } from "../../components/ui";

interface Status {
  sessions?: Record<string, { open?: boolean; status?: string; trade_date?: string; message?: string; source?: string }>;
  sources?: { source: string; ok: boolean; detail?: string; latency_ms?: number }[];
  recorder?: { running?: boolean; last?: Record<string, number> };
}

/** What market data is reachable right now: sessions, each upstream source, the chain recorder. */
export function Sources() {
  const s = usePoll<Status>("/api/markets/status", 30000);
  const d = s.data;
  return (
    <>
      <ErrorNote error={s.error} onRetry={s.reload} />
      {s.loading && !d ? <Loading rows={6} /> : (
        <>
          <div className="grid cols-2">
            {Object.entries(d?.sessions || {}).map(([k, v]) => (
              <Card key={k} title={k === "IN" ? "India session (NSE/BSE)" : k === "US" ? "US session (NYSE/Nasdaq)" : k}
                actions={<Badge tone={v.open ? "up" : undefined} dot>{v.status || (v.open ? "Open" : "Closed")}</Badge>}>
                <div className="muted">{v.message || ""} {v.trade_date ? `· ${v.trade_date}` : ""}</div>
                <div className="faint" style={{ fontSize: 12 }}>source: {v.source || "—"}</div>
              </Card>
            ))}
          </div>
          <Card title="Data sources" sub="Checked live every 30 s" flush>
            {!d?.sources?.length ? <Empty title="No sources reported" /> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Source</th><th>Status</th><th className="r">Latency</th><th>Detail</th></tr></thead>
                <tbody>{d.sources.map((x) => (
                  <tr key={x.source}><td><b>{x.source}</b></td>
                    <td><Badge tone={x.ok ? "up" : "down"} dot>{x.ok ? "reachable" : "down"}</Badge></td>
                    <td className="num">{x.latency_ms ? `${num(x.latency_ms, 0)} ms` : x.ok ? "cached" : "—"}</td>
                    <td className="faint wrap-cell">{x.detail || ""}</td></tr>
                ))}</tbody>
              </table></div>
            )}
          </Card>
          <Card title="Chain recorder" sub="Snapshots option chains every few minutes in market hours (feeds OI shift, IV history, the track record)"
            actions={<Badge tone={d?.recorder?.running ? "up" : "warn"} dot>{d?.recorder?.running ? "running" : "stopped"}</Badge>} flush>
            {!Object.keys(d?.recorder?.last || {}).length ? <Empty title="Nothing recorded yet" /> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Underlying / job</th><th>Last snapshot</th></tr></thead>
                <tbody>{Object.entries(d!.recorder!.last!).map(([k, t]) => <tr key={k}><td><b>{k}</b></td><td>{ago(t)}</td></tr>)}</tbody>
              </table></div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
