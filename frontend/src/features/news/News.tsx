import { useMemo, useState } from "react";
import { api } from "../../lib/api";
import { usePoll } from "../../lib/hooks";
import { useStore } from "../../state/store";
import { useFeedback } from "../../components/feedback";
import { cleanSymbol, duration, parseTime } from "../../lib/format";
import { useInterval } from "../../lib/hooks";
import { Badge, Card, Empty, ErrorNote, Loading, Seg } from "../../components/ui";

interface CalEvent {
  time: string; time_utc: string; currency: string; impact: string; event: string; forecast: string; previous: string; actual: string;
  shock_risk?: string; shock_alert?: string; timestamp_iso?: string; is_live: boolean; is_upcoming: boolean; is_past: boolean; status_badge?: string; time_quality?: string;
}
interface Headline { id: string; title: string; source: string; category: string; age_str: string; link: string; summary: string; sentiment: string; urgency: string; affected_assets?: string[] }
interface NewsPayload { calendar: CalEvent[]; headlines: Headline[]; at_risk_positions: any[]; imminent_event: CalEvent | null; source: string }

const IMPACTS = ["HIGH", "MEDIUM", "LOW"];
const impactTone = (i: string) => (i === "HIGH" ? "down" : i === "MEDIUM" ? "warn" : "flat");
const sentTone = (s: string) => (s === "BULLISH" ? "up" : s === "BEARISH" ? "down" : "flat");
/** EURUSD → [EUR, USD]; XAUUSD → [XAU, USD]. Index and oil CFDs map to their quote currency. */
const currenciesOf = (sym: string) => {
  const s = cleanSymbol(sym);
  const idx: Record<string, string> = { US30: "USD", NAS100: "USD", US500: "USD", GER40: "EUR", UK100: "GBP", WTI: "USD", OILCASH: "USD" };
  return idx[s] ? [idx[s]] : s.length >= 6 ? [s.slice(0, 3), s.slice(3, 6)] : [s];
};

export default function News({ sub, go }: { sub: string; go: (r: string) => void }) {
  const tab = sub === "headlines" ? "headlines" : "calendar";
  const res = usePoll<NewsPayload>("/api/news", 120000);
  const { run } = useFeedback();
  const refresh = () => run(() => api.post("/api/news/refresh", {}), { success: "News feeds refreshing" }).then(res.reload);
  const d = res.data;
  // Tick locally: the payload's status_badge is frozen at fetch time (polled every 2 min).
  const [, tick] = useState(0);
  useInterval(() => tick((t) => t + 1), 1000);
  const evAt = parseTime(d?.imminent_event?.timestamp_iso);
  const evIn = evAt ? (evAt.getTime() - Date.now()) / 1000 : undefined;

  return (
    <>
      <div className="row between wrap">
        <Seg value={tab} onChange={(v) => go(`news/${v}`)} options={[{ value: "calendar", label: "Economic calendar" }, { value: "headlines", label: "Headlines" }]} />
        <button className="btn sm" onClick={refresh}>Refresh feeds</button>
      </div>
      <ErrorNote error={res.error} onRetry={res.reload} />
      {d?.imminent_event && (
        <div className="alert warn"><b>{d.imminent_event.currency} {d.imminent_event.event}</b>&nbsp;· {evIn === undefined ? d.imminent_event.status_badge || d.imminent_event.time : evIn > 0 ? `in ${duration(evIn)}` : "now"}
          {d.imminent_event.shock_alert && <span className="faint">&nbsp;· {d.imminent_event.shock_alert}</span>}</div>
      )}
      {!!d?.at_risk_positions?.length && (
        <div className="alert down"><b>{d.at_risk_positions.length} open position(s) exposed to upcoming events:</b>&nbsp;
          {d.at_risk_positions.map((p: any) => cleanSymbol(p?.symbol || p)).join(", ")}</div>
      )}
      {res.loading && !d ? <Loading rows={6} /> : !d ? null : tab === "calendar" ? <Calendar events={d.calendar || []} source={d.source || ""} /> : <Headlines items={d.headlines || []} />}
    </>
  );
}

