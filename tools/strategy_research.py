"""Crypto + gold strategy research on frozen real XM MT5 bars, judged by profit after costs.

Generalises tools/gold_research.py (same honesty rules): decisions on completed bars only,
entry at the next bar's open, BUY at the ask / SELL exits pay the real per-bar spread,
slippage on stop/time/signal exits, stop assumed first when stop and target share a bar,
gaps through a stop fill at the open, and every result is compared with always-long and
flipped-direction trades at the same entries with the same exit rule.

All parameters are fixed a priori (no tuning). Added here:
  * per-symbol costs from mt5.symbol_info: point, tick value, min lot, broker swap per night;
  * affordability: min-lot $ risk at each trade's stop vs 2.5% of $100 and of $545.

Swap conversion (one night, price units per 1 contract unit; x tick_value/tick_size x lots = $):
  mode 0 DISABLED -> 0;  1 POINTS -> swap x point;  2 CURRENCY_SYMBOL -> swap x price / tvps;
  3 CURRENCY_MARGIN, 4 CURRENCY_DEPOSIT (USD here) -> swap / tvps;  5/6 INTEREST -> swap/100/360 x price.
  Nights = broker-date rollovers crossed; weekend dates count only for symbols that trade on
  weekends (crypto); the swap_rollover3days weekday counts 3x (XM crypto reports 7 = none).
  Current swap rates are applied to the whole history. Points/currency swaps are scaled by
  entry price / today's price: XM sets them as a share of notional (BTC -2802.76 points = $28/BTC/night
  = 0.043%/night ~ 16%/yr at $64.7k), and a fixed $28 would be 28%/night on 2013's $100 BTC.

Usage:
    python tools/strategy_research.py --fetch <bars.pkl>      # freeze closed bars + symbol_info from MT5
    python tools/strategy_research.py <bars.pkl> <out.json>   # run every candidate, print markdown table
    python tools/strategy_research.py --selftest

Results and conclusions: reports/CRYPTO_GOLD_RESEARCH_2026-11-16.md
"""
import os, sys, json, pickle
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_research as gr  # prep / attach / stats machinery

SYMBOLS = {  # name: (MT5 symbol, sane close range -- fetch refuses anything outside it, modeled-spread unit)
    "BTCUSD": ("BTCUSD#", 10, 500_000, "bps"),   # crypto spreads scale with price
    "ETHUSD": ("ETHUSD#", 0.1, 20_000, "bps"),
    "SOLUSD": ("SOLUSD#", 0.1, 2_000, "bps"),
    "XAUUSD": ("GOLD.i#", 200, 10_000, "usd"),   # gold spread ~constant in $ (conservative at old, low prices)
}
FOREX = {  # used by tools/range_research.py; spreads ~constant in price units
    "EURUSD": ("EURUSD#", 0.5, 2.0, "usd"),
    "GBPUSD": ("GBPUSD#", 0.8, 2.5, "usd"),
    "USDJPY": ("USDJPY#", 70, 400, "usd"),  # 1970s ~300
    "USDCAD": ("USDCAD#", 0.9, 1.8, "usd"),
    "AUDUSD": ("AUDUSD#", 0.4, 1.2, "usd"),
}
TFS = ("M5", "M15", "H1", "H4", "D1")
INFO_KEYS = ("point", "digits", "trade_contract_size", "volume_min", "trade_tick_value", "trade_tick_size",
             "swap_long", "swap_short", "swap_mode", "swap_rollover3days", "currency_profit", "spread")
RISK_FRAC, ACCOUNTS = 0.025, (100.0, 545.0)
STOP_ATR = 3.0          # catastrophic / trailing stop width for the trend and pullback candidates
AFFORD_MIN = 0.80       # share of trades whose min-lot risk must fit 2.5% of the account
NS_MIN = 60_000_000_000


# ── data ─────────────────────────────────────────────────────────────────────

