"""Validate the market adviser's predictive claims on real history and publish only what holds up.

1. Direction models (5-day, per symbol): walk-forward Brier vs base rate → config/markets_models.json.
2. Volatility risk premium (the F&O adviser's core edge): does implied vol (India VIX / CBOE VIX)
   exceed the realised volatility that follows, and how often?
3. Cross-sectional 12-1 momentum on each equities-scanner universe (top quintile vs equal weight, monthly).
4. Institutional positioning: FII index-futures long % extremes (NSE participant-wise OI archive) vs NIFTY's
   next-5-day return. Backfill history first: python -c "from jarvis.markets import inst; inst.backfill(1300)"
5. Global institutional: CFTC COT extremes (contrarian, 4 weeks), DXY 20d trend → EURUSD/XAUUSD next 5 days,
   10y-yield 20d change → XAUUSD next 5 days → "institutional_global". Section 5 alone: --only-global
Writes reports/MARKETS_MODEL_VALIDATION_<date>.md.

    python tools/markets_model_validation.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from jarvis.markets.data import yahoo  # noqa: E402
from jarvis.markets.equities import calc, universe  # noqa: E402
from jarvis.markets.signals import direction  # noqa: E402

UNIVERSE = {
    "IN": ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN",
           "AXISBANK", "KOTAKBANK", "LT", "ITC", "BHARTIARTL", "HINDUNILVR", "BAJFINANCE", "MARUTI", "SUNPHARMA", "TITAN"],
    "US": ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "AMD", "AVGO"],
}
VRP_PAIRS = [("IN", "NIFTY", "INDIAVIX"), ("US", "SPX", "VIX")]


def closed(symbol: str, market: str, rng: str = "10y"):
    b = yahoo.bars(symbol, market, "1d", rng)
    return b["bars"][:-1] if b.get("last_bar_forming") else b["bars"]


def vrp(market: str, under: str, vol_index: str) -> dict:
    """Implied (vol index, 30 calendar days ≈ 21 trading days) vs the realised vol over the next 21 days."""
    u = {b["time"] // 86400: b["close"] for b in closed(under, market)}
    v = {b["time"] // 86400: b["close"] for b in closed(vol_index, market)}
    days = sorted(set(u) & set(v))
    closes = [u[d] for d in days]
    rows = []
    for i in range(len(days) - 22):
        rets = [math.log(closes[j + 1] / closes[j]) for j in range(i, i + 21)]
        m = sum(rets) / 21
        rv = math.sqrt(sum((r - m) ** 2 for r in rets) / 20 * 252) * 100
        rows.append((v[days[i]], rv))
    if not rows:
        return {"available": False}
    spread = sorted(iv - rv for iv, rv in rows)
    return {
        "available": True, "days": len(rows), "from": date.fromtimestamp(days[0] * 86400).isoformat(),
        "iv_above_rv_pct": round(sum(1 for s in spread if s > 0) / len(spread) * 100, 1),
        "mean_iv_minus_rv": round(sum(spread) / len(spread), 2),
        "median_iv_minus_rv": round(spread[len(spread) // 2], 2),
        "worst_5pct": round(spread[len(spread) // 20], 2),
    }


SURVIVORSHIP = ("Universe = today's large caps (the scanner list), back-filled 10 years: stocks that fell out or were "
                "delisted are missing, and names that became large caps are included before they were. This biases "
                "momentum results upward; treat the numbers as an optimistic upper bound.")


def momentum(market: str) -> dict:
    this_month = date.today().strftime("%Y-%m")
    monthly = {}
    for s in universe.symbols(market):
        try:
            monthly[s] = calc.month_end_closes(closed(s, market), this_month)
        except Exception:
            monthly[s] = {}
    rows = calc.momentum_backtest(monthly)
    overall = calc.excess_stats(rows)
    years = {}
    for r in rows:
        years.setdefault(r[0][:4], []).append(r)
    per_year = {y: calc.excess_stats(v) if len(v) > 1 else {"months": len(v), "mean_excess_pct": round(v[0][1] * 100, 3)}
                for y, v in sorted(years.items())}
    ok = bool(overall.get("t_stat") is not None and overall["t_stat"] >= 2 and overall["pct_months_positive"] >= 55)
    reason = (f"t-stat {overall.get('t_stat')} and {overall.get('pct_months_positive')}% positive months "
              f"{'meet' if ok else 'do not meet'} the bar (t >= 2 and >= 55%)") if overall.get("months", 0) > 1 else "too few months"
    return {"published": ok, "reason": reason, "overall": overall, "per_year": per_year,
            "symbols_with_history": sum(1 for v in monthly.values() if len(v) >= 14), "universe_size": len(monthly),
            "survivorship_note": SURVIVORSHIP}


INST_LOOKBACK, INST_LO, INST_HI, INST_H = 250, 0.2, 0.8, 5


def institutional() -> dict:
    """Walk-forward: is FII index-futures long % at a trailing-1y extreme followed by an unusual NIFTY move?
    The NSCCL file for day t is published after the close, so the trade is close(t+1) -> close(t+1+5)."""
    from datetime import datetime
    from jarvis.markets import inst
    from jarvis.markets.data.nse import IST
    hist = inst.participant_history(100000)
    xs = {h["date"]: inst.derive(h["rows"]["FII"])["fut_idx_long_pct"] for h in hist}
    bars = closed("NIFTY", "IN")
    days = [datetime.fromtimestamp(b["time"], IST).date().isoformat() for b in bars]
    close = [b["close"] for b in bars]
    k_of = {d: k for k, d in enumerate(days)}
    obs = [(d, xs[d], k_of[d]) for d in sorted(xs) if d in k_of and xs[d] is not None]
    if len(obs) < INST_LOOKBACK + 60:
        return {"published": False, "reason": f"only {len(obs)} days of participant OI aligned with NIFTY closes (need > {INST_LOOKBACK + 60})"}
    rows = []  # (nifty day index, signal, forward return or None, date)
    for i, (d, x, k) in enumerate(obs):
        if i < INST_LOOKBACK:
            continue
        win = [v for _, v, _ in obs[i - INST_LOOKBACK:i]]
        rank = sum(1 for v in win if v < x) / len(win)
        sig = "low" if rank < INST_LO else "high" if rank > INST_HI else None
        fwd = close[k + 1 + INST_H] / close[k + 1] - 1 if k + 1 + INST_H < len(close) else None
        rows.append((k, sig, fwd, d))
    test = [r for r in rows if r[2] is not None]
    base_mean = sum(r[2] for r in test) / len(test)
    base_up = sum(1 for r in test if r[2] > 0) / len(test)
    out = {"from": test[0][3], "to": test[-1][3], "test_days": len(test), "base_mean_5d_pct": round(base_mean * 100, 3),
           "base_up_rate": round(base_up, 4), "signals": {}}
    bm = bb = 0.0
    nb = 0
    for i, (k, sig, fwd, d) in enumerate(test):
        if not sig:
            continue
        known = [r for r in test[:i] if r[0] + 1 + INST_H <= k]  # outcomes fully realised before day k
        same = [r for r in known if r[1] == sig]
        if len(same) < 20:
            continue
        y = 1.0 if fwd > 0 else 0.0
        pm = sum(1 for r in same if r[2] > 0) / len(same)
        pb = sum(1 for r in known if r[2] > 0) / len(known)
        bm += (pm - y) ** 2
        bb += (pb - y) ** 2
        nb += 1
    for sig in ("low", "high"):
        ev = [r for r in test if r[1] == sig]
        thin, last = [], -99
        for r in ev:  # non-overlapping 5-day windows for the t-stat
            if r[0] - last > INST_H:
                thin.append(r)
                last = r[0]
        ex = [r[2] - base_mean for r in thin]
        n = len(ex)
        mean = sum(ex) / n if n else 0.0
        sd = math.sqrt(sum((e - mean) ** 2 for e in ex) / (n - 1)) if n > 1 else 0.0
        out["signals"][sig] = {"days": len(ev), "non_overlapping": n,
                               "mean_5d_pct": round(sum(r[2] for r in ev) / len(ev) * 100, 3) if ev else None,
                               "up_rate": round(sum(1 for r in ev if r[2] > 0) / len(ev), 4) if ev else None,
                               "mean_excess_pct": round(mean * 100, 3), "t_stat": round(mean / (sd / math.sqrt(n)), 2) if sd and n > 1 else None}
    out["brier"] = {"n": nb, "model": round(bm / nb, 5) if nb else None, "base": round(bb / nb, 5) if nb else None,
                    "gain": round((bb - bm) / nb, 5) if nb else None}
    sigs = list(out["signals"].values())
    best = max([v for v in sigs if v["non_overlapping"] >= 30] or sigs, key=lambda v: abs(v["t_stat"] or 0))
    ok = bool(best["t_stat"] is not None and abs(best["t_stat"]) >= 2 and best["non_overlapping"] >= 30
              and nb and (bb - bm) / nb >= direction.MIN_BRIER_GAIN)
    out["published"] = ok
    out["reason"] = (f"best |t| {abs(best['t_stat'] or 0):.2f} on {best['non_overlapping']} non-overlapping events, OOS Brier gain "
                     f"{out['brier']['gain']} over {nb} signal days: {'meets' if ok else 'does not meet'} the bar "
                     f"(|t| >= 2, >= 30 events, Brier gain >= {direction.MIN_BRIER_GAIN})")
    return out


# ---------------------------------------------------------------- 5. global institutional (CFTC COT, DXY, yields)

COT_H_FX, COT_H_CRYPTO, MACRO_H = 20, 28, 5


def walk_events(rows: list, horizon: int, min_known: int = 20) -> dict:
    """rows = [(entry index k, signal or None, forward return, date)] sorted by k (every day/week, not only
    signals). Same honest stats as section 4: base = mean of all forward returns; t-stat on non-overlapping
    signal events; OOS Brier of P(up | same signal, outcomes known before the decision) vs the past base rate."""
    test = [r for r in rows if r[2] is not None]
    if len(test) < 60:
        return {"published": False, "reason": f"only {len(test)} usable observations", "signals": {}}
    base_mean = sum(r[2] for r in test) / len(test)
    out = {"from": test[0][3], "to": test[-1][3], "observations": len(test), "base_mean_pct": round(base_mean * 100, 3),
           "base_up_rate": round(sum(1 for r in test if r[2] > 0) / len(test), 4), "signals": {}}
    bm = bb = 0.0
    nb = 0
    for i, (k, sig, fwd, d) in enumerate(test):
        if not sig:
            continue
        known = [r for r in test[:i] if r[0] + horizon <= k - 1]  # outcome realised before the decision day
        same = [r for r in known if r[1] == sig]
        if len(same) < min_known:
            continue
        y = 1.0 if fwd > 0 else 0.0
        bm += (sum(1 for r in same if r[2] > 0) / len(same) - y) ** 2
        bb += (sum(1 for r in known if r[2] > 0) / len(known) - y) ** 2
        nb += 1
    thin_all = {}
    for sig in sorted({r[1] for r in test if r[1]}):
        ev = [r for r in test if r[1] == sig]
        thin, last = [], -10 ** 9
        for r in ev:  # non-overlapping holding windows for the t-stat
            if r[0] - last >= horizon:
                thin.append(r)
                last = r[0]
        ex = [r[2] - base_mean for r in thin]
        thin_all[sig] = ex
        n = len(ex)
        mean = sum(ex) / n if n else 0.0
        sd = math.sqrt(sum((e - mean) ** 2 for e in ex) / (n - 1)) if n > 1 else 0.0
        out["signals"][sig] = {"days": len(ev), "non_overlapping": n,
                               "mean_fwd_pct": round(sum(r[2] for r in ev) / len(ev) * 100, 3),
                               "up_rate": round(sum(1 for r in ev if r[2] > 0) / len(ev), 4),
                               "mean_excess_pct": round(mean * 100, 3), "t_stat": round(mean / (sd / math.sqrt(n)), 2) if sd and n > 1 else None}
    out["brier"] = {"n": nb, "model": round(bm / nb, 5) if nb else None, "base": round(bb / nb, 5) if nb else None,
                    "gain": round((bb - bm) / nb, 5) if nb else None}
    out["_raw"] = {"thin": thin_all, "bm": bm, "bb": bb, "nb": nb}
    sigs = list(out["signals"].values())
    if not sigs:
        out.update(published=False, reason="no signal events")
        return out
    best = max([v for v in sigs if v["non_overlapping"] >= 30] or sigs, key=lambda v: abs(v["t_stat"] or 0))
    ok = bool(best["t_stat"] is not None and abs(best["t_stat"]) >= 2 and best["non_overlapping"] >= 30
              and nb and (bb - bm) / nb >= direction.MIN_BRIER_GAIN)
    out["published"] = ok
    out["reason"] = (f"best |t| {abs(best['t_stat'] or 0):.2f} on {best['non_overlapping']} non-overlapping events, OOS Brier gain "
                     f"{out['brier']['gain']} over {nb} signal obs: {'meets' if ok else 'does not meet'} the bar "
                     f"(|t| >= 2, >= 30 events, Brier gain >= {direction.MIN_BRIER_GAIN})")
    return out


def _sym_closes(sym: str):
    from jarvis.markets.data import macro
    c = macro.daily(macro.SYMBOL_TICKERS[sym], "20y")["closes"]
    days = sorted(c)
    return days, [c[d] for d in days]


def entry_rows(days, close, signals, horizon):
    """signals = [(decision date ISO, signal or None)]; entry = first symbol close strictly after the decision date.
    Two decisions mapping to the same entry day count once."""
    import bisect
    rows, seen = [], set()
    for d, sig in sorted(signals):
        k = bisect.bisect_right(days, d)
        if not days or d < days[0] or k >= len(days) or k in seen:  # no symbol history yet at the decision date
            continue
        seen.add(k)
        rows.append((k, sig, close[k + horizon] / close[k] - 1 if k + horizon < len(days) else None, d))
    return rows


def cot_extremes() -> dict:
    """(a) Symbol-oriented COT index < 10 → long, > 90 → short (contrarian); entry the first close after the Friday
    release, exit 4 weeks later. Per symbol, then pooled (contrarian-signed excess)."""
    from jarvis.markets.data import cftc
    cftc.refresh()
    per, pooled, acc = {}, [], [0.0, 0.0, 0]
    for sym in cftc.SYMBOL_MAP:
        h = COT_H_CRYPTO if sym in ("BTCUSD", "ETHUSD") else COT_H_FX
        days, close = _sym_closes(sym)
        sigs = [(cftc.release_date(r["date"]), "low" if r["cot_index_3y"] < cftc.EXTREME_LO else "high" if r["cot_index_3y"] > cftc.EXTREME_HI else None)
                for r in cftc.symbol_index_series(sym)]
        r = walk_events(entry_rows(days, close, sigs, h), h, min_known=10)
        raw = r.pop("_raw", None)
        if raw:
            pooled += raw["thin"].get("low", []) + [-e for e in raw["thin"].get("high", [])]
            acc = [acc[0] + raw["bm"], acc[1] + raw["bb"], acc[2] + raw["nb"]]
        r["horizon_bars"] = h
        per[sym] = r
    n = len(pooled)
    mean = sum(pooled) / n if n else 0.0
    sd = math.sqrt(sum((e - mean) ** 2 for e in pooled) / (n - 1)) if n > 1 else 0.0
    t = round(mean / (sd / math.sqrt(n)), 2) if sd and n > 1 else None
    gain = round((acc[1] - acc[0]) / acc[2], 5) if acc[2] else None
    ok = bool(t is not None and t >= 2 and n >= 30 and gain is not None and gain >= direction.MIN_BRIER_GAIN)
    return {"per_symbol": per, "pooled": {"non_overlapping": n, "mean_contrarian_excess_pct": round(mean * 100, 3), "t_stat": t,
                                          "brier_n": acc[2], "brier_gain": gain},
            "published": ok,
            "reason": f"pooled contrarian t {t} on {n} non-overlapping extremes, OOS Brier gain {gain} over {acc[2]} obs: "
                      f"{'meets' if ok else 'does not meet'} the bar (t >= 2, >= 30 events, Brier gain >= {direction.MIN_BRIER_GAIN})"}


def macro_trend(driver: str, sym: str) -> dict:
    """(b)/(c) Driver's 20-day change beyond the regime threshold on day t → symbol close(t+1) → close(t+1+5)."""
    from jarvis.markets.data import macro
    pct = driver == "DXY"
    c = macro.daily(macro.SERIES[driver], "20y")["closes"]
    dd = sorted(c)
    thr = macro.DXY_TREND_PCT if pct else macro.YIELD_TREND_PTS
    sigs = []
    for i in range(macro.TREND_DAYS, len(dd)):
        a, b = c[dd[i - macro.TREND_DAYS]], c[dd[i]]
        chg = (b / a - 1) * 100 if pct else b - a
        sigs.append((dd[i], "up" if chg > thr else "down" if chg < -thr else None))
    days, close = _sym_closes(sym)
    r = walk_events(entry_rows(days, close, sigs, MACRO_H), MACRO_H)
    r.pop("_raw", None)
    return r


