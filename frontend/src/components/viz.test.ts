import { describe, expect, it } from "vitest";
import { arcPoint, levelOf, pushSample, waterfallSteps } from "./viz";

describe("viz helpers", () => {
  it("levels match the guardrail thresholds", () => {
    expect(levelOf(1, 3)).toBe("good");
    expect(levelOf(1.5, 3)).toBe("warn");
    expect(levelOf(2.5, 3)).toBe("danger");
  });

  it("arc runs left → top → right and clamps", () => {
    const close = (a: number[], b: number[]) => a.forEach((v, i) => expect(v).toBeCloseTo(b[i], 6));
    close(arcPoint(0), [10, 50]);
    close(arcPoint(0.5), [50, 10]);
    close(arcPoint(1), [90, 50]);
    close(arcPoint(2), [90, 50]);
  });

  it("waterfall keeps a running total", () => {
    const s = waterfallSteps([{ label: "a", pnl: 10 }, { label: "b", pnl: -4 }, { label: "c", pnl: 1 }]);
    expect(s.map((x) => [x.start, x.end])).toEqual([[0, 10], [10, 6], [6, 7]]);
  });

  it("session buffer skips repeats and non-finite values and caps length", () => {
    const b: { t: number; v: number }[] = [];
    pushSample(b, 1, 100); pushSample(b, 1, 101); pushSample(b, 2, NaN); pushSample(b, 3, 102, 1);
    expect(b).toEqual([{ t: 3, v: 102 }]);
  });
});
