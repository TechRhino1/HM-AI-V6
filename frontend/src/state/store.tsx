import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { usePoll } from "../lib/hooks";
import type { AutoTuneState, RiskStatus, SymbolIntel, Telemetry } from "../lib/types";
import type { Prov } from "../features/markets/logic";

/** A market alert that fired (from /api/alerts/fired or the SSE `alert` event). */
export interface FiredAlert { id: number; rule_id: string; ts: number; type: string; message: string; value?: unknown; prov?: Prov; acked: boolean }
/** What the current page is looking at; sent to the AI copilot as context. */
export interface PageCtx { symbol?: string; market?: string; expiry?: string }
export type Panel = "alerts" | "alerts-new" | "copilot" | null;

/** Order-ticket prefill, set by "Trade this" anywhere in the app. */
export interface TicketDraft {
  symbol: string; side?: "BUY" | "SELL"; entry?: number; sl?: number; tp?: number; source?: string;
}

interface Store {
  telemetry: Telemetry | undefined;
  link: "live" | "polling" | "offline";
  lastUpdate: number;
  refresh: () => void;
  risk: RiskStatus | undefined;
  riskError: string | null;
  symbolsError: string | null;
  reloadRisk: () => void;
  symbols: SymbolIntel[];
  autoTune: AutoTuneState;
  reloadSymbols: () => void;
  symbol: string;
  setSymbol: (s: string) => void;
  draft: TicketDraft | null;
  setDraft: (d: TicketDraft | null) => void;
  alerts: FiredAlert[];
  unread: number;
  /** Newest alert pushed over SSE this session (drives toasts); null until one arrives. */
  lastAlert: FiredAlert | null;
  reloadAlerts: () => void;
  markAcked: (ids: number[]) => void;
  panel: Panel;
  setPanel: (p: Panel) => void;
  /** Prefill for the next "New alert" form (e.g. a level from a position card); cleared when the form reads it. */
  alertDraft: Record<string, unknown> | null;
  setAlertDraft: (r: Record<string, unknown> | null) => void;
  /** Opens the copilot; with text, asks it straight away. */
  askAI: (text?: string) => void;
  aiPrompt: string | null;
  clearAiPrompt: () => void;
  pageCtx: PageCtx;
  setPageCtx: (c: PageCtx) => void;
}

const Ctx = createContext<Store | null>(null);
export const useStore = () => useContext(Ctx)!;

// The SSE digest carries the fast-moving fields; explainability (checks, reasons) and
// market statuses come only from the full snapshot, which is polled less often.
const DIGEST_KEYS = ["account", "positions", "positions_count", "services", "execution_mode", "trade_style", "safe_mode", "is_running", "timestamp"] as const;
const FULL_POLL_MS = 8000;
const FALLBACK_POLL_MS = 3000;

