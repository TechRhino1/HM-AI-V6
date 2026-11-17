"""Multi-timeframe entry research: does a lower-timeframe (trigger) veto, a premium/discount veto,
or a closer target make trend entries better after costs?  Motivated by BTCUSD #995648912
(2026-11-16 15:43 UTC): the H1 engine sold while the M5/M15 view had already turned up; MFE 0.

Same honesty rules and adoption gate as tools/strategy_research.py (machinery reused): completed
bars only, entry at the next open with the real per-bar spread, slippage, swap, stop-first.
All parameters fixed a priori:

* Entry TF -> (higher TF, trigger TF): M15 -> (H1, M5), H1 -> (H4, M15).
* HTF trend: completed HTF bar with EMA50 > EMA200 and close > EMA50 (mirror for down).
* pullback: in HTF trend, low touched EMA20 within 3 bars, then a close beyond the prior bar's
  extreme and EMA20. Stop: beyond the 3-bar extreme + spread + 0.3 ATR, at least 1 ATR.
* chase: in HTF trend, close beyond the prior 20-bar extreme. Same stop rule.
* Trigger-TF bias (completed bar): close > EMA50 and EMA20 > EMA50 -> up; mirror -> down; else flat.
  veto: skip if trigger bias is opposite.  strict: require trigger bias == side.
* zone: position of the close in the entry TF's 50-bar range; no SELL below 0.25, no BUY above 0.75.
* Targets 0.5 / 1.0 / 1.5 / 2.0 R; time stop 24 bars (H1) or 32 bars (M15).

Usage:
    python tools/mtf_entry_research.py <bars.pkl> <out.json> [SYMBOL ...]   # bars with M5..D1
    python tools/mtf_entry_research.py --selftest
"""
import os, sys, json, pickle
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_research as sr
import range_research as rr

PAIRS = {"M15": ("H1", "M5"), "H1": ("H4", "M15")}
MAX_BARS = {"M15": 32, "H1": 24}
TARGETS = (0.5, 1.0, 1.5, 2.0)
FILTERS = ("none", "veto", "strict", "veto_zone")
GROUP = {"BTCUSD": "crypto", "ETHUSD": "crypto", "SOLUSD": "crypto", "XAUUSD": "gold"}


def bias(d):
    """+1 / -1 / 0 trend bias of each completed bar."""
    up = (d.close > d.ema50) & (d.ema20 > d.ema50)
    dn = (d.close < d.ema50) & (d.ema20 < d.ema50)
    return up.astype(int) - dn.astype(int)


def htf_trend(d):
    up = (d.ema50 > d.ema200) & (d.close > d.ema50)
    dn = (d.ema50 < d.ema200) & (d.close < d.ema50)
    return up.astype(int) - dn.astype(int)


def signals(e, A, pattern, flt):
    """e: entry-TF frame with h_trend, l_bias joined. Returns [(i, side, stop_dist)]."""
    c, h, l, atr, spr = A["c"], A["h"], A["l"], A["atr"], A["spr"]
    e20 = e.ema20.to_numpy()
    ht, lb = e.h_trend.fillna(0).to_numpy(), e.l_bias.fillna(0).to_numpy()
    lo3, hi3 = e.low.rolling(3).min().to_numpy(), e.high.rolling(3).max().to_numpy()
    tl = (e.low <= e.ema20).astype(int).rolling(3).max().fillna(0).to_numpy() > 0
    ts = (e.high >= e.ema20).astype(int).rolling(3).max().fillna(0).to_numpy() > 0
    hi20, lo20 = sr._prior_max(h, 20), sr._prior_min(l, 20)
    mx, mn = e.high.rolling(50).max().to_numpy(), e.low.rolling(50).min().to_numpy()
    pos = (c - mn) / np.where(mx > mn, mx - mn, np.nan)
    out = []
    for i in range(210, len(c)):
        side = int(ht[i])
        if side == 0:
            continue
        if pattern == "pullback":
            ok = (tl[i] and c[i] > h[i - 1] and c[i] > e20[i]) if side == 1 else (ts[i] and c[i] < l[i - 1] and c[i] < e20[i])
        else:
            ok = c[i] > hi20[i] if side == 1 else c[i] < lo20[i]
        if not ok:
            continue
        if flt in ("veto", "veto_zone") and lb[i] == -side:
            continue
        if flt == "strict" and lb[i] != side:
            continue
        if flt == "veto_zone" and ((side == -1 and pos[i] < 0.25) or (side == 1 and pos[i] > 0.75)):
            continue
        sd = (c[i] - lo3[i] if side == 1 else hi3[i] - c[i]) + spr[i] + 0.3 * atr[i]
        out.append((i, side, max(sd, atr[i])))
    return out


