import { useMemo, useState } from "react";
import { SECTIONS } from "../App";
import { useStore } from "../state/store";
import { api } from "../lib/api";
import { useFeedback } from "./feedback";
import { requestScan } from "../features/markets/scanCache";
import { briefKind } from "../lib/ist";
import { Icon, IconName } from "./Icon";

interface Cmd { id: string; label: string; hint: string; icon: IconName; run: () => void }

/** Ctrl/Cmd+K: jump to any section, sub-view or symbol, or run an AI / alert action. */
export function CommandPalette({ onClose, go, theme, setTheme }: {
  onClose: () => void; go: (r: string) => void; theme: string; setTheme: (t: "dark" | "light") => void;
}) {
  const { symbols, setSymbol, askAI, setPanel } = useStore();
  const { run } = useFeedback();
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);

  const all = useMemo<Cmd[]>(() => {
    const nav = (r: string) => () => { go(r); onClose(); };
    const subs: [string, string, IconName][] = [
      ["portfolio/open", "Open positions", "briefcase"], ["portfolio/pending", "Pending orders", "briefcase"],
      ["portfolio/history", "Trade journal", "briefcase"], ["analytics/performance", "Performance", "analytics"],
      ["analytics/calibration", "Calibration & deployment", "shield"], ["analytics/lab", "Backtest lab", "flask"],
      ["analytics/research", "Research (missed trades, profiles)", "analytics"], ["system/symbols", "Symbol universe", "settings"], ["system/ai", "AI governor (Gemini activity)", "settings"],
      ["markets/fno", "India F&O adviser", "layers"], ["markets/inst", "Institutional (FII/DII, futures, deals, events)", "users"], ["markets/india", "India equities", "globe"],
      ["markets/us", "US stocks", "globe"], ["markets/sources", "Market data sources", "activity"],
      ["system/users", "User management", "users"], ["system/account", "Account settings", "settings"],
    ];
    const actions: Cmd[] = [
      { id: "ask", label: "Ask AI…", hint: "Action · type a question first", icon: "chat", run: () => { askAI(); onClose(); } },
      { id: "alert", label: "New alert…", hint: "Action", icon: "bell", run: () => { setPanel("alerts-new"); onClose(); } },
      { id: "scan", label: "Run F&O scan", hint: "Action · Markets › F&O scanner", icon: "radar", run: () => {
        requestScan();
        try { localStorage.setItem("hm.mk.fno.tab", JSON.stringify("scanner")); } catch { /* storage blocked */ }
        go("markets/fno"); onClose();
      } },
      { id: "brief", label: "Generate market brief", hint: "Action · takes up to a minute", icon: "news", run: () => {
        onClose(); go("overview");
        run(() => api.post("/api/ai/brief/generate", { kind: briefKind() }), { success: "Market brief generated — open Overview › Today" });
      } },
      { id: "explain", label: "Explain …", hint: "Action · type a metric first", icon: "info", run: () => { askAI("Explain "); onClose(); } },
    ];
    return [
      ...actions,
      ...SECTIONS.map((s) => ({ id: s.id, label: s.label, hint: "Section", icon: s.icon, run: nav(s.id) })),
      ...subs.map(([r, label, icon]) => ({ id: r, label, hint: "View", icon, run: nav(r) })),
      ...symbols.map((s) => ({
        id: `sym-${s.symbol}`, label: s.symbol, hint: `${s.asset_class.toLowerCase()} · chart & ticket`, icon: "candles" as IconName,
        run: () => { setSymbol(s.symbol); go("trade"); onClose(); },
      })),
      { id: "theme", label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme", hint: "Preference", icon: theme === "dark" ? "sun" : "moon",
        run: () => { setTheme(theme === "dark" ? "light" : "dark"); onClose(); } },
    ];
  }, [symbols, go, onClose, setSymbol, theme, setTheme, askAI, setPanel, run]);

  const list = useMemo(() => {
    const raw = q.trim(), t = raw.toLowerCase();
    if (!t) return all.slice(0, 12);
    const typed: Cmd[] = [
      { id: "ask-q", label: `Ask AI: “${raw}”`, hint: "Action", icon: "chat", run: () => { askAI(raw); onClose(); } },
      { id: "explain-q", label: `Explain “${raw}”`, hint: "Action", icon: "info", run: () => { askAI(`Explain ${raw}`); onClose(); } },
    ];
    const hits = all.filter((c) => `${c.label} ${c.hint}`.toLowerCase().includes(t));
    // Navigation matches first; the free-text AI actions stay available below them.
    return [...hits.slice(0, 10), ...typed];
  }, [all, q, askAI, onClose]);

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal palette" role="dialog" aria-label="Search">
        <input className="input" autoFocus placeholder="Jump to a view or symbol, or type a question for the AI…" value={q}
          onChange={(e) => { setQ(e.target.value); setIdx(0); }}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            else if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, list.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
            else if (e.key === "Enter") list[idx]?.run();
          }} />
        <div className="list" role="listbox">
          {list.map((c, i) => (
            <div key={c.id} role="option" aria-selected={i === idx} className={`list-item clickable ${i === idx ? "selected" : ""}`}
              onMouseEnter={() => setIdx(i)} onClick={c.run}>
              <Icon name={c.icon} />
              <span className="grow">{c.label}</span>
              <span className="faint" style={{ fontSize: 12 }}>{c.hint}</span>
            </div>
          ))}
          {!list.length && <div className="empty">No matches</div>}
        </div>
      </div>
    </div>
  );
}
