import { useState } from "react";
import { api } from "../../lib/api";
import { usePoll } from "../../lib/hooks";
import { ago } from "../../lib/format";
import { useStore } from "../../state/store";
import { Badge, Card, Empty, ErrorNote, Loading } from "../../components/ui";
import { Icon } from "../../components/Icon";
import { ProvBadge } from "../../components/ProvBadge";
import { getLastScan } from "../markets/scanCache";
import { inr } from "../markets/Payoff";
import { recName } from "../markets/types";
import type { Prov } from "../markets/logic";
import { briefKind, istNow } from "../../lib/ist";

interface Brief { kind?: string; day?: string; ts?: number; provider?: string; text?: string | null; error?: string }
interface Session { open?: boolean; status?: string; message?: string; trade_date?: string; source?: string }
interface Ev { symbol: string; purpose?: string; date?: string; is_results?: boolean; company?: string }

/** Top of Overview: the day's AI brief, alerts, events, sessions and the last scan's opportunities. */
export function Today({ go }: { go: (r: string) => void }) {
  const kind = briefKind();
  const brief = usePoll<Brief>(`/api/ai/brief?kind=${kind}`, 10 * 60000);
  const status = usePoll<{ sessions?: Record<string, Session> }>("/api/markets/status", 2 * 60000);
  const events = usePoll<{ upcoming?: Ev[]; prov?: Prov }>("/api/markets/inst/events", 10 * 60000);
  const { alerts, unread, setPanel } = useStore();
  const [busy, setBusy] = useState(false);
  const [genErr, setGenErr] = useState<string | null>(null);
  const today = istNow().day;
  const todays = (events.data?.upcoming || []).filter((e) => e.date === today);
  const next = (events.data?.upcoming || []).filter((e) => (e.date || "") > today).slice(0, 3);
  const scan = getLastScan();
  const opps = (scan?.data.summary || []).filter((s) => s.status === "RECOMMEND").sort((a, b) => (b.edge_per_lot ?? 0) - (a.edge_per_lot ?? 0)).slice(0, 3);
  const noBrief = !brief.data?.text;

  const generate = async () => {
    setBusy(true); setGenErr(null);
    try { await api.post("/api/ai/brief/generate", { kind }); brief.reload(); }
    catch (e: any) { setGenErr(e?.message || "Brief generation failed"); }
    finally { setBusy(false); }
  };

  return (
    <Card title={<span className="row" style={{ gap: 8 }}><Icon name="sun" size={16} />Today</span>} sub={`${today} IST`}
      actions={<button className="btn sm" onClick={() => go("markets/inst")}>Institutional view</button>}>
      <div className="grid cols-2" data-tour="today">
        <div className="stack" style={{ gap: 8 }}>
          <div className="row wrap between" style={{ gap: 8 }}>
            <b style={{ fontSize: 13 }}>{kind === "pre" ? "Pre-open brief" : "Post-close brief"}</b>
            <div className="row" style={{ gap: 6 }}>
              {brief.data?.ts && <span className="faint" style={{ fontSize: 12 }}>{ago(brief.data.ts)} · {brief.data.provider === "template" ? "template (AI offline)" : brief.data.provider}</span>}
              <button className="btn sm" disabled={busy} onClick={generate}>{busy ? "Generating… (up to a minute)" : noBrief ? "Generate now" : "Regenerate"}</button>
            </div>
          </div>
          <ErrorNote error={genErr} onRetry={generate} />
          {brief.loading && !brief.data && !brief.error ? <Loading rows={4} />
            : noBrief ? <Empty title={`No ${kind === "pre" ? "pre-open" : "post-close"} brief yet today`} icon="news">
                Briefs are written automatically at 08:50 and 15:45 IST from live data only, or press “Generate now”.</Empty>
              : <div className="brief" style={{ maxHeight: 340, overflow: "auto" }}>{brief.data!.text}</div>}
        </div>

        <div className="stack" style={{ gap: 14 }}>
          <div className="row wrap" style={{ gap: 6 }}>
            {status.loading && !status.data ? <span className="faint">Checking sessions…</span> : status.error && !status.data ? <span className="faint">Session state unavailable</span>
              : Object.entries(status.data?.sessions || {}).map(([k, s]) => (
                <Badge key={k} tone={s.open ? "up" : "flat"} dot><span title={[s.message, s.trade_date, s.source].filter(Boolean).join(" · ")}>{k === "IN" ? "NSE" : k === "US" ? "US" : k} {s.status || (s.open ? "Open" : "Closed")}</span></Badge>
              ))}
          </div>

          <div className="stack" style={{ gap: 6 }}>
            <div className="row between"><b style={{ fontSize: 13 }}>Alerts</b>
              <button className="btn ghost sm" onClick={() => setPanel("alerts")}>{unread ? `${unread} unread` : "Manage"}</button></div>
            {alerts.filter((a) => !a.acked).slice(0, 3).map((a) => (
              <div key={a.id} className="faint" style={{ fontSize: 12.5 }}><span className="dot warn" style={{ display: "inline-block", marginRight: 6 }} />{a.message} · {ago(a.ts)}</div>
            ))}
            {!unread && <div className="faint" style={{ fontSize: 12.5 }}>No unread alerts.</div>}
          </div>

          <div className="stack" style={{ gap: 6 }}>
            <div className="row between"><b style={{ fontSize: 13 }}>Events today</b><ProvBadge prov={events.data?.prov} loading={events.loading && !events.data} /></div>
            {events.error && !events.data ? <div className="faint" style={{ fontSize: 12.5 }}>Event calendar unavailable.</div>
              : todays.length ? todays.slice(0, 5).map((e, i) => (
                <div key={i} style={{ fontSize: 12.5 }}><b>{e.symbol}</b> <span className="faint">{e.purpose}</span>{e.is_results && <> <Badge tone="accent">results</Badge></>}</div>
              )) : <div className="faint" style={{ fontSize: 12.5 }}>None listed for today{next.length ? ` · next: ${next.map((e) => `${e.symbol} ${e.date}`).join(", ")}` : ""}.</div>}
          </div>

          <div className="stack" style={{ gap: 6 }}>
            <div className="row between"><b style={{ fontSize: 13 }}>F&O opportunities</b>
              <button className="btn ghost sm" onClick={() => { try { localStorage.setItem("hm.mk.fno.tab", JSON.stringify("scanner")); } catch { /* storage blocked */ } go("markets/fno"); }}>Open scanner</button></div>
            {!scan ? <div className="faint" style={{ fontSize: 12.5 }}>No scan run in this session. The scanner is slow, so it only runs when you ask.</div>
              : opps.length ? opps.map((o) => (
                <div key={o.symbol} className="row between" style={{ fontSize: 12.5 }}>
                  <span><b>{o.symbol}</b> <span className="faint">{recName(o.recommendation)}</span></span>
                  <span className="row" style={{ gap: 6 }}><span className="mono up">{inr(o.edge_per_lot)}</span><ProvBadge prov={o.prov} loading={false} /></span>
                </div>
              )) : <div className="faint" style={{ fontSize: 12.5 }}>Last scan ({ago(scan.at / 1000)}) found no RECOMMEND verdicts.</div>}
          </div>
        </div>
      </div>
    </Card>
  );
}
