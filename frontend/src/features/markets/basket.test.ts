import { describe, expect, it } from "vitest";
import { basketText, buildBasket, exchangeOf, isMonthly, tradingSymbol } from "./basket";

const NIFTY = ["23-Nov-2026", "01-Dec-2026", "08-Dec-2026", "15-Dec-2026", "22-Dec-2026", "29-Dec-2026", "25-Jan-2027"];

describe("tradingSymbol", () => {
  it("uses the monthly format for the last expiry of a month", () => {
    expect(isMonthly("23-Nov-2026", NIFTY)).toBe(true);
    expect(isMonthly("29-Dec-2026", NIFTY)).toBe(true);
    expect(tradingSymbol("NIFTY", "23-Nov-2026", 25300, "CE", NIFTY)).toBe("NIFTY26NOV25300CE");
    expect(tradingSymbol("NIFTY", "29-Dec-2026", 25000, "PE", NIFTY)).toBe("NIFTY26DEC25000PE");
  });
  it("uses the weekly format otherwise, with 1-9/O/N/D month codes", () => {
    expect(isMonthly("01-Dec-2026", NIFTY)).toBe(false);
    expect(tradingSymbol("NIFTY", "01-Dec-2026", 25300, "CE", NIFTY)).toBe("NIFTY26D0125300CE");
    expect(tradingSymbol("NIFTY", "15-Dec-2026", 24500.5, "PE", NIFTY)).toBe("NIFTY26D1524500.5PE");
    const sx = ["06-Jan-2027", "13-Jan-2027", "07-Oct-2027", "14-Oct-2027", "04-Nov-2027", "11-Nov-2027"];
    expect(tradingSymbol("SENSEX", "06-Jan-2027", 82000, "CE", sx)).toBe("SENSEX2710682000CE");
    expect(tradingSymbol("SENSEX", "07-Oct-2027", 82000, "CE", sx)).toBe("SENSEX27O0782000CE");
    expect(tradingSymbol("SENSEX", "04-Nov-2027", 82000, "PE", sx)).toBe("SENSEX27N0482000PE");
  });
  it("refuses unparseable expiries", () => {
    expect(tradingSymbol("NIFTY", "2026-11-23", 25300, "CE", NIFTY)).toBeNull();
  });
});

describe("buildBasket", () => {
  it("builds Kite-style orders with lots × lot size", () => {
    const r = buildBasket("NIFTY", "23-Nov-2026", NIFTY, 65, [
      { strike: 25300, type: "CE", side: "SELL", lots: 2, price: 101.33 },
      { strike: 25500, type: "CE", side: "BUY", lots: 2, price: 40 },
    ]);
    expect(r.orders).toEqual([
      { exchange: "NFO", tradingsymbol: "NIFTY26NOV25300CE", transaction_type: "SELL", quantity: 130, order_type: "LIMIT", price: 101.35, product: "NRML" },
      { exchange: "NFO", tradingsymbol: "NIFTY26NOV25500CE", transaction_type: "BUY", quantity: 130, order_type: "LIMIT", price: 40, product: "NRML" },
    ]);
    expect(basketText(r.orders!)).toBe("SELL 130 NFO:NIFTY26NOV25300CE LIMIT 101.35 NRML\nBUY 130 NFO:NIFTY26NOV25500CE LIMIT 40.00 NRML");
  });
  it("routes SENSEX/BANKEX to BFO", () => {
    expect(exchangeOf("SENSEX")).toBe("BFO");
    expect(exchangeOf("BANKEX")).toBe("BFO");
    expect(exchangeOf("BANKNIFTY")).toBe("NFO");
  });
  it("errors instead of guessing when data is missing", () => {
    expect(buildBasket("NIFTY", "23-Nov-2026", NIFTY, undefined, [{ strike: 1, type: "CE", side: "BUY", lots: 1, price: 1 }]).error).toBe("lot size unavailable");
    expect(buildBasket("NIFTY", "23-Nov-2026", NIFTY, 65, [{ strike: 25300, type: "CE", side: "BUY", lots: 1, price: null }]).error).toMatch(/no live price/);
  });
});
