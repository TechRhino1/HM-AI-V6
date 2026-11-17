"""SMC/ICT entry, HTF pivot-structure bias and regime-switched exits: cost-honest research.

Question (2026-11-17): does a liquidity sweep -> displacement -> FVG -> CHoCH entry, a better multi-timeframe
bias and regime-switched exits make money after costs, and which components earn their place?

Same honesty rules as tools/strategy_research.py, whose machinery this reuses: completed bars only, decisions at
a bar's close and entry at the next open with the real per-bar spread, slippage on stop exits, broker swap,
the stop assumed first when it shares a bar with a partial or target, and flipped / always-long / spread x2
benchmarks at the same entries with the same exit. Every parameter below is fixed a priori; nothing is tuned.

Styles (entry TF; two bias TFs, the first also gives the regime and the premium/discount range):
    SCALP M5 (H1, H4)    DAY M15 (H1, H4)    SWING H1 (H4, D1)
Structure: fractal pivots K=3 (range_research.pivots), usable from p+3. The BOS state flips to +1 on a close above
    the last confirmed pivot high and to -1 on a close below the last pivot low; a flip from the opposite state is
    a CHoCH. Swing label +1 HH+HL, -1 LH+LL. A TF's read is its BOS state unless the swing label opposes it
    (then 0). Bias = the two bias TFs' reads when they agree (completed bars only).
Regime (first bias TF, completed bar): HIGH_VOL_SHOCK if ATR5/ATR50 > 1.8; else TREND if ADX14 >= 25; else DEAD
    if the BB(20,2) width percentile over 500 bars < 0.2 and ATR5/ATR50 < 0.8; else RANGE.
    VR = Lo-MacKinlay variance ratio of log returns, q = 4 over 100 bars (VR > 1: momentum).
Setup on the entry TF: a displacement bar d (body > 70% of range, range > 1.5 x ATR14 of bar d-1) whose close is
    a CHoCH in its direction and that leaves an FVG (bar d+1 low > bar d-1 high for a BUY). Decision at the close
    of d+1. E1: enter at the next open. E2: limit at the FVG midpoint for 12 bars; it fills only when a bar trades
    a spread through it (BUY: bid low + spread < mid; SELL: bid high > mid + spread).
Sweep: within the 10 bars before d, a bar trades through a completed-session level and closes back inside:
    PDH/PDL (previous UTC day), Asian 00-07 UTC (usable from 07:00), London 07-12 UTC (usable from 12:00),
    EQH/EQL (two of the last 5 confirmed pivots within 0.1 ATR).
Stop: beyond the extreme from the first sweep bar (d-10 without a sweep) to d+1, plus 0.5 ATR forex or 1.0 ATR gold
    and crypto (sells: in ask terms).
Filters (each ablated alone and all together): htf (bias == side), sweep, vol (tick volume of d >= 1.2 x SMA20 of
    the prior 20 bars), session (forex/gold decision 07-10 or 12-15 UTC; crypto regime != DEAD), spread (spread
    <= 20% of the E1 stop), zone (BUY below / SELL above the middle of the first bias TF's last pivot range).
Exits: X0 2.5R. X1 half at 1R, stop to entry + spread, rest at 2.5R. X2 X1 plus a trail beyond the last confirmed
    entry-TF pivot (0.1 ATR). X3 chandelier 3 ATR from the best price once +1R, no target. X4a: X2 when the entry
    regime is TREND and VR > 1, else X0. X4b: the same with X3.
Validation: 4 equal calendar folds per (asset class x style). The exit is chosen per class x style on folds 1-2
    and confirmed on folds 3-4. A layer is adopted only if it raises pooled expectancy and lowers max drawdown
    against the layer below, passes strategy_research.verdict, has PF > 1.5 and is positive in >= 3 of 4 folds.
    Win rate is reported and never decides anything.

Usage:
    python tools/smc_research.py <bars.pkl> <outdir> [SYMBOL ...]   # bars: strategy_research.fetch (M5..D1)
    python tools/smc_research.py --selftest

Writes <outdir>/smc_results.json, smc_tables.md and smc_trades.parquet (every setup's features and its outcome
under each exit, for meta-labeling). Results: reports/SMC_ENTRY_EXIT_RESEARCH_2026-11-17.md
"""
import os, sys, json, pickle
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_research as sr
import range_research as rr
import mtf_entry_research as mtf

gr = sr.gr
STYLES = {"SCALP": ("M5", "H1", "H4"), "DAY": ("M15", "H1", "H4"), "SWING": ("H1", "H4", "D1")}
K = rr.K
SWEEP_WIN, E2_BARS, EQ_ATR = 10, 12, 0.1
BODY, RANGE_ATR, VOL_X = 0.7, 1.5, 1.2
STOP_ATR = {"forex": 0.5, "gold": 1.0, "crypto": 1.0}
TGT, CHAND, PIVOT_BUF = 2.5, 3.0, 0.1
SESSIONS = ((7, 10), (12, 15))
SPREAD_MAX = 0.2
ADX_TREND, SHOCK_ATR, DEAD_BBW, DEAD_ATR, VR_Q, VR_WIN, BBW_WIN = 25, 1.8, 0.2, 0.8, 4, 100, 500
FILTERS = ("htf", "sweep", "vol", "session", "spread", "zone")
# ALL, each filter removed, NONE (the ablation), plus each filter alone on NONE: the full stack can be too rare to test
CFGS = {"ALL": FILTERS, **{f"-{f}": tuple(x for x in FILTERS if x != f) for f in FILTERS}, "NONE": (),
        **{f"+{f}": (f,) for f in FILTERS}}
