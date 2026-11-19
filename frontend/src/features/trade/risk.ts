// Money-at-risk maths for the order ticket. Value of a move = ticks moved × tick value × lots.

export interface PreviewIn {
  side: "BUY" | "SELL"; entry: number; sl: number; tp: number; lots: number;
  tickSize?: number; tickValue?: number; equity?: number;
}

export function riskPreview(p: PreviewIn) {
  const ok = p.entry > 0 && !!p.tickSize && !!p.tickValue && p.lots > 0;
  const perUnit = ok ? (p.tickValue! / p.tickSize!) * p.lots : 0;
  const slWrongSide = p.sl > 0 && p.entry > 0 && (p.side === "BUY" ? p.sl >= p.entry : p.sl <= p.entry);
  const tpWrongSide = p.tp > 0 && p.entry > 0 && (p.side === "BUY" ? p.tp <= p.entry : p.tp >= p.entry);
  const riskMoney = ok && p.sl > 0 && !slWrongSide ? Math.abs(p.entry - p.sl) * perUnit : undefined;
  const rewardMoney = ok && p.tp > 0 && !tpWrongSide ? Math.abs(p.tp - p.entry) * perUnit : undefined;
  return {
    riskMoney,
    rewardMoney,
    riskPct: riskMoney !== undefined && p.equity ? (riskMoney / p.equity) * 100 : undefined,
    rr: riskMoney && rewardMoney ? rewardMoney / riskMoney : undefined,
    slWrongSide,
    tpWrongSide,
  };
}

export type SizeResult =
  | { ok: true; lots: number }
  | { ok: false; reason: "inputs" } // missing entry/stop/contract data
  | { ok: false; reason: "below_min"; minLots: number; minLotRisk: number };

/** Largest volume (rounded DOWN to the broker step, capped at max) whose stop-out loses at most
 *  riskMoney. Never rounds up to the minimum lot: that would silently break the risk limit. */
export function sizeForRisk(p: { entry: number; sl: number; riskMoney: number; tickSize?: number; tickValue?: number; step?: number; min?: number; max?: number }): SizeResult {
  if (!(p.entry > 0 && p.sl > 0 && p.riskMoney > 0 && p.tickSize && p.tickValue)) return { ok: false, reason: "inputs" };
  const lossPerLot = (Math.abs(p.entry - p.sl) / p.tickSize) * p.tickValue;
  if (lossPerLot <= 0) return { ok: false, reason: "inputs" };
  const step = p.step || 0.01;
  const min = p.min || step;
  const decimals = Math.max(0, Math.ceil(-Math.log10(step) - 1e-9));
  const raw = Math.floor(p.riskMoney / lossPerLot / step + 1e-9) * step;
  if (raw < min - 1e-12) return { ok: false, reason: "below_min", minLots: min, minLotRisk: lossPerLot * min };
  return { ok: true, lots: Number(Math.min(p.max || Infinity, raw).toFixed(decimals)) };
}
