"""Range support/resistance research: buy support / sell resistance in sideways markets, and
trade with a trend channel (buy the rising lower line, sell the falling upper line).

Same honesty rules and adoption gate as tools/strategy_research.py (whose machinery this reuses):
completed bars only, entry at the next open with the real per-bar spread, slippage, broker swap,
stop-first when stop and target share a bar, always-long and flipped benchmarks, spread x2.
All parameters are fixed a priori (no tuning):

* Pivots: a fractal high/low with K bars each side, usable only K bars after it prints (no look-ahead).
* range_sr: setup ADX(14) < 20 and higher-timeframe ADX < 25. Resistance = the highest confirmed
  pivot high of the last LOOKBACK bars, with >= 2 pivot highs within 0.5 ATR of it; support mirrored.
  Range width 3-12 ATR. BUY when the bar trades within 0.25 ATR of support and closes back above it in
  the upper half of its range; SELL mirrored at resistance. Stop: boundary -/+ 0.5 ATR. Target: the
  opposite boundary -/+ 0.25 ATR. Time stop MAX_BARS.
* channel_sr: least-squares lines through the last 3 confirmed pivot lows and the last 3 pivot highs,
  both sloping the same way, width 3-12 ATR. Rising channel: BUY at the lower line (same touch and
  rejection rule), target the upper line; falling channel: SELL at the upper line. Stop 0.5 ATR beyond.

Usage:
    python tools/range_research.py <bars.pkl> <out.json> [SYMBOL ...]   # bars: strategy_research.fetch
    python tools/range_research.py --selftest
"""
import os, sys, json, pickle
from bisect import bisect_right
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_research as sr

K, LOOKBACK, MAX_BARS = 3, 100, 48
HTF = {"M15": "H1", "H1": "H4", "H4": "D1"}
UNITS = {**{k: v[3] for k, v in sr.SYMBOLS.items()}, **{k: v[3] for k, v in sr.FOREX.items()}}


def adx(d, n=14):
    h, l, c = d.high, d.low, d.close
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a = 1 / n
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, index=d.index).ewm(alpha=a, adjust=False).mean() / atr
    ndi = 100 * pd.Series(ndm, index=d.index).ewm(alpha=a, adjust=False).mean() / atr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.ewm(alpha=a, adjust=False).mean()


def pivots(h, l):
    """Indices of fractal highs/lows (K bars each side). Pivot p becomes known at bar p + K."""
    n = len(h)
    ph, pl = [], []
    for p in range(K, n - K):
        win_h, win_l = h[p - K:p + K + 1], l[p - K:p + K + 1]
        if h[p] == win_h.max() and (win_h == h[p]).sum() == 1:
            ph.append(p)
        if l[p] == win_l.min() and (win_l == l[p]).sum() == 1:
            pl.append(p)
    return np.array(ph, int), np.array(pl, int)


def _touch(A, i, level, side):
    """BUY: low within 0.25 ATR of support, close back above it in the bar's upper half (SELL mirrored)."""
    h, l, c, atr = A["h"][i], A["l"][i], A["c"][i], A["atr"][i]
    rng = max(h - l, 1e-12)
    if side == 1:
        return l <= level + 0.25 * atr and c > level and (c - l) / rng >= 0.5
    return h >= level - 0.25 * atr and c < level and (h - c) / rng >= 0.5


def range_sr(A, adx_s, adx_h):
    h, l, c, atr = A["h"], A["l"], A["c"], A["atr"]
    ph, pl = pivots(h, l)
    sig = []
    for i in range(250, len(c)):
        a = atr[i]
        if not (adx_s[i] < 20 and adx_h[i] < 25) or not a > 0:
            continue
        hs = ph[(ph >= i - LOOKBACK) & (ph <= i - K)]
        ls = pl[(pl >= i - LOOKBACK) & (pl <= i - K)]
        if len(hs) < 2 or len(ls) < 2:
            continue
        res, sup = h[hs].max(), l[ls].min()
        if (np.abs(h[hs] - res) <= 0.5 * a).sum() < 2 or (np.abs(l[ls] - sup) <= 0.5 * a).sum() < 2:
            continue
        if not (3 * a <= res - sup <= 12 * a):
            continue
        if _touch(A, i, sup, 1):
            sd = c[i] - (sup - 0.5 * a)
            sig.append((i, 1, sd, (res - 0.25 * a - c[i]) / sd))
        elif _touch(A, i, res, -1):
            sd = (res + 0.5 * a) - c[i]
            sig.append((i, -1, sd, (c[i] - (sup + 0.25 * a)) / sd))
    return [s for s in sig if s[2] > 0 and s[3] > 0.3], {"max_bars": MAX_BARS}


def _line(idx, vals, at):
    m, b = np.polyfit(idx.astype(float), vals, 1)
    return m, m * at + b