EXITS = ("X0", "X1", "X2", "X3", "X4a", "X4b")
VARS = ("strategy", "always_long", "flipped", "spread_x2")


# ── market structure, regime, session levels ────────────────────────────────

def _eq(v, tol):
    """Most recent pair among the last 5 pivot levels within tol, or None."""
    v = v[-5:]
    for x in range(len(v) - 1, 0, -1):
        for y in range(x - 1, -1, -1):
            if abs(v[x] - v[y]) <= tol:
                return v[x], v[y]
    return None


def structure(h, l, c, atr):
    """Per bar, from pivots confirmed by that bar only: BOS state, CHoCH (+1/-1 on the flip bar), swing label,
    last pivot high/low, equal highs/lows."""
    ph, pl = rr.pivots(h, l)
    n = len(c)
    state, choch, swing = np.zeros(n, int), np.zeros(n, int), np.zeros(n, int)
    lph, lpl, eqh, eql = (np.full(n, np.nan) for _ in range(4))
    H, L, a, b, st = [], [], 0, 0, 0
    for i in range(n):
        while a < len(ph) and ph[a] + K <= i:
            H.append(h[ph[a]]); a += 1
        while b < len(pl) and pl[b] + K <= i:
            L.append(l[pl[b]]); b += 1
        if H and c[i] > H[-1] and st != 1:
            choch[i], st = (1 if st == -1 else 0), 1
        elif L and c[i] < L[-1] and st != -1:
            choch[i], st = (-1 if st == 1 else 0), -1
        state[i] = st
        if len(H) > 1 and len(L) > 1:
            swing[i] = int(H[-1] > H[-2] and L[-1] > L[-2]) - int(H[-1] < H[-2] and L[-1] < L[-2])
        if H:
            lph[i] = H[-1]
            p = _eq(H, EQ_ATR * atr[i]); eqh[i] = max(p) if p else np.nan
        if L:
            lpl[i] = L[-1]
            p = _eq(L, EQ_ATR * atr[i]); eql[i] = min(p) if p else np.nan
    return {"state": state, "choch": choch, "swing": swing, "lph": lph, "lpl": lpl, "eqh": eqh, "eql": eql}


def regime(d):
    c = d.close
    bbw = (4 * c.rolling(20).std() / c.rolling(20).mean()).rolling(BBW_WIN).rank(pct=True)
    tr = pd.concat([d.high - d.low, (d.high - c.shift()).abs(), (d.low - c.shift()).abs()], axis=1).max(axis=1)
    ar = tr.rolling(5).mean() / tr.rolling(50).mean()
    r = np.log(c).diff()
    vr = r.rolling(VR_Q).sum().rolling(VR_WIN).var() / (VR_Q * r.rolling(VR_WIN).var())
    adx = rr.adx(d)
    lab = np.select([ar > SHOCK_ATR, adx >= ADX_TREND, (bbw < DEAD_BBW) & (ar < DEAD_ATR)],
                    ["HIGH_VOL_SHOCK", "TREND", "DEAD"], "RANGE")
    lab = np.where(bbw.isna() | vr.isna() | ar.isna(), "NA", lab)
    return pd.DataFrame({"adx": adx, "bbw": bbw, "ar": ar, "vr": vr, "lab": lab}, index=d.index)


def levels(e):
    """Completed-session levels per bar: previous UTC day; Asian (00-07) from 07:00; London (07-12) from 12:00."""
    day, hr = e.t_open.dt.floor("D"), e.t_open.dt.hour
    g = e.groupby(day)
    out = {"pdh": day.map(g.high.max().shift(1)), "pdl": day.map(g.low.min().shift(1))}
    for name, lo, hi in (("as", 0, 7), ("ln", 7, 12)):
        m = (hr >= lo) & (hr < hi)
        gs = e[m].groupby(day[m])
        out[name + "h"] = day.map(gs.high.max()).where(hr >= hi)
        out[name + "l"] = day.map(gs.low.min()).where(hr >= hi)
    return {k: v.to_numpy(float) for k, v in out.items()}


# ── setups and candidates ───────────────────────────────────────────────────

def setups(A, S, sw_lo, sw_hi, vol_ok, group):
    """Displacement + FVG + CHoCH setups; the decision bar is i = d + 1."""
    o, h, l, c, atr, spr = (A[k] for k in ("o", "h", "l", "c", "atr", "spr"))
    out = []
    for d in range(SWEEP_WIN + 1, len(c) - 1):
        i, a, rng = d + 1, atr[d - 1], h[d] - l[d]
        if not (a > 0 and rng > RANGE_ATR * a and abs(c[d] - o[d]) > BODY * rng):
            continue
        side = 1 if c[d] > o[d] else -1
        if S["choch"][d] != side or not (l[i] > h[d - 1] if side == 1 else h[i] < l[d - 1]):
            continue
        mid = (h[d - 1] + l[i]) / 2 if side == 1 else (l[d - 1] + h[i]) / 2
        sw = np.flatnonzero((sw_lo if side == 1 else sw_hi)[d - SWEEP_WIN:d])
        s0 = d - SWEEP_WIN + (sw[0] if len(sw) else 0)
        k = STOP_ATR[group] * atr[i]
        if side == 1:
            lvl = l[s0:i + 1].min() - k
            sd, sd2 = c[i] + spr[i] - lvl, mid - lvl
        else:
            lvl = h[s0:i + 1].max() + k + spr[i]
            sd, sd2 = lvl - c[i], lvl - mid
        if sd > 0 and sd2 > 0:
            out.append({"i": i, "d": d, "side": side, "mid": mid, "sd": sd, "sd2": sd2, "sweep": len(sw) > 0,
                        "vol": bool(vol_ok[d]), "body": abs(c[d] - o[d]) / rng, "rng_atr": rng / a})
    return out