def fetch(path, symbols=None):
    """Freeze closed bars (max terminal history) and symbol_info per symbol; refuse non-real prices."""
    import MetaTrader5 as mt5
    assert mt5.initialize(), mt5.last_error()
    count = min(mt5.terminal_info().maxbars - 1, 50_000)
    out = {}
    for name, (sym, lo, hi, _) in (symbols or SYMBOLS).items():
        assert mt5.symbol_select(sym, True), sym
        info = mt5.symbol_info(sym)._asdict()
        frames = {}
        for tf in TFS:
            for _ in range(5):  # the terminal's IPC drops large requests while the live engine is busy
                r = mt5.copy_rates_from_pos(sym, getattr(mt5, "TIMEFRAME_" + tf), 1, count)  # pos 1: closed bars only
                if r is not None and len(r):
                    break
                import time; time.sleep(3); mt5.initialize()
            assert r is not None and len(r), f"{sym} {tf}: {mt5.last_error()}"
            df = pd.DataFrame(r)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df = df.rename(columns={"tick_volume": "volume"})[["time", "open", "high", "low", "close", "volume", "spread"]]
            real = (df.close.between(lo, hi).all() and (df.high >= df[["open", "close"]].max(axis=1)).all()
                    and (df.low <= df[["open", "close"]].min(axis=1)).all() and (df.spread >= 0).all())
            assert real, f"{sym} {tf}: not real {name} prices"
            frames[tf] = df
            print(name, tf, len(df), df.time.iloc[0], df.time.iloc[-1])
        out[name] = {"symbol": sym, "info": {k: info[k] for k in INFO_KEYS}, "frames": frames}
    pickle.dump(out, open(path, "wb"))


def tvps(info):
    """$ per 1.0 price move per 1 lot."""
    return info["trade_tick_value"] / info["trade_tick_size"]


def swap_px(info, side, price):
    """Broker swap for one night in price units (see module docstring)."""
    s, m = (info["swap_long"] if side == 1 else info["swap_short"]), info["swap_mode"]
    k = price / info["price_now"]
    if m == 0:
        return 0.0
    if m == 1:
        return s * info["point"] * k
    if m == 2:
        return s * price / tvps(info)
    if m in (3, 4):
        return s / tvps(info) * k
    if m in (5, 6):
        return s / 100 / 360 * price
    raise ValueError(f"swap_mode {m} not supported")


def night_weights(days, info, weekends):
    """Cumulative rollover weights by broker date: W[d] = nights charged for dates before d."""
    d0, d1 = int(days.min()), int(days.max()) + 2
    d = np.arange(d0, d1)
    wd_py = (d + 3) % 7                      # epoch day 0 was a Thursday; Monday = 0
    wd_mt5 = (wd_py + 1) % 7                 # MT5 ENUM_DAY_OF_WEEK: Sunday = 0
    w = np.where(wd_mt5 == info["swap_rollover3days"], 3, 1)
    if not weekends:
        w = np.where(wd_py >= 5, 0, w)
    return d0, np.concatenate([[0], np.cumsum(w)])


def prep(df, tf, info, ref):
    """gold_research.prep + real per-bar spread. The broker's old history has zero spreads (gold < 2019,
    crypto < 2018) and implausible ones (BTC 2018-21 ~ $1,260): those bars get the last-12-month median
    spread instead (in bps of price for crypto, in $ for gold) and are flagged 'modeled'."""
    d = gr.prep(df, tf)
    real = d["spread"] * info["point"]
    d["modeled"] = (d["spread"] <= 0) | (real / d["close"] > 5 * ref["bps"])
    d["spr"] = np.where(d["modeled"], ref["bps"] * d["close"] if ref["model"] == "bps" else ref["usd"], real)
    d["bday"] = d["time"].values.astype("datetime64[D]").astype(np.int64)  # broker wall-clock date
    return d


def arrays(d, info, slip, weekends):
    A = {k: d[c].to_numpy(float) for k, c in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"),
                                              ("spr", "spr"), ("atr", "atr"))}
    A["to"] = d["t_open"].values.astype("datetime64[ns]").astype(np.int64)
    A["tc"] = d["t_close"].values.astype("datetime64[ns]").astype(np.int64)
    A["day"] = d["bday"].to_numpy()
    A["d0"], A["W"] = night_weights(A["day"], info, weekends)
    A["slip"], A["info"], A["t"] = slip, info, d["t_open"]
    return A


