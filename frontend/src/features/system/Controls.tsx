import { useState } from "react";
import { api } from "../../lib/api";
import { usePoll } from "../../lib/hooks";
import { useStore } from "../../state/store";
import { useFeedback } from "../../components/feedback";
import { duration } from "../../lib/format";
import { STYLES, type TradeStyle } from "../../lib/types";
import { Badge, Card, Field, Loading, Seg, Switch } from "../../components/ui";
import { NOTIFY_KEY } from "../alerts/useTradeAlerts";

const MODES = [
  { value: "PAPER", label: "Paper" },
  { value: "DEMO", label: "Demo" },
  { value: "LIVE", label: "Live" },
];

export function Controls() {
  const { telemetry, risk, refresh, reloadRisk } = useStore();
  const { run } = useFeedback();
  const metrics = usePoll<{ uptime_seconds: number }>("/api/metrics", 60000);
  const [closeOnStop, setCloseOnStop] = useState(false);
  const [reason, setReason] = useState("");

  if (!telemetry) return <Loading rows={5} />;
  const after = () => { refresh(); reloadRisk(); };

  const setMode = (mode: string) => run(() => api.post("/api/action/set_mode", { mode, confirm_live: mode === "LIVE" }), {
    success: `Execution mode set to ${mode}`,
    confirm: mode === "LIVE"
      ? { title: "Switch to LIVE trading?", danger: true, confirmLabel: "Trade real money", body: "The engine will place orders with real money on the connected account." }
      : { title: `Switch to ${mode}?`, body: `New orders will run in ${mode.toLowerCase()} mode.` },
  }).then(after);

  const setStyle = (trade_style: TradeStyle) => run(() => api.post<{ applied_to_orchestrator: boolean }>("/api/action/set_trade_style", { trade_style }), {
    success: `Trade style set to ${STYLES.find((s) => s.value === trade_style)?.label ?? trade_style}`,
  }).then(after);

  const toggleSafe = () => run(() => api.post("/api/action/toggle_safe_mode"), { success: telemetry.safe_mode ? "Safe mode off" : "Safe mode on" }).then(after);

  const stop = () => run(() => api.post("/api/action/emergency_stop", { reason: reason || undefined, close_positions: closeOnStop }), {
    success: "Emergency stop engaged",
    confirm: { title: "Emergency stop?", danger: true, confirmLabel: "Stop trading",
      body: closeOnStop ? "New entries stop, pending orders are cancelled and every open position is closed at market." : "New entries stop and pending orders are cancelled. Open positions stay open." },
  }).then(after);

  const resume = () => run(() => api.post("/api/action/resume_trading"), {
    success: "Trading resumed",
    confirm: { title: "Resume trading?", confirmLabel: "Resume", body: "Resets the circuit breaker and the drawdown guard so the engine can take new entries again." },
  }).then(after);

  const services = Object.entries(telemetry.services || {});

  return (
    <div className="grid cols-2" style={{ alignItems: "start" }}>
      <Card title="Execution" sub="Where orders go and how the engine trades">
        <div className="stack" style={{ gap: 18 }}>
          <Field label={`Account mode · now ${telemetry.execution_mode}`}>
            <Seg value={telemetry.execution_mode} onChange={setMode} options={MODES} full />
          </Field>
          <Field label="Trade style">
            <Seg value={telemetry.trade_style as TradeStyle} onChange={setStyle} options={STYLES} full />
            <div className="faint" style={{ fontSize: 12.5, marginTop: 6 }}>
              {telemetry.trade_style === "AUTO" ? "Auto picks the best-earning style and strategy per symbol and checks the news first. See Signals › Auto picks."
                : telemetry.trade_style === "ALL" ? "Every style can trade; the arbiter takes the best setup." : "Only this style can open trades."}
            </div>
          </Field>
          <div className="row between">
            <div><b>Safe mode</b><div className="faint" style={{ fontSize: 12.5 }}>Stricter gates and smaller size while you watch the engine.</div></div>
            <Switch checked={!!telemetry.safe_mode} onChange={toggleSafe} label="Safe mode" />
          </div>
        </div>
      </Card>

      <Card title="Safety" sub="Stop or resume the engine"
        actions={risk?.circuit_breaker_active ? <Badge tone="down" dot>Stopped</Badge> : <Badge tone="up" dot>Running</Badge>}>
        <div className="stack" style={{ gap: 14 }}>
          {risk?.circuit_breaker_active && <div className="alert down">{risk.circuit_breaker_reason || "Circuit breaker active"}</div>}
          <Field label="Reason (optional, logged)">
            <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. news spike, manual review" />
          </Field>
          <label className="row" style={{ gap: 10 }}>
            <Switch checked={closeOnStop} onChange={setCloseOnStop} label="Also close all positions" />Also close all open positions
          </label>
          <div className="grid cols-2" style={{ gap: 8 }}>
            <button className="btn sell lg" onClick={stop}>Emergency stop</button>
            <button className="btn lg" onClick={resume}>Resume trading</button>
          </div>
          <div className="faint" style={{ fontSize: 12.5 }}>Resume also resets the drawdown guard (the server treats both as one action).</div>
        </div>
      </Card>

      <Card title="Services" sub={metrics.data ? `Engine up ${duration(metrics.data.uptime_seconds)}` : undefined} flush>
        <div className="list">
          {services.map(([k, v]) => {
            const ok = /CONNECTED|STREAMING|READY|ACTIVE|ONLINE/.test(v);
            return (
              <div key={k} className="list-item">
                <span className={`dot ${ok ? "up" : "down"}`} />
                <span className="grow">{k.replace(/_/g, " ").toLowerCase()}</span>
                <span className="mono faint" style={{ fontSize: 12 }}>{v}</span>
              </div>
            );
          })}
        </div>
      </Card>

      <NotificationPrefs />
    </div>
  );
}

function NotificationPrefs() {
  const read = () => { try { return localStorage.getItem(NOTIFY_KEY) === "1"; } catch { return false; } };
  const [on, setOn] = useState(read);
  const supported = typeof Notification !== "undefined";
  const toggle = async (v: boolean) => {
    if (v && supported && Notification.permission !== "granted") {
      const p = await Notification.requestPermission();
      if (p !== "granted") return;
    }
    try { localStorage.setItem(NOTIFY_KEY, v ? "1" : "0"); } catch { /* storage blocked */ }
    setOn(v);
  };
  return (
    <Card title="Alerts" sub="In-app toasts always appear; desktop alerts are optional">
      <div className="row between">
        <div><b>Desktop notifications</b><div className="faint" style={{ fontSize: 12.5 }}>
          {supported ? "When this tab is in the background: positions opened or closed, circuit breaker tripped." : "This browser does not support notifications."}
        </div></div>
        <Switch checked={on} onChange={toggle} label="Desktop notifications" disabled={!supported} />
      </div>
    </Card>
  );
}