def build(P, style, group, info, slip, weekends):
    """Entry frame with completed HTF reads/regime joined, its arrays, and every setup with its filter flags."""
    etf, t1, t2 = STYLES[style]
    hs = []
    for tf in (t1, t2):
        d = P[tf].copy()
        S = structure(*(d[k].to_numpy(float) for k in ("high", "low", "close", "atr")))
        d["read"] = np.where(S["swing"] == -S["state"], 0, S["state"])
        d["plh"], d["pll"] = S["lph"], S["lpl"]
        hs.append(d)
    hs[0] = hs[0].join(regime(hs[0]))
    e = gr.attach(P[etf], hs[0], ["read", "plh", "pll", "adx", "bbw", "ar", "vr", "lab"], "a_")
    e = gr.attach(e, hs[1], ["read"], "b_").reset_index(drop=True)
    A = sr.arrays(e, info, slip, weekends)
    h, l, c, spr, atr = A["h"], A["l"], A["c"], A["spr"], A["atr"]
    S = structure(h, l, c, atr)
    A["lph"], A["lpl"] = S["lph"], S["lpl"]
    lv = levels(e)
    sw_lo, sw_hi = np.zeros(len(c), bool), np.zeros(len(c), bool)
    with np.errstate(invalid="ignore"):
        for L in (lv["pdl"], lv["asl"], lv["lnl"], S["eql"]):
            sw_lo |= (l < L) & (c > L)
        for H in (lv["pdh"], lv["ash"], lv["lnh"], S["eqh"]):
            sw_hi |= (h > H) & (c < H)
    vol = e.volume.to_numpy(float)
    vsma = e.volume.rolling(20).mean().shift(1).to_numpy()
    hod = (e.t_close.dt.hour + e.t_close.dt.minute / 60).to_numpy()
    in_sess = np.zeros(len(c), bool)
    for lo, hi in SESSIONS:
        in_sess |= (hod >= lo) & (hod < hi)
    lab = e.a_lab.fillna("NA").to_numpy()
    ar_, br_ = e.a_read.fillna(0).to_numpy(), e.b_read.fillna(0).to_numpy()
    plh, pll, vr = e.a_plh.to_numpy(float), e.a_pll.to_numpy(float), e.a_vr.to_numpy(float)
    cands = []
    for s in setups(A, S, sw_lo, sw_hi, vol >= VOL_X * vsma, group):
        i, side, d = s["i"], s["side"], s["d"]
        if lab[i] == "NA":
            continue
        pos = (c[i] - pll[i]) / (plh[i] - pll[i]) if plh[i] > pll[i] else np.nan
        flags = {"htf": bool(ar_[i] == side and br_[i] == side), "sweep": s["sweep"], "vol": s["vol"],
                 "session": bool(lab[i] != "DEAD") if group == "crypto" else bool(in_sess[i]),
                 "spread": bool(spr[i] <= SPREAD_MAX * s["sd"]),
                 "zone": bool(pos < 0.5) if side == 1 else bool(pos > 0.5)}   # no defined range -> rejected
        feat = {"body": s["body"], "rng_atr": s["rng_atr"], "vol_ratio": vol[d] / vsma[d] if vsma[d] > 0 else np.nan,
                "spread_stop": spr[i] / s["sd"], "sd_atr": s["sd"] / atr[i], "zone_pos": pos, "hour": hod[i],
                "read_1": ar_[i], "read_2": br_[i], "adx": e.a_adx.iat[i], "bbw_pct": e.a_bbw.iat[i],
                "atr_ratio": e.a_ar.iat[i], "vr": vr[i]}
        cands.append({**s, "k": len(cands), "t": e.t_open.iat[i], "flags": flags, "lab": lab[i],
                      "trend_vr": bool(lab[i] == "TREND" and vr[i] > 1), "feat": feat})
    return e, A, cands


# ── simulation ──────────────────────────────────────────────────────────────

def fill(A, cd, kind):
    """(first live bar, limit price or None = next open at the side's price, stop distance), or None if unfilled."""
    i, n = cd["i"], len(A["o"])
    if kind == "E1":
        return (i + 1, None, cd["sd"]) if i + 1 < n else None
    mid, side = cd["mid"], cd["side"]
    for j in range(i + 1, min(i + 1 + E2_BARS, n)):
        if (A["l"][j] + A["spr"][j] < mid) if side == 1 else (A["h"][j] > mid + A["spr"][j]):
            return j, mid, cd["sd2"]
    return None


