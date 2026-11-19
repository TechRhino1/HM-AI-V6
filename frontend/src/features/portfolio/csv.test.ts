import { describe, expect, it } from "vitest";
import { toCsv } from "./csv";

describe("toCsv", () => {
  it("unions columns, quotes separators and keeps negative numbers", () => {
    const out = toCsv([{ symbol: "EURUSD", pnl: -1.5 }, { symbol: 'A,"B"', note: "x\ny" }]);
    expect(out.split("\r\n")).toEqual(["symbol,pnl,note", "EURUSD,-1.5,", '"A,""B""",,"x\ny"']);
  });

  it("neutralises spreadsheet formulas from broker text", () => {
    expect(toCsv([{ comment: "=HYPERLINK(1)" }])).toBe("comment\r\n'=HYPERLINK(1)");
  });
});
