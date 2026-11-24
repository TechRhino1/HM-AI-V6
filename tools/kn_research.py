"""KN-Adaptive research: raw KN (EMA 5/13 cross, 1.5xATR stop, 1/2/3R ladder) against four dynamic
layers (jarvis/forward_tests/kn_adaptive.py), on frozen real MT5 bars, with an anchored walk-forward.

Honesty rules are those of tools/strategy_research.py: decisions at a completed bar's close, entry at the
next open, BUY pays the per-bar spread, shorts cover at the ask, slippage on stop and signal exits, a stop
is assumed to fill before a target in the same bar, gaps fill at the open, and broker swap is charged per
night for each leg until it closes. Every trade is compared with flipped-direction, always-long and
spread x2 trades at the same entries.

Walk-forward: for each calendar quarter Q after a two-year warm-up, the ER threshold (and, for the
"WF_best" row, the variant too) is picked on the trades that CLOSED before Q starts, then only Q's trades
count. The V4 ladder levels at each signal come from MFE of earlier signals that had already finished.
Adoption = strategy_research.verdict() (unchanged; min lot x3 for the three legs) AND deflated Sharpe > 0.95.

Usage:
    python tools/strategy_research.py --fetch-universe <bars.pkl>   # or any fetch with H1 + H4
    python tools/kn_research.py <bars.pkl> [out.json] [SYMBOL ...]
"""
import os, sys, json, pickle
import numpy as np
import pandas as pd
from scipy import stats as sps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import strategy_research as sr  # noqa: E402
from jarvis.forward_tests import kn_adaptive as kn  # noqa: E402
from jarvis.forward_tests.research_leads import chandelier_stop  # noqa: E402
from jarvis.learning.deflated_sharpe import deflated_sharpe_ratio  # noqa: E402

DEFAULT_SYMBOLS = ("GBPUSD", "BTCUSD", "SOLUSD", "EURUSD")
WARMUP_DAYS = 730
MIN_TRAIN = 30
DSR_MIN = 0.95


def walk_ladder(A, i, side, sd, legs, be, trail, xr, m=1.0):
    """Three-leg trade from bar i+1's open. legs = [(weight, R target or None)]; be: stop to entry once a
    target fills; trail: chandelier trail on what is left; xr: close-based exit mask (fills next open).
    Returns (net R incl. swap, exit bar, swap R) or None if the trade is still open at the data's end."""
    o, h, l, spr, atr = A["o"], A["h"], A["l"], A["spr"], A["atr"]
    n, j0, slip = len(o), i + 1, A["slip"]
    if j0 >= n:
        return None
    entry = o[j0] + spr[j0] * m if side == 1 else o[j0]
    stop, best = entry - side * sd, entry
    open_legs = [[w, entry + side * r * sd if r else None] for w, r in legs]
    tot = [0.0, 0.0]

    def book(px, j, w):
        nights = A["W"][A["day"][j] - A["d0"]] - A["W"][A["day"][j0] - A["d0"]]
        sw = nights * sr.swap_px(A["info"], side, entry) * w
        tot[0] += (side * (px - entry) * w + sw) / sd
        tot[1] += sw / sd

    for j in range(j0, n):
        sp = spr[j] * m
        hi, lo = (h[j], l[j]) if side == 1 else (h[j] + sp, l[j] + sp)   # shorts trade at the ask
        if (lo <= stop) if side == 1 else (hi >= stop):
            px = min(o[j], stop) - slip if side == 1 else max(o[j] + sp, stop) + slip
            for w, _ in open_legs:
                book(px, j, w)
            return tot[0], j, tot[1]
        for leg in [g for g in open_legs if g[1] is not None and ((hi >= g[1]) if side == 1 else (lo <= g[1]))]:
            book(leg[1], j, leg[0])
            open_legs.remove(leg)
        if not open_legs:
            return tot[0], j, tot[1]
        if be and len(open_legs) < len(legs):
            stop = max(stop, entry) if side == 1 else min(stop, entry)
        if trail:
            best = max(best, hi) if side == 1 else min(best, lo)
            stop = chandelier_stop(side, entry, stop, best, atr[j])
        if xr[j]:
            if j + 1 >= n:
                return None
            px = o[j + 1] - slip if side == 1 else o[j + 1] + spr[j + 1] * m + slip
            for w, _ in open_legs:
                book(px, j + 1, w)
            return tot[0], j + 1, tot[1]
    return None


