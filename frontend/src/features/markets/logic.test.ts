import { describe, expect, it } from "vitest";
import { addLeg, aroundAtm, isMissingEndpoint, legsParam, provLabel, sortRows } from "./logic";

describe("provLabel", () => {
  it("labels live data with its age", () => {
    expect(provLabel({ kind: "live", age_sec: 4.2 })).toMatchObject({ text: "live · 4s", tone: "up" });
    expect(provLabel({ kind: "live", age_sec: 82.5 }).text).toBe("live · 1m");
  });
  it("labels delayed, stale, close and eod", () => {
    expect(provLabel({ kind: "delayed", delay_sec: 900 }).text).toBe("delayed 15m");
    expect(provLabel({ kind: "stale", age_sec: 180 })).toMatchObject({ text: "stale · 3m", tone: "warn" });
    expect(provLabel({ kind: "eod", as_of: 1794853800 }).text).toMatch(/^EOD \d\d \w{3}/);
    expect(provLabel({ kind: "close", as_of: 1794949200 }).text).toMatch(/^close · \d\d \w{3}/);
  });
  it("treats missing or unknown provenance as unavailable, never live", () => {
    expect(provLabel(undefined)).toMatchObject({ text: "unavailable", kind: "unavailable" });
    expect(provLabel({ kind: "weird" }).kind).toBe("unavailable");
  });
});

describe("legs", () => {
  it("builds the evaluate query string", () => {
    expect(legsParam([
      { strike: 25200, type: "CE", side: "BUY", lots: 1 },
      { strike: 25400, type: "CE", side: "SELL", lots: 2 },
    ])).toBe("25200:CE:BUY:1,25400:CE:SELL:2");
  });
  it("drops zero-lot legs and merges duplicates", () => {
    let legs = addLeg([], { strike: 100, type: "PE", side: "SELL", lots: 1 });
    legs = addLeg(legs, { strike: 100, type: "PE", side: "SELL", lots: 1 });
    legs = addLeg(legs, { strike: 100, type: "PE", side: "BUY", lots: 0 });
    expect(legs).toHaveLength(2);
    expect(legsParam(legs)).toBe("100:PE:SELL:2");
  });
});

describe("sortRows / aroundAtm / isMissingEndpoint", () => {
  it("puts missing values last in both directions", () => {
    const rows = [{ v: 2 }, { v: null }, { v: 5 }];
    expect(sortRows(rows, (r) => r.v, true).map((r) => r.v)).toEqual([5, 2, null]);
    expect(sortRows(rows, (r) => r.v, false).map((r) => r.v)).toEqual([2, 5, null]);
  });
  it("windows strikes around ATM", () => {
    const rows = Array.from({ length: 50 }, (_, i) => ({ strike: 100 + i * 10 }));
    const w = aroundAtm(rows, 352, 2);
    expect(w.map((r) => r.strike)).toEqual([330, 340, 350, 360, 370]);
    expect(aroundAtm(rows, 100, 2)).toHaveLength(3);
  });
  it("recognises a not-yet-deployed endpoint", () => {
    expect(isMissingEndpoint("404 Not Found")).toBe(true);
    expect(isMissingEndpoint("500 Internal Server Error")).toBe(false);
    expect(isMissingEndpoint(null)).toBe(false);
  });
});
