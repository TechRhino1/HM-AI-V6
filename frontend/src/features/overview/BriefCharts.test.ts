import { describe, expect, it } from "vitest";
import { briefModel } from "./BriefCharts";

describe("briefModel", () => {
  it("maps fact-sheet sections to chart rows without filling gaps", () => {
    const m = briefModel({
      global_cues: [{ name: "S&P 500", price: 7323.63, change_pct: -0.23 }, { name: "Nikkei 225", change_pct: null }],
      indices: { rows: [{ name: "NIFTY 50", last: 25313.3, change_pct: 0.34 }, { name: "NIFTY BANK", change_pct: "0.5" }] },
      vix: { value: 15.98, year_low: 8.72, year_high: 28.91, change_pct: 2.66 },
      fii_dii: { rows: [{ category: "FII/FPI", date: "18-Nov-2026", net_cr: 5866.78 }] },
      options_NIFTY: { spot: 25313.3, max_pain: 25200, expected_move: { lower_1sd: 24980.14, upper_1sd: 25682.26 }, pcr: { oi: 1.134 },
        walls: { resistance: [{ strike: 26000 }, { strike: 25500 }], support: [{ strike: 25000 }] } },
      options_SENSEX: { error: "timeout" },
    })!;
    expect(m.global.map((r) => [r.label, r.value])).toEqual([["S&P 500", -0.23], ["Nikkei 225", null]]);
    expect(m.indices.map((r) => [r.label, r.value])).toEqual([["NIFTY 50", 0.34], ["NIFTY BANK", 0.5]]);
    expect(m.vix).toMatchObject({ value: 15.98, lo: 8.72, hi: 28.91 });
    expect(m.flows[0]).toMatchObject({ label: "FII/FPI", value: 5866.78 });
    expect(m.strikes[0]).toMatchObject({ name: "NIFTY", spot: 25313.3, maxPain: 25200, resistance: [26000, 25500], support: [25000], pcr: 1.134 });
    expect(m.strikes[1]).toEqual({ name: "SENSEX", unavailable: true });
  });

  it("handles a missing or empty sheet", () => {
    expect(briefModel(undefined)).toBeNull();
    const m = briefModel({ vix: { value: 15 } })!;
    expect(m.vix).toBeUndefined();
    expect(m.global).toEqual([]);
  });
});
