"""Gold strategy research on frozen real MT5 bars (GOLD.i#).

No parameters are fitted: every rule uses standard a-priori values, so there is
nothing to overfit and no train/test split is needed. Robustness is judged by
consistency across calendar halves/years and against direction benchmarks.

Usage:
    python tools/gold_research.py --fetch <gold.pkl>   # freeze real GOLD.i# M5..D1 bars from MT5
    python tools/gold_research.py <gold.pkl> <out.json>

Results and conclusions: reports/GOLD_RESEARCH_2026-11-16.md
"""
import os, sys, json, pickle
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jarvis.data.broker_time import broker_bar_times_to_utc

TF_MIN = {"M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}
STYLES = {  # bias / setup / trigger timeframes, live time stop (exit_policy per style)
    "SCALP": ("H1", "M15", "M5", 90),
    "DAY_TRADING": ("H4", "H1", "M15", 240),
    "SWING": ("D1", "H4", "H1", 720),
}
BUDGET_FRAC = 28.0 / 3900.0   # $28 cap at 0.01 lot ($1 per $1) on a ~$3,900 gold: max stop as a share of price
SLIP = 0.10                   # $ slippage on stop and time exits


def prep(df, tf):
    d = df.copy()
    d["t_open"] = broker_bar_times_to_utc(d["time"]).dt.tz_localize(None).values
    d["t_close"] = d["t_open"] + pd.Timedelta(minutes=TF_MIN[tf])
    d["spr"] = d["spread"] * 0.01
    pc = d.close.shift()
    tr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    for n in (20, 50, 200):
        d[f"ema{n}"] = d.close.ewm(span=n, adjust=False).mean()
    return d


def attach(t, src, cols, prefix):
    """As-of join of COMPLETED src bars onto trigger bars (decision at trigger close)."""
    s = src[["t_close"] + cols].rename(columns={c: prefix + c for c in cols}).rename(columns={"t_close": prefix + "tc"})
    return pd.merge_asof(t.sort_values("t_close"), s.sort_values(prefix + "tc"),
                         left_on="t_close", right_on=prefix + "tc", direction="backward")


def walk(t, i, side, stop_dist, tgt_r, time_min):
    """Enter at bar i+1 open; walk forward. Returns (net R, exit bar index) or (None, None)."""
    if i + 1 >= len(t):
        return None, None
    o, spr = t.open.iat[i + 1], t.spr.iat[i + 1]
    entry = o + spr if side == 1 else o            # BUY at ask, SELL at bid
    stop = entry - side * stop_dist
    tgt = entry + side * tgt_r * stop_dist
    t0 = t.t_open.iat[i + 1]
    for j in range(i + 1, len(t)):
        hi, lo, sp = t.high.iat[j], t.low.iat[j], t.spr.iat[j]
        if side == 1:   # long exits at bid; stop checked first (conservative)
            if lo <= stop: return (stop - SLIP - entry) / stop_dist, j
            if hi >= tgt: return (tgt - entry) / stop_dist, j
            px = t.close.iat[j]
        else:           # short exits at ask
            if hi + sp >= stop: return (entry - stop - SLIP) / stop_dist, j
            if lo + sp <= tgt: return (entry - tgt) / stop_dist, j
            px = t.close.iat[j] + sp
        held = (t.t_close.iat[j] - t0).total_seconds() / 60
        r = side * (px - entry) / stop_dist
        if time_min and held >= time_min and r < 0.10:
            return r - SLIP / stop_dist, j
    return None, None


def stats(rs, times):
    rs = np.array(rs, float)
    if len(rs) == 0:
        return {"n": 0}
    eq = np.cumsum(rs)
    dd = float(np.max(np.maximum.accumulate(eq) - eq))
    pos, neg = rs[rs > 0].sum(), -rs[rs < 0].sum()
    yrs = pd.Series(rs, index=pd.DatetimeIndex(times)).groupby(lambda x: x.year).agg(["count", "mean"])
    half = len(rs) // 2
    return {"n": int(len(rs)), "wr": round(float((rs > 0).mean()), 3), "exp_r": round(float(rs.mean()), 3),
            "pf": round(float(pos / neg), 2) if neg > 0 else None, "max_dd_r": round(dd, 1),
            "h1_exp": round(float(rs[:half].mean()), 3), "h2_exp": round(float(rs[half:].mean()), 3),
            "by_year": {int(y): [int(c), round(float(m), 3)] for y, (c, m) in yrs.iterrows()}}


def run(t, signals, tgt_r, time_min):
    """signals: list of (i, side, stop_dist). One position at a time; stops wider than the budget are skipped."""
    out = {"strategy": [], "always_long": [], "flipped": []}
    times, busy_until, skipped = [], -1, 0
    for i, side, sd in signals:
        if i <= busy_until:
            continue
        if sd <= 0 or sd > BUDGET_FRAC * t.close.iat[i]:
            skipped += 1
            continue
        r, j = walk(t, i, side, sd, tgt_r, time_min)
        if r is None:
            continue
        out["strategy"].append(r)
        out["always_long"].append(walk(t, i, 1, sd, tgt_r, time_min)[0] or 0.0)
        out["flipped"].append(walk(t, i, -side, sd, tgt_r, time_min)[0] or 0.0)
        times.append(t.t_open.iat[i])
        busy_until = j
    res = {k: stats(v, times) for k, v in out.items()}
    res["over_budget_skipped"] = skipped
    return res


# ── Strategies ───────────────────────────────────────────────────────────────

def _trend(t, i):
    up = t.b_close.iat[i] > t.b_ema50.iat[i] > t.b_ema200.iat[i]
    dn = t.b_close.iat[i] < t.b_ema50.iat[i] < t.b_ema200.iat[i]
    return up, dn


def trend_pullback(t, use_bias=True):
    """Top-down: HTF trend (EMA50/200), setup-TF pullback into EMA20, trigger-TF micro-structure break.
    Stop beyond the trigger-TF swing + spread + 0.3 ATR, never inside 1 ATR."""
    sig = []
    hh = t.high.rolling(4).max().shift(1)
    ll = t.low.rolling(4).min().shift(1)
    sw_lo, sw_hi = t.low.rolling(10).min(), t.high.rolling(10).max()
    for i in range(210, len(t) - 1):
        up, dn = _trend(t, i) if use_bias else (True, True)
        atr = t.atr.iat[i]
        if up and t.s_pull_long.iat[i] and t.close.iat[i] > hh.iat[i] and t.close.iat[i - 1] <= hh.iat[i]:
            sig.append((i, 1, max(t.close.iat[i] - sw_lo.iat[i] + t.spr.iat[i] + 0.3 * atr, atr)))
        elif dn and t.s_pull_short.iat[i] and t.close.iat[i] < ll.iat[i] and t.close.iat[i - 1] >= ll.iat[i]:
            sig.append((i, -1, max(sw_hi.iat[i] - t.close.iat[i] + t.spr.iat[i] + 0.3 * atr, atr)))
    return sig


def session_levels(t):
    d = t.t_open.dt
    day = d.floor("D")
    asian = d.hour < 7
    g = t[asian].groupby(day[asian])
    return day, g.high.max(), g.low.min()


def london_sweep(t):
    """Judas swing: London/NY sweeps the Asian high/low by >= 0.1 ATR and closes back inside,
    traded in the HTF trend direction. Stop beyond the sweep extreme + spread + 0.3 ATR."""
    day, ah, al = session_levels(t)
    sig, used = [], set()
    for i in range(210, len(t) - 1):
        h = t.t_open.iat[i].hour + t.t_open.iat[i].minute / 60
        if not (7 <= h < 11 or 12.5 <= h < 16):
            continue
        dk = day.iat[i]
        if dk in used or dk not in ah.index:
            continue
        a_hi, a_lo, atr = ah[dk], al[dk], t.atr.iat[i]
        up, dn = _trend(t, i)
        if dn and t.high.iat[i] >= a_hi + 0.1 * atr and t.close.iat[i] < a_hi:
            sig.append((i, -1, max(t.high.iat[i] - t.close.iat[i] + t.spr.iat[i] + 0.3 * atr, atr))); used.add(dk)
        elif up and t.low.iat[i] <= a_lo - 0.1 * atr and t.close.iat[i] > a_lo:
            sig.append((i, 1, max(t.close.iat[i] - t.low.iat[i] + t.spr.iat[i] + 0.3 * atr, atr))); used.add(dk)
    return sig


def asian_breakout(t):
    """First London-window close beyond the Asian range in the HTF trend direction; stop at the range midpoint."""
    day, ah, al = session_levels(t)
    sig, used = [], set()
    for i in range(210, len(t) - 1):
        if not (7 <= t.t_open.iat[i].hour < 11):
            continue
        dk = day.iat[i]
        if dk in used or dk not in ah.index:
            continue
        mid, atr = (ah[dk] + al[dk]) / 2, t.atr.iat[i]
        up, dn = _trend(t, i)
        if up and t.close.iat[i] > ah[dk]:
            sig.append((i, 1, max(t.close.iat[i] - mid + t.spr.iat[i], atr))); used.add(dk)
        elif dn and t.close.iat[i] < al[dk]:
            sig.append((i, -1, max(mid - t.close.iat[i] + t.spr.iat[i], atr))); used.add(dk)
    return sig


def build(frames, style):
    b_tf, s_tf, t_tf, _ = STYLES[style]
    b, s, t = prep(frames[b_tf], b_tf), prep(frames[s_tf], s_tf), prep(frames[t_tf], t_tf)
    s["pull_long"] = (s.low <= s.ema20).astype(int).rolling(3).max().fillna(0).astype(bool)
    s["pull_short"] = (s.high >= s.ema20).astype(int).rolling(3).max().fillna(0).astype(bool)
    t = attach(t, b, ["close", "ema50", "ema200"], "b_")
    t = attach(t, s, ["pull_long", "pull_short"], "s_")
    t[["s_pull_long", "s_pull_short"]] = t[["s_pull_long", "s_pull_short"]].fillna(False).astype(bool)
    return t.dropna(subset=["b_ema200"]).reset_index(drop=True)


def fetch(path):
    """Freeze closed GOLD.i# bars (2018+) per timeframe; refuses anything outside a real gold price range."""
    import MetaTrader5 as mt5
    mt5.initialize(); mt5.symbol_select("GOLD.i#", True)
    tfs = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
           "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
    out = {}
    for k, tf in tfs.items():
        r = mt5.copy_rates_from_pos("GOLD.i#", tf, 1, 50000)  # pos 1: closed bars only
        df = pd.DataFrame(r); df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={"tick_volume": "volume"})[["time", "open", "high", "low", "close", "volume", "spread"]]
        df = df[df.time >= "2018-01-01"].reset_index(drop=True)
        assert df.close.between(1000, 10000).all(), f"{k}: not real gold prices"
        out[k] = df
        print(k, len(df), df.time.iloc[0], df.time.iloc[-1])
    pickle.dump(out, open(path, "wb"))