def simulate(A, F, bias, cfg):
    """One position at a time; raw per-trade lists in strategy_research.run()'s layout."""
    sig = kn.signals(F, cfg, bias, A["spr"])
    t = A["t"].to_numpy()
    mfe = [kn.signal_mfe(A["h"], A["l"], A["o"], F, i, s, sd) for i, s, sd in sig] if cfg.dyn_ladder else []
    raw = {k: [] for k in ("strategy", "always_long", "flipped", "spread_x2", "time", "sd", "swap_r", "side", "i", "j")}
    busy = -1
    for k, (i, side, sd) in enumerate(sig):
        if i < busy:
            continue
        levels = (1.0, 2.0)
        if cfg.dyn_ladder:
            past = [mfe[q][0] for q in range(k) if mfe[q][1] < i and t[i] - t[sig[q][0]] <= kn.MFE_LOOKBACK]
            levels = kn.ladder_levels(past)
        legs, be, trail = kn.exit_plan(cfg, levels)
        xr = F["cross_dn"] if side == 1 else F["cross_up"]
        w = walk_ladder(A, i, side, sd, legs, be, trail, xr)
        if w is None:
            continue
        raw["strategy"].append(w[0])
        for key, s2, m in (("always_long", 1, 1.0), ("flipped", -side, 1.0), ("spread_x2", side, 2.0)):
            b = walk_ladder(A, i, s2, sd, legs, be, trail, xr, m)
            raw[key].append(b[0] if b else 0.0)
        raw["time"].append(A["t"].iat[i]); raw["sd"].append(sd); raw["swap_r"].append(w[2])
        raw["side"].append(side); raw["i"].append(i); raw["j"].append(w[1])
        busy = w[1]
    return raw


def _take(raw, mask):
    return {k: [v for v, keep in zip(raw[k], mask) if keep] for k in raw}


def walk_forward(raws, t, pick_from):
    """raws: {combo: raw}. Per quarter, pick the combo in pick_from with the best mean R on trades that
    closed before the quarter (>= MIN_TRAIN of them), then keep that combo's trades entered in the quarter."""
    q = pd.PeriodIndex(pd.DatetimeIndex(t), freq="Q")
    first = pd.Timestamp(t[0]) + pd.Timedelta(days=WARMUP_DAYS)
    out = {k: [] for k in next(iter(raws.values()))}
    picks = []
    for per in q.unique():
        if per.start_time < first:
            continue
        q0, q1 = np.searchsorted(t, per.start_time.to_datetime64()), np.searchsorted(t, per.end_time.to_datetime64())
        best, best_exp = None, -np.inf
        for name in pick_from:
            r = raws[name]
            train = [x for x, j in zip(r["strategy"], r["j"]) if j < q0]
            if len(train) >= MIN_TRAIN and np.mean(train) > best_exp:
                best, best_exp = name, float(np.mean(train))
        if best is None:
            continue
        picks.append(best)
        sel = _take(raws[best], [q0 <= i < q1 for i in raws[best]["i"]])
        for k in out:
            out[k] += sel[k]
    return out, picks


def dsr(rs, n_trials, trial_srs):
    x = np.asarray(rs, float)
    if len(x) < 10 or x.std() == 0:
        return None
    return round(deflated_sharpe_ratio(float(x.mean() / x.std(ddof=1)), len(x), float(sps.skew(x)),
                                       float(sps.kurtosis(x, fisher=False)), n_trials,
                                       float(np.var(trial_srs)) if len(trial_srs) > 1 else 0.0), 3)


