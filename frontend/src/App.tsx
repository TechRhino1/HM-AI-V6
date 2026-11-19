import { lazy, Suspense, useEffect, useState } from "react";
import { onUnauthorized, api } from "./lib/api";
import { useHashRoute, useLocalStorage } from "./lib/hooks";
import { Icon, IconName } from "./components/Icon";
import { Loading } from "./components/ui";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { useStore } from "./state/store";
import { TopBar } from "./components/TopBar";
import { CommandPalette } from "./components/CommandPalette";
import { Copilot } from "./features/copilot/Copilot";
import { LoginScreen } from "./features/auth/LoginScreen";
import { useTradeAlerts } from "./features/alerts/useTradeAlerts";
import { AlertsDrawer } from "./features/alerts/Alerts";
import { Tour } from "./components/Tour";

const Overview = lazy(() => import("./features/overview/Overview"));
const Trade = lazy(() => import("./features/trade/Trade"));
const Signals = lazy(() => import("./features/signals/Signals"));
const Portfolio = lazy(() => import("./features/portfolio/Portfolio"));
const Analytics = lazy(() => import("./features/analytics/Analytics"));
const News = lazy(() => import("./features/news/News"));
const System = lazy(() => import("./features/system/System"));
const Markets = lazy(() => import("./features/markets/Markets"));

export interface Section { id: string; label: string; icon: IconName; title: string; mobile?: boolean }
export const SECTIONS: Section[] = [
  { id: "overview", label: "Overview", icon: "home", title: "Overview", mobile: true },
  { id: "trade", label: "Trade", icon: "candles", title: "Trade", mobile: true },
  { id: "signals", label: "Signals", icon: "radar", title: "Signals & AI selection", mobile: true },
  { id: "portfolio", label: "Portfolio", icon: "briefcase", title: "Portfolio", mobile: true },
  { id: "analytics", label: "Analytics", icon: "analytics", title: "Analytics & research" },
  { id: "markets", label: "Markets", icon: "globe", title: "Markets · India F&O, equities, US", mobile: true },
  { id: "news", label: "News & events", icon: "news", title: "News & economic events" },
  { id: "system", label: "System", icon: "settings", title: "System & controls", mobile: true },
];
const VIEWS: Record<string, React.ComponentType<{ sub: string; go: (r: string) => void }>> = {
  overview: Overview, trade: Trade, signals: Signals, portfolio: Portfolio, analytics: Analytics, news: News, system: System, markets: Markets,
};
// Old hashes from the previous dashboard keep working.
const ALIASES: Record<string, string> = {
  trading: "trade", positions: "portfolio/open", performance: "analytics/performance", controls: "system",
  symbols: "system/symbols", analyst: "signals", backtest: "analytics/lab",
  stocks: "markets/us", india: "markets/india", options: "markets/fno",
};

export default function App() {
  const [route, go] = useHashRoute("overview");
  const [theme, setTheme] = useLocalStorage<"dark" | "light">("hm.theme", "dark");
  const [authState, setAuthState] = useState<"checking" | "ok" | "login">("checking");
  const [user, setUser] = useState<{ username: string; role: string; full_name?: string } | null>(null);
  const [palette, setPalette] = useState(false);
  const { telemetry, panel, setPanel } = useStore();
  useTradeAlerts();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    api.post<{ valid: boolean; user: any }>("/api/auth/verify")
      .then((r) => { setUser(r.user); setAuthState("ok"); })
      .catch(() => setAuthState("login"));
    return onUnauthorized(() => setAuthState("login"));
  }, []);

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  const [head, ...rest] = route.split("/");
  const alias = ALIASES[head];
  useEffect(() => {
    if (alias) go(alias);
  }, [alias, go]);
  const section = SECTIONS.find((s) => s.id === head) ? head : "overview";
  const View = VIEWS[section];
  const meta = SECTIONS.find((s) => s.id === section)!;

  useEffect(() => {
    document.title = `${meta.label} · HM Trading`;
  }, [meta.label]);

  if (authState === "checking") return <div className="content"><Loading rows={4} /></div>;
  if (authState === "login") return <LoginScreen onDone={(u) => { setUser(u); setAuthState("ok"); }} />;

  const openPositions = telemetry?.positions?.length || 0;

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand">
          <div className="brand-mark">HM</div>
          <div>HM Trading<small>Algo 5.0 console</small></div>
        </div>
        {SECTIONS.map((s) => (
          <button key={s.id} className={`nav-item ${s.id === section ? "active" : ""}`} onClick={() => go(s.id)}
            aria-current={s.id === section ? "page" : undefined}>
            <Icon name={s.icon} />
            {s.label}
            {s.id === "portfolio" && openPositions > 0 && <span className="count">{openPositions}</span>}
          </button>
        ))}
        <div className="sidebar-foot">
          <button className="nav-item" onClick={() => setPalette(true)}>
            <Icon name="search" />Search<span className="count kbd">Ctrl K</span>
          </button>
          <button className="nav-item" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            <Icon name={theme === "dark" ? "sun" : "moon"} />{theme === "dark" ? "Light theme" : "Dark theme"}
          </button>
        </div>
      </aside>

      <div className="main">
        <TopBar title={meta.title} user={user} onSearch={() => setPalette(true)} go={go}
          onLogout={async () => { await api.post("/api/auth/logout").catch(() => undefined); setAuthState("login"); }} />
        <main className="content">
          <ErrorBoundary resetKey={route}>
            <Suspense fallback={<Loading rows={5} />}>
              <View sub={rest.join("/")} go={go} />
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>

      <nav className="bottom-nav" aria-label="Main navigation">
        {SECTIONS.filter((s) => s.mobile).map((s) => (
          <button key={s.id} className={s.id === section ? "active" : ""} onClick={() => go(s.id)}>
            <Icon name={s.icon} size={20} />
            {s.label}
          </button>
        ))}
      </nav>

      <Copilot section={section} />
      {(panel === "alerts" || panel === "alerts-new") && <AlertsDrawer initialTab={panel === "alerts-new" ? "new" : "feed"} onClose={() => setPanel(null)} />}
      <Tour go={go} />
      {palette && <CommandPalette onClose={() => setPalette(false)} go={go} theme={theme} setTheme={setTheme} />}
    </div>
  );
}
