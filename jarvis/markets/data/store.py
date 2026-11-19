"""Local history the exchanges don't serve: intraday option-chain snapshots, ATM IV and FII/DII by day.

Everything stored here was fetched from a real source by the recorder below. Readers
(IV percentile, intraday OI shift, FII/DII trend) report how much history exists, and
analyses that need more than that say "collecting" instead of guessing.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
RECORD_SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX")
RECORD_EVERY_SEC = 180   # chain snapshots
CYCLE_SEC = 60           # alerts / scheduled jobs
_lock = threading.Lock()


def _path() -> str:
    from jarvis.config.paths import DATA_DIR
    return os.path.join(DATA_DIR, "markets.db")


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_path(), timeout=10)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS chain_snapshots (symbol TEXT, expiry TEXT, ts REAL, spot REAL, payload BLOB,
            PRIMARY KEY (symbol, expiry, ts));
        CREATE TABLE IF NOT EXISTS atm_iv (symbol TEXT, ts REAL, expiry TEXT, spot REAL, iv REAL, PRIMARY KEY (symbol, ts));
        CREATE TABLE IF NOT EXISTS fii_dii (date TEXT, category TEXT, buy_cr REAL, sell_cr REAL, net_cr REAL,
            PRIMARY KEY (date, category));
    """)
    return con


def atm_iv_of(chain) -> Optional[float]:
    """Exchange-reported IV at the strike nearest spot (average of CE and PE where both are quoted)."""
    if not chain.rows:
        return None
    atm = min(chain.rows, key=lambda r: abs(r.strike - chain.spot))
    ivs = [s.iv for s in (atm.call, atm.put) if s and s.iv]
    return round(sum(ivs) / len(ivs), 3) if ivs else None


def record_chain(chain) -> None:
    payload = gzip.compress(json.dumps(asdict(chain), default=str).encode())
    ts = chain.prov.as_of or time.time()
    iv = atm_iv_of(chain)
    with _lock, _db() as con:
        con.execute("INSERT OR REPLACE INTO chain_snapshots VALUES (?,?,?,?,?)", (chain.symbol, chain.expiry, ts, chain.spot, payload))
        if iv:
            con.execute("INSERT OR REPLACE INTO atm_iv VALUES (?,?,?,?,?)", (chain.symbol, ts, chain.expiry, chain.spot, iv))


def record_fii_dii(rows: List[Dict[str, Any]]) -> None:
    with _lock, _db() as con:
        con.executemany("INSERT OR REPLACE INTO fii_dii VALUES (?,?,?,?,?)",
                        [(r["date"], r["category"], r["buy_cr"], r["sell_cr"], r["net_cr"]) for r in rows])


def snapshots(symbol: str, expiry: str, since: float) -> List[Dict[str, Any]]:
    with _db() as con:
        rows = con.execute("SELECT ts, payload FROM chain_snapshots WHERE symbol=? AND expiry=? AND ts>=? ORDER BY ts",
                           (symbol, expiry, since)).fetchall()
    return [{"ts": ts, **json.loads(gzip.decompress(p))} for ts, p in rows]


def iv_history(symbol: str, days: int = 365) -> List[Dict[str, float]]:
    """One ATM IV per trading day (the last snapshot of each day)."""
    with _db() as con:
        rows = con.execute(
            "SELECT date(ts,'unixepoch','+5 hours','+30 minutes') d, iv FROM atm_iv WHERE symbol=? AND ts>=? "
            "GROUP BY d HAVING ts=MAX(ts) ORDER BY d", (symbol, time.time() - days * 86400)).fetchall()
    return [{"date": d, "iv": iv} for d, iv in rows]


def fii_dii_history(days: int = 60) -> List[Dict[str, Any]]:
    with _db() as con:
        rows = con.execute("SELECT date, category, net_cr FROM fii_dii").fetchall()
    from datetime import datetime
    out = [{"date": d, "category": c, "net_cr": n} for d, c, n in rows]
    out.sort(key=lambda r: datetime.strptime(r["date"], "%d-%b-%Y"))
    return out[-days * 2:]


class Recorder(threading.Thread):
    """Snapshots the index chains every few minutes while NSE is open, and FII/DII once it is published."""

    def __init__(self) -> None:
        super().__init__(name="markets-recorder", daemon=True)
        self.stop = threading.Event()
        self.last: Dict[str, Any] = {}

    def _daily(self, key: str, hhmm: tuple, fn, until: tuple = (23, 59)) -> None:
        """Run `fn` once per IST weekday in the window [hhmm, until]."""
        from datetime import datetime
        from .nse import IST
        now = datetime.now(IST)
        day = now.strftime("%Y-%m-%d")
        if now.weekday() < 5 and hhmm <= (now.hour, now.minute) <= until and self.last.get(key) != day:
            self.last[key] = day
            try:
                fn()
            except Exception as exc:
                logger.warning("recorder %s failed: %s", key, exc)

    def _jobs(self) -> None:
        """Alerts every cycle; institutional EOD job after 18:30 IST; AI briefs at 08:50 and 15:45 IST."""
        from .. import alerts
        try:
            from .. import inst as inst_module  # built separately; may not exist yet
        except ImportError:
            inst_module = None
        try:
            alerts.evaluate_all()
        except Exception as exc:
            logger.info("alerts cycle: %s", exc)
        if inst_module is not None and hasattr(inst_module, "daily_job"):
            self._daily("inst_daily", (18, 30), inst_module.daily_job)
        from jarvis.ai import briefs
        self._daily("brief_pre", (8, 50), lambda: briefs.generate("pre"), until=(9, 15))
        self._daily("brief_post", (15, 45), lambda: briefs.generate("post"), until=(18, 0))

    def run(self) -> None:
        from . import feeds
        while not self.stop.is_set():
            try:
                self._jobs()
            except Exception as exc:
                logger.warning("recorder jobs failed: %s", exc)
            try:
                if feeds.session("IN")["open"] and time.time() - self.last.get("chains", 0) >= RECORD_EVERY_SEC:
                    self.last["chains"] = time.time()
                    for sym in RECORD_SYMBOLS:
                        try:
                            record_chain(feeds.chain(sym))
                            self.last[sym] = time.time()
                        except Exception as exc:
                            logger.info("recorder %s: %s", sym, exc)
                    try:
                        from .. import ledger
                        ledger.score_open()
                        if time.time() - self.last.get("scan", 0) > 900:
                            from ..adviser import fno
                            fno.scan()  # records new recommendations in the ledger every 15 min
                            self.last["scan"] = time.time()
                    except Exception as exc:
                        logger.info("ledger cycle: %s", exc)
                fd = feeds.fii_dii()
                if fd.get("rows"):
                    record_fii_dii(fd["rows"])
            except Exception as exc:
                logger.warning("markets recorder cycle failed: %s", exc)
            self.stop.wait(CYCLE_SEC)


RECORDER: Optional[Recorder] = None


def start_recorder() -> None:
    global RECORDER
    if RECORDER is None:
        RECORDER = Recorder()
        RECORDER.start()
