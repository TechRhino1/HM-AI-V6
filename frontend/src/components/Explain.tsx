import { useEffect, useRef, useState } from "react";
import { api, qs } from "../lib/api";
import { isNum } from "../lib/format";

interface Explained { metric: string; text: string; source: string }
const cache = new Map<string, Explained>();
/** The definitions fallback always appends "Current value: X."; drop it when no value was sent. */
export const tidyExplain = (text: string) => text.replace(/\s*Current value(?: for [^:]+)?: \.\s*/, " ").trim();

/** Plain-English meaning of a metric value (AI when configured, else the server's definitions). */
export function Explain({ metric, value, symbol, fallback }: {
  metric: string; value?: unknown; symbol?: string;
  /** Shown when the server has no definition for this metric. */
  fallback?: string;
}) {
  const [open, setOpen] = useState(false);
  const [res, setRes] = useState<Explained | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pos, setPos] = useState<{ top?: number; bottom?: number; left: number }>({ left: 0 });
  const btn = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const v = isNum(value) ? String(Math.round(value * 100) / 100) : value === null || value === undefined ? "" : String(value);
  const key = `${metric}|${v}|${symbol || ""}`;

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node) && !btn.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", close);
    const onScroll = (e: Event) => !box.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener("scroll", onScroll, true);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", close); window.removeEventListener("scroll", onScroll, true); };
  }, [open]);

  const toggle = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (open) return setOpen(false);
    const r = btn.current!.getBoundingClientRect();
    const w = Math.min(300, window.innerWidth - 24);
    const left = Math.max(12, Math.min(r.left - w / 2, window.innerWidth - w - 12));
    // Open upward when the button sits in the lower part of the viewport.
    setPos(r.bottom > window.innerHeight - 200 ? { bottom: window.innerHeight - r.top + 6, left } : { top: r.bottom + 6, left });
    setOpen(true);
    if (cache.has(key)) return setRes(cache.get(key)!);
    setRes(null); setErr(null);
    try {
      const out = await api.get<Explained>(`/api/ai/explain${qs({ metric, value: v, symbol })}`);
      out.text = tidyExplain(out.text);
      cache.set(key, out);
      setRes(out);
    } catch (ex: any) {
      setErr(ex?.message || "Explanation unavailable");
    }
  };

  const text = res && (res.source === "none" && fallback ? `${fallback}${v ? ` Current value: ${v}.` : ""}` : res.text);
  return (
    <>
      <button ref={btn} type="button" className="explain-btn" onClick={toggle} aria-label={`Explain ${metric.replace(/_/g, " ")}`} aria-expanded={open}>i</button>
      {open && (
        <div ref={box} className="popover" role="dialog" style={pos} onClick={(e) => e.stopPropagation()}>
          {err ? <span className="down">{err}</span> : !res ? <span className="faint">Explaining…</span> : (
            <>
              <div>{text}</div>
              <div className="faint" style={{ fontSize: 11, marginTop: 6 }}>
                {res.source === "definitions" || (res.source === "none" && fallback) ? "Source: built-in definitions" : res.source === "none" ? "No definition available" : `Source: AI (${res.source})`}
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
}
