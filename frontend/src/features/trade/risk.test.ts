import { describe, expect, it } from "vitest";
import { riskPreview, sizeForRisk } from "./risk";

// XM gold per MT5: tick_size 0.01, tick_value 1.0 per lot → $1 per 0.01 lot per $1 move.
const GOLD = { tickSize: 0.01, tickValue: 1.0 };
// EURUSD: tick 0.00001 worth $1 per lot.
const EUR = { tickSize: 0.00001, tickValue: 1.0 };

describe("riskPreview", () => {
  it("prices a gold sell stop like MT5 (0.01 lot, $46.26 move = $46.26)", () => {
    const r = riskPreview({ side: "SELL", entry: 3792.8, sl: 3839.06, tp: 3731.26, lots: 0.01, ...GOLD, equity: 522 });
    expect(r.riskMoney).toBeCloseTo(46.26, 2);
    expect(r.rewardMoney).toBeCloseTo(61.54, 2);
    expect(r.riskPct).toBeCloseTo(8.86, 2);
    expect(r.rr).toBeCloseTo(1.33, 2);
  });

  it("flags stops and targets on the wrong side and does not price them", () => {
    const r = riskPreview({ side: "BUY", entry: 1.1, sl: 1.11, tp: 1.09, lots: 0.1, ...EUR });
    expect(r.slWrongSide).toBe(true);
    expect(r.tpWrongSide).toBe(true);
    expect(r.riskMoney).toBeUndefined();
  });
});

describe("sizeForRisk", () => {
  it("rounds down to the volume step", () => {
    // 20 pip stop on EURUSD = $200/lot; $55 risk → 0.275 → 0.27 lots.
    const r = sizeForRisk({ entry: 1.1, sl: 1.098, riskMoney: 55, ...EUR, step: 0.01, min: 0.01 });
    expect(r).toEqual({ ok: true, lots: 0.27 });
  });

  it("refuses instead of rounding up to the minimum lot", () => {
    // Gold, $46.26 stop at 0.01 lot; 0.5% of $522 = $2.61 is below what the minimum lot risks.
    const r = sizeForRisk({ entry: 3792.8, sl: 3839.06, riskMoney: 2.61, ...GOLD, step: 0.01, min: 0.01 });
    if (r.ok || r.reason !== "below_min") throw new Error("expected below_min");
    expect(r.minLotRisk).toBeCloseTo(46.26, 2);
  });

  it("caps at the broker maximum", () => {
    const r = sizeForRisk({ entry: 1.1, sl: 1.0999, riskMoney: 1e6, ...EUR, step: 0.01, min: 0.01, max: 50 });
    expect(r).toEqual({ ok: true, lots: 50 });
  });

  it("needs a stop and contract data", () => {
    expect(sizeForRisk({ entry: 1.1, sl: 0, riskMoney: 10, ...EUR })).toEqual({ ok: false, reason: "inputs" });
  });
});