def channel_sr(A):
    h, l, c, atr = A["h"], A["l"], A["c"], A["atr"]
    ph, pl = pivots(h, l)
    sig = []
    for i in range(250, len(c)):
        a = atr[i]
        if not a > 0:
            continue
        kh, kl = ph[:bisect_right(ph, i - K)][-3:], pl[:bisect_right(pl, i - K)][-3:]
        if len(kh) < 3 or len(kl) < 3 or min(kh[0], kl[0]) < i - LOOKBACK:
            continue
        mh, upper = _line(kh, h[kh], i)
        ml, lower = _line(kl, l[kl], i)
        if not (3 * a <= upper - lower <= 12 * a) or np.sign(mh) != np.sign(ml) or mh == 0:
            continue
        if ml > 0 and _touch(A, i, lower, 1):
            sd = c[i] - (lower - 0.5 * a)
            sig.append((i, 1, sd, (upper - 0.25 * a - c[i]) / sd))
        elif mh < 0 and _touch(A, i, upper, -1):
            sd = (upper + 0.5 * a) - c[i]
            sig.append((i, -1, sd, (c[i] - (lower + 0.25 * a)) / sd))
    return [s for s in sig if s[2] > 0 and s[3] > 0.3], {"max_bars": MAX_BARS}


def prepare(name, blob):
    """strategy_research.research()'s per-symbol set-up: costs, spread model, real-spread era."""
    info, fr = {**blob["info"], "price_now": float(blob["frames"]["H1"].close.iat[-1])}, blob["frames"]
    weekends = bool((fr["H1"].time.dt.dayofweek >= 5).any())
    h = fr["H1"][fr["H1"].time > fr["H1"].time.iloc[-1] - pd.Timedelta(days=365)]
    rs = h.spread * info["point"]
    ref = {"bps": float(np.median(rs / h.close)), "usd": float(np.median(rs)), "model": UNITS[name]}
    slip = 0.5 * ref["usd"]
    P = {tf: sr.prep(fr[tf], tf, info, ref) for tf in ("M15", "H1", "H4", "D1")}
    yr = P["H1"].groupby(P["H1"].t_open.dt.year).modeled.mean()
    bad = yr[yr >= 0.05].index
    real_start = pd.Timestamp(f"{bad.max() + 1}-01-01") if len(bad) else P["H1"].t_open.iat[0]
    return info, P, slip, weekends, real_start


def candidates(P, A, tf):
    """(name, signals, exits) for one timeframe. Higher-timeframe ADX is as-of joined on completed bars."""
    d = P[tf].copy()
    d["adx"] = adx(d)
    hd = P[HTF[tf]].copy()
    hd["adx"] = adx(hd)
    j = sr.gr.attach(d, hd, ["adx"], "h_")   # sorted by t_close, same rows as d (t_close is increasing)
    return [("range_sr", *range_sr(A, d["adx"].to_numpy(), j["h_adx"].fillna(99).to_numpy())),
            ("channel_sr", *channel_sr(A))]


def research(data, symbols=None):
    res, rows = {}, []
    for name in (symbols or data):
        info, P, slip, weekends, real_start = prepare(name, data[name])
        res[name] = {"real_spread_from": str(real_start), "slip": slip}
        for tf in ("M15", "H1", "H4"):
            A = sr.arrays(P[tf], info, slip, weekends)
            for cand, sig, ex in candidates(P, A, tf):
                s = sr.summarise(sr.run(A, sig, ex), info, real_start)
                ok, why, low = sr.verdict(s, name, tf)
                s.update(adopted=ok, reasons=why, low_confidence=low, signals=len(sig))
                res[name][f"{cand}|{tf}"] = s
                rows.append((name, cand, tf, s))
                st = s["strategy"]
                print(name, cand, tf, {k: st.get(k) for k in ("n", "wr", "exp_r", "pf", "h1_exp", "h2_exp")},
                      "long", s["always_long"].get("exp_r"), "flip", s["flipped"].get("exp_r"),
                      "x2", s["spread_x2"].get("exp_r"), "ADOPT" if ok else why, flush=True)
    return res, rows


def selftest():
    # A flat range 100-110 (ATR 2): a dip to support that closes back up is a BUY targeting resistance;
    # a spike to resistance that closes back down is a SELL; a trending ADX takes no range trade.
    n = 300
    base = 105 + 5 * np.sin(np.arange(n) / 6.0)
    A = {"h": base + 1, "l": base - 1, "c": base.copy(), "atr": np.full(n, 2.0)}
    A["l"][299], A["c"][299], A["h"][299] = 99.2, 100.9, 101.0
    sig, _ = range_sr(A, np.full(n, 15.0), np.full(n, 15.0))
    assert sig and sig[-1][0] == 299 and sig[-1][1] == 1 and sig[-1][3] > 1, sig[-3:]
    sig, _ = range_sr(A, np.full(n, 30.0), np.full(n, 15.0))
    assert not sig
    A2 = {k: v.copy() for k, v in A.items()}
    A2["h"][299], A2["c"][299], A2["l"][299] = 110.8, 109.1, 109.0
    sig, _ = range_sr(A2, np.full(n, 15.0), np.full(n, 15.0))
    assert sig[-1][0] == 299 and sig[-1][1] == -1, sig[-3:]
    print("selftest ok")


def main():
    if sys.argv[1] == "--selftest":
        return selftest()
    res, rows = research(pickle.load(open(sys.argv[1], "rb")), sys.argv[3:] or None)
    json.dump(res, open(sys.argv[2], "w"), indent=1, default=str)
    print(sr.table(rows))


if __name__ == "__main__":
    main()
