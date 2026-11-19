// Broker order basket for an adviser plan (Kite-style JSON). Pure; the UI copies it, nothing is ever sent.

export interface BasketOrder {
  exchange: "NFO" | "BFO"; tradingsymbol: string; transaction_type: "BUY" | "SELL"; quantity: number;
  order_type: "LIMIT"; price: number; product: "NRML";
}
export interface BasketLeg { strike: number; type: "CE" | "PE"; side: "BUY" | "SELL"; lots: number; price?: number | null }

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const WEEKLY_MONTH = "123456789OND";

/** "23-Nov-2026" → {d, m (0-11), y}; null when it is not that format. */
export function parseExpiry(s: string): { d: number; m: number; y: number } | null {
  const x = /^(\d{1,2})-([A-Za-z]{3})-(\d{4})$/.exec(s.trim());
  if (!x) return null;
  const m = MONTHS.indexOf(x[2].toUpperCase());
  return m < 0 ? null : { d: Number(x[1]), m, y: Number(x[3]) };
}

/** Monthly = the last listed expiry in its calendar month. */
export function isMonthly(expiry: string, expiries: string[]): boolean {
  const e = parseExpiry(expiry);
  if (!e) return false;
  return !expiries.some((o) => { const p = parseExpiry(o); return p && p.y === e.y && p.m === e.m && p.d > e.d; });
}

export const exchangeOf = (symbol: string): "NFO" | "BFO" => (/^(SENSEX|BANKEX)/i.test(symbol) ? "BFO" : "NFO");

/**
 * NSE/BSE option tradingsymbol.
 * Monthly: SYMBOL + YY + MON + STRIKE + CE|PE (NIFTY26NOV25300CE).
 * Weekly:  SYMBOL + YY + M + DD + STRIKE + CE|PE, M = 1-9, O, N, D (NIFTY26D0125300CE for 01-Dec-2026).
 */
export function tradingSymbol(symbol: string, expiry: string, strike: number, type: "CE" | "PE", expiries: string[]): string | null {
  const e = parseExpiry(expiry);
  if (!e || !Number.isFinite(strike)) return null;
  const yy = String(e.y % 100).padStart(2, "0");
  const k = String(Number(strike.toFixed(2)));
  const mid = isMonthly(expiry, expiries) ? MONTHS[e.m] : `${WEEKLY_MONTH[e.m]}${String(e.d).padStart(2, "0")}`;
  return `${symbol.toUpperCase()}${yy}${mid}${k}${type}`;
}

/** Orders for every leg, or an error naming what is missing (never a guessed contract). */
export function buildBasket(symbol: string, expiry: string, expiries: string[], lotSize: number | undefined, legs: BasketLeg[]):
  { orders: BasketOrder[]; error?: undefined } | { orders?: undefined; error: string } {
  if (!lotSize || !Number.isFinite(lotSize)) return { error: "lot size unavailable" };
  if (!legs.length) return { error: "no legs" };
  const orders: BasketOrder[] = [];
  for (const l of legs) {
    const ts = tradingSymbol(symbol, expiry, l.strike, l.type, expiries);
    if (!ts) return { error: `cannot form a contract for expiry "${expiry}"` };
    if (typeof l.price !== "number" || !Number.isFinite(l.price)) return { error: `no live price for ${ts}` };
    orders.push({ exchange: exchangeOf(symbol), tradingsymbol: ts, transaction_type: l.side, quantity: Math.round(l.lots) * lotSize,
      order_type: "LIMIT", price: Math.round(l.price * 20) / 20, product: "NRML" });
  }
  return { orders };
}

export const basketText = (orders: BasketOrder[]) =>
  orders.map((o) => `${o.transaction_type} ${o.quantity} ${o.exchange}:${o.tradingsymbol} LIMIT ${o.price.toFixed(2)} ${o.product}`).join("\n");