def walk_partial(A, j0, side, sd, mode, m=1.0, entry=None):
    """sr.walk with partials and trails. Live from bar j0: at its open (entry None) or at a limit price filled
    inside j0 (then only the stop is checked on j0). Stop first; if a bar reaches 1R and also the new break-even
    stop, the rest is assumed stopped. Trails move after the bar closes. Returns (net R incl. swap, last exit bar,
    swap R) or None if the trade is still open at the end of the data."""
    o, h, l, spr, atr = A["o"], A["h"], A["l"], A["spr"], A["atr"]
    n, slip, limit = len(o), A["slip"], entry is not None
    if entry is None:
        entry = o[j0] + spr[j0] * m if side == 1 else o[j0]
    stop, one = entry - side * sd, entry + side * sd
    tgt = entry + side * TGT * sd if mode in ("X0", "X1", "X2") else None
    left, acc, swr, best = 1.0, 0.0, 0.0, -np.inf

    def book(px, j, w):
        nights = A["W"][A["day"][j] - A["d0"]] - A["W"][A["day"][j0] - A["d0"]]
        sw = nights * sr.swap_px(A["info"], side, entry)
        return w * (side * (px - entry) + sw) / sd, w * sw / sd

    def ratchet(ns):
        return ns if side * (ns - stop) > 0 else stop

    for j in range(j0, n):
        sp = spr[j] * m
        adv = l[j] if side == 1 else h[j] + sp          # worst exit price this bar (bid low / ask high)
        fav = h[j] if side == 1 else l[j] + sp
        if side * (adv - stop) <= 0:
            r, s = book((min(o[j], stop) - slip) if side == 1 else (max(o[j] + sp, stop) + slip), j, left)
            return acc + r, j, swr + s
        if not (limit and j == j0):
            if mode in ("X1", "X2") and left == 1.0 and side * (fav - one) >= 0:
                r, s = book(one, j, 0.5)
                acc, swr, left = acc + r, swr + s, 0.5
                stop = ratchet(entry + side * spr[j0] * m)
                if side * (adv - stop) <= 0:
                    r, s = book(stop - side * slip, j, left)
                    return acc + r, j, swr + s
            if tgt is not None and side * (fav - tgt) >= 0:
                r, s = book(tgt, j, left)
                return acc + r, j, swr + s
            best = max(best, side * fav)
        if mode == "X3" and best >= side * one:
            stop = ratchet(side * best - side * CHAND * atr[j])
        if mode == "X2" and left < 1.0:
            pv = A["lpl"][j] - PIVOT_BUF * atr[j] if side == 1 else A["lph"][j] + sp + PIVOT_BUF * atr[j]
            if pv == pv:
                stop = ratchet(pv)
    return None


def resolve(mode, cd):
    if mode in ("X4a", "X4b"):
        return ("X2" if mode == "X4a" else "X3") if cd["trend_vr"] else "X0"
    return mode


def outcome(A, cd, kind, mode, var, memo):
    key = (cd["k"], kind, mode, var)
    if key not in memo:
        f = fill(A, cd, kind)
        side = {"strategy": cd["side"], "flipped": -cd["side"], "always_long": 1, "spread_x2": cd["side"]}[var]
        memo[key] = f and walk_partial(A, f[0], side, f[2], resolve(mode, cd), 2.0 if var == "spread_x2" else 1.0, f[1])
    return memo[key]


def run_cfg(A, cands, flt, kind, mode, memo, info):
    """One position at a time (as sr.run). Benchmarks reuse the strategy's entry bar and fill."""
    raw = {k: [] for k in (*VARS, "time", "sd", "swap_r", "risk")}
    busy, unfilled, usd = -1, 0, sr.tvps(info) * info["volume_min"]
    for cd in cands:
        if cd["i"] < busy or not all(cd["flags"][f] for f in flt):
            continue
        if kind == "E2" and fill(A, cd, kind) is None:
            unfilled += 1
            continue
        w = outcome(A, cd, kind, mode, "strategy", memo)
        if w is None:
            continue
        r, j, sw = w
        sd = cd["sd2"] if kind == "E2" else cd["sd"]
        raw["strategy"].append(r)
        for v in VARS[1:]:
            b = outcome(A, cd, kind, mode, v, memo)
            raw[v].append(b[0] if b else 0.0)
        raw["time"].append(cd["t"]); raw["sd"].append(sd); raw["swap_r"].append(sw); raw["risk"].append(sd * usd)
        busy = j
    return raw, unfilled


# ── statistics and gates ────────────────────────────────────────────────────

def summ(raw, group, tf, edges):
    s = {k: gr.stats(raw[k], raw["time"]) for k in VARS}
    risk = np.array(raw["risk"], float)
    for acct in sr.ACCOUNTS:
        s[f"afford_{int(acct)}"] = float((risk <= sr.RISK_FRAC * acct).mean()) if len(risk) else 0.0
    ok, why, _ = sr.verdict(s, "XAUUSD" if group == "gold" else group, tf)
    r = np.array(raw["strategy"], float)
    fold = np.searchsorted(edges[1:-1], np.array(raw["time"], dtype="datetime64[ns]"), side="right")
    mean = lambda m: round(float(r[m].mean()), 3) if m.any() else None
    s["folds"] = [mean(fold == f) for f in range(4)]
    s["f12"], s["f34"], s["n12"], s["n34"] = mean(fold < 2), mean(fold >= 2), int((fold < 2).sum()), int((fold >= 2).sum())
    s.update(verdict=ok, why=why)
    return s