def research(data, symbols):
    res, rows = {}, []
    names = kn.combos()
    for name in symbols:
        if name not in data:
            print("skip", name, "(not in the bars file)")
            continue
        info, slip, weekends, ref, real_start, P, A = sr.setup(name, data[name])
        info3 = {**info, "volume_min": 3 * info["volume_min"]}   # three legs at the minimum lot each
        res[name] = {"symbol": data[name]["symbol"], "bars": {tf: [str(P[tf].t_open.iat[0]), str(P[tf].t_open.iat[-1])] for tf in P}}
        b4 = P["H4"][["t_close"]].assign(bias=kn.htf_bias(P["H4"]))
        for tf in ("H1", "H4"):
            d = P[tf]
            bias = (kn.htf_bias(d) if tf == "H4" else
                    pd.merge_asof(d[["t_close"]], b4.rename(columns={"t_close": "tc4"}), left_on="t_close",
                                  right_on="tc4", direction="backward")["bias"].fillna(0).astype(int).to_numpy())
            F = kn.features(d)
            raws = {combo: simulate(A[tf], F, bias, cfg) for _, combo, cfg in names}
            t = A[tf]["t"].to_numpy()
            trial_srs = [np.mean(r["strategy"]) / np.std(r["strategy"]) for r in raws.values() if len(r["strategy"]) > 1]
            groups = {v: [c for vv, c, _ in names if vv == v] for v in kn.VARIANTS}
            groups["WF_best"] = [c for _, c, _ in names]
            for label, pick_from in groups.items():
                oos, picks = walk_forward(raws, t, pick_from)
                s = sr.summarise(oos, info3, real_start)
                ok, why, low = sr.verdict(s, name, tf)
                d_ = dsr(oos["strategy"], len(names), trial_srs)
                if d_ is None or d_ <= DSR_MIN:
                    why = why + [f"DSR {d_} <= {DSR_MIN}"]
                    ok = False
                s.update(adopted=ok, reasons=why, low_confidence=low, dsr=d_,
                         last_pick=picks[-1] if picks else None,
                         picks={k: int(v) for k, v in pd.Series(picks).value_counts().items()} if picks else {})
                res[name][f"{label}|{tf}"] = s
                rows.append((name, tf, label, s))
                st = s["strategy"]
                print(name, tf, label, {k: st.get(k) for k in ("n", "wr", "exp_r", "pf", "max_dd_r")},
                      "dsr", d_, "ADOPT" if ok else why, flush=True)
    return res, rows


def table(rows):
    out = ["| Symbol | TF | Variant | n | Win% | ExpR | PF | MaxDD R | 1st half | 2nd half | Spread x2 | Always-long | Flipped | DSR | Verdict |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, tf, label, s in rows:
        st = s["strategy"]
        if not st.get("n"):
            out.append(f"| {name} | {tf} | {label} | 0 |" + " |" * 10 + " no trades |")
            continue
        v = "**ADOPT**" if s["adopted"] else "; ".join(s["reasons"])
        out.append(f"| {name} | {tf} | {label} | {st['n']} | {st['wr']:.0%} | {st['exp_r']:+.3f} | {st['pf']} | "
                   f"{st['max_dd_r']} | {st['h1_exp']:+.3f} | {st['h2_exp']:+.3f} | {s['spread_x2']['exp_r']:+.3f} | "
                   f"{s['always_long']['exp_r']:+.3f} | {s['flipped']['exp_r']:+.3f} | {s['dsr']} | {v} |")
    return "\n".join(out)


def main():
    args = sys.argv[1:]
    data = pickle.load(open(args[0], "rb"))
    out = next((a for a in args[1:] if a.endswith(".json")), None)
    symbols = [a for a in args[1:] if not a.endswith(".json")] or DEFAULT_SYMBOLS
    res, rows = research(data, symbols)
    if out:
        json.dump(res, open(out, "w"), indent=1, default=str)
    print(table(rows))


if __name__ == "__main__":
    main()
