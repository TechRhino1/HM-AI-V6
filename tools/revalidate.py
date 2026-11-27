"""Weekly revalidation of the deployment evidence (PR D, 2026-11-27): propose -> validate -> promote.

Out of process and off the trading path. On fresh real MT5 bars it replays the LIVE exit policy
(trading.exit_mode / exit_hold_symbols) through the existing engine grid on rolling windows:

    holdout = the 183 days ending --end (default: yesterday, UTC)   -> the evidence the gate reads
    train   = the 157 days ending 3 days before the holdout starts  -> the train-sign rule

The holdout is only measured, never used to choose anything. Each run's cells are stored under
reports/staging/cells/<fingerprint>/ where the fingerprint hashes the code commit (and any local
edits under jarvis/ tools/ config/), the bar files, the settings and profiles, the exit policy and
the windows: a cell is reused only when every input is identical, never because a file exists.

The candidate report goes to jarvis.learning.evidence.promote: cells that stop passing are refused
at once (tightening); cells that would start trading, or a changed exit policy, wait PENDING for
    python tools/promote_model.py approve mode_evidence <version> --reason "..."
and any version can be restored with  promote_model.py rollback mode_evidence <version> --approve "...".

    python tools/revalidate.py [--workers 2] [--no-fetch] [--no-promote] [--symbols A,B] [--styles S,..]

Weekly schedule (Windows Task Scheduler, created only with the operator's OK), e.g. Saturday 02:00:
    schtasks /Create /TN "JARVIS revalidation" /SC WEEKLY /D SAT /ST 02:00
             /TR "\"<python.exe>\" \"<repo>\\tools\\revalidate.py\" --workers 2"
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

SYMBOLS = "XAUUSD,XAGUSD,BTCUSD,ETHUSD,SOLUSD,EURUSD,GBPUSD,USDJPY,USDCHF,USDCAD,AUDUSD,NZDUSD,US30,NAS100,GER40,UK100"
STYLES = "SCALP,DAY_TRADING,SWING,H4_SWING"
NO_TRAIN = {"SCALP"}          # M1 history is too short for a train window before the holdout
HOLDOUT_DAYS, GAP_DAYS, TRAIN_DAYS, CACHE_DAYS = 183, 3, 157, 365
TRIALS_PER_CELL = 6           # DSR trial count per cell, as in the 2026-11-27 audit grid
MAX_DATA_LAG_DAYS = 4         # the bars must reach the holdout end (a weekend of slack)
STAGING = os.path.join(REPO, "reports", "staging")


def windows(end: dt.date) -> Dict[str, dt.date]:
    h0 = end - dt.timedelta(days=HOLDOUT_DAYS)
    t1 = h0 - dt.timedelta(days=GAP_DAYS)
    return {"holdout_start": h0, "holdout_end": end, "train_start": t1 - dt.timedelta(days=TRAIN_DAYS), "train_end": t1}


def _sha_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, timeout=60).stdout
    except Exception:  # noqa: BLE001
        return ""


def fingerprint(symbols: List[str], policy: Dict[str, object], win: Dict[str, dt.date],
                data_dir: Optional[str] = None) -> Dict[str, str]:
    """Every input a cell result depends on, hashed; the cells directory is keyed by `all`."""
    data_dir = data_dir or os.path.join(REPO, "data", "market", "real")
    data = hashlib.sha256()
    for sym in symbols:
        for p in sorted(glob.glob(os.path.join(data_dir, sym, f"{sym}_*_{CACHE_DAYS}d.parquet"))):
            data.update(f"{os.path.basename(p)}:{_sha_file(p)}".encode())
    cfg = hashlib.sha256()
    for name in ("settings.json", "winrate_profiles.json"):
        p = os.path.join(REPO, "config", name)
        cfg.update(f"{name}:{_sha_file(p) if os.path.exists(p) else '-'}".encode())
    local = _git("diff", "HEAD", "--", "jarvis", "tools", "config")
    parts = {"commit": _git("rev-parse", "HEAD").strip() + ("+" + hashlib.sha256(local.encode()).hexdigest()[:8] if local else ""),
             "data": data.hexdigest()[:16], "config": cfg.hexdigest()[:16],
             "policy": json.dumps(policy, sort_keys=True), "windows": json.dumps({k: str(v) for k, v in win.items()}),
             "symbols": ",".join(symbols)}
    parts["all"] = hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:12]
    return parts


def data_gaps(symbols: List[str], end: dt.date, data_dir: Optional[str] = None) -> List[str]:
    """Symbols whose M5 bars stop more than MAX_DATA_LAG_DAYS before the holdout end."""
    import pandas as pd
    data_dir = data_dir or os.path.join(REPO, "data", "market", "real")
    bad = []
    for sym in symbols:
        p = os.path.join(data_dir, sym, f"{sym}_M5_{CACHE_DAYS}d.parquet")
        try:
            last = pd.to_datetime(pd.read_parquet(p, columns=["time"])["time"].iloc[-1], utc=True).date()
        except Exception:  # noqa: BLE001
            bad.append(f"{sym}: no {CACHE_DAYS}d M5 bars")
            continue
        if (end - last).days > MAX_DATA_LAG_DAYS:
            bad.append(f"{sym}: bars end {last}")
    return bad


def _missing(out: str, symbols: List[str], styles: List[str]) -> List[str]:
    return [f"{s}__{st}" for st in styles for s in symbols if not os.path.exists(os.path.join(out, f"{s}__{st}.json"))]


def _run(cmd: List[str], log) -> int:
    log.write(f"\n$ {' '.join(cmd)}\n")
    log.flush()
    return subprocess.run(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT).returncode


def main(argv: Optional[List[str]] = None, run: Callable[[List[str], object], int] = _run,
         today: Optional[dt.date] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--symbols", default=SYMBOLS)
    ap.add_argument("--styles", default=STYLES)
    ap.add_argument("--end", default="", help="holdout end YYYY-MM-DD (default: yesterday, UTC)")
    ap.add_argument("--no-fetch", action="store_true", help="use the cached bars as they are")
    ap.add_argument("--no-promote", action="store_true", help="stop at the candidate report (dry run)")
    a = ap.parse_args(argv)
    from jarvis.config.settings import SETTINGS
    from jarvis.learning import evidence

    symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    styles = [s.strip().upper() for s in a.styles.split(",") if s.strip()]
    end = dt.date.fromisoformat(a.end) if a.end else (today or dt.datetime.now(dt.timezone.utc).date()) - dt.timedelta(days=1)
    win = windows(end)
    mode = str(SETTINGS.trading.exit_mode or "legacy").lower()
    hold = sorted(str(s).upper() for s in (SETTINGS.trading.exit_hold_symbols or []))
    os.makedirs(STAGING, exist_ok=True)
    lock = os.path.join(STAGING, "revalidate.lock")
    try:
        if os.path.exists(lock) and time.time() - os.path.getmtime(lock) > 86400:
            os.remove(lock)  # a run that died a day ago
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        print("another revalidation is running (reports/staging/revalidate.lock)")
        return 3
    stamp = time.strftime("%Y%m%d_%H%M%S")
    summary: Dict[str, object] = {"started": stamp, "windows": {k: str(v) for k, v in win.items()},
                                  "exit_mode": mode, "exit_hold_symbols": hold}
    try:
        with open(os.path.join(STAGING, f"revalidate_{stamp}.log"), "w", encoding="utf-8") as log:
            py = sys.executable
            if not a.no_fetch and run([py, "tools/fetch_real_data.py", "--days", str(CACHE_DAYS),
                                       "--symbols", ",".join(symbols)], log) != 0:
                summary["outcome"] = "FETCH_FAILED: nothing promoted"
                return 2
            gaps = data_gaps(symbols, end)
            if gaps:
                summary["outcome"] = f"DATA_GAPS: nothing promoted ({'; '.join(gaps)})"
                return 2
            fp = fingerprint(symbols, {"exit_mode": mode, "exit_hold_symbols": hold}, win)
            summary["fingerprint"] = fp
            cells = os.path.join(STAGING, "cells", fp["all"])
            stages = [("holdout", styles, win["holdout_start"], win["holdout_end"]),
                      ("train", [s for s in styles if s not in NO_TRAIN], win["train_start"], win["train_end"])]
            for name, sts, start, stop in stages:
                out = os.path.join(cells, name)
                todo = _missing(out, symbols, sts)
                if not todo or not sts:
                    continue
                cmd = [py, "tools/backtests/run_mode_backtest.py", "--workers", str(a.workers), "--days", str(CACHE_DAYS),
                       "--symbols", ",".join(sorted({t.split("__")[0] for t in todo})), "--styles", ",".join(sts),
                       "--start", str(start), "--end", str(stop), "--out", out]
                if mode != "legacy":
                    cmd += ["--exit-mode", mode]
                run(cmd, log)
                still = _missing(out, symbols, sts)
                if still:
                    summary["outcome"] = f"GRID_INCOMPLETE ({name}): nothing promoted; missing {still}"
                    return 2
            cand = os.path.join(STAGING, "mode_backtest_report.candidate.json")
            if run([py, "tools/loss_audit_eval.py", os.path.join(cells, "holdout"),
                    "--train-run", os.path.join(cells, "train"), "--write-mode-report", cand,
                    "--holdout-window", f"{win['holdout_start']}..{win['holdout_end']}",
                    "--exit-mode", mode if mode != "legacy" else "", "--exit-hold-symbols", ",".join(hold),
                    "--trials", str(TRIALS_PER_CELL * len(symbols) * len(styles)),
                    "--json", os.path.join(STAGING, f"eval_{stamp}.json")], log) != 0:
                summary["outcome"] = "EVAL_FAILED: nothing promoted"
                return 2
            if a.no_promote:
                summary["outcome"] = f"DRY_RUN: candidate at {cand}"
                summary["plan"] = evidence.plan(evidence.load(evidence.active_file()), evidence.load(cand))[1]
                return 0
            res = evidence.promote(cand, reason=f"weekly revalidation {win['holdout_start']}..{win['holdout_end']} "
                                                f"fp={fp['all']}")
            summary["promotion"] = res
            summary["outcome"] = (res.get("result") or {}).get("status")
            return 0
    finally:
        summary["finished"] = time.strftime("%Y%m%d_%H%M%S")
        with open(os.path.join(STAGING, f"revalidation_{stamp}.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)
        print(json.dumps({k: summary.get(k) for k in ("outcome", "windows")}, default=str))
        try:
            os.remove(lock)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
