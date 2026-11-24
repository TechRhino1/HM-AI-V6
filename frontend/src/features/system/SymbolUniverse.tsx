import { useState } from "react";
import { api } from "../../lib/api";
import { useStore } from "../../state/store";
import { useFeedback } from "../../components/feedback";
import { Badge, Card, Empty, Switch } from "../../components/ui";

const CLASSES = ["ALL", "FOREX", "COMMODITY", "CRYPTO", "INDEX"];
const PROFILES: [string, string][] = [
  ["DYNAMIC", "Dynamic (live edge)"], ["BALANCED", "Balanced"], ["CONSERVATIVE", "Conservative"],
  ["AGGRESSIVE", "Aggressive"], ["SESSION_ADAPTIVE", "Session adaptive"],
];

/** Which symbols the engine scans and trades. Changes are persisted by the server. */
export function SymbolUniverse() {
  const { symbols, autoTune, reloadSymbols } = useStore();
  const { run } = useFeedback();
  const [cls, setCls] = useState("ALL");
  const [profile, setProfile] = useState("DYNAMIC");
  const list = symbols.filter((s) => cls === "ALL" || s.asset_class === cls);

  const toggle = (symbol: string, enabled: boolean) =>
    run(() => api.post("/api/action/toggle_symbol", { symbol, enabled }), { success: `${symbol} ${enabled ? "enabled" : "disabled"}` }).then(reloadSymbols);

  const batch = (action: "ENABLE_ALL" | "DISABLE_ALL" | "AUTO_TUNE") =>
    run(() => api.post("/api/action/batch_symbols", { action, asset_class: cls, mode: profile }), {
      success: action === "AUTO_TUNE" ? "Auto-tune applied" : `${action === "ENABLE_ALL" ? "Enabled" : "Disabled"} ${cls === "ALL" ? "all symbols" : cls.toLowerCase()}`,
      confirm: { title: action === "AUTO_TUNE" ? "Auto-tune the universe?" : `${action === "ENABLE_ALL" ? "Enable" : "Disable"} ${cls === "ALL" ? "every symbol" : `all ${cls.toLowerCase()}`}?`,
        body: action === "AUTO_TUNE"
          ? (profile === "DYNAMIC" ? "Picks symbols by each one's live edge (its recent closed trades, shrunk toward its calibrated backtest) and saves the selection."
            : "The server picks symbols from current conditions and saves the selection.")
          : "The engine's symbol list is saved and takes effect on the next scan." },
    }).then(reloadSymbols);

  const setAuto = (on: boolean) =>
    run(() => api.post("/api/action/batch_symbols", { action: "SET_AUTO_TUNE", auto_tune: on ? "dynamic" : "off" }), {
      success: on ? "Dynamic auto-tune on: runs every 30 min" : "Dynamic auto-tune off",
    }).then(reloadSymbols);

  const last = autoTune.last;
  const lastRows = last ? [...last.details].sort((a, b) => (a.status === b.status ? a.symbol.localeCompare(b.symbol) : a.status === "ACTIVATED" ? -1 : 1)) : [];

  return (
    <>
    <Card title="Auto-tune" sub={autoTune.mode === "dynamic" ? "Dynamic runs every 30 min and changes the list only when the evidence does" : "Manual: runs when you press Auto-tune"}
      actions={
        <div className="row wrap" style={{ gap: 8, alignItems: "center" }}>
          <select className="select" style={{ width: "auto", height: 30 }} value={profile} onChange={(e) => setProfile(e.target.value)} aria-label="Auto-tune profile">
            {PROFILES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <button className="btn sm" onClick={() => batch("AUTO_TUNE")}>Run now{cls === "ALL" ? "" : ` (${cls.toLowerCase()})`}</button>
          <span className="muted" style={{ fontSize: 12.5 }}>Every 30 min</span>
          <Switch checked={autoTune.mode === "dynamic"} onChange={setAuto} label="Run dynamic auto-tune every 30 min" />
        </div>
      }>
      {!last ? <Empty title="No auto-tune run yet" /> : (
        <>
          <div className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>
            Last run {new Date(last.at * 1000).toLocaleString()} · {last.trigger} · {last.mode.toLowerCase()} · {last.changed ? "list changed" : "no change"}
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Symbol</th><th>Result</th><th className="r">Edge</th><th>Why</th></tr></thead>
              <tbody>
                {lastRows.map((d) => (
                  <tr key={d.symbol}>
                    <td><b>{d.symbol}</b></td>
                    <td><Badge tone={d.status === "ACTIVATED" ? "up" : "flat"}>{d.status === "ACTIVATED" ? "on" : "off"}</Badge></td>
                    <td className="num">{d.edge_r == null ? "–" : `${d.edge_r >= 0 ? "+" : ""}${d.edge_r.toFixed(2)}R`}</td>
                    <td className="muted" style={{ whiteSpace: "normal", fontSize: 12.5 }}>{d.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>

    <Card title="Symbol universe" sub={`${symbols.filter((s) => s.is_enabled).length} of ${symbols.length} enabled for the engine`} flush
      actions={
        <div className="row wrap" style={{ gap: 6 }}>
          {CLASSES.map((c) => <button key={c} className={`chip ${cls === c ? "on" : ""}`} onClick={() => setCls(c)}>{c === "ALL" ? "All" : c.toLowerCase()}</button>)}
          <button className="btn sm" onClick={() => batch("ENABLE_ALL")}>Enable all</button>
          <button className="btn sm" onClick={() => batch("DISABLE_ALL")}>Disable all</button>
        </div>
      }>
      {!list.length ? <Empty title="No symbols" /> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Symbol</th><th>Class</th><th>Session</th><th className="r">Spread / max</th><th>Engine view</th><th>Allowed</th><th className="r">Trade</th></tr></thead>
            <tbody>
              {list.map((s) => (
                <tr key={s.symbol}>
                  <td><b>{s.symbol}</b></td>
                  <td className="muted">{s.asset_class.toLowerCase()}</td>
                  <td><Badge tone={s.is_open ? "up" : "flat"} dot>{s.is_open ? s.session_name.toLowerCase() : "closed"}</Badge></td>
                  <td className={`num ${s.spread_pips > s.max_spread_pips ? "down" : ""}`}>{s.spread_pips} / {s.max_spread_pips}</td>
                  <td className="muted" style={{ whiteSpace: "normal", maxWidth: 320, fontSize: 12.5 }}>{s.suggestion}</td>
                  <td>{s.spread_pips > s.max_spread_pips ? <Badge tone="warn">spread too wide</Badge> : <Badge tone="flat">ok</Badge>}</td>
                  <td style={{ textAlign: "right" }}><Switch checked={s.is_enabled} onChange={(v) => toggle(s.symbol, v)} label={`Trade ${s.symbol}`} /></td>
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