# ── simulation ───────────────────────────────────────────────────────────────

def walk(A, i, side, sd, ex, rule_side, m=1.0):
    """Enter at bar i+1 open; exits: stop (gap fills at open), target, close-based signal / max bars
    (filled at the next open), stagnation (filled at the close), trailing stop updated on closes.
    rule_side picks which side's exit signal to follow (benchmarks follow the original trade's rule).
    Returns (net R incl. swap, exit bar, swap R) or None if the trade never closes in-sample."""
    o, h, l, c, spr, atr = A["o"], A["h"], A["l"], A["c"], A["spr"], A["atr"]
    n, j0, slip = len(o), i + 1, A["slip"]
    if j0 >= n:
        return None
    entry = o[j0] + spr[j0] * m if side == 1 else o[j0]
    stop = entry - side * sd
    tgt = entry + side * ex["tgt"] * sd if ex.get("tgt") else None
    xr = ex.get("exit_long") if rule_side == 1 else ex.get("exit_short")
    mb, trail = ex.get("max_bars"), ex.get("trail")
    stag = ex.get("stag_min", 0) * NS_MIN

    def fin(px, j):
        nights = A["W"][A["day"][j] - A["d0"]] - A["W"][A["day"][j0] - A["d0"]]
        sw = nights * swap_px(A["info"], side, entry)
        return (side * (px - entry) + sw) / sd, j, sw / sd

    for j in range(j0, n):
        sp = spr[j] * m
        if side == 1:
            if l[j] <= stop:
                return fin(min(o[j], stop) - slip, j)
            if tgt is not None and h[j] >= tgt:
                return fin(tgt, j)
            px = c[j]
        else:
            if h[j] + sp >= stop:
                return fin(max(o[j] + sp, stop) + slip, j)
            if tgt is not None and l[j] + sp <= tgt:
                return fin(tgt, j)
            px = c[j] + sp
        if (xr is not None and xr[j]) or (mb and j - j0 + 1 >= mb):
            if j + 1 >= n:
                return None
            return fin(o[j + 1] - slip if side == 1 else o[j + 1] + spr[j + 1] * m + slip, j + 1)
        if stag and A["tc"][j] - A["to"][j0] >= stag and side * (px - entry) / sd < 0.10:
            return fin(px - side * slip, j)
        if trail:
            ns = c[j] - side * trail * atr[j]
            stop = max(stop, ns) if side == 1 else min(stop, ns)
    return None


def run(A, sig, ex):
    """One position at a time. Raw per-trade lists for the strategy, benchmarks and spread x2.
    For long-only candidates 'always_long' at the same entries would be the strategy itself, so it is
    replaced by longs on 5 random bars (seeded) held the same number of bars with the same ATR stop."""
    raw = {k: [] for k in ("strategy", "always_long", "flipped", "spread_x2", "time", "sd", "swap_r")}
    busy, long_only, rng, n = -1, all(sd_[1] == 1 for sd_ in sig), np.random.default_rng(0), len(A["c"])
    ex0 = ex
    for item in sig:  # (i, side, stop_dist[, target_r]) -- a per-trade target overrides ex["tgt"]
        i, side, sd = item[:3]
        ex = {**ex0, "tgt": item[3]} if len(item) > 3 else ex0
        if i < busy or not sd > 0:
            continue
        w = walk(A, i, side, sd, ex, side)
        if w is None:
            continue
        r, j, sw = w
        raw["strategy"].append(r)
        for k, s2, m in (("always_long", 1, 1.0), ("flipped", -side, 1.0), ("spread_x2", side, 2.0)):
            if k == "always_long" and long_only:
                hold = j - i
                rb = [walk(A, k2, 1, sd / A["atr"][i] * A["atr"][k2], {"max_bars": hold}, 1)
                      for k2 in rng.integers(200, n - hold - 2, 5)]
                raw[k].append(float(np.mean([b[0] for b in rb if b])))
                continue
            b = walk(A, i, s2, sd, ex, side, m)
            raw[k].append(b[0] if b else 0.0)
        raw["time"].append(A["t"].iat[i]); raw["sd"].append(sd); raw["swap_r"].append(sw)
        busy = j
    return raw


