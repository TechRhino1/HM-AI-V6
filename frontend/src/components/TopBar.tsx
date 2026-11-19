import { useState } from "react";
import { useStore } from "../state/store";
import { Badge } from "./ui";
import { Icon } from "./Icon";
import { AlertBell } from "../features/alerts/Alerts";

/** Global status only (mode, link, safety state, user). Account numbers live on Overview. */
export function TopBar({ title, user, onSearch, onLogout, go }: {
  title: string; user: { username: string; role: string; full_name?: string } | null;
  onSearch: () => void; onLogout: () => void; go: (r: string) => void;
}) {
  const { telemetry, link, risk } = useStore();
  const [menu, setMenu] = useState(false);
  const mode = telemetry?.execution_mode || "—";
  const mt5 = telemetry?.services?.MT5;
  const linkTone = link === "offline" || (mt5 && mt5 !== "CONNECTED") ? "down" : link === "live" ? "up" : "warn";
  const linkLabel = link === "offline" ? "Offline" : mt5 && mt5 !== "CONNECTED" ? `MT5 ${mt5.toLowerCase()}` : link === "live" ? "Live" : "Polling";

  return (
    <header className="topbar">
      <h1>{title}</h1>
      <div className="spacer" />
      {risk?.circuit_breaker_active && (
        <button className="badge down" style={{ border: 0, cursor: "pointer" }} onClick={() => go("system")} title={risk.circuit_breaker_reason}>
          <Icon name="alert" size={13} />Circuit breaker
        </button>
      )}
      {telemetry?.safe_mode && <Badge tone="warn">Safe mode</Badge>}
      <span className="hide-mobile"><Badge tone={mode === "LIVE" ? "down" : mode === "DEMO" ? "accent" : "flat"}>{mode}</Badge></span>
      <Badge tone={linkTone} dot>{linkLabel}</Badge>
      <AlertBell />
      <button className="btn ghost icon-btn hide-desktop" onClick={onSearch} aria-label="Search"><Icon name="search" /></button>
      <div style={{ position: "relative" }}>
        <button className="btn ghost sm" onClick={() => setMenu((m) => !m)} aria-haspopup="menu" aria-expanded={menu}>
          <span className="brand-mark" style={{ width: 24, height: 24, fontSize: 11, borderRadius: 7 }}>
            {(user?.username || "?").slice(0, 2).toUpperCase()}
          </span>
          <span className="hide-mobile">{user?.username}</span>
        </button>
        {menu && (
          <div className="card" role="menu" style={{ position: "absolute", right: 0, top: 40, width: 220, zIndex: 40, boxShadow: "var(--shadow)" }}
            onMouseLeave={() => setMenu(false)}>
            <div className="list-item" style={{ display: "grid", gap: 2 }}>
              <b>{user?.full_name || user?.username}</b>
              <span className="faint" style={{ fontSize: 12 }}>{user?.role}</span>
            </div>
            <button className="list-item clickable btn ghost" style={{ width: "100%", justifyContent: "flex-start", borderRadius: 0, height: 40 }}
              onClick={() => { setMenu(false); go("system/account"); }}>
              <Icon name="settings" />Account settings
            </button>
            <button className="list-item clickable btn ghost" style={{ width: "100%", justifyContent: "flex-start", borderRadius: 0, height: 40 }}
              onClick={onLogout}>
              <Icon name="logout" />Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