def frames(name, blob):
    info, P, slip, weekends, real_start = rr.prepare(name, blob)
    h = blob["frames"]["H1"]
    h = h[h.time > h.time.iloc[-1] - pd.Timedelta(days=365)]
    rs = h.spread * info["point"]
    ref = {"bps": float(np.median(rs / h.close)), "usd": float(np.median(rs)), "model": rr.UNITS[name]}
    P["M5"] = sr.prep(blob["frames"]["M5"], "M5", info, ref)
    return info, P, slip, weekends, real_start


def research(data, symbols=None):
    rows, raws = [], {}
    for name in (symbols or data):
        info, P, slip, weekends, real_start = frames(name, data[name])
        for tf, (htf, ltf) in PAIRS.items():
            hd, ld = P[htf].copy(), P[ltf].copy()
            hd["trend"], ld["bias"] = htf_trend(hd), bias(ld)
            e = sr.gr.attach(P[tf], hd, ["trend"], "h_")
            e = sr.gr.attach(e, ld, ["bias"], "l_").reset_index(drop=True)
            A = sr.arrays(e, info, slip, weekends)
            for pattern in ("pullback", "chase"):
                for flt in FILTERS:
                    sig = signals(e, A, pattern, flt)
                    for tg in TARGETS:
                        raw = sr.run(A, sig, {"tgt": tg, "max_bars": MAX_BARS[tf]})
                        s = sr.summarise(raw, info, real_start)
                        ok, why, _ = sr.verdict(s, name, tf)
                        st = s["strategy"]
                        rows.append(dict(sym=name, tf=tf, pattern=pattern, flt=flt, tgt=tg, n=st["n"], wr=st.get("wr"),
                                         exp=st.get("exp_r"), pf=st.get("pf"), h1=st.get("h1_exp"), h2=st.get("h2_exp"),
                                         x2=s["spread_x2"].get("exp_r"), flip=s["flipped"].get("exp_r"), adopt=ok, why=why))
                        raws[(name, tf, pattern, flt, tg)] = raw
                        print(name, tf, pattern, flt, tg, {k: st.get(k) for k in ("n", "wr", "exp_r", "pf", "h1_exp", "h2_exp")},
                              "x2", s["spread_x2"].get("exp_r"), "ADOPT" if ok else why, flush=True)
    return rows, raws


def grouped(raws):
    """Pool trades per (group, tf, pattern, filter, target)."""
    acc = {}
    for (name, tf, pattern, flt, tg), raw in raws.items():
        acc.setdefault((GROUP.get(name, "forex"), tf, pattern, flt, tg), []).append(raw)
    out = []
    for k, rs in sorted(acc.items()):
        p = sr.pool(rs)
        st, x2 = sr.gr.stats(p["strategy"], p["time"]), sr.gr.stats(p["spread_x2"], p["time"])
        out.append((*k, st, x2))
    return out


def table(g):
    lines = ["| Group | TF | Pattern | Filter | Target | n | Win rate | Exp R | PF | 1st half | 2nd half | Spread x2 |",
             "|" + "---|" * 12]
    for grp, tf, pattern, flt, tg, st, x2 in g:
        if not st["n"]:
            continue
        lines.append(f"| {grp} | {tf} | {pattern} | {flt} | {tg}R | {st['n']} | {st['wr']:.0%} | {st['exp_r']:+.3f} | "
                     f"{st['pf']} | {st['h1_exp']:+.3f} | {st['h2_exp']:+.3f} | {x2['exp_r']:+.3f} |")
    return "\n".join(lines)


def selftest():
    n = 400
    t = pd.date_range("2026-01-01", periods=n, freq="h")
    c = 100 + np.arange(n) * 0.1
    e = pd.DataFrame({"t_open": t, "close": c, "high": c + 0.5, "low": c - 0.5, "ema20": c - 0.2,
                      "h_trend": 1, "l_bias": 1})
    e.loc[n - 2, "low"] = e.loc[n - 2, "ema20"] - 0.1   # pullback touch
    e.loc[n - 1, "close"] = e.loc[n - 2, "high"] + 0.1  # break of prior high
    A = {"c": e.close.to_numpy(), "h": e.high.to_numpy(), "l": e.low.to_numpy(),
         "atr": np.ones(n), "spr": np.full(n, 0.01)}
    assert signals(e, A, "pullback", "none")[-1][:2] == (n - 1, 1)
    e["l_bias"] = -1
    assert not [s for s in signals(e, A, "pullback", "veto") if s[0] == n - 1]   # trigger TF opposite -> vetoed
    e["l_bias"] = 0
    assert [s for s in signals(e, A, "pullback", "veto") if s[0] == n - 1]       # flat passes veto
    assert not [s for s in signals(e, A, "pullback", "strict") if s[0] == n - 1]  # but not strict
    print("selftest ok")


def main():
    if sys.argv[1] == "--selftest":
        return selftest()
    rows, raws = research(pickle.load(open(sys.argv[1], "rb")), sys.argv[3:] or None)
    json.dump(rows, open(sys.argv[2], "w"), indent=1, default=str)
    print(table(grouped(raws)))


if __name__ == "__main__":
    main()