def main():
    frames = pickle.load(open(sys.argv[1], "rb"))
    res = {}
    for style, (_, _, _, tstop) in STYLES.items():
        t = build(frames, style)
        cands = {"trend_pullback": trend_pullback(t), "trend_pullback_no_bias": trend_pullback(t, use_bias=False)}
        if style != "SWING":
            cands["london_sweep"] = london_sweep(t)
            cands["asian_breakout"] = asian_breakout(t)
        res[style] = {"bars": [str(t.t_open.iat[0]), str(t.t_open.iat[-1]), len(t)]}
        for name, sig in cands.items():
            for tgt, ts, tag in ((2.5, tstop, "2.5R+timestop"), (2.0, tstop, "2.0R+timestop"),
                                 (2.5, 120, "2.5R+120min"), (2.5, 0, "2.5R_no_timestop")):
                r = run(t, sig, tgt, ts)
                res[style][f"{name}|{tag}"] = r
                s = r["strategy"]
                print(style, name, tag, {k: s.get(k) for k in ("n", "wr", "exp_r", "pf", "max_dd_r", "h1_exp", "h2_exp")},
                      "| long", r["always_long"].get("exp_r"), "flip", r["flipped"].get("exp_r"),
                      "| over_budget", r["over_budget_skipped"], flush=True)
    json.dump(res, open(sys.argv[2], "w"), indent=1, default=str)


if __name__ == "__main__":
    fetch(sys.argv[2]) if sys.argv[1] == "--fetch" else main()
