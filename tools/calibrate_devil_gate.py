"""
Calibrate the Devil's Advocate gate on real history (walk-forward, out-of-sample).

The "Devil Adversarial Guard" passes when ``penalty_score <= max_devil_penalty (+10 if
ai_score >= 75)`` and ``len(threats) <= 3``. The per-threat penalty weights were hand-picked and
never validated. This tool measures them.

Pipeline
--------
1. ``--scan``: run the production pipeline (SignalScanner) over the cached real MT5 H1 bars and
   record, per candidate, the Devil's Advocate threat flags. Written to ``data/signals/devil/`` so
   the shared candidate caches other calibrations read are not touched.
2. Outcome: every candidate is replayed under its symbol's deployed exit geometry
   (``config/winrate_profiles.json``) with the same simulator, costs and stop slippage the win-rate
   calibration uses -> realised R.
3. Per group (forex, gold, crypto) and pooled: per-flag conditional stats, then an expanding-window
   walk-forward (time-ordered folds, embargoed) logistic model P(loss | flags); the loss-probability
   threshold is chosen on the training data only to maximise the expectancy of the trades it lets
   through. The CURRENT gate is scored on the very same test folds.
4. ``config/devil_gate_calibration.json`` is written with ``published: true`` for a group only if
   the calibrated gate beats the current gate OOS on expectancy with comparable or larger n.

Usage::

    python tools/calibrate_devil_gate.py --scan --workers 8     # ~15-25 min
    python tools/calibrate_devil_gate.py                        # calibrate from the scan
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jarvis.analysts.devil_calibration import FLAG_IDS, group_for  # noqa: E402
from jarvis.config.paths import DATA_DIR  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

REAL_DIR = Path(DATA_DIR) / "market" / "real"
SCAN_DIR = Path(DATA_DIR) / "signals" / "devil"
OUT_PATH = REPO_ROOT / "config" / "devil_gate_calibration.json"
DAYS = 730
SLIPPAGE_PIPS = 0.5          # same stop slippage as tools/calibrate_winrate.py / BacktestEngine
GATE_NAME = "Devil Adversarial Guard"
FOLDS = 5
EMBARGO_BARS = 48            # max_bars of the deployed geometries: no train trade overlaps a test trade
MIN_TEST_N = 30
L2 = 1.0


# ─────────────────────────────────────────────────────────────── 1. scan
def scan_symbol(symbol: str) -> Dict[str, Any]:
    from jarvis.backtesting.signal_scan import SignalScanner
    path = REAL_DIR / symbol / f"{symbol}_H1_{DAYS}d.parquet"
    if not path.exists():
        return {"symbol": symbol, "ok": False, "error": f"missing {path}"}
    df = pd.read_parquet(path).reset_index(drop=True)
    t0 = time.time()
    res = SignalScanner(start_bar_idx=60).scan(df, symbol)
    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    res.candidates.to_parquet(SCAN_DIR / f"{symbol}_H1_{DAYS}d_candidates.parquet", index=False)
    return {**res.summary(), "ok": True, "seconds": round(time.time() - t0, 1)}


def run_scan(symbols: Sequence[str], workers: int) -> None:
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(scan_symbol, s): s for s in symbols}
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception as exc:  # pragma: no cover
                r = {"symbol": futs[f], "ok": False, "error": str(exc)}
            print(f"  {r['symbol']:8s} {'ok' if r.get('ok') else 'FAILED ' + str(r.get('error'))} "
                  f"candidates={r.get('candidates')} [{r.get('seconds')}s]", flush=True)
    print(f"scan done in {time.time() - t0:.0f}s", flush=True)


# ─────────────────────────────────────────────────────────────── 2. outcomes
def outcomes_for(symbol: str) -> pd.DataFrame:
    """Candidates whose traded side is the side the critic judged, with realised R."""
    from jarvis.backtesting.trade_simulator import Geometry, simulate_all_candidates_with_rows
    from jarvis.data.symbol_registry import resolve as resolve_symbol
    from jarvis.intelligence.winrate_targeting import WRTargetCalibrator, get_dollar_risk_per_price_unit, load_profiles

    cands = pd.read_parquet(SCAN_DIR / f"{symbol}_H1_{DAYS}d_candidates.parquet")
    cands = cands[cands["side"] == cands["devil_side"]].sort_values("bar_idx").reset_index(drop=True)
    df = pd.read_parquet(REAL_DIR / symbol / f"{symbol}_H1_{DAYS}d.parquet").reset_index(drop=True)
    prof = load_profiles().get(symbol)
    geom = prof.geometry if prof is not None else Geometry(tp_r=1.5, max_bars=48)
    geom = Geometry(**{**geom.to_dict(), "min_score": 0.0})  # the devil gate is studied on every candidate
    spec = resolve_symbol(symbol)
    mpu = get_dollar_risk_per_price_unit(symbol)
    cost = WRTargetCalibrator()._cost_price_equiv(symbol, mpu)
    slip = SLIPPAGE_PIPS * float(getattr(spec, "pip_size", 0.0001) or 0.0001)
    pairs = simulate_all_candidates_with_rows(df=df, candidates=cands, geom=geom, money_per_unit=mpu,
                                              cost_price_equiv=cost, slippage_price_equiv=slip,
                                              spec=spec, symbol=symbol)
    idx = [i for i, _ in pairs]
    out = cands.loc[idx, ["symbol", "bar_idx", "time", "side", "devil_flags", "devil_n_threats",
                          "adversarial_penalty", "failing_gates"]].copy()
    out["r"] = [o.pnl_r for _, o in pairs]
    out["exit_idx"] = [o.exit_idx for _, o in pairs]
    out["win"] = out["r"] > 0
    out["current_pass"] = ~out["failing_gates"].fillna("").str.split("|").apply(lambda g: GATE_NAME in g)
    out["group"] = group_for(symbol)
    out["geometry"] = geom.key()
    return out.reset_index(drop=True)


def flag_matrix(frame: pd.DataFrame) -> np.ndarray:
    sets = frame["devil_flags"].fillna("").str.split("|").apply(set)
    return np.array([[f in s for f in FLAG_IDS] for s in sets], dtype=float).reshape(len(frame), len(FLAG_IDS))


# ─────────────────────────────────────────────────────────────── 3. statistics
def flag_stats(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    """Per flag: n with/without, win rate and mean R with vs without, Welch t on R."""
    X = flag_matrix(frame)
    r, w = frame["r"].to_numpy(float), frame["win"].to_numpy(float)
    out = []
    for j, f in enumerate(FLAG_IDS):
        on = X[:, j] > 0
        n1, n0 = int(on.sum()), int((~on).sum())
        if n1 < 2 or n0 < 2:
            out.append({"flag": f, "n": n1, "n_without": n0})
            continue
        r1, r0 = r[on], r[~on]
        se = math.sqrt(r1.var(ddof=1) / n1 + r0.var(ddof=1) / n0)
        out.append({
            "flag": f, "n": n1, "n_without": n0,
            "win_rate": round(float(w[on].mean()), 4), "win_rate_without": round(float(w[~on].mean()), 4),
            "win_rate_delta": round(float(w[on].mean() - w[~on].mean()), 4),
            "mean_r": round(float(r1.mean()), 4), "mean_r_without": round(float(r0.mean()), 4),
            "mean_r_delta": round(float(r1.mean() - r0.mean()), 4),
            "t_stat": round(float((r1.mean() - r0.mean()) / se), 2) if se > 0 else None,
        })
    return out


def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = L2, iters: int = 50) -> np.ndarray:
    """L2-regularised logistic regression by Newton-Raphson. Returns [intercept, w...]."""
    A = np.hstack([np.ones((len(X), 1)), X])
    beta = np.zeros(A.shape[1])
    reg = np.full(A.shape[1], l2)
    reg[0] = 0.0  # never shrink the intercept
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-np.clip(A @ beta, -30, 30)))
        g = A.T @ (p - y) + reg * beta
        H = (A * (p * (1 - p))[:, None]).T @ A + np.diag(reg) + 1e-9 * np.eye(A.shape[1])
        step = np.linalg.solve(H, g)
        beta -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta


def predict(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(beta[0] + X @ beta[1:], -30, 30)))


def summary(r: np.ndarray) -> Dict[str, Any]:
    r = np.asarray(r, float)
    if len(r) == 0:
        return {"n": 0, "win_rate": None, "expectancy_r": None, "profit_factor": None, "total_r": 0.0}
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    return {"n": int(len(r)), "win_rate": round(float((r > 0).mean()), 4), "expectancy_r": round(float(r.mean()), 4),
            "profit_factor": round(float(gains / losses), 3) if losses > 0 else None, "total_r": round(float(r.sum()), 2)}


def choose_threshold(p: np.ndarray, r: np.ndarray, min_keep: float = 0.2) -> float:
    """Loss-probability cut maximising mean R of the trades kept (training data only)."""
    best_t, best_e = 1.0, -np.inf
    for t in np.unique(np.quantile(p, np.linspace(0.2, 1.0, 33), method="lower")):  # actual p values
        keep = p <= t
        if keep.mean() < min_keep:
            continue
        e = r[keep].mean()
        if e > best_e:
            best_t, best_e = float(t), e
    return best_t


def walk_forward(frame: pd.DataFrame, folds: int = FOLDS, embargo: int = EMBARGO_BARS) -> Dict[str, Any]:
    """Expanding-window, time-ordered walk-forward. Test fold k trains on everything before it,
    minus an embargo of ``embargo`` bars (and any trade still open when the test fold starts)."""
    f = frame.sort_values("time").reset_index(drop=True)
    X, y, r = flag_matrix(f), (~f["win"]).to_numpy(float), f["r"].to_numpy(float)
    bounds = np.linspace(0, len(f), folds + 2).astype(int)  # first chunk is train-only
    cal_r, cur_r, per_fold = [], [], []
    for k in range(1, folds + 1):
        lo, hi = bounds[k], bounds[k + 1]
        test_start_t = f["time"].iloc[lo]
        tr = np.zeros(len(f), bool)
        tr[:lo] = True
        # embargo: drop training trades that end within `embargo` bars of the test start
        same_sym = f["symbol"].to_numpy()
        first_test_bar = f.iloc[lo:hi].groupby("symbol")["bar_idx"].min().to_dict()
        for i in range(lo):
            fb = first_test_bar.get(same_sym[i])
            if fb is not None and f["exit_idx"].iat[i] >= fb - embargo:
                tr[i] = False
        if tr.sum() < 50:
            continue
        beta = fit_logistic(X[tr], y[tr])
        # keep at least the share the current gate passes on the SAME training data -> like-for-like n
        thr = choose_threshold(predict(beta, X[tr]), r[tr], min_keep=max(0.2, float(f["current_pass"].to_numpy()[tr].mean())))
        te = slice(lo, hi)
        keep = predict(beta, X[te]) <= thr
        cur = f["current_pass"].to_numpy()[te]
        cal_r.append(r[te][keep])
        cur_r.append(r[te][cur])
        per_fold.append({"fold": k, "test_from": str(test_start_t), "test_to": str(f["time"].iloc[hi - 1]),
                         "threshold": round(thr, 4), "all": summary(r[te]),
                         "calibrated": summary(r[te][keep]), "current": summary(r[te][cur])})
    cal = np.concatenate(cal_r) if cal_r else np.array([])
    cur = np.concatenate(cur_r) if cur_r else np.array([])
    return {"folds": per_fold, "calibrated": summary(cal), "current": summary(cur),
            "all_test": summary(np.concatenate([r[bounds[k]:bounds[k + 1]] for k in range(1, folds + 1)]))}


def beats(wf: Dict[str, Any], n_ratio: float = 0.8) -> Tuple[bool, str]:
    c, k = wf["calibrated"], wf["current"]
    if c["n"] < MIN_TEST_N or c["expectancy_r"] is None:
        return False, f"too few OOS trades ({c['n']})"
    if k["expectancy_r"] is not None and c["expectancy_r"] <= k["expectancy_r"]:
        return False, f"OOS expectancy {c['expectancy_r']:+.4f}R does not beat current {k['expectancy_r']:+.4f}R"
    if c["n"] < n_ratio * k["n"]:
        return False, f"OOS n {c['n']} < {n_ratio:.0%} of current {k['n']}"
    if c["expectancy_r"] <= 0:
        return False, f"OOS expectancy {c['expectancy_r']:+.4f}R is not positive"
    folds = wf.get("folds") or []
    won = sum(1 for x in folds if (x["calibrated"]["expectancy_r"] or -9) > (x["current"]["expectancy_r"] or -9))
    if folds and won * 2 <= len(folds):  # a pooled edge carried by one fold is noise
        return False, f"beats current in only {won}/{len(folds)} test folds"
    return True, "beats current gate OOS"


def calibrate(frames: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    allf = pd.concat(frames.values(), ignore_index=True)
    groups: Dict[str, Any] = {}
    for g, sub in [*sorted(allf.groupby("group")), ("pooled", allf)]:
        wf = walk_forward(sub)
        ok, why = beats(wf)
        final = fit_logistic(flag_matrix(sub), (~sub["win"]).to_numpy(float))  # deployable fit on all data
        thr = choose_threshold(predict(final, flag_matrix(sub)), sub["r"].to_numpy(float),
                               min_keep=max(0.2, float(sub["current_pass"].mean())))
        groups[g] = {
            "symbols": sorted(sub["symbol"].unique().tolist()), "n": int(len(sub)),
            "from": str(sub["time"].min()), "to": str(sub["time"].max()),
            "base": summary(sub["r"].to_numpy(float)), "flag_stats": flag_stats(sub),
            "walk_forward": wf, "published": bool(ok and g != "pooled"), "decision": why,
            "intercept": round(float(final[0]), 6),
            "weights": {f: round(float(w), 6) for f, w in zip(FLAG_IDS, final[1:])},
            "threshold": round(thr, 6),
        }
    return {
        "generated_utc": pd.Timestamp.now("UTC").isoformat(),
        "method": (f"expanding walk-forward, {FOLDS} test folds, {EMBARGO_BARS}-bar embargo; L2 logistic "
                   "P(loss|flags); threshold maximises train-fold expectancy; outcome = deployed exit geometry"),
        "days": DAYS, "flags": list(FLAG_IDS),
        "published": any(v["published"] for v in groups.values()),
        "groups": groups,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scan", action="store_true", help="(re)run the devil-flag scan first")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()
    symbols = ([s.strip().upper() for s in args.symbols.split(",")] if args.symbols
               else sorted(d.name for d in REAL_DIR.iterdir() if (d / f"{d.name}_H1_{DAYS}d.parquet").exists()))
    if args.scan:
        run_scan(symbols, args.workers)
    frames = {}
    for s in symbols:
        if (SCAN_DIR / f"{s}_H1_{DAYS}d_candidates.parquet").exists():
            frames[s] = outcomes_for(s)
            print(f"  {s:8s} n={len(frames[s])} {frames[s]['geometry'].iat[0]}", flush=True)
    if not frames:
        print("no devil scan found; run with --scan")
        return 2
    doc = calibrate(frames)
    Path(args.out).write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    for g, v in doc["groups"].items():
        wf = v["walk_forward"]
        print(f"{g:7s} n={v['n']:6d} current OOS {wf['current']}  calibrated OOS {wf['calibrated']}  "
              f"-> {'PUBLISHED' if v['published'] else 'not published'}: {v['decision']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