export function StoreProvider({ children }: { children: ReactNode }) {
  const [telemetry, setTelemetry] = useState<Telemetry>();
  const [link, setLink] = useState<Store["link"]>("polling");
  const [lastUpdate, setLastUpdate] = useState(0);
  const [tick, setTick] = useState(0);
  const sseUp = useRef(false);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // Full snapshot: faster cadence while the push stream is down.
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const run = async () => {
      if (!document.hidden) {
        try {
          const t = await api.get<Telemetry>("/api/telemetry_state");
          if (!alive) return;
          setTelemetry(t);
          setLastUpdate(Date.now());
          if (!sseUp.current) setLink("polling");
        } catch {
          if (alive && !sseUp.current) setLink("offline");
        }
      }
      if (alive) timer = window.setTimeout(run, sseUp.current ? FULL_POLL_MS : FALLBACK_POLL_MS);
    };
    run();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [tick]);

  // Push stream: the server closes it after ~60s and EventSource reconnects on its own.
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const es = new EventSource("/api/stream/telemetry");
    es.addEventListener("telemetry", (ev) => {
      try {
        const d = JSON.parse((ev as MessageEvent).data);
        sseUp.current = true;
        setLink("live");
        setLastUpdate(Date.now());
        setTelemetry((prev) => {
          if (!prev) return prev;
          const next: any = { ...prev };
          for (const k of DIGEST_KEYS) if (k in d) next[k] = d[k];
          return next;
        });
      } catch {
        /* malformed frame: ignore it, the poll still runs */
      }
    });
    es.addEventListener("alert", (ev) => {
      try {
        const a = JSON.parse((ev as MessageEvent).data) as FiredAlert;
        setLastAlert(a);
        setFired((prev) => (prev.some((x) => x.id === a.id) ? prev : [a, ...prev]));
      } catch {
        /* malformed frame */
      }
    });
    es.onerror = () => {
      sseUp.current = false;
      setLink((l) => (l === "live" ? "polling" : l));
    };
    return () => es.close();
  }, []);

  useEffect(() => {
    const on = () => !document.hidden && refresh();
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, [refresh]);

  const [fired, setFired] = useState<FiredAlert[]>([]);
  const [lastAlert, setLastAlert] = useState<FiredAlert | null>(null);
  // Last 7 days of fired alerts; the SSE stream adds new ones between polls.
  const firedRes = usePoll<{ fired?: FiredAlert[] }>(`/api/alerts/fired?since=${Math.floor(Date.now() / 86400000 - 7) * 86400}`, 60000);
  useEffect(() => { if (firedRes.data?.fired) setFired(firedRes.data.fired); }, [firedRes.data]);
  const markAcked = useCallback((ids: number[]) => setFired((f) => f.map((a) => (ids.includes(a.id) ? { ...a, acked: true } : a))), []);
  const [panel, setPanel] = useState<Panel>(null);
  const [aiPrompt, setAiPrompt] = useState<string | null>(null);
  const [alertDraft, setAlertDraft] = useState<Record<string, unknown> | null>(null);
  const askAI = useCallback((text?: string) => { setAiPrompt(text?.trim() || null); setPanel("copilot"); }, []);
  const clearAiPrompt = useCallback(() => setAiPrompt(null), []);
  const [pageCtx, setPageCtx] = useState<PageCtx>({});

  const riskRes = usePoll<RiskStatus>("/api/risk_status", 10000);
  const symRes = usePoll<{ symbols: SymbolIntel[]; auto_tune?: string; last_auto_tune?: AutoTuneState["last"] }>("/api/symbols/intelligence", 15000);

  const [symbol, setSymbolState] = useState<string>(() => {
    try { return localStorage.getItem("hm.symbol") || "EURUSD"; } catch { return "EURUSD"; }
  });
  const setSymbol = useCallback((s: string) => {
    setSymbolState(s);
    try { localStorage.setItem("hm.symbol", s); } catch { /* storage blocked */ }
  }, []);
  const [draft, setDraft] = useState<TicketDraft | null>(null);

  const value = useMemo<Store>(() => ({
    telemetry, link, lastUpdate, refresh,
    risk: riskRes.data, reloadRisk: riskRes.reload, riskError: riskRes.error, symbolsError: symRes.error,
    symbols: symRes.data?.symbols || [], reloadSymbols: symRes.reload,
    autoTune: { mode: symRes.data?.auto_tune === "dynamic" ? "dynamic" : "off", last: symRes.data?.last_auto_tune ?? null },
    symbol, setSymbol, draft, setDraft,
    alerts: fired, unread: fired.filter((a) => !a.acked).length, lastAlert, reloadAlerts: firedRes.reload, markAcked,
    panel, setPanel, askAI, aiPrompt, clearAiPrompt, pageCtx, setPageCtx, alertDraft, setAlertDraft,
  }), [alertDraft, telemetry, link, lastUpdate, refresh, riskRes.data, riskRes.reload, riskRes.error, symRes.error, symRes.data, symRes.reload, symbol, setSymbol, draft,
    fired, lastAlert, firedRes.reload, markAcked, panel, askAI, aiPrompt, clearAiPrompt, pageCtx]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
