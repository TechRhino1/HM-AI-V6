"""Why so few trades, and are the blocked trades worth taking? Gate attribution on the live engine.

Runs the production backtest path (tools/backtests/run_mode_backtest.run_one, unchanged engine) and
records EVERY directional decision the DecisionEngine forms - executed or not - with its entry, stop,
target and failing gates. Each candidate is then replayed as a shadow trade on the primary series:

    entry at the next bar's open (BUY pays the ask), the engine's own SL/TP shifted by the fill,
    stop checked first, SELLs exit on the ask, horizon HORIZON bars then closed at the bar close,
    one shadow position at a time per (symbol, style) so overlapping repeats are not double counted.

Result: per gate, how many candidates it blocked ALONE (sole failing gate) or at all, and the
expectancy (R, after spread) of the trades it blocked. A gate whose blocked trades lose money is
doing its job; a gate that blocks positive-expectancy trades is a root cause of lost profit.

Usage:
    python tools/gate_attribution.py --out <dir> [--symbols A,B] [--styles S,D] [--workers 3]
    python tools/gate_attribution.py --report <dir>
"""
from __future__ import annotations

import argparse, json, os, sys, time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "backtests"))

HORIZON = {"SCALP": 36, "DAY_TRADING": 32, "SWING": 48}   # primary bars: 3h M5, 8h M15, 2d H1


def capture_job(job):
    """run_one with DecisionEngine.evaluate wrapped to record every decision."""
    import run_mode_backtest as rmb
    from jarvis.intelligence.decision_engine import DecisionEngine
    rows = []
    orig = DecisionEngine.evaluate

    def wrapped(self, context, *a, **k):
        d = orig(self, context, *a, **k)
        try:
            prim = (k.get("mtf_data") or {}).get("primary")
            t = prim["time"].iloc[-1] if prim is not None and len(prim) else None
            bias = str(getattr(d, "bias", "") or "").upper()
            if bias in ("BUY", "SELL") and t is not None and float(d.stop_loss or 0) > 0:
                rows.append({"time": str(t), "bias": bias, "entry": float(d.entry_price), "sl": float(d.stop_loss),
                             "tp": float(d.take_profit or 0), "decision": str(d.decision),
                             "strategy": str(getattr(d, "strategy", "")),
                             "regime": str(getattr(getattr(d, "regime", None), "primary_regime", "")),
                             "failing": list(getattr(d.quality_gate, "failing_reasons", []) or [])})
        except Exception:
            pass
        return d

    DecisionEngine.evaluate = wrapped
    res = rmb.run_one(job)
    res.pop("trades", None)
    return {"job": job, "summary": {k: res.get(k) for k in ("n_trades", "primary_tf", "window_start", "window_end", "error")},
            "candidates": rows}


