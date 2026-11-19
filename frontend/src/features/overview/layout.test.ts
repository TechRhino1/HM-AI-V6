import { describe, expect, it } from "vitest";
import {
  DEFAULT_LAYOUT, filterTimeline, LAYOUT_KEY, loadLayout, move, moveTo, normalize, resetLayout, saveLayout, setHidden, toggleSpan,
  type TimelineEvent,
} from "./layout";

const mem = () => {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k), m };
};
const ids = (l: { id: string }[]) => l.map((w) => w.id);

describe("overview layout", () => {
  it("defaults when nothing or garbage is stored", () => {
    expect(loadLayout(mem())).toEqual(DEFAULT_LAYOUT);
    const s = mem(); s.setItem(LAYOUT_KEY, "{not json");
    expect(loadLayout(s)).toEqual(DEFAULT_LAYOUT);
  });

  it("persists order, visibility and width and survives a reload", () => {
    const s = mem();
    let l = move(DEFAULT_LAYOUT, "kpis", -1);
    l = setHidden(l, "hours", true);
    l = toggleSpan(l, "since");
    saveLayout(l, s);
    const back = loadLayout(s);
    expect(ids(back).slice(0, 2)).toEqual(["kpis", "today"]);
    expect(back.find((w) => w.id === "hours")!.hidden).toBe(true);
    expect(back.find((w) => w.id === "since")!.span).toBe(2);
  });

  it("reset clears storage and restores defaults", () => {
    const s = mem();
    saveLayout(setHidden(DEFAULT_LAYOUT, "today", true), s);
    expect(resetLayout(s)).toEqual(DEFAULT_LAYOUT);
    expect(s.m.has(LAYOUT_KEY)).toBe(false);
  });

  it("drops unknown ids and duplicates, appends widgets added later", () => {
    const l = normalize([{ id: "hours", hidden: false, span: 1 }, { id: "nope" }, { id: "hours", span: 2 }]);
    expect(l[0]).toEqual({ id: "hours", hidden: false, span: 1 });
    expect(ids(l)).toHaveLength(DEFAULT_LAYOUT.length);
    expect(new Set(ids(l)).size).toBe(DEFAULT_LAYOUT.length);
  });

  it("moves skip hidden widgets and stop at the ends", () => {
    let l = setHidden(setHidden(DEFAULT_LAYOUT, "kpis", true), "attention", true);
    l = move(l, "since", -1);                       // jumps over hidden attention + kpis to before today
    expect(ids(l).slice(0, 3)).toEqual(["since", "today", "kpis"]);
    expect(move(l, "since", -1)).toBe(l);
    const last = ids(l)[l.length - 1] as any;
    expect(move(l, last, 1)).toBe(l);
  });

  it("drag-and-drop puts the widget at the target's slot", () => {
    expect(ids(moveTo(DEFAULT_LAYOUT, "hours", "today"))[0]).toBe("hours");
    const down = ids(moveTo(DEFAULT_LAYOUT, "today", "since"));
    expect(down.indexOf("today")).toBe(down.indexOf("since") + 1);
  });
});

describe("timeline filtering", () => {
  const ev = (kind: TimelineEvent["kind"], symbol: string | null, title: string = kind): TimelineEvent => ({ ts: 1, kind, symbol, title, detail: "", link: "" });
  const all = [ev("trade", "XAUUSD"), ev("alert", null, "NIFTY spot crossed 25000"), ev("brief", null), ev("recommendation", "FINNIFTY"), ev("signal", "EURUSD")];

  it("keeps only the kinds whose chips are on", () => {
    expect(filterTimeline(all, ["trades", "signals"]).map((e) => e.kind)).toEqual(["trade", "signal"]);
    expect(filterTimeline(all, ["briefs"]).map((e) => e.kind)).toEqual(["brief", "recommendation"]);
    expect(filterTimeline(all, [])).toEqual([]);
  });

  it("narrows by symbol, matching the title when an event has no symbol", () => {
    const on = ["trades", "alerts", "briefs", "signals"];
    expect(filterTimeline(all, on, "xau").map((e) => e.kind)).toEqual(["trade"]);
    expect(filterTimeline(all, on, "nifty").map((e) => e.kind)).toEqual(["alert", "recommendation"]);
  });
});
