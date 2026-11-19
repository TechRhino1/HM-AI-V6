import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export interface Resource<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** GET a JSON endpoint and optionally re-poll it. Polling pauses while the browser tab is hidden. */
export function usePoll<T>(path: string | null, intervalMs = 0): Resource<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!path);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!path) return;
    let alive = true;
    let timer: number | undefined;
    const ctl = new AbortController();
    const run = async () => {
      if (document.hidden && intervalMs) {
        timer = window.setTimeout(run, intervalMs);
        return;
      }
      try {
        const d = await api.get<T>(path, ctl.signal);
        if (!alive) return;
        setData(d);
        setError(null);
      } catch (e: any) {
        if (!alive || e?.name === "AbortError") return;
        setError(e?.message || "Request failed");
      } finally {
        if (alive) setLoading(false);
      }
      if (alive && intervalMs) timer = window.setTimeout(run, intervalMs);
    };
    setLoading(true);
    run();
    return () => {
      alive = false;
      ctl.abort();
      window.clearTimeout(timer);
    };
  }, [path, intervalMs, tick]);

  return { data, error, loading, reload };
}

/** Section routing in the URL hash: #section or #section/sub. */
export function useHashRoute(defaultRoute: string) {
  const read = () => window.location.hash.replace(/^#\/?/, "") || defaultRoute;
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const go = useCallback((r: string) => {
    if (window.location.hash !== `#${r}`) window.location.hash = r;
  }, []);
  return [route, go] as const;
}

export function useInterval(fn: () => void, ms: number) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const id = window.setInterval(() => ref.current(), ms);
    return () => window.clearInterval(id);
  }, [ms]);
}

/** Per-viewer UI preference (selected symbol, filters). Falls back to memory if storage is blocked. */
export function useLocalStorage<T>(key: string, initial: T) {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (nv: T) => {
      setV(nv);
      try {
        localStorage.setItem(key, JSON.stringify(nv));
      } catch {
        /* storage blocked: keep it in memory */
      }
    },
    [key],
  );
  return [v, set] as const;
}
