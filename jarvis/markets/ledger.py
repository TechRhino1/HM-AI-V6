"""Every recommendation the adviser makes, scored against real later prices.

A recommendation is recorded once per (symbol, strategy, legs, expiry, day). While open it
is marked to the live chain's mid prices; it closes when the plan's target or stop is hit,
or at expiry against the underlying's settlement value. The resulting hit rate and average
P&L per lot are shown next to every new signal, so claims can be checked, not trusted.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from .data.nse import IST
from .data.store import _db, _lock

logger = logging.getLogger(__name__)


def _init(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS ledger (
        id TEXT PRIMARY KEY, ts REAL, symbol TEXT, strategy TEXT, expiry TEXT, lot_size INTEGER,
        legs TEXT, entry_net REAL, target REAL, stop REAL, is_credit INTEGER, edge_per_lot REAL,
        status TEXT, closed_ts REAL, exit_net REAL, pnl_per_lot REAL, exit_reason TEXT, last_mark REAL, last_pnl REAL)""")


def record(advice: Dict[str, Any]) -> Optional[str]:
    if advice.get("status") != "RECOMMEND":
        return None
    rec, plan, an = advice["recommendation"], advice["plan"], advice["analytics"]
    legs = [{k: l[k] for k in ("strike", "type", "side", "lots", "price")} for l in rec["legs"]]
    day = datetime.now(IST).strftime("%Y-%m-%d")
    rid = f"{day}|{advice['symbol']}|{rec['name']}|{an['expiry']}|" + ";".join(f"{l['strike']:g}{l['type']}{l['side'][0]}{l['lots']}" for l in legs)
    is_credit = plan["entry"]["type"] == "credit"
    target = plan["target"].get("close_at_net_debit") if is_credit else plan["target"].get("close_at_net_credit")
    stop = plan["stop"].get("close_at_net_debit") if is_credit else plan["stop"].get("close_at_net_credit")
    with _lock, _db() as con:
        _init(con)
        con.execute("INSERT OR IGNORE INTO ledger (id, ts, symbol, strategy, expiry, lot_size, legs, entry_net, target, stop, is_credit, edge_per_lot, status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'OPEN')",
                    (rid, time.time(), advice["symbol"], rec["name"], an["expiry"], an["lot_size"] or 1, json.dumps(legs),
                     plan["entry"]["net"], target, stop, int(is_credit), rec["edge_per_lot"]))
    return rid


def _mark(legs: List[Dict[str, Any]], an: Dict[str, Any]) -> Optional[float]:
    """Current net value to close (positive = you receive). None if any leg has no live mid."""
    rows = {r["strike"]: r for r in an["strikes"]}
    total = 0.0
    for l in legs:
        q = (rows.get(l["strike"]) or {}).get("call" if l["type"] == "CE" else "put")
        if not q or not q.get("mid"):
            return None
        total += (1 if l["side"] == "BUY" else -1) * q["mid"] * l["lots"]
    return total


def score_open() -> int:
    """Mark open recommendations to the live chains; close on target, stop or expiry."""
    from .data import feeds
    from .options import chain_analytics
    with _lock, _db() as con:
        _init(con)
        rows = con.execute("SELECT id, symbol, expiry, lot_size, legs, entry_net, target, stop, is_credit FROM ledger WHERE status='OPEN'").fetchall()
    closed = 0
    for rid, sym, exp, lot, legs_json, entry, target, stop, is_credit in rows:
        legs = json.loads(legs_json)
        try:
            an = chain_analytics.analyse(feeds.chain(sym, exp))
        except Exception as exc:
            # The chain is gone after expiry: settle on the underlying's real close.
            if datetime.strptime(exp, "%d-%b-%Y").date() < datetime.now(IST).date():
                closed += _settle(rid, sym, legs, entry, lot, is_credit)
            else:
                logger.info("ledger mark %s: %s", rid, exc)
            continue
        value = _mark(legs, an)
        if value is None:
            continue
        pnl_unit = value + (entry if is_credit else -entry)  # credit: received entry, pay to close; debit: paid entry
        reason = None
        cost_to_close = -value
        if is_credit:
            if target is not None and cost_to_close <= target:
                reason = "target"
            elif stop is not None and cost_to_close >= stop:
                reason = "stop"
        else:
            if target is not None and value >= target:
                reason = "target"
            elif stop is not None and value <= stop:
                reason = "stop"
        with _lock, _db() as con:
            if reason:
                con.execute("UPDATE ledger SET status='CLOSED', closed_ts=?, exit_net=?, pnl_per_lot=?, exit_reason=? WHERE id=?",
                            (time.time(), value, round(pnl_unit * lot, 2), reason, rid))
                closed += 1
            else:
                con.execute("UPDATE ledger SET last_mark=?, last_pnl=? WHERE id=?", (value, round(pnl_unit * lot, 2), rid))
    return closed


def _settle(rid, sym, legs, entry, lot, is_credit) -> int:
    from .data import yahoo
    try:
        b = yahoo.bars(sym, "IN", "1d", "1mo")["bars"]
    except Exception:
        return 0
    s = b[-1]["close"]
    value = sum((1 if l["side"] == "BUY" else -1) * (max(0.0, s - l["strike"]) if l["type"] == "CE" else max(0.0, l["strike"] - s)) * l["lots"] for l in legs)
    pnl_unit = value + (entry if is_credit else -entry)
    with _lock, _db() as con:
        con.execute("UPDATE ledger SET status='CLOSED', closed_ts=?, exit_net=?, pnl_per_lot=?, exit_reason='expiry' WHERE id=?",
                    (time.time(), value, round(pnl_unit * lot, 2), rid))
    return 1


def summary() -> Dict[str, Any]:
    with _lock, _db() as con:
        _init(con)
        rows = con.execute("SELECT ts, symbol, strategy, expiry, entry_net, is_credit, edge_per_lot, status, pnl_per_lot, exit_reason, last_pnl "
                           "FROM ledger ORDER BY ts DESC LIMIT 200").fetchall()
    cols = ["ts", "symbol", "strategy", "expiry", "entry_net", "is_credit", "edge_per_lot", "status", "pnl_per_lot", "exit_reason", "open_pnl"]
    items = [dict(zip(cols, r)) for r in rows]
    closed = [i for i in items if i["status"] == "CLOSED" and i["pnl_per_lot"] is not None]
    by: Dict[str, Dict[str, Any]] = {}
    for i in closed:
        s = by.setdefault(i["strategy"], {"n": 0, "wins": 0, "pnl": 0.0})
        s["n"] += 1; s["wins"] += i["pnl_per_lot"] > 0; s["pnl"] += i["pnl_per_lot"]
    return {
        "recorded": len(items), "open": sum(i["status"] == "OPEN" for i in items), "closed": len(closed),
        "win_rate": round(sum(i["pnl_per_lot"] > 0 for i in closed) / len(closed) * 100, 1) if closed else None,
        "avg_pnl_per_lot": round(sum(i["pnl_per_lot"] for i in closed) / len(closed), 2) if closed else None,
        "by_strategy": [{"strategy": k, **v, "win_rate": round(v["wins"] / v["n"] * 100, 1), "avg_pnl": round(v["pnl"] / v["n"], 2)} for k, v in by.items()],
        "items": items[:50],
    }
