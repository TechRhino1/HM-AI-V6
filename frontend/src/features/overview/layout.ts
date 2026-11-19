/** Overview widget layout (order, visibility, width) kept per browser in localStorage, plus timeline filtering. */

export type WidgetId =
  | "today" | "kpis" | "attention" | "since" | "positions" | "timeline" | "guardrails" | "exposure"
  | "trades" | "pulse" | "watchlist" | "hours";

export const WIDGETS: Record<WidgetId, string> = {
  today: "Today", kpis: "Account KPIs", attention: "Needs attention", since: "Since you last looked", positions: "Positions", timeline: "Today timeline",
  guardrails: "Risk guardrails", exposure: "Exposure", trades: "Today's closed trades", pulse: "Market pulse",
  watchlist: "Watchlist", hours: "Market hours",
};

export interface WidgetState { id: WidgetId; hidden: boolean; span: 1 | 2 }
export const LAYOUT_KEY = "hm.overview.layout";

export const DEFAULT_LAYOUT: WidgetState[] = ([
  ["today", 2], ["kpis", 2], ["attention", 2], ["since", 1], ["positions", 1], ["timeline", 1], ["pulse", 1],
  ["guardrails", 1], ["exposure", 1], ["trades", 1], ["watchlist", 1], ["hours", 2],
] as [WidgetId, 1 | 2][]).map(([id, span]) => ({ id, hidden: false, span }));

/** Saved layout merged with the defaults: unknown ids dropped, widgets added in a later release appended. */
export function normalize(saved: unknown): WidgetState[] {
  const rows = Array.isArray(saved) ? saved : [];
  const seen = new Set<string>();
  const out: WidgetState[] = [];
  for (const r of rows) {
    if (!r || typeof r !== "object" || !((r as WidgetState).id in WIDGETS) || seen.has((r as WidgetState).id)) continue;
    const w = r as WidgetState;
    seen.add(w.id);
    out.push({ id: w.id, hidden: !!w.hidden, span: w.span === 1 ? 1 : 2 });
  }
  return [...out, ...DEFAULT_LAYOUT.filter((d) => !seen.has(d.id))];
}

export function loadLayout(store: Pick<Storage, "getItem"> | undefined = globalThis.localStorage): WidgetState[] {
  try {
    const raw = store?.getItem(LAYOUT_KEY);
    return normalize(raw ? JSON.parse(raw) : null);
  } catch {
    return normalize(null);
  }
}

export function saveLayout(l: WidgetState[], store: Pick<Storage, "setItem" | "removeItem"> | undefined = globalThis.localStorage) {
  try { store?.setItem(LAYOUT_KEY, JSON.stringify(l)); } catch { /* storage blocked: layout lives in memory */ }
}

export function resetLayout(store: Pick<Storage, "setItem" | "removeItem"> | undefined = globalThis.localStorage): WidgetState[] {
  try { store?.removeItem(LAYOUT_KEY); } catch { /* storage blocked */ }
  return normalize(null);
}

/** Move a widget by `delta` places among the visible ones (hidden widgets keep their slots). */
export function move(l: WidgetState[], id: WidgetId, delta: number): WidgetState[] {
  const vis = l.filter((w) => !w.hidden).map((w) => w.id);
  const i = vis.indexOf(id), j = i + delta;
  if (i < 0 || j < 0 || j >= vis.length) return l;
  return moveTo(l, id, vis[j]);
}

/** Drag-and-drop: put `id` where `target` is (before it when moving up, after it when moving down). */
export function moveTo(l: WidgetState[], id: WidgetId, target: WidgetId): WidgetState[] {
  const from = l.findIndex((w) => w.id === id), to = l.findIndex((w) => w.id === target);
  if (from < 0 || to < 0 || from === to) return l;
  const next = l.slice();
  const [w] = next.splice(from, 1);
  next.splice(to, 0, w);
  return next;
}

export const setHidden = (l: WidgetState[], id: WidgetId, hidden: boolean) => l.map((w) => (w.id === id ? { ...w, hidden } : w));
export const toggleSpan = (l: WidgetState[], id: WidgetId) => l.map((w) => (w.id === id ? { ...w, span: (w.span === 2 ? 1 : 2) as 1 | 2 } : w));

// ---------------------------------------------------------------- timeline

export type TimelineKind = "trade" | "alert" | "brief" | "signal" | "recommendation";
export interface TimelineEvent {
  ts: number; kind: TimelineKind; symbol?: string | null; title: string; detail: string; link: string;
  prov?: { source?: string; kind?: string; as_of?: number | string | null; note?: string };
}
/** Filter chips: "briefs" also covers adviser recommendations (both are written AI/adviser output). */
export const FILTERS: { id: string; label: string; kinds: TimelineKind[] }[] = [
  { id: "trades", label: "Trades", kinds: ["trade"] },
  { id: "alerts", label: "Alerts", kinds: ["alert"] },
  { id: "briefs", label: "Briefs & adviser", kinds: ["brief", "recommendation"] },
  { id: "signals", label: "Signals", kinds: ["signal"] },
];

export function filterTimeline(events: TimelineEvent[], on: string[], symbol = ""): TimelineEvent[] {
  const kinds = new Set(FILTERS.filter((f) => on.includes(f.id)).flatMap((f) => f.kinds));
  const s = symbol.trim().toUpperCase();
  return events.filter((e) => kinds.has(e.kind) && (!s || (e.symbol || "").toUpperCase().includes(s) || e.title.toUpperCase().includes(s)));
}
