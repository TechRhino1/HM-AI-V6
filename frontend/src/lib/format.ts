const nf = (min: number, max: number) => new Intl.NumberFormat(undefined, { minimumFractionDigits: min, maximumFractionDigits: max });

export const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export const money = (v: unknown, ccy = "USD") =>
  isNum(v) ? new Intl.NumberFormat(undefined, { style: "currency", currency: ccy || "USD", maximumFractionDigits: 2 }).format(v) : "—";

export const signedMoney = (v: unknown, ccy = "USD") => (isNum(v) ? (v > 0 ? "+" : "") + money(v, ccy) : "—");

export const num = (v: unknown, digits = 2) => (isNum(v) ? nf(0, digits).format(v) : "—");

export const fixed = (v: unknown, digits = 2) => (isNum(v) ? nf(digits, digits).format(v) : "—");

export const pct = (v: unknown, digits = 1) => (isNum(v) ? `${nf(0, digits).format(v)}%` : "—");

export const price = (v: unknown, digits?: number) => {
  if (!isNum(v)) return "—";
  const d = digits ?? (Math.abs(v) >= 1000 ? 2 : Math.abs(v) >= 10 ? 3 : 5);
  return v.toFixed(d);
};

export const rMult = (v: unknown) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(2)}R` : "—");

export const tone = (v: unknown): "up" | "down" | "flat" => (isNum(v) ? (v > 0 ? "up" : v < 0 ? "down" : "flat") : "flat");

/** Server timestamps are ISO, epoch seconds, or 'YYYY-MM-DD HH:MM:SS' (treated as UTC). */
export const parseTime = (v: unknown): Date | null => {
  if (typeof v === "number") return new Date(v < 1e12 ? v * 1000 : v);
  if (typeof v !== "string" || !v) return null;
  const s = /[zZ]$|[+-]\d\d:?\d\d$/.test(v) ? v : v.replace(" ", "T") + "Z";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
};

export const dateTime = (v: unknown) => {
  const d = parseTime(v);
  return d ? d.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";
};

export const ago = (v: unknown) => {
  const d = parseTime(v);
  if (!d) return "—";
  const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
};

export const duration = (seconds: unknown) => {
  if (!isNum(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
};

/** Broker names carry suffixes (EURUSD#, GOLD.i#); show the canonical part. */
export const cleanSymbol = (s: unknown) => (typeof s === "string" ? s.replace(/[#.].*$/, "") : "");
