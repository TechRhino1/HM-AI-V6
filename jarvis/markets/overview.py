"""Feeds for the Overview home screen: today's timeline, a "since you last looked" fact sheet (with a
short AI summary grounded only in that sheet), and batched intraday sparklines.

Every figure comes from a stored or live source and carries provenance. A source that cannot be read is
reported as unavailable in `sources`; nothing is filled in.

Day basis: the timeline's default window starts at 00:00 IST (the NSE trading day). Forex events use the
same window rather than a UTC day, so one list covers both books.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from .data.models import grade, unavailable
from .data.nse import IST

logger = logging.getLogger(__name__)

DAY_BASIS = "IST calendar day (from 00:00 Asia/Kolkata); forex events use the same window"
# The journal flaps NO_TRADE <-> WAIT every few seconds; one verdict event per symbol/style per half hour.
THROTTLE_SEC = 1800
JOURNAL_PROV = {"source": "trade journal (executed_trades)", "kind": "live", "as_of": None}
DECISIONS_PROV = {"source": "engine decision journal (data/decisions)", "kind": "live", "as_of": None}
ALERTS_PROV = {"source": "alert_fired (markets.db)", "kind": "live", "as_of": None}
BRIEFS_PROV = {"source": "ai_briefs (markets.db)", "kind": "live", "as_of": None}
LEDGER_PROV = {"source": "adviser ledger (markets.db)", "kind": "live", "as_of": None}
QUIET_ROUTER = ("SKIP", "HOLD", "FLAT")


def day_start(now: Optional[float] = None) -> float:
    d = datetime.fromtimestamp(now if now is not None else time.time(), IST)
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def epoch(v: Any) -> Optional[float]:
    """ISO string (naive = UTC) or epoch seconds/ms → epoch seconds; None when unreadable."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v) / 1000 if v > 1e12 else float(v)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def _n(v: Any, d: int = 2) -> Any:
    return round(float(v), d) if isinstance(v, (int, float)) else v


def _ev(ts: float, kind: str, title: str, detail: str, link: str, prov: Dict[str, Any], symbol: Optional[str] = None) -> Dict[str, Any]:
    return {"ts": ts, "kind": kind, "symbol": symbol, "title": title, "detail": detail, "link": link, "prov": prov}


# ---------------------------------------------------------------- sources

def _trades(days: int = 2) -> List[Dict[str, Any]]:
    from jarvis.data.database import TRADE_DB
    return TRADE_DB.fetch_recent_trades(limit=500, days=days) or []