def gate(s, below):
    """Adoption gate for a layer against the layer below it."""
    st, why = s["strategy"], []
    if not st["n"]:
        return False, ["no trades"]
    b = below["strategy"]
    if b["n"]:
        if st["exp_r"] <= b["exp_r"]: why.append(f"exp {st['exp_r']:+.3f} not above {b['exp_r']:+.3f}")
        if st["max_dd_r"] >= b["max_dd_r"]: why.append(f"DD {st['max_dd_r']} not below {b['max_dd_r']}")
    if not s["verdict"]: why += s["why"]
    if (st["pf"] or 0) <= 1.5: why.append(f"PF {st['pf']} <= 1.5")
    pos = sum(1 for f in s["folds"] if f is not None and f > 0)
    if pos < 3: why.append(f"positive in {pos}/4 folds")
    return not why, why


def choose_exit(S, g, kind, cfg):
    """Exit with the best folds 1-2 expectancy; confirmed if folds 3-4 are positive and (unless X0) beat X0 there."""
    cand = [(S[(*g, kind, cfg, x)]["f12"], x) for x in EXITS if S[(*g, kind, cfg, x)]["f12"] is not None]
    if not cand:
        return None, False
    x = max(cand)[1]
    f34, f34_x0 = S[(*g, kind, cfg, x)]["f34"], S[(*g, kind, cfg, "X0")]["f34"]
    ok = f34 is not None and f34 > 0 and (x == "X0" or (f34_x0 is not None and f34 > f34_x0))
    return x, ok


# ── research driver ─────────────────────────────────────────────────────────

def research(data, symbols, outdir):
    raws, rej, span, rows = {}, {}, {}, []
    for name in symbols:
        info, P, slip, weekends, _ = mtf.frames(name, data[name])
        group = mtf.GROUP.get(name, "forex")
        for style, (etf, _, _) in STYLES.items():
            e, A, cands = build(P, style, group, info, slip, weekends)
            g = (group, style)
            t0, t1 = e.t_open.iat[0], e.t_open.iat[-1]
            span[g] = (min(span.get(g, (t0, t1))[0], t0), max(span.get(g, (t0, t1))[1], t1))
            R = rej.setdefault(g, {"setups": 0, **{f: 0 for f in FILTERS}, "pass_all": 0, "e2_unfilled": 0})
            R["setups"] += len(cands)
            for cd in cands:
                for f in FILTERS:
                    R[f] += not cd["flags"][f]
                R["pass_all"] += all(cd["flags"].values())
            memo = {}
            jobs = [("E1", c, "X0") for c in CFGS] + [(k, c, x) for k in ("E1", "E2") for c in ("ALL", "NONE")
                                                      for x in EXITS if (k, x) != ("E1", "X0")]
            for kind, cfg, mode in jobs:
                raw, unf = run_cfg(A, cands, CFGS[cfg], kind, mode, memo, info)
                if (kind, cfg, mode) == ("E2", "ALL", "X0"):
                    R["e2_unfilled"] += unf
                raws.setdefault((group, style, kind, cfg, mode), []).append(raw)
            for cd in cands:   # every setup, outcome independent of position overlap (meta-labeling input)
                row = {"symbol": name, "group": group, "style": style, "tf": etf, "time": cd["t"], "side": cd["side"],
                       "regime": cd["lab"], "trend_vr": cd["trend_vr"], "sd": cd["sd"],
                       **{f"f_{f}": v for f, v in cd["flags"].items()}, **cd["feat"]}
                for x in EXITS:
                    w = outcome(A, cd, "E1", x, "strategy", memo)
                    row[f"r_{x}"] = w[0] if w else np.nan
                w = outcome(A, cd, "E2", "X0", "strategy", memo)
                row["r_E2_X0"] = w[0] if w else np.nan
                rows.append(row)
            print(name, style, etf, "setups", len(cands), flush=True)
    edges = {g: pd.to_datetime(np.linspace(lo.value, hi.value, 5)).values for g, (lo, hi) in span.items()}
    S = {k: summ(sr.pool(v), k[0], STYLES[k[1]][0], edges[k[:2]]) for k, v in raws.items()}
    df = pd.DataFrame(rows)
    df["fold"] = [int(np.searchsorted(edges[(g, s)][1:-1], np.datetime64(t), side="right"))
                  for g, s, t in zip(df.group, df.style, df.time)]
    df.to_parquet(os.path.join(outdir, "smc_trades.parquet"))
    return S, rej, edges, df


def components(S, groups):
    out = []
    for g in groups:
        k = lambda kind, cfg, x: S[(*g, kind, cfg, x)]
        out.append((g, "all filters (vs none)", *gate(k("E1", "ALL", "X0"), k("E1", "NONE", "X0"))))
        for f in FILTERS:
            out.append((g, f"filter {f} (ALL vs ALL without it)", *gate(k("E1", "ALL", "X0"), k("E1", f"-{f}", "X0"))))
            out.append((g, f"filter {f} (alone vs NONE)", *gate(k("E1", f"+{f}", "X0"), k("E1", "NONE", "X0"))))
        out.append((g, "E2 retrace entry (vs E1)", *gate(k("E2", "ALL", "X0"), k("E1", "ALL", "X0"))))
        for cfg in ("ALL", "NONE"):
            x, conf = choose_exit(S, g, "E1", cfg)
            if x is None:
                out.append((g, f"exit ({cfg} entries)", False, ["no trades"]))
                continue
            ok, why = gate(k("E1", cfg, x), k("E1", cfg, "X0")) if x != "X0" else (False, ["X0 is the baseline"])
            if not conf: why = why + ["not confirmed on folds 3-4"]
            out.append((g, f"exit {x} ({cfg} entries, chosen on folds 1-2)", ok and conf, why))
    return out


