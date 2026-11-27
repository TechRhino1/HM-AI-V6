"""Daily housekeeping run by the orchestrator watchdog in a background thread (2026-11-27).

Before this, nothing pruned anything: data/decisions grew 34-70 MB a day (308 MB in 11 files), the
trade databases had no backup, and the only WAL checkpoint was trade_memory's own. Each step is
isolated: one failure is reported and the rest still run. Files are matched by the YYYYMMDD in their
name, so today's and yesterday's files are never touched (retention is bounded to >= 3 days).
"""
from __future__ import annotations

import gzip
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

JOURNAL_DIRS = ("decisions", "advisories", "alerts")
BACKUP_DBS = ("jarvis_history.db", "jarvis_trade_memory.db")
_DATE = re.compile(r"(\d{8})")


def _file_day(name: str) -> Optional[datetime]:
    m = _DATE.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def rotate_journals(directory: str, today: datetime, retention_days: int, delete_after_days: int) -> Dict[str, int]:
    """gzip *.jsonl older than retention_days; delete *.jsonl.gz older than delete_after_days."""
    out = {"compressed": 0, "deleted": 0, "freed_bytes": 0}
    if not os.path.isdir(directory):
        return out
    keep_after = today - timedelta(days=max(3, int(retention_days)))
    drop_before = today - timedelta(days=max(int(retention_days) + 1, int(delete_after_days)))
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        day = _file_day(name)
        if day is None or not os.path.isfile(path):
            continue
        if name.endswith(".jsonl") and day < keep_after:
            before = os.path.getsize(path)
            with open(path, "rb") as src, gzip.open(path + ".gz", "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.remove(path)
            out["compressed"] += 1
            out["freed_bytes"] += before - os.path.getsize(path + ".gz")
        elif name.endswith(".jsonl.gz") and day < drop_before:
            out["freed_bytes"] += os.path.getsize(path)
            os.remove(path)
            out["deleted"] += 1
    return out


def backup_database(db_path: str, backup_dir: str, today: datetime, keep: int) -> Dict[str, Any]:
    """Online SQLite backup (consistent while the engine writes), quick_check, passive WAL checkpoint,
    and pruning to the newest `keep` backups of this database."""
    base = os.path.splitext(os.path.basename(db_path))[0]
    os.makedirs(backup_dir, exist_ok=True)
    target = os.path.join(backup_dir, f"{base}_{today:%Y%m%d}.db")
    src = sqlite3.connect(db_path, timeout=10.0)
    try:
        check = src.execute("PRAGMA quick_check").fetchone()[0]
        if not os.path.exists(target):
            dst = sqlite3.connect(target)
            try:
                src.backup(dst)
            finally:
                dst.close()
        src.execute("PRAGMA wal_checkpoint(PASSIVE)")
    finally:
        src.close()
    mine = sorted(n for n in os.listdir(backup_dir) if n.startswith(base + "_") and n.endswith(".db"))
    for old in mine[:-max(1, int(keep))]:
        os.remove(os.path.join(backup_dir, old))
    return {"quick_check": check, "backup": os.path.basename(target), "kept": min(len(mine), max(1, int(keep)))}


def dir_size_gb(path: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 1e9


def run_daily(data_dir: str, cfg: Any, now: Optional[float] = None) -> Dict[str, Any]:
    """One housekeeping pass. Returns a report; never raises."""
    today = datetime.fromtimestamp(now or time.time(), timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    report: Dict[str, Any] = {"at": today.isoformat(), "errors": []}
    for sub in JOURNAL_DIRS:
        try:
            report[sub] = rotate_journals(os.path.join(data_dir, sub), today, cfg.retention_days, cfg.delete_after_days)
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"{sub}: {type(exc).__name__}: {exc}")
    backups: List[Dict[str, Any]] = []
    for name in BACKUP_DBS:
        path = os.path.join(data_dir, name)
        if not os.path.exists(path):
            continue
        try:
            backups.append(dict(backup_database(path, os.path.join(data_dir, "backups"), today, cfg.backups_keep),
                                db=name))
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"{name}: {type(exc).__name__}: {exc}")
    report["backups"] = backups
    report["corrupt"] = [b["db"] for b in backups if str(b.get("quick_check")).lower() != "ok"]
    return report
