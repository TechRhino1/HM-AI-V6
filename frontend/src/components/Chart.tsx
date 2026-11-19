import { useEffect, useRef } from "react";
import {
  createChart, ColorType, CrosshairMode, IChartApi, IPriceLine, ISeriesApi, LineStyle, SeriesMarker, Time, UTCTimestamp,
} from "lightweight-charts";

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function baseOptions() {
  return {
    layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--text-3"), fontFamily: css("--font") },
    grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
    rightPriceScale: { borderColor: css("--line") },
    timeScale: { borderColor: css("--line"), timeVisible: true, secondsVisible: false },
    crosshair: { mode: CrosshairMode.Normal },
    autoSize: true,
  };
}

export interface Candle { time: number; open: number; high: number; low: number; close: number; volume?: number }
export interface PriceLevel { price: number; label: string; tone: "up" | "down" | "accent" | "warn" | "flat"; dashed?: boolean }

export function CandleChart({ candles, levels, markers, digits, tips }: {
  candles: Candle[]; levels: PriceLevel[]; markers?: SeriesMarker<Time>[]; digits?: number;
  /** Hover text per bar time (epoch s), e.g. a pattern marker's historical stats. */
  tips?: Map<number, string>;
}) {
  const box = useRef<HTMLDivElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const tipsRef = useRef(tips);
  tipsRef.current = tips;
  const chart = useRef<IChartApi>();
  const series = useRef<ISeriesApi<"Candlestick">>();
  const vol = useRef<ISeriesApi<"Histogram">>();
  const lines = useRef<IPriceLine[]>([]);
  const fitted = useRef(false);

  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, baseOptions());
    const up = css("--up"), down = css("--down");
    series.current = c.addCandlestickSeries({ upColor: up, downColor: down, wickUpColor: up, wickDownColor: down, borderVisible: false });
    vol.current = c.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, color: css("--surface-3") });
    c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    chart.current = c;
    c.subscribeCrosshairMove((p) => {
      const el = tip.current;
      const text = p.time !== undefined ? tipsRef.current?.get(p.time as number) : undefined;
      if (!el) return;
      if (!text || !p.point) { el.style.display = "none"; return; }
      el.textContent = text;
      el.style.display = "block";
      el.style.left = `${Math.max(4, Math.min(p.point.x + 12, (box.current?.clientWidth || 300) - 244))}px`;
      el.style.top = `${Math.max(4, p.point.y - 40)}px`;
    });
    const obs = new MutationObserver(() => c.applyOptions(baseOptions()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      obs.disconnect();
      c.remove();
      chart.current = undefined;
      fitted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!series.current || !vol.current) return;
    const data = candles.map((k) => ({ time: k.time as UTCTimestamp, open: k.open, high: k.high, low: k.low, close: k.close }));
    series.current.setData(data);
    vol.current.setData(candles.map((k) => ({
      time: k.time as UTCTimestamp, value: k.volume || 0,
      color: k.close >= k.open ? css("--up-soft") : css("--down-soft"),
    })));
    if (digits !== undefined) series.current.applyOptions({ priceFormat: { type: "price", precision: digits, minMove: 1 / 10 ** digits } });
    if (!fitted.current && data.length) {
      chart.current?.timeScale().fitContent();
      fitted.current = true;
    }
  }, [candles, digits]);

  useEffect(() => {
    const s = series.current;
    if (!s) return;
    lines.current.forEach((l) => s.removePriceLine(l));
    const color = (t: PriceLevel["tone"]) => css(t === "accent" ? "--accent" : t === "flat" ? "--text-3" : `--${t}`);
    lines.current = levels.filter((l) => l.price > 0).map((l) =>
      s.createPriceLine({ price: l.price, color: color(l.tone), lineWidth: 1, lineStyle: l.dashed ? LineStyle.Dashed : LineStyle.Solid, axisLabelVisible: true, title: l.label }));
  }, [levels, candles]);

  useEffect(() => {
    // Only markers on a bar the chart actually has (overlays may span more history than is drawn).
    const have = new Set(candles.map((k) => k.time));
    series.current?.setMarkers((markers || []).filter((m) => have.has(m.time as number)));
  }, [markers, candles]);

  return <div ref={box} className="chart-box"><div ref={tip} className="chart-tip" role="tooltip" /></div>;
}

/** Area/line series over time (equity curve, drawdown). Values are {time: epoch seconds, value}. */
export function LineChart({ data, tone = "accent", height, baseline }: {
  data: { time: number; value: number }[]; tone?: "accent" | "up" | "down"; height?: number; baseline?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, { ...baseOptions(), handleScroll: false, handleScale: false });
    const col = css(tone === "accent" ? "--accent" : `--${tone}`);
    const s = baseline
      ? c.addBaselineSeries({ baseValue: { type: "price", price: 0 }, topLineColor: css("--up"), bottomLineColor: css("--down"),
          topFillColor1: css("--up-soft"), topFillColor2: "transparent", bottomFillColor1: "transparent", bottomFillColor2: css("--down-soft"), lineWidth: 2 })
      : c.addAreaSeries({ lineColor: col, topColor: col + "55", bottomColor: col + "05", lineWidth: 2 });
    // Several trades can share a second; the chart needs strictly increasing times.
    const seen = new Map<number, number>();
    for (const p of data) seen.set(p.time, p.value);
    s.setData([...seen.entries()].sort((a, b) => a[0] - b[0]).map(([t, v]) => ({ time: t as UTCTimestamp, value: v })));
    c.timeScale().fitContent();
    const obs = new MutationObserver(() => c.applyOptions(baseOptions()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      obs.disconnect();
      c.remove();
    };
  }, [data, tone, baseline]);
  return <div ref={box} className="chart-box sm" style={height ? { height } : undefined} />;
}