# ── tables ──────────────────────────────────────────────────────────────────

def _f(v, fmt="{:+.3f}"):
    return "-" if v is None else fmt.format(v)


def _row(s):
    st = s["strategy"]
    if not st["n"]:
        return "0 |" + " - |" * 7
    folds = " / ".join(_f(f, "{:+.2f}") for f in s["folds"])
    return (f"{st['n']} | {st['wr']:.0%} | {st['exp_r']:+.3f} | {_f(st['pf'], '{}')} | {st['max_dd_r']} | {folds} | "
            f"{s['spread_x2']['exp_r']:+.3f} | {s['flipped']['exp_r']:+.3f} / {s['always_long']['exp_r']:+.3f}")


HDR = "n | WR | Exp R | PF | Max DD R | Folds 1-4 | Spread x2 | Flipped / long"


def tables(S, rej, comps, df, groups):
    out = ["## Per group (E1 next-open entry, X0 2.5R)", "",
           f"| Group | Style | Filters | {HDR} | sr.verdict |", "|" + "---|" * 13]
    for g in groups:
        for cfg in ("NONE", "ALL"):
            s = S[(*g, "E1", cfg, "X0")]
            out.append(f"| {g[0]} | {g[1]} | {cfg} | {_row(s)} | {'pass' if s['verdict'] else '; '.join(s['why'])} |")
    out += ["", "## Filter ablation (E1, X0): all filters, each one removed, none, each one alone", "",
            f"| Group | Style | Config | {HDR} |", "|" + "---|" * 12]
    for g in groups:
        for cfg in CFGS:
            out.append(f"| {g[0]} | {g[1]} | {cfg} | {_row(S[(*g, 'E1', cfg, 'X0')])} |")
    out += ["", "## Exits (exit chosen per class x style on folds 1-2, checked on folds 3-4)", "",
            f"| Group | Style | Entry | Filters | Exit | {HDR} | Folds 1-2 | Folds 3-4 | Chosen |", "|" + "---|" * 17]
    for g in groups:
        for kind in ("E1", "E2"):
            for cfg in ("ALL", "NONE"):
                x, conf = choose_exit(S, g, kind, cfg)
                for ex in EXITS:
                    s = S[(*g, kind, cfg, ex)]
                    mark = ("**chosen, confirmed**" if conf else "chosen, not confirmed") if ex == x else ""
                    out.append(f"| {g[0]} | {g[1]} | {kind} | {cfg} | {ex} | {_row(s)} | {_f(s['f12'])} ({s['n12']}) | "
                               f"{_f(s['f34'])} ({s['n34']}) | {mark} |")
    out += ["", "## Rejections (setups failing each filter, counted independently)", "",
            "| Group | Style | Setups | " + " | ".join(f"REJECTED_{f.upper()}" for f in FILTERS)
            + " | Pass all | REJECTED_E2_UNFILLED (of ALL) |", "|" + "---|" * 11]
    for g in groups:
        R = rej[g]
        out.append(f"| {g[0]} | {g[1]} | {R['setups']} | " + " | ".join(str(R[f]) for f in FILTERS)
                   + f" | {R['pass_all']} | {R['e2_unfilled']} |")
    out += ["", "## Every setup by entry regime (independent outcomes, no position overlap; E1)", "",
            "| Group | Regime | n | X0 | X1 | X2 | X3 | WR X0 |", "|" + "---|" * 8]
    for (grp, lab), d in df.groupby(["group", "regime"]):
        out.append(f"| {grp} | {lab} | {len(d)} | " + " | ".join(f"{d[f'r_{x}'].mean():+.3f}" for x in EXITS[:4])
                   + f" | {(d.r_X0 > 0).mean():.0%} |")
    tv = df[df.trend_vr]
    out.append(f"| all | TREND and VR > 1 | {len(tv)} | " + " | ".join(f"{tv[f'r_{x}'].mean():+.3f}" for x in EXITS[:4])
               + f" | {(tv.r_X0 > 0).mean():.0%} |")
    out += ["", "## Components against the adoption gate", "", "| Group | Style | Component | Passes | Why not |",
            "|---|---|---|---|---|"]
    for g, comp, ok, why in comps:
        out.append(f"| {g[0]} | {g[1]} | {comp} | {'**PASS**' if ok else 'fail'} | {'; '.join(why)} |")
    return "\n".join(out)


# ── self-test ───────────────────────────────────────────────────────────────

def _zigzag():
    """Falling zigzag (LH/LL, BOS down) ending in a bar that closes above the last confirmed pivot high."""
    c, x = [], 100.0
    for _ in range(5):
        for _ in range(6): x -= 1; c.append(x)
        for _ in range(4): x += 0.5; c.append(x)
    for _ in range(6): x -= 1; c.append(x)
    for _ in range(3): x += 0.5; c.append(x)
    c.append(x + 5)
    c = np.array(c)
    o = np.r_[c[0], c[:-1]]
    h, l = c + 0.1, c - 0.1          # from the close only: max(o, c) would tie neighbouring bars and hide pivots
    l[-1] = o[-1] - 0.1              # the displacement bar spans its open
    return o, h, l, c


