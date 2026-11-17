"""M1 study (plan v3, Phase 3): is there an M1 SMC entry worth trading after costs?

Cost viability first: for every M1 setup (tools/smc_research.py rules) the entry cost
(spread + slippage) is measured against that setup's own stop distance. A symbol whose median
cost/stop exceeds COST_MAX (15%) is rejected before any strategy result is looked at: at a 2.5R
target, 15% of 1R is already 6% of the whole reward. The same ratio is shown for the M5 SCALP
setups for comparison.

Every symbol then runs the unchanged smc_research pipeline with one extra style, M1 entry with
bias from completed M15 + H1 bars. Same honesty rules, filters, exits (X0..X4b), 4 calendar folds
and adoption gate (sr.verdict + PF > 1.5 + >= 3/4 folds). A symbol must pass BOTH gates.

The broker serves at most ~100k M1 bars (~69 days for 24/7 crypto, ~95 days for FX/gold), so M1
is fetched separately up to terminal maxbars; M5..D1 come from strategy_research.fetch.

Usage:
    python tools/m1_research.py --fetch <bars_m1.pkl> [SYMBOL ...]
    python tools/m1_research.py <bars_m1.pkl> <outdir> [SYMBOL ...]
"""
import os, sys, json, pickle
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_research as sr
import mtf_entry_research as mtf
import smc_research as smc

SYMS = ("XAUUSD", "EURUSD", "GBPUSD", "BTCUSD")
COST_MAX = 0.15
smc.gr.TF_MIN["M1"] = 1
_orig_frames = mtf.frames


def fetch(path, names):
    import MetaTrader5 as mt5
    spec = {**sr.SYMBOLS, **sr.FOREX}
    sr.fetch(path, {n: spec[n] for n in names})
    data = pickle.load(open(path, "rb"))
    assert mt5.initialize(), mt5.last_error()
    count = mt5.terminal_info().maxbars - 1
    for n in names:
        sym, lo, hi, _ = spec[n]
        r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 1, count)   # pos 1: closed bars only
        assert r is not None and len(r), f"{sym} M1: {mt5.last_error()}"
        df = pd.DataFrame(r)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={"tick_volume": "volume"})[["time", "open", "high", "low", "close", "volume", "spread"]]
        assert df.close.between(lo, hi).all() and (df.spread >= 0).all(), f"{sym} M1: not real prices"
        data[n]["frames"]["M1"] = df
        print(n, "M1", len(df), df.time.iloc[0], df.time.iloc[-1])
    pickle.dump(data, open(path, "wb"))


def _frames_with_m1(name, blob):
    """mtf.frames plus the M1 frame, priced with the same spread model."""
    info, P, slip, weekends, real_start = _orig_frames(name, blob)
    h = blob["frames"]["H1"]
    h = h[h.time > h.time.iloc[-1] - pd.Timedelta(days=365)]
    rs = h.spread * info["point"]
    ref = {"bps": float(np.median(rs / h.close)), "usd": float(np.median(rs)), "model": mtf.rr.UNITS[name]}
    P["M1"] = sr.prep(blob["frames"]["M1"], "M1", info, ref)
    return info, P, slip, weekends, real_start


def cost_gate(data, names):
    """Median (entry spread + slippage) / stop over every setup, per symbol and entry TF."""
    out = {}
    for n in names:
        info, P, slip, weekends, _ = _frames_with_m1(n, data[n])
        group = mtf.GROUP.get(n, "forex")
        for style, etf in (("M1", "M1"), ("SCALP", "M5")):
            _, A, cands = smc.build(P, style, group, info, slip, weekends)
            if not cands:
                out[(n, etf)] = {"setups": 0}
                continue
            spr = A["spr"]
            sd = np.array([c["sd"] for c in cands])
            cost = np.array([spr[min(c["i"] + 1, len(spr) - 1)] for c in cands]) + slip
            ratio = cost / sd
            out[(n, etf)] = {"setups": len(cands), "median_cost_stop": round(float(np.median(ratio)), 3),
                             "p75_cost_stop": round(float(np.percentile(ratio, 75)), 3),
                             "median_stop_atr": round(float(np.median([c["sd"] / A["atr"][c["i"]] for c in cands])), 2),
                             "days": round((P[etf].t_open.iat[-1] - P[etf].t_open.iat[0]).total_seconds() / 86400, 1)}
            print(n, etf, out[(n, etf)], flush=True)
    return out


def main():
    if sys.argv[1] == "--fetch":
        return fetch(sys.argv[2], sys.argv[3:] or list(SYMS))
    data = pickle.load(open(sys.argv[1], "rb"))
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    names = sys.argv[3:] or [s for s in SYMS if s in data]
    smc.STYLES["M1"] = ("M1", "M15", "H1")
    cg = cost_gate(data, names)
    passed = [n for n in names if cg[(n, "M1")].get("median_cost_stop", 9) <= COST_MAX]
    print("COST GATE (M1, median cost/stop <= %.0f%%): passed %s" % (COST_MAX * 100, passed or "none"), flush=True)
    for k in ("SCALP", "DAY", "SWING"):   # M5..H1 results are in SMC_ENTRY_EXIT_RESEARCH_2026-11-17.md
        smc.STYLES.pop(k)
    mtf.frames = _frames_with_m1
    S, rej, edges, df = smc.research(data, names, outdir)
    groups = sorted({k[:2] for k in S})
    comps = smc.components(S, groups)
    md = smc.tables(S, rej, comps, df, groups)
    open(os.path.join(outdir, "m1_tables.md"), "w", encoding="utf-8").write(md)
    json.dump({"cost_gate": {"|".join(k): v for k, v in cg.items()}, "cost_gate_passed": passed,
               "stats": {"|".join(k): v for k, v in S.items()}, "rejections": {"|".join(g): v for g, v in rej.items()},
               "components": [["|".join(g), c, ok, why] for g, c, ok, why in comps]},
              open(os.path.join(outdir, "m1_results.json"), "w"), indent=1, default=str)
    print(md)
    print("\nCOST GATE passed:", passed or "none")
    print("STRATEGY PASSED:", [f"{'|'.join(g)} {c}" for g, c, ok, _ in comps if ok] or "none")


if __name__ == "__main__":
    main()