function Calendar({ events, source }: { events: CalEvent[]; source: string }) {
  const { telemetry } = useStore();
  const [impacts, setImpacts] = useState<string[]>(["HIGH", "MEDIUM"]);
  const [mine, setMine] = useState(false);
  const [showPast, setShowPast] = useState(false);
  const held = useMemo(() => new Set((telemetry?.positions || []).flatMap((p) => currenciesOf(p.symbol))), [telemetry?.positions]);

  const list = events.filter((e) => impacts.includes(e.impact) && (showPast || !e.is_past) && (!mine || held.has(e.currency)));

  return (
    <Card title="Economic calendar" sub={`Source: ${source.replace(/_/g, " ")} · times in UTC`} flush
      actions={
        <div className="row wrap" style={{ gap: 6 }}>
          {IMPACTS.map((i) => (
            <button key={i} className={`chip ${impacts.includes(i) ? "on" : ""}`}
              onClick={() => setImpacts(impacts.includes(i) ? impacts.filter((x) => x !== i) : [...impacts, i])}>{i.toLowerCase()}</button>
          ))}
          <button className={`chip ${mine ? "on" : ""}`} onClick={() => setMine(!mine)} disabled={!held.size}
            title={held.size ? `Only ${[...held].join(", ")}` : "No open positions"}>My exposure</button>
          <button className={`chip ${showPast ? "on" : ""}`} onClick={() => setShowPast(!showPast)}>Past</button>
        </div>
      }>
      {!list.length ? <Empty title="No events match" icon="news" /> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>When</th><th>Ccy</th><th>Impact</th><th>Event</th><th className="r">Actual</th><th className="r">Forecast</th><th className="r">Previous</th><th>Shock risk</th></tr></thead>
            <tbody>
              {list.map((e, i) => (
                <tr key={i} style={e.is_live ? { background: "var(--warn-soft)" } : undefined}>
                  <td style={{ whiteSpace: "normal", minWidth: 150 }}>{e.is_live && <Badge tone="warn" dot>Live</Badge>} <span className="muted">{e.time_utc}</span>
                    {e.time_quality === "estimated" && <span className="faint" title="Time estimated by the feed"> ~</span>}</td>
                  <td><b>{e.currency}</b>{held.has(e.currency) && <span className="warn" title="You hold this currency"> ●</span>}</td>
                  <td><Badge tone={impactTone(e.impact) as any}>{e.impact.toLowerCase()}</Badge></td>
                  <td style={{ whiteSpace: "normal", minWidth: 200 }}>{e.event}</td>
                  <td className="num">{e.actual}</td>
                  <td className="num">{e.forecast}</td>
                  <td className="num">{e.previous}</td>
                  <td className="muted">{(e.shock_risk || "—").toLowerCase()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function Headlines({ items }: { items: Headline[] }) {
  const [sent, setSent] = useState("ALL");
  const [q, setQ] = useState("");
  const list = items.filter((h) => (sent === "ALL" || h.sentiment === sent) && (!q || `${h.title} ${h.summary}`.toLowerCase().includes(q.toLowerCase())));
  return (
    <Card title="Headlines" sub={`${items.length} recent market headlines with sentiment`} flush
      actions={
        <div className="row wrap" style={{ gap: 6 }}>
          <input className="input" style={{ height: 30, width: 180 }} placeholder="Filter" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter headlines" />
          {["ALL", "BULLISH", "BEARISH", "NEUTRAL"].map((s) => <button key={s} className={`chip ${sent === s ? "on" : ""}`} onClick={() => setSent(s)}>{s.toLowerCase()}</button>)}
        </div>
      }>
      {!list.length ? <Empty title="No headlines match" icon="news" /> : (
        <div className="list">
          {list.map((h) => (
            <div key={h.id} className="list-item" style={{ alignItems: "flex-start" }}>
              <div className="grow stack" style={{ gap: 4 }}>
                <a href={h.link} target="_blank" rel="noopener noreferrer" style={{ color: "var(--text)", fontWeight: 600 }}>{h.title}</a>
                {h.summary && <div className="muted" style={{ fontSize: 13 }}>{h.summary}</div>}
                <div className="row wrap" style={{ gap: 6, fontSize: 12 }}>
                  <span className="faint">{h.source} · {h.age_str}</span>
                  {h.urgency === "HIGH_PRIORITY" && <Badge tone="warn">high priority</Badge>}
                  {(h.affected_assets || []).slice(0, 4).map((a) => <Badge key={a}>{a}</Badge>)}
                </div>
              </div>
              <Badge tone={sentTone(h.sentiment) as any}>{String(h.sentiment || "").toLowerCase()}</Badge>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