def _arrays(o, h, l, c, spr=0.1, atr=1.0):
    n = len(c)
    info = {"price_now": 100.0, "point": 0.01, "swap_long": 0.0, "swap_short": 0.0, "swap_mode": 0, "swap_rollover3days": 3}
    A = {"o": np.array(o, float), "h": np.array(h, float), "l": np.array(l, float), "c": np.array(c, float),
         "spr": np.full(n, spr), "atr": np.full(n, atr), "day": np.full(n, 20_000), "slip": 0.05, "info": info,
         "lph": np.full(n, np.nan), "lpl": np.full(n, np.nan)}
    A["d0"], A["W"] = sr.night_weights(A["day"], info, False)
    return A


def _synth(seed, n=17_280):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.standard_t(3, n) * 0.0008))
    o = np.r_[100.0, c[:-1]]
    w = np.abs(rng.normal(0, 0.0004, (2, n))) * c
    return pd.DataFrame({"time": pd.date_range("2026-01-05", periods=n, freq="5min"), "open": o,
                         "high": np.maximum(o, c) + w[0], "low": np.minimum(o, c) - w[1], "close": c,
                         "volume": rng.integers(50, 500, n), "spread": 2})


def _frames(m5):
    info = {"point": 0.01, "swap_rollover3days": 3}
    ref = {"bps": 1e-3, "usd": 0.02, "model": "usd"}
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "spread": "max"}
    rs = lambda rule: m5.set_index("time").resample(rule).agg(agg).dropna().reset_index()
    return {"M5": sr.prep(m5, "M5", info, ref), "H1": sr.prep(rs("1h"), "H1", info, ref),
            "H4": sr.prep(rs("4h"), "H4", info, ref)}


def selftest():
    # 1. structure: CHoCH up on the last bar of a falling zigzag, not before.
    o, h, l, c = _zigzag()
    S = structure(h, l, c, np.ones(len(c)))
    d = len(c) - 1
    assert S["state"][d - 1] == -1 and S["swing"][d - 1] == -1 and S["choch"][d] == 1, (S["state"][-3:], S["choch"][-3:])
    assert not S["choch"][:d].any() or (S["choch"][:d] != 1).all()
    # 2. displacement + FVG + CHoCH setup, sweep, stop arithmetic; the mirror image gives a SELL.
    o, h, l, c = (np.r_[x, y] for x, y in zip((o, h, l, c), (c[d], c[d] + 0.6, c[d] - 0.2, c[d] + 0.5)))
    n = len(c)
    sw = np.zeros(n, bool); sw[d - 3] = True
    for sgn in (1, -1):
        A = _arrays(*((o, h, l, c) if sgn == 1 else (-o, -l, -h, -c)), spr=0.01)
        S = structure(A["h"], A["l"], A["c"], A["atr"])
        su = setups(A, S, sw if sgn == 1 else np.zeros(n, bool), sw if sgn == -1 else np.zeros(n, bool), np.ones(n, bool), "forex")
        assert len(su) == 1 and su[0]["i"] == d + 1 and su[0]["side"] == sgn and su[0]["sweep"], su
        i = d + 1
        lvl = A["l"][d - 3:i + 1].min() - 0.5 if sgn == 1 else A["h"][d - 3:i + 1].max() + 0.5 + 0.01
        assert abs(su[0]["sd"] - (sgn * (A["c"][i] - lvl) + (0.01 if sgn == 1 else 0))) < 1e-9
        assert not setups(A, S, np.zeros(n, bool), np.zeros(n, bool), np.ones(n, bool), "forex")[0]["sweep"]
    l2 = l.copy(); l2[d + 1] = h[d - 1] - 0.01                                  # no gap -> no setup
    A = _arrays(o, h, l2, c, spr=0.01)
    assert not setups(A, structure(A["h"], A["l"], A["c"], A["atr"]), sw, sw, np.ones(n, bool), "forex")
    # 3. session levels: previous day, Asian from 07:00, London from 12:00.
    t = pd.date_range("2026-01-05", periods=192, freq="15min")
    e = pd.DataFrame({"t_open": t, "high": 101.0, "low": 100.0})
    e.loc[40, "low"], e.loc[96 + 12, "low"], e.loc[96 + 36, "low"] = 95.0, 97.0, 98.0   # d1 10:00, d2 03:00, d2 09:00
    lv = levels(e)
    assert np.isnan(lv["pdl"][:96]).all() and (lv["pdl"][96:] == 95).all()
    assert np.isnan(lv["asl"][96 + 27]) and lv["asl"][96 + 28] == 97 and np.isnan(lv["lnl"][96 + 47]) and lv["lnl"][96 + 48] == 98
    # 4. E2 fill: only when the bar trades a spread through the midpoint, within 12 bars.
    A = _arrays(np.full(20, 100.0), np.full(20, 100.55), np.full(20, 99.45), np.full(20, 100.0))
    assert fill(A, {"i": 0, "side": 1, "mid": 99.5, "sd2": 1}, "E2") is None
    A["l"][5] = 99.35
    assert fill(A, {"i": 0, "side": 1, "mid": 99.5, "sd2": 1}, "E2")[0] == 5
    A["l"][5], A["l"][14] = 99.45, 99.0
    assert fill(A, {"i": 0, "side": 1, "mid": 99.5, "sd2": 1}, "E2") is None   # bar 14 is past 12 bars
    A["h"][3] = 100.65
    assert fill(A, {"i": 0, "side": -1, "mid": 100.5, "sd2": 1}, "E2")[0] == 3
    # 5. partial-exit arithmetic. BUY entry 100.1 (open 100 + spread 0.1), sd 1: 1R 101.1, 2.5R 102.6, BE 100.2.
    A = _arrays([100, 100.5, 101], [101.2, 101.0, 102.7], [100.3, 100.1, 100.9], [101, 100.5, 102])
    r, j, _ = walk_partial(A, 0, 1, 1.0, "X1")                    # half at 1R, rest at BE 100.2 - slip 0.05
    assert j == 1 and abs(r - (0.5 * 1.0 + 0.5 * 0.05)) < 1e-9, r
    A["l"][1] = 100.3
    r, j, _ = walk_partial(A, 0, 1, 1.0, "X1")
    assert j == 2 and abs(r - 1.75) < 1e-9, r                     # 0.5 x 1R + 0.5 x 2.5R
    assert abs(walk_partial(A, 0, 1, 1.0, "X0")[0] - 2.5) < 1e-9
    A["l"][0] = 99.0                                              # stop and 1R in one bar: stop first
    assert abs(walk_partial(A, 0, 1, 1.0, "X1")[0] - (99.1 - 0.05 - 100.1)) < 1e-9
    # SELL mirror: entry 100 (bid), stop 101 ask, 1R 99, 2.5R 97.5, BE 99.9 ask; exits at bid + 0.1.
    A = _arrays([100, 99.5, 98], [99.75, 99.7, 98.2], [98.85, 97.35, 97.0], [99, 98, 97.5])
    r, j, _ = walk_partial(A, 0, -1, 1.0, "X1")
    assert j == 1 and abs(r - 1.75) < 1e-9, r
    # X3 chandelier: armed at 1R, stop 3 ATR (0.1) under the 101.2 high -> 100.9, gap-free exit at 100.9 - slip.
    A = _arrays([100, 101.0], [101.2, 101.1], [100.3, 100.8], [101, 101], atr=0.1)
    r, j, _ = walk_partial(A, 0, 1, 1.0, "X3")
    assert j == 1 and abs(r - (100.85 - 100.1)) < 1e-9, r
    # E2 fill bar: only the stop counts on the fill bar (a target touch there is ignored). Entry 99.8, 2.5R 102.3.
    A = _arrays([100, 100, 100], [102.5, 100.5, 102.4], [99.6, 99.6, 99.6], [100, 100, 100])
    r, j, _ = walk_partial(A, 0, 1, 1.0, "X0", entry=99.8)
    assert j == 2 and abs(r - 2.5) < 1e-9, r
    # 6. no look-ahead: perturbing bars after T must not change any setup decided before T.
    m5 = _synth(7)
    T = m5.time.iat[int(len(m5) * 0.75)]
    m5b = m5.copy()
    fut = (m5b.time >= T).to_numpy()
    shift = np.cumsum(np.random.default_rng(1).normal(0, 0.3, fut.sum()))
    for col in ("open", "high", "low", "close"):
        m5b.loc[fut, col] += shift
    m5b.loc[fut, "volume"] = m5b.loc[fut, "volume"][::-1].to_numpy()
    info = {"price_now": 100.0, "point": 0.01, "swap_rollover3days": 3, "trade_tick_value": 1.0,
            "trade_tick_size": 0.01, "volume_min": 0.01}
    keys = []
    for df in (m5, m5b):
        e, A, cands = build(_frames(df), "SCALP", "forex", info, 0.01, True)
        past = [(str(cd["t"]), cd["side"], round(cd["sd"], 9), round(cd["sd2"], 9), tuple(cd["flags"].values()), cd["lab"])
                for cd in cands if e.time.iat[cd["i"]] + pd.Timedelta(minutes=5) <= T]
        keys.append((past, len(cands)))
    assert keys[0][0] == keys[1][0] and len(keys[0][0]) > 5, (len(keys[0][0]), len(keys[1][0]))
    print(f"selftest ok ({len(keys[0][0])} setups before T identical after perturbing the future; "
          f"{keys[0][1]} vs {keys[1][1]} setups in total)")


