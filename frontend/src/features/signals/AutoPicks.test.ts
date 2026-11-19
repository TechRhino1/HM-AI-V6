import { describe, expect, it } from "vitest";
import { autoRow, type AutoRow } from "./AutoPicks";

const row = (o: Partial<AutoRow> = {}): AutoRow => ({
  symbol: "EURUSD", action: "TRADE", live: false,
  pick: { style: "DAY_TRADING", strategy: "TREND", n: 24, expectancy_r: 0.31, bias: "BUY" },
  news: { state: "CAUTION", size_mult: 0.5, blocked_directions: [], reasons: ["High-impact USD CPI in 60m; half size"] },
  ...o,
});

describe("autoRow", () => {
  it("labels shadow vs live and shows the size cut", () => {
    expect(autoRow(row()).actionLabel).toBe("Would trade");
    expect(autoRow(row({ live: true })).actionLabel).toBe("Trade");
    const m = autoRow(row());
    expect([m.newsTone, m.size, m.style, m.record]).toEqual(["warn", "50% size", "day trading", "24 live trades, 0.31R avg"]);
  });

  it("marks news vetoes and empty picks", () => {
    const v = autoRow(row({ action: "VETO", news: { state: "BLOCK", size_mult: 0, blocked_directions: ["BUY", "SELL"], reasons: ["CPI in 10m"] } }));
    expect([v.actionLabel, v.actionTone, v.newsTone, v.size]).toEqual(["Vetoed by news", "down", "down", null]);
    const s = autoRow(row({ action: "SKIP", pick: { reason: "no actionable setup" } }));
    expect([s.actionLabel, s.style, s.record]).toEqual(["No pick", null, "no actionable setup"]);
  });
});
