// Pure helpers for the Markets section (provenance labels, option-leg strings, sorting).
import { isNum, parseTime } from "../../lib/format";

export interface Prov {
  source?: string; kind?: string; as_of?: number | string | null; age_sec?: number | null;
  delay_sec?: number | null; note?: string; fetched_at?: number | null;
}
export type ProvTone = "up" | "accent" | "flat" | "warn";

export const shortAge = (sec: unknown) => {
  if (!isNum(sec)) return "";
  const s = Math.max(0, sec);
  return s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.round(s / 60)}m` : s < 86400 ? `${Math.round(s / 3600)}h` : `${Math.round(s / 86400)}d`;
};

const shortDate = (v: unknown) => {
  const d = parseTime(v);
  return d ? d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" }) : "";
};

/** Badge text + tone for a provenance record. Missing prov counts as unavailable, never as live. */
export function provLabel(p?: Prov | null): { text: string; tone: ProvTone; kind: string } {
  const kind = (p?.kind || "unavailable").toLowerCase();
  const age = shortAge(p?.age_sec);
  switch (kind) {
    case "live": return { kind, tone: "up", text: age ? `live · ${age}` : "live" };
    case "delayed": {
      const m = isNum(p?.delay_sec) ? Math.round(p!.delay_sec! / 60) : null;
      return { kind, tone: "accent", text: m ? `delayed ${m}m` : "delayed" };
    }
    case "close": return { kind, tone: "flat", text: `close${shortDate(p?.as_of) ? ` · ${shortDate(p?.as_of)}` : ""}` };
    case "eod": return { kind, tone: "flat", text: `EOD${shortDate(p?.as_of) ? ` ${shortDate(p?.as_of)}` : ""}` };
    case "stale": return { kind, tone: "warn", text: age ? `stale · ${age}` : "stale" };
    default: return { kind: "unavailable", tone: "flat", text: "unavailable" };
  }
}

export interface Leg { strike: number; type: "CE" | "PE"; side: "BUY" | "SELL"; lots: number }

/** Adds a leg, merging into an existing identical strike/type/side by adding lots. */
export function addLeg(legs: Leg[], leg: Leg): Leg[] {
  const i = legs.findIndex((l) => l.strike === leg.strike && l.type === leg.type && l.side === leg.side);
  if (i < 0) return [...legs, leg];
  return legs.map((l, j) => (j === i ? { ...l, lots: l.lots + leg.lots } : l));
}

/** `legs=` query value for /api/markets/fno/evaluate: strike:CE|PE:BUY|SELL:lots, comma separated. */
export const legsParam = (legs: Leg[]) =>
  legs.filter((l) => l.lots > 0 && isNum(l.strike)).map((l) => `${l.strike}:${l.type}:${l.side}:${Math.round(l.lots)}`).join(",");

/** Sort by a key; nulls/unavailable values always go last regardless of direction. */
export function sortRows<T>(rows: T[], key: (r: T) => unknown, desc: boolean): T[] {
  return [...rows].sort((a, b) => {
    const x = key(a), y = key(b);
    const xn = x === null || x === undefined || x === "", yn = y === null || y === undefined || y === "";
    if (xn || yn) return xn === yn ? 0 : xn ? 1 : -1;
    const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
    return desc ? -c : c;
  });
}

/** Strikes within ±n rows of the one closest to ATM. */
export function aroundAtm<T extends { strike: number }>(rows: T[], atm: unknown, n = 15): T[] {
  if (!rows.length || !isNum(atm)) return rows.slice(0, 2 * n + 1);
  let best = 0;
  rows.forEach((r, i) => { if (Math.abs(r.strike - atm) < Math.abs(rows[best].strike - atm)) best = i; });
  return rows.slice(Math.max(0, best - n), best + n + 1);
}

/** API errors that mean "route not deployed yet" rather than a data failure. */
export const isMissingEndpoint = (err: string | null) => !!err && /^(404|501)\b|not found/i.test(err);
