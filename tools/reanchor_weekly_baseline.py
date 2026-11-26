"""Operator tool: re-anchor ONLY the weekly-loss baseline to current MT5 equity.

The dashboard's "resume trading" resets the daily baseline but not the weekly one,
so a weekly-loss halt can only be lifted early by an operator. Peak equity (the
max-drawdown memory) and the daily baseline are left untouched.

The engine keeps its baselines in memory and overwrites the file, so this refuses
to run while the engine's API port is listening. Stop the engine first.

    python tools/reanchor_weekly_baseline.py --mode demo            # preview
    python tools/reanchor_weekly_baseline.py --mode demo --apply    # write
"""
from __future__ import annotations

import argparse
import os
import socket
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.config.paths import mode_scoped_db_path, resolve_db_path  # noqa: E402

AUDIT_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "drawdown_audit.log")


def _engine_running(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="demo", choices=["live", "demo", "paper"])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--port", type=int, default=int(os.environ.get("JARVIS_PORT", "8501")))
    args = ap.parse_args()

    if _engine_running(args.port):
        print(f"Refusing: engine is running (port {args.port}). Stop it first, or it overwrites this.")
        return 2

    import MetaTrader5 as mt5
    if not mt5.initialize():
        print(f"MT5 unavailable: {mt5.last_error()}")
        return 2
    acct = mt5.account_info()
    equity = float(acct.equity)

    db = resolve_db_path(mode_scoped_db_path("jarvis_drawdown_state.db", args.mode))
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT daily_start_equity, peak_equity, weekly_start_equity, week_key "
                           "FROM drawdown_state WHERE id = 1").fetchone()
        if row is None:
            print(f"No drawdown state in {db}")
            return 2
        daily, peak, weekly, week = row
        print(f"{db}\n  account #{acct.login} equity {equity:.2f}\n  daily {daily:.2f}  peak {peak:.2f} "
              f"(drawdown {max(0.0, (peak - equity) / peak * 100):.2f}%)\n  weekly {weekly:.2f} -> {equity:.2f}  ({week})")
        if not args.apply:
            print("Preview only; pass --apply to write.")
            return 0
        conn.execute("UPDATE drawdown_state SET weekly_start_equity = ? WHERE id = 1", (equity,))
        got = conn.execute("SELECT weekly_start_equity FROM drawdown_state WHERE id = 1").fetchone()[0]
    assert abs(got - equity) < 1e-9, "weekly baseline did not persist"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] REANCHOR_WEEKLY: Operator='{os.environ.get('USERNAME', 'operator')}', "
                f"Account=#{acct.login}, Mode={args.mode}, PrevWeekly=${weekly:.2f}, NewWeekly=${equity:.2f}, "
                f"Peak=${peak:.2f} (unchanged), Week={week}\n")
    print("Weekly baseline re-anchored; peak and daily unchanged. Audit line written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