def pool(raws):
    """Ensemble of independent sub-systems (each 1/n of capital): merge trades in time order."""
    keys = list(raws[0].keys())
    rows = sorted(zip(*[sum((r[k] for r in raws), []) for k in keys]), key=lambda x: x[keys.index("time")])
    return {k: [row[n] for row in rows] for n, k in enumerate(keys)}


def summarise(raw, info, real_start):
    s = {k: gr.stats(raw[k], raw["time"]) for k in ("strategy", "always_long", "flipped", "spread_x2")}
    if not raw["strategy"]:
        return s
    real = np.array(raw["time"]) >= np.datetime64(real_start)   # trades on real broker spreads only
    s["real_era"] = {k: round(float(np.mean(np.array(raw[k])[real])), 3) if real.any() else None
                     for k in ("strategy", "always_long", "flipped")}
    s["real_era"]["n"] = int(real.sum())
    risk = np.array(raw["sd"]) * tvps(info) * info["volume_min"]   # $ at min lot if the stop is hit
    s["usd_min_lot"] = round(float(np.sum(np.array(raw["strategy"]) * risk)), 2)
    s["min_lot_risk_median"] = round(float(np.median(risk)), 2)
    for acct in ACCOUNTS:
        s[f"afford_{int(acct)}"] = round(float((risk <= RISK_FRAC * acct).mean()), 3)
    s["account_for_80pct"] = round(float(np.percentile(risk, 80) / RISK_FRAC), 0)   # 80% of trades fit 2.5%
    s["swap_r_mean"] = round(float(np.mean(raw["swap_r"])), 3)
    return s


def verdict(s, name, tf):
    """Agreed adoption criteria; returns (adopted, reasons, low_confidence)."""
    st, why = s["strategy"], []
    if st["n"] == 0:
        return False, ["no trades"], False
    min_n = 40 if tf == "D1" else 100
    if st["n"] < min_n: why.append(f"n {st['n']} < {min_n}")
    if st["exp_r"] <= 0: why.append("loses after costs+swap")
    if (st["pf"] or 0) <= 1.1: why.append(f"PF {st['pf']} <= 1.1")
    if st["h1_exp"] <= 0 or st["h2_exp"] <= 0: why.append("a half is negative")
    if s["spread_x2"]["exp_r"] <= 0: why.append("fails spread x2")
    if st["exp_r"] <= s["always_long"]["exp_r"]: why.append("not above always-long")
    if st["exp_r"] <= s["flipped"]["exp_r"]: why.append("not above flipped")
    acct = 545 if name == "XAUUSD" else 100
    if s[f"afford_{acct}"] < AFFORD_MIN: why.append(f"min lot unaffordable at ${acct} ({s[f'afford_{acct}']:.0%} fit)")
    return not why, why, tf == "D1" and st["n"] < 100


# ── candidates (fixed a-priori parameters) ──────────────────────────────────

def _prior_max(x, n):
    return pd.Series(x).rolling(n).max().shift(1).to_numpy()


def _prior_min(x, n):
    return pd.Series(x).rolling(n).min().shift(1).to_numpy()


def donchian(A, n_in, n_out):
    """Close beyond the prior n_in-bar high/low; exit on the opposite n_out-bar channel or a 3xATR trail."""
    c, atr = A["c"], A["atr"]
    up, dn = c > _prior_max(A["h"], n_in), c < _prior_min(A["l"], n_in)
    sig = [(i, 1 if up[i] else -1, STOP_ATR * atr[i]) for i in range(200, len(c)) if up[i] or dn[i]]
    ex = {"exit_long": c < _prior_min(A["l"], n_out), "exit_short": c > _prior_max(A["h"], n_out), "trail": STOP_ATR}
    return sig, ex


