import { useEffect, useRef } from "react";
import { useStore } from "../../state/store";
import { useFeedback } from "../../components/feedback";
import { cleanSymbol, signedMoney } from "../../lib/format";

export const NOTIFY_KEY = "hm.notify";

export const notificationsEnabled = () => {
  try {
    return localStorage.getItem(NOTIFY_KEY) === "1" && typeof Notification !== "undefined" && Notification.permission === "granted";
  } catch {
    return false;
  }
};

/** Toasts (and optional desktop notifications) when positions open or close, the circuit breaker trips, or a market alert fires. */
export function useTradeAlerts() {
  const { telemetry, risk, lastAlert } = useStore();
  const { toast } = useFeedback();
  const prev = useRef<Map<number, { symbol: string; type: string; profit: number }> | null>(null);
  const prevCb = useRef<boolean | null>(null);

  const notify = (title: string, body: string, tone: "up" | "down" | "info") => {
    toast(tone, title, body);
    if (notificationsEnabled() && document.hidden) {
      try { new Notification(title, { body, tag: title }); } catch { /* unsupported context */ }
    }
  };

  useEffect(() => {
    const positions = telemetry?.positions;
    if (!positions) return;
    const now = new Map(positions.map((p) => [p.ticket, { symbol: cleanSymbol(p.symbol), type: p.type, profit: p.profit }]));
    if (prev.current) {
      for (const [t, p] of now) if (!prev.current.has(t)) notify(`${p.type} ${p.symbol} opened`, `Ticket ${t}`, "info");
      for (const [t, p] of prev.current)
        if (!now.has(t)) notify(`${p.symbol} closed`, `Last P&L ${signedMoney(p.profit)} · ticket ${t}`, p.profit >= 0 ? "up" : "down");
    }
    prev.current = now;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [telemetry?.positions]);

  useEffect(() => {
    if (!risk) return;
    if (prevCb.current === false && risk.circuit_breaker_active) notify("Circuit breaker tripped", risk.circuit_breaker_reason || "New entries are paused", "down");
    prevCb.current = risk.circuit_breaker_active;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [risk?.circuit_breaker_active]);

  useEffect(() => {
    if (lastAlert) notify(`Alert · ${lastAlert.type.replace(/_/g, " ")}`, lastAlert.message, "info");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastAlert?.id]);
}