def shadow(frame: pd.DataFrame, cands: list, spread_px: float, pip: float, horizon: int) -> list:
    """Replay candidates on the primary frame; returns rows with R after spread."""
    t = pd.to_datetime(frame["time"]).values.astype("datetime64[ns]")
    o, h, l, c = (frame[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    out, busy = [], -1
    for cd in sorted(cands, key=lambda x: x["time"]):
        i = int(np.searchsorted(t, np.datetime64(pd.Timestamp(cd["time"]).tz_localize(None) if pd.Timestamp(cd["time"]).tzinfo else pd.Timestamp(cd["time"])), side="left"))
        if i >= len(t) - 1 or i < busy:
            continue
        side = 1 if cd["bias"] == "BUY" else -1
        j0 = i + 1
        entry = o[j0] + (spread_px if side == 1 else 0.0)
        shift = entry - cd["entry"]
        sl, tp = cd["sl"] + shift, (cd["tp"] + shift if cd["tp"] > 0 else None)
        risk = abs(entry - sl)
        if risk <= 0 or side * (entry - sl) <= 0 or (tp is not None and side * (tp - entry) <= 0):
            continue
        r, j = _walk(o, h, l, c, j0, side, entry, sl, tp, risk, spread_px, horizon)
        # Flipped benchmark: same bar, opposite side, mirrored stop/target distances. If the
        # flipped trade also wins, the "edge" is market drift, not the signal.
        fs = -side
        fe = o[j0] + (spread_px if fs == 1 else 0.0)
        tpd = abs(tp - entry) if tp is not None else None
        fr, _ = _walk(o, h, l, c, j0, fs, fe, fe - fs * risk, (fe + fs * tpd) if tpd else None, risk, spread_px, horizon)
        busy = j
        out.append({**cd, "r": float(r), "r_flip": float(fr), "rr_plan": (tpd / risk) if tpd else None})
    return out


def _walk(o, h, l, c, j0, side, entry, sl, tp, risk, spread_px, horizon):
    """Stop first; SELL exits on the ask; close at the horizon bar's close."""
    j = j0
    for j in range(j0, min(len(o), j0 + horizon)):
        lo, hi = (l[j], h[j]) if side == 1 else (l[j] + spread_px, h[j] + spread_px)
        if (lo <= sl) if side == 1 else (hi >= sl):
            return side * (sl - entry) / risk, j
        if tp is not None and ((hi >= tp) if side == 1 else (lo <= tp)):
            return side * (tp - entry) / risk, j
    px = c[j] if side == 1 else c[j] + spread_px
    return side * (px - entry) / risk, j


def run(args):
    import run_mode_backtest as rmb
    from jarvis.data.symbol_registry import resolve
    from jarvis.market.data_feed import style_timeframes
    os.makedirs(args.out, exist_ok=True)
    jobs = [{"symbol": s, "style": st, "days": args.days, "profile": False, "start": "", "end": ""}
            for st in args.styles.split(",") for s in args.symbols.split(",")]
    print(f"{len(jobs)} jobs, {args.workers} workers", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(capture_job, j): j for j in jobs}
        for fut in as_completed(futs):
            j = futs[fut]
            res = fut.result()
            frames = rmb.load_frames(j["symbol"], j["days"])
            tf = style_timeframes(j["style"])["primary"]
            spec = resolve(j["symbol"])
            sh = shadow(frames[tf], res["candidates"], float(spec.typical_spread_pips) * spec.pip_size,
                        spec.pip_size, HORIZON[j["style"]])
            res["shadow"] = sh
            json.dump(res, open(os.path.join(args.out, f"{j['symbol']}__{j['style']}.json"), "w"), default=str)
            print(f"{j['symbol']:8s} {j['style']:12s} trades={res['summary']['n_trades']} "
                  f"candidates={len(res['candidates'])} shadow={len(sh)} ({time.time() - t0:.0f}s)", flush=True)


def report(d):
    rows = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".json"):
            res = json.load(open(os.path.join(d, f)))
            for s in res.get("shadow", []):
                rows.append({**s, "symbol": res["job"]["symbol"], "style": res["job"]["style"]})
    df = pd.DataFrame(rows)
    if df.empty:
        print("no candidates"); return
    df["r_long"] = np.where(df.bias == "BUY", df.r, df.r_flip)   # always-long benchmark at the same bars
    df["n_fail"] = df.failing.map(len)
    df["sole"] = df.failing.map(lambda f: f[0] if len(f) == 1 else ("<none>" if not f else ""))
    st = lambda g: (f"n={len(g):5d}  exp={g.r.mean():+.3f}R  wr={(g.r > 0).mean():.0%}  totalR={g.r.sum():+8.1f}"
                    f"  | flipped {g.r_flip.mean():+.3f}R  long {g.r_long.mean():+.3f}R  buy% {(g.bias == 'BUY').mean():.0%}")
    print("ALL shadow candidates:", st(df))
    print("Executed by engine (decision==EXECUTE):", st(df[df.decision == "EXECUTE"]) if (df.decision == "EXECUTE").any() else "none")
    print("Passed every quality gate:", st(df[df.n_fail == 0]) if (df.n_fail == 0).any() else "none")
    print("\nBy style:")
    for k, g in df.groupby("style"):
        print(f"  {k:12s}", st(g))
    print("\nBy number of failing gates:")
    for k, g in df.groupby(df.n_fail.clip(upper=6)):
        print(f"  {k}{'+' if k == 6 else ' '} gates", st(g))
    print("\nSOLE blocking gate (the trade would have been taken without it):")
    for k, g in sorted(df[df.n_fail == 1].groupby("sole"), key=lambda x: -len(x[1])):
        print(f"  {k[:55]:55s}", st(g))
    print("\nAny-blocking gate (trades it blocked, with or without others):")
    acc = defaultdict(list)
    for fs, r, rf in zip(df.failing, df.r, df.r_flip):
        for g in fs:
            acc[g].append((r, rf))
    for g, v in sorted(acc.items(), key=lambda x: -len(x[1]))[:30]:
        v = np.array(v)
        print(f"  {g[:55]:55s} n={len(v):5d}  exp={v[:, 0].mean():+.3f}R  wr={(v[:, 0] > 0).mean():.0%}  flipped={v[:, 1].mean():+.3f}R")
    print("\nBy symbol x style:")
    for k, g in df.groupby(["symbol", "style"]):
        print(f"  {k[0]:7s} {k[1]:12s}", st(g))
    print("\nHit stop:", f"{(df.r <= -0.99).mean():.0%}", " median planned RR", f"{df.rr_plan.median():.2f}")
    df.to_csv(os.path.join(d, "shadow_all.csv"), index=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--report")
    ap.add_argument("--symbols", default="XAUUSD,EURUSD,GBPUSD,BTCUSD")
    ap.add_argument("--styles", default="SWING,DAY_TRADING,SCALP")
    ap.add_argument("--days", type=int, default=183)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    if a.report:
        report(a.report)
    else:
        run(a)
        report(a.out)
