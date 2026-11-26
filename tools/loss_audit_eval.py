"""Evaluate run_mode_backtest outputs for the 2026-11-27 loss audit.

Reads one or more run directories (``<SYM>__<STYLE>.json`` from tools/backtests/run_mode_backtest.py)
and prints per symbol x style metrics in R: trades, win%, net R, PF, expectancy, avg win/loss,
max drawdown (R), max consecutive losses, trades/week, per-trade Sharpe and the deflated Sharpe
ratio over the true number of trials. Entry filters are screened post-hoc on the same trade list
(skip a trade when the filter is false); a filter that passes is then implemented and re-run.
(tools/summarize_mode_backtest.py only prints one directory's stored metrics.)

    python tools/loss_audit_eval.py reports/loss_audit/after_holdout_default [--base DIR] [--filters]
            [--json OUT] [--trials N]

Real MT5 parquet only (data/market/real/<SYM>/<SYM>_<TF>_365d.parquet); no generated data.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = os.path.join(REPO, "data", "market", "real")
ENTRY_TF = {"SCALP": "M5", "DAY_TRADING": "M15", "SWING": "H1", "H4_SWING": "H4"}


def load_run(d: str) -> Dict[tuple, Dict[str, Any]]:
    out = {}
    for p in glob.glob(os.path.join(d, "*__*.json")):
        r = json.load(open(p, encoding="utf-8"))
        if "error" in r or "trades" not in r:
            continue
        out[(r["symbol"], r["style"])] = r
    return out


def metrics(rs: List[float], days: float) -> Dict[str, Any]:
    n = len(rs)
    if n == 0:
        return {"n": 0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    eq = peak = dd = 0.0
    streak = mstreak = 0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        streak = streak + 1 if r < 0 else 0
        mstreak = max(mstreak, streak)
    mean = sum(rs) / n
    sd = (sum((r - mean) ** 2 for r in rs) / (n - 1)) ** 0.5 if n > 1 else 0.0
    return {
        "n": n, "win_pct": round(100.0 * len(wins) / n, 1), "net_r": round(sum(rs), 2),
        "pf": round(sum(wins) / abs(sum(losses)), 2) if losses else None,
        "exp_r": round(mean, 3),
        "avg_win_r": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss_r": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "max_dd_r": round(dd, 2), "max_consec_losses": mstreak,
        "trades_per_week": round(n / max(days / 7.0, 1e-9), 2),
        "sharpe_trade": round(mean / sd, 3) if sd > 0 else 0.0,
    }


def dsr(rs: List[float], n_trials: int, var_trials: float) -> Optional[float]:
    from jarvis.learning.deflated_sharpe import deflated_sharpe_ratio, sharpe_stats
    if len(rs) < 10:
        return None
    s = sharpe_stats(rs)
    v = deflated_sharpe_ratio(s["sr"], s["n"], s["skew"], s["kurt"], max(n_trials, 2), max(var_trials, 1e-6))
    return None if v != v else round(v, 3)


# ── post-hoc entry filters (True = keep the trade) ────────────────────────────
_CACHE: Dict[tuple, Any] = {}


def _frame(sym: str, tf: str):
    import pandas as pd
    k = (sym, tf)
    if k not in _CACHE:
        p = os.path.join(REAL, sym, f"{sym}_{tf}_365d.parquet")
        if not os.path.exists(p):
            _CACHE[k] = None
        else:
            df = pd.read_parquet(p)
            df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_localize(None)
            _CACHE[k] = df.set_index("time").sort_index()
    return _CACHE[k]


def _closed_before(df, t):
    """Rows of `df` whose bar CLOSED at or before t (bar open + one bar <= t): no look-ahead."""
    if df is None or len(df) < 3:
        return None
    step = df.index[1] - df.index[0]
    return df[df.index + step <= t]


def _d1_trend(sym: str, t) -> int:
    d = _closed_before(_frame(sym, "D1"), t)
    if d is None or len(d) < 50:
        return 0
    c = d["close"]
    up = c.iloc[-1] > c.iloc[-50:].mean() and c.iloc[-1] > c.iloc[-21]
    dn = c.iloc[-1] < c.iloc[-50:].mean() and c.iloc[-1] < c.iloc[-21]
    return 1 if up else (-1 if dn else 0)


def _atr(sym: str, tf: str, t, n: int = 14) -> Optional[float]:
    d = _closed_before(_frame(sym, tf), t)
    if d is None or len(d) < n + 1:
        return None
    d = d.iloc[-(n + 1):]
    pc = d["close"].shift(1)
    tr = (d["high"] - d["low"]).combine((d["high"] - pc).abs(), max).combine((d["low"] - pc).abs(), max)
    return float(tr.iloc[1:].mean())


def _usd_weak(t) -> int:
    d = _closed_before(_frame("EURUSD", "D1"), t)
    if d is None or len(d) < 20:
        return 0
    c = d["close"]
    return 1 if c.iloc[-1] > c.iloc[-20:].mean() else -1


def _side(tr) -> int:
    return 1 if str(tr.get("type", "BUY")).upper() == "BUY" else -1


def _t(tr):
    import pandas as pd
    return pd.Timestamp(tr["open_time"])


def _stop(tr) -> float:
    return abs(float(tr["entry"]) - float(tr.get("initial_sl") or tr["sl"]))


def _ny_open_ok(sym: str, st: str, tr) -> bool:
    if st not in ("SCALP", "DAY_TRADING") or not (13 <= _t(tr).hour < 16):
        return True
    a = _atr(sym, "H1", _t(tr))
    return a is not None and _stop(tr) >= a


def _stop_k(k: float) -> Callable[[str, str, Dict[str, Any]], bool]:
    def f(sym, st, tr):
        a = _atr(sym, ENTRY_TF.get(st, "H1"), _t(tr))
        return a is None or _stop(tr) >= k * a
    return f


FILTERS: Dict[str, Callable[[str, str, Dict[str, Any]], bool]] = {
    # G6: trade only with the D1 trend (close vs SMA50 and the 20-day return agree)
    "d1_trend": lambda sym, st, tr: _d1_trend(sym, _t(tr)) == _side(tr),
    # G10: no SCALP/DAY entries 13:00-16:00 UTC unless the stop is >= 1x H1 ATR
    "ny_open": _ny_open_ok,
    # G7 (skip variant): the stop must be >= k x ATR(entry TF)
    "stop_1atr": _stop_k(1.0),
    "stop_1_5atr": _stop_k(1.5),
    # G11: metals BUY only when USD is weak (EURUSD > SMA20 D1), SELL only when strong
    "usd_regime": lambda sym, st, tr: sym not in ("XAUUSD", "XAGUSD") or _usd_weak(_t(tr)) == _side(tr),
}


def evaluate(run: Dict[tuple, Dict[str, Any]], filt: Optional[str] = None) -> Dict[tuple, Dict[str, Any]]:
    out = {}
    for (sym, st), r in sorted(run.items()):
        trades = r.get("trades", [])
        if filt:
            f = FILTERS[filt]
            trades = [tr for tr in trades if f(sym, st, tr)]
        rs = [float(tr.get("pnl_r", 0.0) or 0.0) for tr in trades]
        out[(sym, st)] = metrics(rs, float(r.get("window_days") or 1.0))
        out[(sym, st)]["_rs"] = rs
    return out


def add_dsr(ev: Dict[tuple, Dict[str, Any]], n_trials: int) -> None:
    srs = [m["sharpe_trade"] for m in ev.values() if m.get("n", 0) >= 10]
    var = (sum((s - sum(srs) / len(srs)) ** 2 for s in srs) / (len(srs) - 1)) if len(srs) > 1 else 0.0
    for m in ev.values():
        m["dsr"] = dsr(m.get("_rs", []), n_trials, var) if m.get("n", 0) >= 10 else None


def fmt(ev, base=None) -> str:
    rows = ["| Symbol | Style | n | Win% | Net R | PF | Exp R | AvgW | AvgL | MaxDD R | MaxCL | /wk | DSR |"
            + (" Base exp R | Base n |" if base else ""),
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|" + ("---:|---:|" if base else "")]
    for k, m in ev.items():
        if not m.get("n"):
            continue
        b = (base or {}).get(k, {})
        rows.append(f"| {k[0]} | {k[1]} | {m['n']} | {m['win_pct']} | {m['net_r']:+.1f} | {m['pf']} | {m['exp_r']:+.3f} | "
                    f"{m['avg_win_r']:+.2f} | {m['avg_loss_r']:+.2f} | {m['max_dd_r']} | {m['max_consec_losses']} | "
                    f"{m['trades_per_week']} | {m.get('dsr')} |"
                    + (f" {b.get('exp_r', float('nan')):+.3f} | {b.get('n', 0)} |" if base else ""))
    return "\n".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--base", default="")
    ap.add_argument("--filters", action="store_true", help="screen every post-hoc entry filter")
    ap.add_argument("--trials", type=int, default=0, help="true number of trials for DSR (default: cells x variants)")
    ap.add_argument("--json", default="")
    ap.add_argument("--write-mode-report", default="",
                    help="write holdout evidence in ModeReliabilityModel's schema (reports/mode_backtest_report.json); "
                         "the deployment gate and the AUTO prior read it")
    ap.add_argument("--holdout-window", default="", help="e.g. 2026-05-24..2026-11-26 (required with --write-mode-report)")
    ap.add_argument("--exit-mode", default="", help="exit policy the run replayed (recorded in the report)")
    a = ap.parse_args()
    run = load_run(a.run)
    base = evaluate(load_run(a.base)) if a.base else None
    ev = evaluate(run)
    n_trials = a.trials or max(len(ev) * (1 + (len(FILTERS) if a.filters else 0)), 2)
    add_dsr(ev, n_trials)
    print(f"## {a.run}  (DSR over {n_trials} trials)\n")
    print(fmt(ev, base))
    res = {"run": a.run, "n_trials": n_trials,
           "cells": {f"{k[0]}|{k[1]}": {x: y for x, y in m.items() if x != "_rs"} for k, m in ev.items()}}
    if a.filters:
        res["filters"] = {}
        for name in FILTERS:
            fe = evaluate(run, name)
            add_dsr(fe, n_trials)
            res["filters"][name] = {f"{k[0]}|{k[1]}": {x: y for x, y in m.items() if x != "_rs"} for k, m in fe.items()}
            print(f"\n### filter {name}\n")
            print(fmt(fe, ev))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2, default=str)
    if a.write_mode_report:
        if not a.holdout_window:
            raise SystemExit("--holdout-window is required: the gate only trusts a report that says it is a holdout")
        write_mode_report(ev, a.write_mode_report, a.holdout_window, a.exit_mode, a.run, n_trials)
    return 0


def write_mode_report(ev, path: str, window: str, exit_mode: str, run: str, n_trials: int) -> None:
    """Holdout evidence per style with per-symbol rows (schema of reports/mode_backtest_report.json)."""
    import datetime
    modes = {}
    for (sym, st), m in ev.items():
        if not m.get("n"):
            continue
        modes.setdefault(st, []).append({"symbol": sym, "trades": m["n"], "expectancy_r": m["exp_r"],
                                         "profit_factor": m["pf"] or 0.0, "win_rate_pct": m["win_pct"],
                                         "max_dd_r": m["max_dd_r"], "dsr": m.get("dsr")})
    out = {"generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "source": run, "holdout_window": window, "exit_mode": exit_mode or "default",
           "n_trials": n_trials, "data": "MT5 real bars, data/market/real/*_365d.parquet", "modes": []}
    for st, rows in sorted(modes.items()):
        rs = [r for (s2, t2), m in ev.items() if t2 == st for r in m.get("_rs", [])]
        pm = metrics(rs, 1.0) if rs else {"n": 0}
        out["modes"].append({"style": st, "pooled": {"trades": pm.get("n", 0), "expectancy_r": pm.get("exp_r", 0.0),
                                                     "profit_factor": pm.get("pf") or 0.0,
                                                     "win_rate_pct": pm.get("win_pct", 0.0)},
                             "per_symbol": sorted(rows, key=lambda r: r["symbol"])})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, default=str)


if __name__ == "__main__":
    raise SystemExit(main())