def tsmom(A, lb):
    """Sign of the lb-bar return, re-evaluated every close; flip/exit on sign change; fixed 3xATR stop."""
    c = A["c"]
    s = np.sign(c - pd.Series(c).shift(lb).to_numpy())
    sig = [(i, int(s[i]), STOP_ATR * A["atr"][i]) for i in range(max(lb, 200), len(c)) if s[i] in (1, -1)]
    return sig, {"exit_long": s < 0, "exit_short": s > 0}


def max10(A):
    """Long-only: hold while the close is the 10-day closing high (Quantpedia MAX); 3xATR catastrophic stop."""
    c = A["c"]
    at_hi = c >= pd.Series(c).rolling(10).max().to_numpy()
    sig = [(i, 1, STOP_ATR * A["atr"][i]) for i in range(200, len(c)) if at_hi[i]]
    return sig, {"exit_long": ~at_hi, "exit_short": at_hi}


def rsi2(A, ema200):
    """Connors-style: with the EMA200 trend, RSI(2) < 10 (> 90 short); exit RSI(2) > 70 (< 30) or 5 bars."""
    cs = pd.Series(A["c"])
    d = cs.diff()
    rs = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean() / (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    r = (100 - 100 / (1 + rs)).fillna(50).to_numpy()
    c, sig = A["c"], []
    for i in range(200, len(c)):
        if c[i] > ema200[i] and r[i] < 10:
            sig.append((i, 1, STOP_ATR * A["atr"][i]))
        elif c[i] < ema200[i] and r[i] > 90:
            sig.append((i, -1, STOP_ATR * A["atr"][i]))
    return sig, {"exit_long": r > 70, "exit_short": r < 30, "max_bars": 5}


def scalp(t, A, tgt):
    """M5, 12:30-16:00 UTC decisions, H1 EMA50 vs EMA200 permission, pull back to EMA20/VWAP within
    3 bars then a close beyond the prior bar's extreme and EMA20; structural stop; 45-min stagnation exit."""
    hod = t.t_close.dt.hour + t.t_close.dt.minute / 60
    win = ((hod >= 12.5) & (hod < 16)).to_numpy()
    up, dn = (t.b_ema50 > t.b_ema200).to_numpy(), (t.b_ema50 < t.b_ema200).to_numpy()
    tl = ((t.low <= t.ema20) | (t.low <= t.vwap)).astype(int).rolling(3).max().fillna(0).to_numpy() > 0
    ts = ((t.high >= t.ema20) | (t.high >= t.vwap)).astype(int).rolling(3).max().fillna(0).to_numpy() > 0
    lo3, hi3 = t.low.rolling(3).min().to_numpy(), t.high.rolling(3).max().to_numpy()
    c, h, l, e20, atr, spr = A["c"], A["h"], A["l"], t.ema20.to_numpy(), A["atr"], A["spr"]
    sig = []
    for i in range(210, len(c)):
        if not win[i]:
            continue
        if up[i] and tl[i] and c[i] > h[i - 1] and c[i] > e20[i]:
            sig.append((i, 1, max(c[i] - lo3[i] + spr[i] + 0.3 * atr[i], atr[i])))
        elif dn[i] and ts[i] and c[i] < l[i - 1] and c[i] < e20[i]:
            sig.append((i, -1, max(hi3[i] - c[i] + spr[i] + 0.3 * atr[i], atr[i])))
    return sig, {"tgt": tgt, "stag_min": 45}


def bars_per_month(d):
    last = d.t_open.iat[-1]
    return int(round((d.t_open > last - pd.Timedelta(days=365)).sum() / 12))


def research(data):
    res, rows = {}, []
    for name, blob in data.items():
        info, fr = {**blob["info"], "price_now": float(blob["frames"]["H1"].close.iat[-1])}, blob["frames"]
        weekends = bool((fr["H1"].time.dt.dayofweek >= 5).any())
        h = fr["H1"][fr["H1"].time > fr["H1"].time.iloc[-1] - pd.Timedelta(days=365)]
        rs = h.spread * info["point"]
        ref = {"bps": float(np.median(rs / h.close)), "usd": float(np.median(rs)), "model": SYMBOLS[name][3]}
        slip = 0.5 * ref["usd"]   # half the recent median spread: gold ~$0.10, as gold_research
        P = {tf: prep(fr[tf], tf, info, ref) for tf in TFS if tf in fr}
        yr = P["H1"].groupby(P["H1"].t_open.dt.year).modeled.mean()      # real era: from the first year after
        bad_years = yr[yr >= 0.05].index                                  # which every year is >= 95% real spreads
        real_start = pd.Timestamp(f"{bad_years.max() + 1}-01-01") if len(bad_years) else P["H1"].t_open.iat[0]
        m5 = gr.attach(P["M5"], P["H1"], ["ema50", "ema200"], "b_").dropna(subset=["b_ema200"]).reset_index(drop=True)
        day = m5.t_open.dt.floor("D")
        tp, v = (m5.high + m5.low + m5.close) / 3, m5.volume.clip(lower=1)
        m5["vwap"] = (tp * v).groupby(day).cumsum() / v.groupby(day).cumsum()
        P["M5"] = m5
        A = {tf: arrays(P[tf], info, slip, weekends) for tf in P}
        res[name] = {"symbol": blob["symbol"], "info": info, "slip": slip, "weekends": weekends, "spread_ref": ref,
                     "real_spread_from": str(real_start),
                     "modeled_share": {tf: round(float(P[tf].modeled.mean()), 3) for tf in P},
                     "bars": {tf: [str(P[tf].t_open.iat[0]), str(P[tf].t_open.iat[-1]), len(P[tf])] for tf in P},
                     "median_spread": {tf: float(np.median(P[tf].spr)) for tf in P}}
        jobs = []
        for tf in ("D1", "H4"):
            jobs.append(("donchian_ens", tf, [run(A[tf], *donchian(A[tf], a, b)) for a, b in ((20, 10), (55, 20), (100, 20))]))
            bpm = bars_per_month(P[tf])
            jobs.append(("tsmom_ens", tf, [run(A[tf], *tsmom(A[tf], k * bpm)) for k in (1, 3, 6)]))
        jobs.append(("max10_long", "D1", [run(A["D1"], *max10(A["D1"]))]))
        for tf in ("H1", "H4"):
            jobs.append(("rsi2_trend", tf, [run(A[tf], *rsi2(A[tf], P[tf].ema200.to_numpy()))]))
        for tg in (1.0, 1.5):
            jobs.append((f"m5_scalp_{tg}R", "M5", [run(A["M5"], *scalp(m5, A["M5"], tg))]))
        for cand, tf, raws in jobs:
            s = summarise(pool(raws) if len(raws) > 1 else raws[0], info, real_start)
            ok, why, low = verdict(s, name, tf)
            s.update(adopted=ok, reasons=why, low_confidence=low)
            res[name][f"{cand}|{tf}"] = s
            rows.append((name, cand, tf, s))
            st = s["strategy"]
            print(name, cand, tf, {k: st.get(k) for k in ("n", "exp_r", "pf", "h1_exp", "h2_exp")},
                  "long", s["always_long"].get("exp_r"), "flip", s["flipped"].get("exp_r"),
                  "x2", s["spread_x2"].get("exp_r"), "real-era", s.get("real_era"), "ADOPT" if ok else why, flush=True)
    return res, rows


def table(rows):
    out = ["| Symbol | Candidate | TF | n | WR | Exp R | PF | 1st half | 2nd half | Spread x2 | Always long | Flipped "
           "| Real-spread era n: strat / long / flip | Swap R/trade | $ at min lot | Min-lot risk (median) | Fit $100 | Fit $545 "
           "| Account for 80% fit | Verdict |",
           "|" + "---|" * 20]
    for name, cand, tf, s in rows:
        st = s["strategy"]
        if not st["n"]:
            out.append(f"| {name} | {cand} | {tf} | 0 |" + " |" * 15 + " rejected: no trades |")
            continue
        edge_only = s["reasons"] and all(r.startswith("min lot") for r in s["reasons"])
        v = ("**ADOPT**" + (" (low confidence)" if s["low_confidence"] else "")) if s["adopted"] else             ("**edge passes**, rejected only on min lot: " if edge_only else "rejected: ") + "; ".join(s["reasons"])
        out.append(f"| {name} | {cand} | {tf} | {st['n']} | {st['wr']:.0%} | {st['exp_r']:+.3f} | {st['pf']} | "
                   f"{st['h1_exp']:+.3f} | {st['h2_exp']:+.3f} | {s['spread_x2']['exp_r']:+.3f} | "
                   f"{s['always_long']['exp_r']:+.3f} | {s['flipped']['exp_r']:+.3f} | "
                   f"{s['real_era']['n']}: {s['real_era']['strategy']} / {s['real_era']['always_long']} / {s['real_era']['flipped']} | "
                   f"{s['swap_r_mean']:+.3f} | "
                   f"{s['usd_min_lot']:+,.0f} | ${s['min_lot_risk_median']:,.2f} | {s['afford_100']:.0%} | "
                   f"{s['afford_545']:.0%} | ${s['account_for_80pct']:,.0f} | {v} |")
    return "\n".join(out)


def selftest():
    info = {"price_now": 100.0, "point": 0.01, "trade_tick_value": 1.0, "trade_tick_size": 0.01, "volume_min": 0.01,
            "swap_long": -100.0, "swap_short": 0.0, "swap_mode": 1, "swap_rollover3days": 3}
    days = np.arange(20_000, 20_014)                       # two full weeks
    d0, W = night_weights(days, info, weekends=False)
    assert W[7] - W[0] == 7                                # 5 weekdays, Wednesday triple
    d0, W = night_weights(days, {**info, "swap_rollover3days": 7}, weekends=True)
    assert W[7] - W[0] == 7                                # crypto: every night once
    n = 5
    A = {"o": np.full(n, 100.0), "h": np.full(n, 100.5), "l": np.full(n, 99.5), "c": np.full(n, 100.0),
         "spr": np.full(n, 0.2), "atr": np.ones(n), "to": np.arange(n) * NS_MIN, "tc": (np.arange(n) + 1) * NS_MIN,
         "day": np.full(n, 20_000), "slip": 0.1, "info": info}
    A["d0"], A["W"] = night_weights(A["day"], info, False)
    r, j, sw = walk(A, 0, 1, 2.0, {"max_bars": 1}, 1)      # buy 100.2, exit next open 100 - 0.1
    assert j == 2 and abs(r - (-0.3 / 2.0)) < 1e-9 and sw == 0
    r, j, _ = walk(A, 0, -1, 2.0, {"max_bars": 1}, -1)     # sell 100, buy back 100.2 + 0.1
    assert abs(r - (-0.3 / 2.0)) < 1e-9
    r, j, _ = walk(A, 0, 1, 0.5, {}, 1)                    # stop 99.7 inside first bar's low 99.5
    assert j == 1 and abs(r - (-0.6 / 0.5)) < 1e-9
    A["day"] = np.array([20_003, 20_003, 20_004, 20_005, 20_006])  # Mon..Thu: crosses Mon + Tue nights
    A["d0"], A["W"] = night_weights(A["day"], info, False)
    r, j, sw = walk(A, 0, 1, 2.0, {"max_bars": 2}, 1)      # held bars 1-2, exit open of bar 3
    assert j == 3 and abs(sw - (-2.0 * 1.002 / 2.0)) < 1e-9  # 2 nights x -100 pts x 0.01 x (100.2/100 price scale), / sd 2
    print("selftest ok")


def main():
    if sys.argv[1] == "--selftest":
        return selftest()
    if sys.argv[1] == "--fetch":
        return fetch(sys.argv[2])
    res, rows = research(pickle.load(open(sys.argv[1], "rb")))
    json.dump(res, open(sys.argv[2], "w"), indent=1, default=str)
    print(table(rows))


if __name__ == "__main__":
    main()