def trade_events(since: float, trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for t in trades:
        sym, side, mode = t.get("symbol"), t.get("action") or "", t.get("execution_mode") or "unknown mode"
        vol = f"{t['volume']:g}" if isinstance(t.get("volume"), (int, float)) else "?"
        opened, closed = epoch(t.get("timestamp")), epoch(t.get("closed_at"))
        if opened and opened >= since:
            out.append(_ev(opened, "trade", f"Opened {side} {vol} {sym}",
                           f"entry {_n(t.get('entry_price'), 5)} · SL {_n(t.get('sl'), 5) or 'none'} · TP {_n(t.get('tp'), 5) or 'none'} · {mode}"
                           + (f" · {t['strategy']}" if t.get("strategy") else ""),
                           "portfolio/history" if closed else "portfolio/open", JOURNAL_PROV, sym))
        if closed and closed >= since:
            pnl = t.get("realized_pnl")
            out.append(_ev(closed, "trade", f"Closed {side} {vol} {sym}" + (f" {pnl:+.2f}" if isinstance(pnl, (int, float)) else " (P&L not recorded)"),
                           f"exit {_n(t.get('exit_price'), 5)} · {t.get('exit_reason') or 'reason not recorded'} · {mode}",
                           "portfolio/history", JOURNAL_PROV, sym))
    return out


def _alerts(since: float) -> List[Dict[str, Any]]:
    from . import alerts
    return alerts.fired(since, 200)


def alert_events(fired: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_ev(a["ts"], "alert", a["message"], str(a.get("type") or "").replace("_", " "), "alerts", a.get("prov") or ALERTS_PROV)
            for a in fired]


def _rows(sql: str, args: tuple) -> List[tuple]:
    import sqlite3
    from .data.store import _db, _lock
    with _lock, _db() as con:
        try:
            return con.execute(sql, args).fetchall()
        except sqlite3.OperationalError as exc:  # table not created yet = nothing stored yet
            if "no such table" in str(exc):
                return []
            raise


def _briefs(since: float) -> List[Dict[str, Any]]:
    return [{"kind": k, "ts": ts, "provider": p, "text": t}
            for k, ts, p, t in _rows("SELECT kind, ts, provider, text FROM ai_briefs WHERE ts>=? ORDER BY ts", (since,))]


def brief_events(briefs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for b in briefs:
        first = next((ln.strip() for ln in (b.get("text") or "").splitlines() if ln.strip()), "")
        out.append(_ev(b["ts"], "brief", f"{'Pre-open' if b['kind'] == 'pre' else 'Post-close'} brief written",
                       f"by {b.get('provider') or 'unknown'} · {first[:160]}", "overview", {**BRIEFS_PROV, "as_of": b["ts"]}))
    return out


def _ledger(since: float) -> List[Dict[str, Any]]:
    cols = ("ts", "symbol", "strategy", "expiry", "edge_per_lot", "status", "closed_ts", "pnl_per_lot", "exit_reason")
    return [dict(zip(cols, r)) for r in _rows(f"SELECT {', '.join(cols)} FROM ledger WHERE ts>=? OR closed_ts>=? ORDER BY ts", (since, since))]


def ledger_events(since: float, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        if r["ts"] and r["ts"] >= since:
            out.append(_ev(r["ts"], "recommendation", f"Adviser recommends {r['strategy']} on {r['symbol']}",
                           f"edge {_n(r['edge_per_lot'])} per lot after costs · expiry {r['expiry']}", "markets/fno", LEDGER_PROV, r["symbol"]))
        if r.get("closed_ts") and r["closed_ts"] >= since:
            out.append(_ev(r["closed_ts"], "recommendation", f"Ledger settled {r['strategy']} on {r['symbol']}",
                           f"{_n(r['pnl_per_lot'])} per lot · {r.get('exit_reason') or 'reason not recorded'}", "markets/fno", LEDGER_PROV, r["symbol"]))
    return out


# ---------------------------------------------------------------- decision journal (incremental reader)

_KEEP = ("kind", "symbol", "style", "decision", "bias", "failing", "authorized", "executed", "status", "vetoes",
         "component", "action", "reason", "strategy")
_JCACHE: Dict[str, Dict[str, Any]] = {}
_jlock = threading.Lock()


def _journal_dir() -> str:
    from jarvis.config.paths import DATA_DIR
    return os.path.join(DATA_DIR, "decisions")


def _read_journal(path: str) -> List[Dict[str, Any]]:
    """Parse only the bytes appended since the last call (the file grows every few seconds)."""
    with _jlock:
        c = _JCACHE.setdefault(path, {"pos": 0, "rows": []})
        try:
            size = os.path.getsize(path)
        except OSError:
            return []
        if size < c["pos"]:
            c.update(pos=0, rows=[])
        if size > c["pos"]:
            with open(path, "rb") as f:
                f.seek(c["pos"])
                chunk = f.read()
            end = chunk.rfind(b"\n") + 1  # complete lines only; a half-written line waits for the next call
            for ln in chunk[:end].splitlines():
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                row = {k: r.get(k) for k in _KEEP}
                row["ts"] = epoch(r.get("ts"))
                if row["ts"] is not None:
                    c["rows"].append(row)
            c["pos"] += end
        return c["rows"]


def journal_rows(since: float, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Rows from the UTC-day files covering the day before `since` (the baseline) up to now, at most 3 files."""
    now = now if now is not None else time.time()
    days = sorted({time.strftime("%Y%m%d", time.gmtime(t)) for t in (since - 86400, since, now)})
    days = [d for d in days if d <= time.strftime("%Y%m%d", time.gmtime(now))][-3:]
    out: List[Dict[str, Any]] = []
    for d in days:
        out.extend(_read_journal(os.path.join(_journal_dir(), f"decisions_{d}.jsonl")))
    return out


def _veto_codes(v: Any) -> Tuple[str, ...]:
    return tuple(str(x).split(":", 1)[0].strip() for x in (v or []))


def signal_events(since: float, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Verdict changes (with gates newly failing / now passing), dispatch outcomes and trend-router actions."""
    out: List[Dict[str, Any]] = []
    last: Dict[tuple, Dict[str, Any]] = {}
    emitted: Dict[tuple, float] = {}
    folded: Dict[tuple, int] = {}
    for r in rows:
        ts, kind = r["ts"], r.get("kind")
        if kind == "router":
            if ts >= since and r.get("action") not in QUIET_ROUTER:
                comp = str(r.get("component") or "")
                out.append(_ev(ts, "signal", f"Trend router {r.get('action')} · {comp}", f"{r.get('reason') or ''} · regime {r.get('regime') or 'n/a'}".strip(" ·"),
                               "signals", DECISIONS_PROV, (re.search(r"_([A-Z]{6})_", comp) or [None, None])[1]))
            continue
        key = (r.get("symbol"), r.get("style"), kind or "verdict")
        sig = (r.get("status"), _veto_codes(r.get("vetoes"))) if kind == "dispatch" else r.get("decision")
        prev = last.get(key)
        last[key] = {"sig": sig, "row": r}
        must = kind != "dispatch" and (r.get("executed") or r.get("authorized")) and not (prev and prev["row"].get("authorized") == r.get("authorized") and prev["row"].get("executed") == r.get("executed"))
        if ts < since or (prev is None and kind != "dispatch") or (prev and prev["sig"] == sig and not must):
            continue
        if not must and ts - emitted.get(key, 0) < THROTTLE_SEC:
            folded[key] = folded.get(key, 0) + 1
            continue
        emitted[key] = ts
        extra = f" · {folded.pop(key)} more change(s) folded since the previous event" if folded.get(key) else ""
        sym, style = r.get("symbol"), r.get("style")
        if kind == "dispatch":
            out.append(_ev(ts, "signal", f"Dispatch {r.get('status')} · {sym} {style} {r.get('bias') or ''}".rstrip(),
                           "; ".join(str(v) for v in (r.get("vetoes") or [])[:2]) + extra, "signals", DECISIONS_PROV, sym))
            continue
        pf, nf = set(prev["row"].get("failing") or []), set(r.get("failing") or [])
        parts = []
        if nf - pf:
            parts.append("now failing: " + ", ".join(sorted(nf - pf)))
        if pf - nf:
            parts.append("now passing: " + ", ".join(sorted(pf - nf)))
        if r.get("executed"):
            parts.append(f"execution {r['executed']}")
        elif r.get("authorized"):
            parts.append("authorised to trade")
        out.append(_ev(ts, "signal", f"{sym} {style}: {prev['sig']} → {sig}" + (f" ({r.get('bias')})" if r.get("bias") else ""),
                       ("; ".join(parts) or "same gates") + extra, "signals", DECISIONS_PROV, sym))
    return out


def gate_changes(since: float, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per symbol/style: verdict and failing gates now vs. just before `since` (only those that differ)."""
    before: Dict[tuple, Dict[str, Any]] = {}
    after: Dict[tuple, Dict[str, Any]] = {}
    for r in rows:
        if r.get("kind"):
            continue
        (before if r["ts"] < since else after)[(r.get("symbol"), r.get("style"))] = r
    out = []
    for key, r in sorted(after.items(), key=lambda kv: str(kv[0])):
        b = before.get(key)
        pf, nf = set((b or {}).get("failing") or []), set(r.get("failing") or [])
        if b and b.get("decision") == r.get("decision") and pf == nf:
            continue
        out.append({"symbol": key[0], "style": key[1], "from": b.get("decision") if b else None, "to": r.get("decision"),
                    "now_failing": sorted(nf - pf), "now_passing": sorted(pf - nf)})
    return out


# ---------------------------------------------------------------- timeline

def _gather(fns: Dict[str, Callable[[], List[Dict[str, Any]]]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    status: Dict[str, Any] = {}
    with ThreadPoolExecutor(len(fns)) as ex:
        futs = {k: ex.submit(fn) for k, fn in fns.items()}
    for k, f in futs.items():
        try:
            evs = f.result()
            events.extend(evs)
            status[k] = {"ok": True, "events": len(evs)}
        except Exception as exc:
            logger.info("overview source %s failed: %s", k, exc)
            status[k] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
    return events, status


def timeline(since: Optional[float] = None, limit: int = 200) -> Dict[str, Any]:
    start = day_start()
    since = start if since is None else since
    events, status = _gather({
        "trades": lambda: trade_events(since, _trades()),
        "alerts": lambda: alert_events(_alerts(since)),
        "briefs": lambda: brief_events(_briefs(since)),
        "recommendations": lambda: ledger_events(since, _ledger(since)),
        "signals": lambda: signal_events(since, journal_rows(since)),
    })
    events.sort(key=lambda e: e["ts"], reverse=True)
    return {"since": since, "day_start": start, "day_basis": DAY_BASIS, "total": len(events), "events": events[:limit],
            "sources": status,
            "prov": {"source": "trade journal, alerts, briefs, adviser ledger, engine decision journal", "kind": "live", "as_of": time.time(),
                     "note": "each event carries its own source; sources that failed are listed in `sources`"}}


# ---------------------------------------------------------------- sparklines

def parse_spark_closes(payload: Dict[str, Any], t2s: Dict[str, str], session_open: bool) -> Dict[str, Dict[str, Any]]:
    """Yahoo /v8/finance/spark → symbol → {times, closes, last, prev_close, change_pct, prov}."""
    out: Dict[str, Dict[str, Any]] = {}
    for t, d in (payload or {}).items():
        sym = t2s.get(t)
        if not sym or not isinstance(d, dict):
            continue
        pts = [(int(ts), float(c)) for ts, c in zip(d.get("timestamp") or [], d.get("close") or []) if c is not None]
        if not pts:
            continue
        prev = d.get("previousClose") or d.get("chartPreviousClose")
        prev = float(prev) if prev not in (None, "") else None
        last = pts[-1][1]
        out[sym] = {"times": [p[0] for p in pts], "closes": [p[1] for p in pts], "last": last, "prev_close": prev,
                    "change_pct": round((last - prev) / prev * 100, 3) if prev else None,
                    "prov": grade(f"yahoo:spark/{t} 5m", float(pts[-1][0]), session_open, fresh_sec=600).to_dict()}
    return out


def _yahoo_spark(symbols: List[str], market: str) -> Dict[str, Dict[str, Any]]:
    import requests
    from .data import feeds, yahoo
    from .equities.service import _H, SPARK
    t2s = {yahoo.ticker(s, market): s for s in symbols}
    is_open = feeds.session(market)["open"]

    def one(chunk: List[str]) -> Dict[str, Dict[str, Any]]:
        try:
            r = requests.get(SPARK, params={"symbols": ",".join(chunk), "range": "1d", "interval": "5m"}, headers=_H, timeout=12)
            return parse_spark_closes(r.json(), t2s, is_open)
        except Exception as exc:
            logger.info("spark batch failed: %s", exc)
            return {}

    out: Dict[str, Dict[str, Any]] = {}
    tickers = list(t2s)
    with ThreadPoolExecutor(4) as ex:
        for part in ex.map(one, [tickers[i:i + 20] for i in range(0, len(tickers), 20)]):  # Yahoo caps spark at 20
            out.update(part)
    return out


def _fx_spark(symbol: str) -> Optional[Dict[str, Any]]:
    """Last 96 M15 bars (24 h) from the same MT5 feed /api/candles serves."""
    from jarvis.api.server import JarvisRequestHandler, _broker_frame
    df = JarvisRequestHandler.data_feed.fetch_rates(symbol, timeframe="M15", num_bars=96, include_current_bar=True)
    if not _broker_frame(df):
        return None
    times, closes = [], []
    for r in df.to_dict(orient="records"):
        t = r["time"]
        if hasattr(t, "tzinfo") and t.tzinfo is None:
            t = t.tz_localize("UTC")
        times.append(int(t.timestamp()) if hasattr(t, "timestamp") else int(t))
        closes.append(float(r["close"]))
    if not closes:
        return None
    return {"times": times, "closes": closes, "last": closes[-1], "prev_close": None,
            "change_pct": round((closes[-1] - closes[0]) / closes[0] * 100, 3) if closes[0] else None,
            "prov": grade("mt5:copy_rates_from_pos M15", float(times[-1]), True, fresh_sec=1800).to_dict()}


def sparklines(symbols: List[str], market: str) -> Dict[str, Any]:
    market = (market or "FX").upper()
    if market not in ("FX", "IN", "US"):
        raise ValueError("market must be FX, IN or US")
    syms = list(dict.fromkeys(s.strip() for s in symbols if s and s.strip()))[:40]
    if market == "FX":
        def fx(s):
            try:
                return s, _fx_spark(s)
            except Exception as exc:
                logger.info("fx spark %s failed: %s", s, exc)
                return s, None
        got = {s: v for s, v in map(fx, syms) if v}
        src = "mt5:copy_rates_from_pos M15 (24 h)"
    else:
        got = _yahoo_spark(syms, market) if syms else {}
        src = "yahoo:spark 5m (today)"
    series, missing = {}, []
    for s in syms:
        if s in got:
            series[s] = got[s]
        else:
            missing.append(s)
            series[s] = {"times": [], "closes": [], "prov": unavailable(src, "no bars returned for this symbol").to_dict()}
    return {"market": market, "series": series, "unavailable": missing,
            "prov": {"source": src, "kind": "unavailable" if syms and len(missing) == len(syms) else "live", "as_of": time.time(),
                     "note": "each series carries its own provenance"}}


# ---------------------------------------------------------------- what changed since

# (symbol, market, label): sparkline sources for the market-move part of the fact sheet.
MOVERS = [("NIFTY", "IN", "NIFTY 50"), ("BANKNIFTY", "IN", "Bank Nifty"), ("INDIAVIX", "IN", "India VIX"),
          ("^GSPC", "US", "S&P 500"), ("DX-Y.NYB", "US", "US dollar index"), ("^TNX", "US", "US 10Y yield")]


def move_since(s: Dict[str, Any], since: float) -> Optional[Dict[str, Any]]:
    """Move from the last close at or before `since` to now; the previous close when `since` predates today's bars."""
    times, closes = s.get("times") or [], s.get("closes") or []
    if not closes:
        return None
    i = max((j for j, t in enumerate(times) if t <= since), default=None)
    ref, basis = (closes[i], "since your last visit") if i is not None else (s.get("prev_close"), "since previous close")
    if not ref:
        return None
    return {"from": _n(ref), "now": _n(closes[-1]), "change_pct": round((closes[-1] - ref) / ref * 100, 2), "basis": basis}


def market_moves(since: float) -> List[Dict[str, Any]]:
    out = []
    for market in ("IN", "US"):
        rows = [m for m in MOVERS if m[1] == market]
        try:
            series = sparklines([m[0] for m in rows], market)["series"]
        except Exception as exc:
            series = {m[0]: {"prov": unavailable("yahoo:spark", str(exc)[:120]).to_dict()} for m in rows}
        for sym, _, label in rows:
            s = series.get(sym) or {}
            mv = move_since(s, since)
            out.append({"name": label, **(mv or {"change_pct": None}), "prov": s.get("prov") or unavailable("yahoo:spark", "no data").to_dict()})
    return out


def _account() -> Dict[str, Any]:
    from jarvis.application.state_manager import GLOBAL_STATE
    snap = GLOBAL_STATE.get_state_snapshot()
    return {"account": snap.get("account") or {}, "positions": snap.get("positions") or [], "ts": snap.get("timestamp")}


def changes(since: float, equity_then: Optional[float] = None) -> Dict[str, Any]:
    """Compact fact sheet of what changed between `since` and now. Every number here is real or absent."""
    def safe(fn, fallback):
        try:
            return fn()
        except Exception as exc:
            logger.info("changes source failed: %s", exc)
            return fallback(exc)

    err = lambda name: (lambda exc: {"error": f"{type(exc).__name__}: {exc}"[:160], "prov": unavailable(name, "read failed").to_dict()})
    with ThreadPoolExecutor(6) as ex:
        f_tr = ex.submit(safe, lambda: _trades(days=max(1, int((time.time() - since) // 86400) + 1)), lambda e: e)
        f_al = ex.submit(safe, lambda: _alerts(since), lambda e: e)
        f_j = ex.submit(safe, lambda: journal_rows(since), lambda e: e)
        f_mk = ex.submit(safe, lambda: market_moves(since), lambda e: [])
        f_lg = ex.submit(safe, lambda: _ledger(since), lambda e: e)
        f_br = ex.submit(safe, lambda: _briefs(since), lambda e: e)
        f_ac = ex.submit(safe, _account, lambda e: e)
    acc_s, trades, fired, rows, ledg, briefs = f_ac.result(), f_tr.result(), f_al.result(), f_j.result(), f_lg.result(), f_br.result()

    facts: Dict[str, Any] = {"since_ist": datetime.fromtimestamp(since, IST).strftime("%Y-%m-%d %H:%M"),
                             "now_ist": datetime.now(IST).strftime("%Y-%m-%d %H:%M")}
    if isinstance(acc_s, Exception) or not acc_s["account"].get("equity"):
        facts["account"] = {"equity_now": None, "prov": unavailable("broker account (state manager)", "no account synced").to_dict()}
    else:
        a = acc_s["account"]
        facts["account"] = {"currency": a.get("currency") or "USD", "equity_now": _n(a.get("equity")), "open_pnl_now": _n(a.get("profit")),
                            "open_positions_now": len(acc_s["positions"]),
                            "prov": {"source": "broker account via state manager (MT5 sync)", "kind": "live", "as_of": epoch(acc_s["ts"])}}
        if isinstance(equity_then, (int, float)) and equity_then > 0:
            facts["account"]["equity_at_last_visit"] = _n(equity_then)
            facts["account"]["equity_change"] = _n(a.get("equity") - equity_then)
            facts["account"]["equity_at_last_visit_source"] = "this browser's reading of the live account at the last visit"
    if isinstance(trades, Exception):
        facts["trades"] = err("trade journal")(trades)
    else:
        opened = [t for t in trades if (epoch(t.get("timestamp")) or 0) >= since]
        closed = [t for t in trades if (epoch(t.get("closed_at")) or 0) >= since]
        pnls = [t["realized_pnl"] for t in closed if isinstance(t.get("realized_pnl"), (int, float))]
        facts["trades"] = {
            "opened": [{"symbol": t.get("symbol"), "side": t.get("action"), "lots": t.get("volume"), "mode": t.get("execution_mode")} for t in opened][:10],
            "opened_count": len(opened),
            "closed": [{"symbol": t.get("symbol"), "side": t.get("action"), "pnl": _n(t.get("realized_pnl")), "exit_reason": t.get("exit_reason")} for t in closed][:10],
            "closed_count": len(closed), "realised_pnl": _n(sum(pnls)) if pnls else None, "prov": JOURNAL_PROV}
    facts["alerts"] = err("alerts")(fired) if isinstance(fired, Exception) else {
        "fired_count": len(fired), "latest": [a["message"] for a in fired[:6]], "prov": ALERTS_PROV}
    if isinstance(rows, Exception):
        facts["engine"] = err("decision journal")(rows)
    else:
        gc = gate_changes(since, rows)
        disp = [r for r in rows if r.get("kind") == "dispatch" and r["ts"] >= since]
        facts["engine"] = {"verdict_changes_count": len(gc), "verdict_changes": gc[:12],
                           "dispatches": len(disp), "dispatch_vetoed": sum(r.get("status") == "VETOED" for r in disp),
                           "router_actions": [{"component": r.get("component"), "action": r.get("action"), "reason": r.get("reason")}
                                              for r in rows if r.get("kind") == "router" and r["ts"] >= since and r.get("action") not in QUIET_ROUTER][:6],
                           "prov": DECISIONS_PROV}
    facts["markets"] = f_mk.result()
    if isinstance(ledg, Exception):
        facts["recommendations"] = err("adviser ledger")(ledg)
    else:
        facts["recommendations"] = {
            "new": [{"symbol": r["symbol"], "strategy": r["strategy"], "edge_per_lot": _n(r["edge_per_lot"])} for r in ledg if (r["ts"] or 0) >= since][:8],
            "settled": [{"symbol": r["symbol"], "strategy": r["strategy"], "pnl_per_lot": _n(r["pnl_per_lot"]), "reason": r["exit_reason"]}
                        for r in ledg if (r.get("closed_ts") or 0) >= since][:8], "prov": LEDGER_PROV}
    facts["briefs"] = err("briefs")(briefs) if isinstance(briefs, Exception) else {
        "written": [{"kind": b["kind"], "provider": b["provider"]} for b in briefs], "prov": BRIEFS_PROV}
    return {"since": since, "facts": facts,
            "prov": {"source": "broker account, trade journal, alerts, decision journal, Yahoo spark, adviser ledger, briefs",
                     "kind": "live", "as_of": time.time(), "note": "each section carries its own provenance"}}


def _fmt(v: Any) -> str:
    return f"{v:,.2f}" if isinstance(v, float) else str(v)


def template(f: Dict[str, Any]) -> List[str]:
    """Deterministic bullets; every number is copied from the fact sheet."""
    out = []
    a, t = f.get("account") or {}, f.get("trades") or {}
    if a.get("equity_now") is None:
        acc = "Account: unavailable (no broker account synced)"
    else:
        acc = f"Equity {_fmt(a['equity_now'])} {a.get('currency', '')}".rstrip()
        if a.get("equity_change") is not None:
            acc += f", {'+' if a['equity_change'] >= 0 else ''}{_fmt(a['equity_change'])} since your last visit"
        acc += f"; open P&L {_fmt(a.get('open_pnl_now'))} on {a.get('open_positions_now')} open position(s)"
    out.append(acc + ".")
    if "error" in t:
        out.append("Trades: trade journal unavailable.")
    else:
        bits = []
        if t.get("opened_count"):
            bits.append(f"{t['opened_count']} opened ({', '.join(sorted({str(x['symbol']) for x in t['opened']}))})")
        if t.get("closed_count"):
            bits.append(f"{t['closed_count']} closed" + (f", realised {_fmt(t['realised_pnl'])}" if t.get("realised_pnl") is not None else ", P&L not recorded"))
        out.append("Trades: " + ("; ".join(bits) if bits else "none opened or closed") + ".")
    al = f.get("alerts") or {}
    out.append("Alerts: " + ("unavailable" if "error" in al else f"{al['fired_count']} fired" + (f", latest: {al['latest'][0]}" if al.get("latest") else "")) + ".")
    e = f.get("engine") or {}
    if "error" in e:
        out.append("Engine: decision journal unavailable.")
    else:
        ch = e.get("verdict_changes") or []
        txt = f"Engine: {e['verdict_changes_count']} symbol/style verdict(s) changed"
        if ch:
            c = ch[0]
            txt += f", e.g. {c['symbol']} {c['style']} {c['from'] or 'new'} → {c['to']}" + (f" (now failing: {', '.join(c['now_failing'][:2])})" if c["now_failing"] else "")
        txt += f"; {e['dispatches']} dispatch attempt(s), {e['dispatch_vetoed']} vetoed"
        out.append(txt + ".")
    mk = [m for m in f.get("markets") or [] if m.get("change_pct") is not None]
    gone = [m["name"] for m in f.get("markets") or [] if m.get("change_pct") is None]
    rec = f.get("recommendations") or {}
    tail = f" Adviser: {len(rec['new'])} new recommendation(s)." if rec.get("new") else ""
    out.append("Markets: " + (", ".join(f"{m['name']} {'+' if m['change_pct'] >= 0 else ''}{m['change_pct']}% ({m['basis']})" for m in mk) or "no index data")
               + (f"; unavailable: {', '.join(gone)}" if gone else "") + "." + tail)
    return out


SYSTEM = ("You summarise what changed on a trader's desk using ONLY the JSON fact sheet given. Every number you write must appear in "
          "the facts (you may round). Say 'unavailable' for sections marked unavailable or with an error. Never invent figures, never "
          "recommend placing or closing an order.")


def summary(since: float, equity_then: Optional[float] = None, provider: Any = "auto") -> Dict[str, Any]:
    from .levels import grounded
    ch = changes(since, equity_then)
    facts = ch["facts"]
    bullets, source, note = template(facts), "template", ""
    p = provider
    if p == "auto":
        try:
            from jarvis.ai import client
            p = client.get_provider()
        except Exception as exc:
            p, note = None, f"provider unavailable: {exc}"
    if p is not None:
        from jarvis.ai.providers.base import ProviderError
        prompt = ("Facts (JSON):\n" + json.dumps(facts, default=str) + "\n\nWrite 3 to 5 bullets, one line each, starting with '- ', "
                  "on what changed since the trader last looked: account and P&L, positions opened/closed, alerts, engine verdict and "
                  "gate changes, market moves, new recommendations or briefs. Most important first. Use only numbers present in the facts.")
        try:
            res = p.chat([p.user(prompt)], [], SYSTEM, effort="low")
            lines = [re.sub(r"^\s*(?:[-*•]|\d[.)])\s*", "", ln).strip() for ln in (res.text or "").splitlines() if ln.strip()]
            lines = [ln for ln in lines if ln][:5]
            if res.stop_reason != "refusal" and len(lines) >= 3 and grounded(" ".join(lines), facts):
                bullets, source = lines, p.name
            else:
                note = "AI answer cited a figure not in the facts (or was incomplete); deterministic summary shown"
        except ProviderError as exc:
            note = f"AI provider busy or failed ({type(exc).__name__}); deterministic summary shown"
        except Exception as exc:  # a provider bug must not break the Overview
            note = f"AI provider error ({type(exc).__name__}); deterministic summary shown"
    elif not note:
        note = "no AI provider configured; deterministic summary shown"
    return {"since": since, "bullets": bullets, "source": source, "note": note, "facts": facts, "prov": ch["prov"]}