def main():
    if sys.argv[1] == "--selftest":
        return selftest()
    data = pickle.load(open(sys.argv[1], "rb"))
    outdir = sys.argv[2]
    symbols = sys.argv[3:] or [s for s in ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD", "ETHUSD") if s in data]
    S, rej, edges, df = research(data, symbols, outdir)
    groups = sorted({k[:2] for k in S}, key=lambda g: (g[0], list(STYLES).index(g[1])))
    for g in groups:
        print(" ".join(f"REJECTED_{f.upper()}={rej[g][f]}" for f in FILTERS), f"REJECTED_E2_UNFILLED={rej[g]['e2_unfilled']}",
              f"setups={rej[g]['setups']} pass_all={rej[g]['pass_all']}", *g)
    comps = components(S, groups)
    md = tables(S, rej, comps, df, groups)
    open(os.path.join(outdir, "smc_tables.md"), "w", encoding="utf-8").write(md)
    json.dump({"stats": {"|".join(k): v for k, v in S.items()}, "rejections": {"|".join(g): v for g, v in rej.items()},
               "fold_edges": {"|".join(g): [str(x) for x in v] for g, v in edges.items()},
               "components": [["|".join(g), c, ok, why] for g, c, ok, why in comps]},
              open(os.path.join(outdir, "smc_results.json"), "w"), indent=1, default=str)
    print(md)
    print("\nPASSED:", [f"{'|'.join(g)} {c}" for g, c, ok, _ in comps if ok] or "none")


if __name__ == "__main__":
    main()
