"""
Engine-in-the-loop per-symbol selection with a blind 6-month holdout.

WHY: the calibrator ranks configurations with its own simulator, and its OOS
numbers did not survive the production BacktestEngine (2026-11-24 audit:
XAUUSD calibrator OOS +0.204R -> engine holdout -0.106R). Here every candidate
is scored by the ENGINE itself, on a training window only, and the single
winner per symbol is then traded once on the untouched holdout.

    train   = [train_start, train_end)   candidates ranked here (engine)
    holdout = [holdout_start, last bar]  selected candidate traded once, blind

Candidates per symbol: the train-only calibrated profile as-is, plus exit
geometry variants of it (regime geometry cleared so the variant applies).
Ranking: t-stat of train R (mean/sd*sqrt(n)) among candidates with >= 30
trades, PF > 1.05 and mean R > 0. No passing candidate -> "no edge", not traded.

The written profile's oos_* AND holdout_* fields are the holdout engine result
(the only out-of-sample evidence), so the existing EXPECTANCY_GATE and
HOLDOUT_GATE judge deployment unchanged. --promote copies only symbols whose
holdout passes into the live store (backup first) and stamps the rest.

Usage:
    python tools/engine_select.py --profiles data/signals/holdout/winrate_profiles_train_to_2026-05-21.json \
        --train-start 2025-05-21 --train-end 2026-05-21 --holdout-start 2026-05-24
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "tools" / "backtests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import run_3month_backtest as rb  # noqa: E402  (reuse R, spread, DD helpers)
from jarvis.backtesting.exit_geometry import HOLDOUT_MIN_TRADES  # noqa: E402
from jarvis.intelligence.winrate_targeting import WRProfileStore  # noqa: E402
from jarvis.learning.deflated_sharpe import deflated_sharpe_ratio, sharpe_stats  # noqa: E402

MIN_TRAIN_TRADES = 30
MIN_TRAIN_PF = 1.05
# Exit-geometry variants: (tp_r, be_trigger_r, max_bars). Kept small on purpose:
# every extra candidate is another trial the selection must be deflated for.
# BE variants only above 1.65R: below it ExitPolicy.profit_locks already locks BE at 50% of TP.
VARIANTS = [(tp, None, mb) for tp in (1.0, 1.5, 2.0, 2.5) for mb in (24, 48)] + [(2.0, 1.0, 48), (2.5, 1.0, 48)]


def candidates(profile) -> list[tuple[str, object]]:
    out = [("calibrated", profile)]
    for tp, be, mb in VARIANTS:
        g = dataclasses.replace(profile.geometry, tp_r=tp, be_trigger_r=be, max_bars=mb)
        out.append((f"tp{tp}_be{be}_mb{mb}", dataclasses.replace(profile, geometry=g, regime_geometry={})))
    return out


def run_engine(sym: str, days: int, profile, start: str, end: str | None) -> dict:
    """One engine run on bars [start, end); bars before start are warmup only."""
    from jarvis.backtesting.engine import BacktestEngine
    from jarvis.config.runtime import offline_mode

    df = pd.read_parquet(rb.REAL_DIR / sym / f"{sym}_H1_{days}d.parquet").reset_index(drop=True)
    times = pd.to_datetime(df["time"], utc=True)
    if end:
        df = df[times < pd.Timestamp(end, tz="UTC")].reset_index(drop=True)
        times = pd.to_datetime(df["time"], utc=True)
    start_idx = max(60, int((times < pd.Timestamp(start, tz="UTC")).sum()))
    with offline_mode():
        res = BacktestEngine(initial_balance=rb.INITIAL_BALANCE, risk_per_trade_pct=rb.RISK_PER_TRADE_PCT) \
            .run_backtest(df_h1=df, symbol=sym, spread_pips=rb.median_spread_pips(df, sym),
                          wr_profile=profile, start_bar_idx=start_idx)
    rs = [rb.r_multiple(t) for t in res.get("trades", [])]
    m = res.get("metrics", {})
    sd = float(np.std(rs, ddof=1)) if len(rs) > 1 else 0.0
    return {
        "trades": len(rs),
        "win_rate": m.get("win_rate_pct", 0.0),
        "expectancy_r": float(np.mean(rs)) if rs else 0.0,
        "t_stat": float(np.mean(rs) / sd * np.sqrt(len(rs))) if sd > 0 else 0.0,
        "profit_factor": float(m.get("profit_factor", 0.0) or 0.0),
        "max_drawdown_r": rb.max_drawdown_r(rs) if rs else 0.0,
        "max_drawdown_pct": m.get("max_drawdown_pct", 0.0),
        "net_profit": m.get("net_profit", 0.0),
        "rs": rs,
        "window": f"{df['time'].iloc[min(start_idx, len(df) - 1)]} -> {df['time'].iloc[-1]}",
    }


def _train_job(a):
    sym, name, prof, days, start, end = a
    # Research copy: clear the calibrator's own OOS so entry_policy evaluates it instead of
    # refusing it; the engine train run is the evidence being gathered here.
    prof = dataclasses.replace(prof, oos_trades=0)
    return sym, name, run_engine(sym, days, prof, start, end)


def _holdout_job(a):
    sym, name, prof, days, start = a
    return sym, name, run_engine(sym, days, dataclasses.replace(prof, oos_trades=0), start, None)


def pick(results: dict[str, dict]) -> str | None:
    ok = {n: r for n, r in results.items()
          if r["trades"] >= MIN_TRAIN_TRADES and r["profit_factor"] > MIN_TRAIN_PF and r["expectancy_r"] > 0}
    return max(ok, key=lambda n: ok[n]["t_stat"]) if ok else None


def passes_holdout(h: dict) -> bool:
    return h["trades"] >= HOLDOUT_MIN_TRADES and h["expectancy_r"] > 0 and h["profit_factor"] > 1.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profiles", required=True, help="TRAIN-ONLY profile store (calibrate_winrate.py --train-end)")
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--train-start", required=True)
    ap.add_argument("--train-end", required=True)
    ap.add_argument("--holdout-start", required=True, help="after train-end plus a purge gap")
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=None, help="report stem under reports/")
    ap.add_argument("--promote", default=None,
                    help="live store (config/winrate_profiles.json): copy holdout-passing symbols in, stamp the rest")
    ap.add_argument("--exit-mode", default="", choices=["", "legacy", "institutional_lock", "hold", "chandelier"],
                    help="replay this exit policy offline (default: calibrated/legacy); sets JARVIS_BACKTEST_EXIT_MODE")
    args = ap.parse_args()
    if args.exit_mode:
        import os as _os
        _os.environ["JARVIS_BACKTEST_EXIT_MODE"] = args.exit_mode
    if pd.Timestamp(args.holdout_start) <= pd.Timestamp(args.train_end):
        ap.error("--holdout-start must be after --train-end")

    base = WRProfileStore(Path(args.profiles)).load()
    syms = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else sorted(base)
    syms = [s for s in syms if s in base and (rb.REAL_DIR / s / f"{s}_H1_{args.days}d.parquet").exists()]
    cands = {s: dict(candidates(base[s])) for s in syms}
    t0 = time.time()

    train: dict[str, dict[str, dict]] = {s: {} for s in syms}
    jobs = [(s, n, p, args.days, args.train_start, args.train_end) for s in syms for n, p in cands[s].items()]
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for s, n, r in ex.map(_train_job, jobs):
            train[s][n] = r
            print(f"  train {s:8s} {n:22s} n={r['trades']:4d} exp={r['expectancy_r']:+.3f}R "
                  f"PF={r['profit_factor']:4.2f} t={r['t_stat']:+.2f}", flush=True)

    chosen = {s: pick(train[s]) for s in syms}
    hjobs = [(s, chosen[s], cands[s][chosen[s]], args.days, args.holdout_start) for s in syms if chosen[s]]
    holdout: dict[str, dict] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for s, n, r in ex.map(_holdout_job, hjobs):
            holdout[s] = r

    # Holdout: one configuration per symbol was fixed before the window -> n_trials = symbols tested.
    n_trials = max(1, len(holdout))
    rows, selected = [], {}
    for s in syms:
        n, h = chosen[s], holdout.get(s)
        row = {"symbol": s, "candidates": len(cands[s]), "selected": n,
               "train": {k: (round(v, 4) if isinstance(v, float) else v)
                         for k, v in (train[s][n] if n else {}).items() if k != "rs"}}
        if h:
            st = sharpe_stats(h["rs"])
            row["dsr"] = (round(float(deflated_sharpe_ratio(st["sr"], st["n"], st["skew"], st["kurt"],
                                                            var_of_trial_sharpes=1.0 / st["n"], n_trials=n_trials)), 4)
                          if st["n"] >= 3 else None)
            row["holdout"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in h.items() if k != "rs"}
            row["passes"] = passes_holdout(h)
            p = dataclasses.replace(
                cands[s][n],
                oos_trades=h["trades"], oos_win_rate=h["win_rate"] / 100.0,
                oos_expectancy_r=h["expectancy_r"], oos_profit_factor=h["profit_factor"],
                oos_total_r=float(sum(h["rs"])),
                holdout_window=h["window"], holdout_trades=h["trades"],
                holdout_expectancy_r=h["expectancy_r"], holdout_profit_factor=h["profit_factor"],
                notes=f"engine_select {n}; train {args.train_start}->{args.train_end}; holdout {h['window']}",
            )
            selected[s] = p
        else:
            row["passes"] = False
        rows.append(row)

    out = args.out or f"engine_select_{pd.Timestamp.now(tz='UTC'):%Y-%m-%d}"
    meta = {"train": [args.train_start, args.train_end], "holdout_start": args.holdout_start,
            "base_profiles": args.profiles, "variants": len(VARIANTS) + 1, "n_trials_holdout": n_trials,
            "min_train_trades": MIN_TRAIN_TRADES, "min_train_pf": MIN_TRAIN_PF,
            "data": "MT5 terminal real H1 bars", "elapsed_seconds": round(time.time() - t0, 1)}
    sel_path = REPO_ROOT / "data" / "signals" / "holdout" / f"{out}_profiles.json"
    WRProfileStore(sel_path).save(selected, meta=meta)
    (rb.REPORT_DIR / f"{out}.json").write_text(json.dumps({"meta": meta, "symbols": rows}, indent=2, default=str),
                                               encoding="utf-8")
    print(f"\n{'sym':8s} {'selected':22s} {'train exp':>9s} {'hold n':>6s} {'hold exp':>9s} {'PF':>5s} {'DSR':>6s} pass")
    for r in rows:
        h = r.get("holdout", {})
        print(f"{r['symbol']:8s} {str(r['selected']):22s} {r['train'].get('expectancy_r', 0):+9.3f} "
              f"{h.get('trades', 0):6d} {h.get('expectancy_r', 0):+9.3f} {h.get('profit_factor', 0):5.2f} "
              f"{str(r.get('dsr')):>6s} {r['passes']}")
    print(f"profiles -> {sel_path}\nreport   -> reports/{out}.json")

    if args.promote:
        live = Path(args.promote)
        shutil.copy2(live, sel_path.with_name(f"{live.stem}.before_{out}.json"))
        raw = json.loads(live.read_text(encoding="utf-8"))
        store = WRProfileStore(live)
        profs = store.load()
        for r in rows:
            s = r["symbol"]
            if r["passes"]:
                profs[s] = selected[s]
            elif s in profs and r.get("holdout"):
                h = r["holdout"]  # keep it refused on the newest blind evidence
                profs[s] = dataclasses.replace(profs[s], holdout_window=h["window"], holdout_trades=h["trades"],
                                               holdout_expectancy_r=h["expectancy_r"],
                                               holdout_profit_factor=h["profit_factor"])
        store.save(profs, meta=raw.get("meta"))
        print(f"promoted: {[r['symbol'] for r in rows if r['passes']] or 'none'} (backup next to {sel_path.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