def global_section() -> tuple:
    """(registry block, report lines) for section 5."""
    reg, lines = {}, ["## 5. Global institutional (CFTC COT, dollar, yields) — forex / gold / crypto", "",
                      "Real data only: CFTC Legacy futures-only COT (publicreporting.cftc.gov dataset 6dca-aqww, since 2010), Yahoo daily "
                      "closes (FX relabelled to the session they close; XAUUSD = COMEX GC=F). Same bar as section 4: |t| >= 2 on >= 30 "
                      f"non-overlapping events and OOS Brier gain >= {direction.MIN_BRIER_GAIN}.", ""]
    try:
        a = cot_extremes()
    except Exception as exc:
        a = {"published": False, "reason": f"{type(exc).__name__}: {exc}", "per_symbol": {}}
    reg["cot_extremes"] = a
    lines += [f"(a) COT extremes (3y index < 10 long / > 90 short, entry first close after the Friday release, 4-week hold): "
              f"**{'PUBLISHED' if a['published'] else 'not published'}** — {a['reason']}", "",
              "| Symbol | Weeks | Signal | Events | Non-overlapping | Mean 4w fwd | Up rate | Mean excess | t |", "|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for sym, r in a.get("per_symbol", {}).items():
        for sig, v in (r.get("signals") or {}).items():
            lines.append(f"| {sym} | {r.get('observations')} | {sig} | {v['days']} | {v['non_overlapping']} | {v['mean_fwd_pct']}% | "
                         f"{v['up_rate'] * 100:.1f}% | {v['mean_excess_pct']:+.3f}% | {v['t_stat']} |")
        if not r.get("signals"):
            lines.append(f"| {sym} | {r.get('observations', '—')} | — | | | | | | {r.get('reason')} |")
    lines.append("")
    for key, driver, sym, label in (("dxy_trend_EURUSD", "DXY", "EURUSD", "(b) DXY 20d trend → EURUSD next 5d"),
                                    ("dxy_trend_XAUUSD", "DXY", "XAUUSD", "(b) DXY 20d trend → XAUUSD next 5d"),
                                    ("yields_gold", "US10Y", "XAUUSD", "(c) 10y yield 20d change → XAUUSD next 5d")):
        try:
            r = macro_trend(driver, sym)
        except Exception as exc:
            r = {"published": False, "reason": f"{type(exc).__name__}: {exc}", "signals": {}}
        reg[key] = r
        lines += [f"{label}: **{'PUBLISHED' if r['published'] else 'not published'}** — {r['reason']}", ""]
        if r.get("signals"):
            lines += [f"Window {r['from']} to {r['to']} ({r['observations']} days), base mean {r['base_mean_pct']}%, "
                      f"up {r['base_up_rate'] * 100:.1f}%; Brier model {r['brier']['model']} vs base {r['brier']['base']}.", "",
                      "| Driver signal | Days | Non-overlapping | Mean 5d fwd | Up rate | Mean excess | t |", "|---|---:|---:|---:|---:|---:|---:|"]
            for sig, v in r["signals"].items():
                lines.append(f"| {sig} | {v['days']} | {v['non_overlapping']} | {v['mean_fwd_pct']}% | {v['up_rate'] * 100:.1f}% | "
                             f"{v['mean_excess_pct']:+.3f}% | {v['t_stat']} |")
            lines.append("")
    lines += ["Unpublished tests stay labelled \"context · not validated\" in /api/markets/inst/global.", ""]
    return reg, lines


def main_global_only() -> None:
    """Re-run section 5 only; every other key of the registry is kept."""
    path = os.path.join(ROOT, "config", "markets_models.json")
    with open(path, encoding="utf-8") as f:
        reg = json.load(f)
    reg["institutional_global"], lines = global_section()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=1)
    out = os.path.join(ROOT, "reports", f"MARKETS_MODEL_VALIDATION_GLOBAL_{date.today().isoformat()}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join([f"# Market model validation (section 5 only) — {date.today().isoformat()}", ""] + lines) + "\n")
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    if "--only-global" in sys.argv:
        return main_global_only()
    t0 = time.time()
    reg = {"generated": date.today().isoformat(), "direction": {}, "vrp": {}, "momentum": {}, "institutional": {}}
    lines = [f"# Market model validation — {date.today().isoformat()}", "",
             "All data: real daily closes from the Yahoo chart API (closed bars only). Nothing simulated.", ""]
    lines += ["## 1. Volatility risk premium (core edge of the F&O adviser)", "",
              "| Market | Underlying | Implied index | Days | IV > next-21d realised | Mean IV−RV | Median | Worst 5% |", "|---|---|---|---:|---:|---:|---:|---:|"]
    for market, under, vix in VRP_PAIRS:
        try:
            r = vrp(market, under, vix)
        except Exception as exc:
            r = {"available": False, "error": str(exc)}
        reg["vrp"][f"{market}:{under}"] = r
        if r.get("available"):
            lines.append(f"| {market} | {under} | {vix} | {r['days']} | {r['iv_above_rv_pct']}% | {r['mean_iv_minus_rv']:+.2f} | {r['median_iv_minus_rv']:+.2f} | {r['worst_5pct']:+.2f} |")
        else:
            lines.append(f"| {market} | {under} | {vix} | — | unavailable: {r.get('error', '')} | | | |")
    lines += ["", "Read: positive IV−RV means option sellers were paid more than the moves that followed; the worst-5% column is the tail risk that defined-risk structures exist to cap.", "",
              "## 2. Direction models (5-day horizon, walk-forward, embargoed)", "",
              f"Published only if out-of-sample Brier beats the base rate by ≥ {direction.MIN_BRIER_GAIN} over ≥ {direction.MIN_TEST} test days.", "",
              "| Market | Symbol | Test days | Brier model | Brier base | Gain | Hit rate | Published |", "|---|---|---:|---:|---:|---:|---:|---|"]
    pub = 0
    for market, syms in UNIVERSE.items():
        for s in syms:
            try:
                r = direction.walk_forward(closed(s, market))
            except Exception as exc:
                r = {"published": False, "reason": f"{type(exc).__name__}: {exc}"}
            reg["direction"][f"{market}:{s}"] = r
            pub += bool(r.get("published"))
            if "n_test" in r:
                lines.append(f"| {market} | {s} | {r['n_test']} | {r['brier_model']:.4f} | {r['brier_base']:.4f} | {r['brier_gain']:+.4f} | {r['hit_rate'] * 100:.1f}% | {'yes' if r['published'] else 'no'} |")
            else:
                lines.append(f"| {market} | {s} | — | — | — | — | — | no: {r.get('reason')} |")
    total = sum(len(v) for v in UNIVERSE.values())
    lines += ["", f"**{pub} of {total} direction models published.** Symbols without a published model get no directional view: "
              "the adviser then relies only on the volatility edge and shows trend/OI as unvalidated context.", "",
              "## 3. Cross-sectional momentum (12-1 month, equities scanner universes)", "",
              "Each month end: rank eligible stocks by their return from month t-12 to t-1 (most recent month skipped), "
              "hold the top quintile equal-weight for the next month, compare with the equal-weight eligible universe. "
              "Real month-end closes from Yahoo daily bars; a stock is eligible only with real closes for every month needed. "
              "Published only if t-stat >= 2 and >= 55% of months beat the universe.", ""]
    for market in ("IN", "US"):
        try:
            m = momentum(market)
        except Exception as exc:
            m = {"published": False, "reason": f"{type(exc).__name__}: {exc}", "overall": {}, "per_year": {}}
        reg["momentum"][market] = m
        o = m["overall"]
        lines += [f"### {market} — {'PUBLISHED' if m['published'] else 'not published'}", "",
                  f"{m['reason']}. Universe {m.get('universe_size')} symbols, {m.get('symbols_with_history')} with >= 14 month-ends; "
                  f"{o.get('months', 0)} test months {o.get('from', '')} to {o.get('to', '')}, avg {o.get('avg_names')} names eligible.", "",
                  "| Period | Months | Mean monthly excess | t-stat | % months positive | Max DD of excess | Cumulative excess |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for label, st in list(m["per_year"].items()) + [("**overall**", o)]:
            lines.append(f"| {label} | {st.get('months', 0)} | {st.get('mean_excess_pct', '—')}% | {st.get('t_stat', '—')} | "
                         f"{st.get('pct_months_positive', '—')}% | {st.get('max_drawdown_excess_pct', '—')}% | {st.get('cum_excess_pct', '—')}% |")
        lines.append("")
    lines += [f"**Survivorship bias:** {SURVIVORSHIP}", ""]
    lines += ["## 4. Institutional positioning (NSE participant-wise OI)", "",
              f"(a) FII index-futures long % = long / (long + short) from NSCCL `fao_participant_oi` files. Signal on day t when it is "
              f"below the {int(INST_LO * 100)}th / above the {int(INST_HI * 100)}th percentile of the previous {INST_LOOKBACK} files. "
              f"Outcome: NIFTY close(t+1) → close(t+{1 + INST_H}) (the file comes out after t's close). t-stat on non-overlapping "
              "events; Brier compares P(up | same signal, past only) with the past base rate.", ""]
    try:
        ir = institutional()
    except Exception as exc:
        ir = {"published": False, "reason": f"{type(exc).__name__}: {exc}"}
    ir["pcr"] = "skipped: no historical option-chain PCR source (only today's chain is served; markets.db snapshots are too short)"
    ir["basis"] = ("skipped: futures basis history exists only inside the daily NSE F&O bhavcopy (~1.4 MB/day zip, ~1 GB for "
                   "3 years); not downloaded for this run")
    reg["institutional"] = ir
    lines.append(f"**{'PUBLISHED' if ir.get('published') else 'Not published'}** — {ir.get('reason')}")
    if ir.get("signals"):
        lines += ["", f"Test window {ir['from']} to {ir['to']} ({ir['test_days']} days); base: mean 5-day NIFTY return "
                  f"{ir['base_mean_5d_pct']}%, up {ir['base_up_rate'] * 100:.1f}% of the time.", "",
                  "| FII long % signal | Days | Non-overlapping | Mean 5d return | Up rate | Mean excess | t-stat |", "|---|---:|---:|---:|---:|---:|---:|"]
        for sig, v in ir["signals"].items():
            lines.append(f"| {sig} | {v['days']} | {v['non_overlapping']} | {v['mean_5d_pct']}% | "
                         f"{(v['up_rate'] or 0) * 100:.1f}% | {v['mean_excess_pct']:+.3f}% | {v['t_stat']} |")
        b = ir["brier"]
        lines += ["", f"OOS Brier on {b['n']} signal days: model {b['model']} vs base {b['base']} (gain {b['gain']})."]
    lines += ["", f"(b) PCR: {ir['pcr']}.", f"(c) Futures basis: {ir['basis']}.", ""]
    reg["institutional_global"], glines = global_section()
    lines += glines + [f"_Run time {time.time() - t0:.0f}s._"]
    with open(os.path.join(ROOT, "config", "markets_models.json"), "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=1)
    out = os.path.join(ROOT, "reports", f"MARKETS_MODEL_VALIDATION_{date.today().isoformat()}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    sys.stdout.reconfigure(encoding="utf-8")  # the report has − and ≥; cp1252 consoles cannot print them
    print("\n".join(lines))


if __name__ == "__main__":
    main()
