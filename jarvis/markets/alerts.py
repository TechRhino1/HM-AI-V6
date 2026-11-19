"""User alert rules evaluated against live market data.

A rule fires once per crossing and re-arms only after the condition goes false again.
Every fired alert stores the real value that triggered it plus that value's provenance;
when the data needed for a rule is unavailable the rule is skipped, never guessed.

Rule types (``type`` field):
  level_cross            symbol, market (IN|US|FX), level, direction (above|below)
  oi_wall_cross          symbol, side (call|put), nth (1-based wall rank)
  max_pain_distance      symbol, pct            spot within pct % of max pain
  iv_change              symbol, points, window_min   |ATM IV change| over the window >= points
  pcr_cross              symbol, threshold, direction (above|below)
  fii_flip               category (FII|DII), participant (bool, optional)
  futures_buildup_change symbol
  ledger_event           (no params; optional symbol)  target/stop/expiry close of a recommendation
  new_recommendation     symbol ("ANY" for every symbol)
  expiry_pin             symbol, pct            expiry day and spot within pct % of max pain
  event_upcoming         symbol, days
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from .data.nse import IST
from .data.store import _db, _lock

logger = logging.getLogger(__name__)

RULE_TYPES: Dict[str, Dict[str, Any]] = {
    "level_cross": {"required": ["symbol", "level", "direction"], "props": {
        "symbol": {"type": "string"}, "market": {"type": "string", "enum": ["IN", "US", "FX"]},
        "level": {"type": "number"}, "direction": {"type": "string", "enum": ["above", "below"]}}},
    "oi_wall_cross": {"required": ["symbol", "side"], "props": {
        "symbol": {"type": "string"}, "side": {"type": "string", "enum": ["call", "put"]}, "nth": {"type": "integer"}}},
    "max_pain_distance": {"required": ["symbol", "pct"], "props": {"symbol": {"type": "string"}, "pct": {"type": "number"}}},
    "iv_change": {"required": ["symbol", "points"], "props": {
        "symbol": {"type": "string"}, "points": {"type": "number"}, "window_min": {"type": "integer"}}},
    "pcr_cross": {"required": ["symbol", "threshold", "direction"], "props": {
        "symbol": {"type": "string"}, "threshold": {"type": "number"},
        "direction": {"type": "string", "enum": ["above", "below"]}}},
    "fii_flip": {"required": ["category"], "props": {
        "category": {"type": "string", "enum": ["FII", "DII"]}, "participant": {"type": "boolean"}}},
    "futures_buildup_change": {"required": ["symbol"], "props": {"symbol": {"type": "string"}}},
    "ledger_event": {"required": [], "props": {"symbol": {"type": "string"}}},
    "new_recommendation": {"required": [], "props": {"symbol": {"type": "string"}}},
    "expiry_pin": {"required": ["symbol", "pct"], "props": {"symbol": {"type": "string"}, "pct": {"type": "number"}}},
    "event_upcoming": {"required": ["symbol", "days"], "props": {"symbol": {"type": "string"}, "days": {"type": "integer"}}},
}

# Fired alerts waiting for the telemetry SSE stream (bounded; each stream remembers the last id it sent).
_RECENT: Deque[Dict[str, Any]] = deque(maxlen=200)
_eval_lock = threading.Lock()


def _init(con) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS alert_rules (id TEXT PRIMARY KEY, created REAL, rule TEXT, active INTEGER, state TEXT);
        CREATE TABLE IF NOT EXISTS alert_fired (id INTEGER PRIMARY KEY AUTOINCREMENT, rule_id TEXT, ts REAL, type TEXT,
            message TEXT, value TEXT, prov TEXT, acked INTEGER DEFAULT 0);
    """)


# ---------------------------------------------------------------- validation + CRUD

def validate_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    """Return a clean rule dict or raise ValueError naming the problem."""
    if not isinstance(rule, dict):
        raise ValueError("rule must be an object")
    t = rule.get("type")
    spec = RULE_TYPES.get(t)
    if not spec:
        raise ValueError(f"unknown rule type {t!r}; one of {sorted(RULE_TYPES)}")
    out: Dict[str, Any] = {"type": t}
    for k, p in spec["props"].items():
        if k not in rule or rule[k] in (None, ""):
            continue
        v = rule[k]
        try:
            if p["type"] == "number":
                v = float(v)
            elif p["type"] == "integer":
                v = int(v)
            elif p["type"] == "boolean":
                v = bool(v)
            else:
                v = str(v).strip().upper() if k in ("symbol", "market", "category") else str(v).strip().lower()
        except (TypeError, ValueError):
            raise ValueError(f"{k} must be a {p['type']}")
        if "enum" in p and v not in p["enum"]:
            raise ValueError(f"{k} must be one of {p['enum']}")
        out[k] = v
    missing = [k for k in spec["required"] if k not in out]
    if missing:
        raise ValueError(f"{t} needs {missing}")
    if t == "level_cross":
        out.setdefault("market", "IN")
    if t == "oi_wall_cross":
        out["nth"] = max(1, min(3, out.get("nth", 1)))
    if t == "iv_change":
        out["window_min"] = max(5, out.get("window_min", 60))
    if "note" in rule:
        out["note"] = str(rule["note"])[:200]
    return out


def create(rule: Dict[str, Any]) -> Dict[str, Any]:
    clean = validate_rule(rule)
    rid = uuid.uuid4().hex[:12]
    with _lock, _db() as con:
        _init(con)
        con.execute("INSERT INTO alert_rules VALUES (?,?,?,1,?)", (rid, time.time(), json.dumps(clean), json.dumps({})))
    return {"id": rid, "created": time.time(), "active": True, **clean}


def list_rules() -> List[Dict[str, Any]]:
    with _lock, _db() as con:
        _init(con)
        rows = con.execute("SELECT id, created, rule, active, state FROM alert_rules ORDER BY created").fetchall()
    return [{"id": i, "created": c, "active": bool(a), **json.loads(r), "state": json.loads(s or "{}")} for i, c, r, a, s in rows]


def delete(rule_id: str) -> bool:
    with _lock, _db() as con:
        _init(con)
        return con.execute("DELETE FROM alert_rules WHERE id=?", (rule_id,)).rowcount > 0


def ack(fired_ids: List[int]) -> int:
    with _lock, _db() as con:
        _init(con)
        return sum(con.execute("UPDATE alert_fired SET acked=1 WHERE id=?", (int(i),)).rowcount for i in fired_ids)


def fired(since: float = 0.0, limit: int = 200) -> List[Dict[str, Any]]:
    with _lock, _db() as con:
        _init(con)
        rows = con.execute("SELECT id, rule_id, ts, type, message, value, prov, acked FROM alert_fired WHERE ts>? "
                           "ORDER BY ts DESC LIMIT ?", (since, limit)).fetchall()
    return [{"id": i, "rule_id": r, "ts": ts, "type": t, "message": m, "value": json.loads(v), "prov": json.loads(p),
             "acked": bool(a)} for i, r, ts, t, m, v, p, a in rows]


def recent_since(last_id: int) -> List[Dict[str, Any]]:
    """Alerts fired in this process after `last_id`, oldest first (for the SSE stream)."""
    return [a for a in list(_RECENT) if a["id"] > last_id]


def sse_event(alert: Dict[str, Any]) -> str:
    return f"event: alert\nid: alert-{alert['id']}\ndata: {json.dumps(alert, default=str)}\n\n"


# ---------------------------------------------------------------- live inputs

class LiveInputs:
    """Real data for one evaluation cycle; each source is fetched at most once per cycle."""

    def __init__(self) -> None:
        self._memo: Dict[Tuple, Any] = {}

    def _once(self, key: Tuple, fn: Callable[[], Any]) -> Any:
        if key not in self._memo:
            try:
                self._memo[key] = fn()
            except Exception as exc:
                logger.info("alerts input %s unavailable: %s", key, exc)
                self._memo[key] = None
        return self._memo[key]

    def quote(self, symbol: str, market: str) -> Optional[Dict[str, Any]]:
        from .data import feeds
        if market == "FX":  # forex/gold/crypto: the broker's price, not Yahoo
            from .levels import fx_quote
            q = self._once(("quote", symbol, market), lambda: fx_quote(symbol))
        else:
            q = self._once(("quote", symbol, market), lambda: feeds.quote(symbol, market))
        return q if q and q.get("price") is not None else None

    def analytics(self, symbol: str) -> Optional[Dict[str, Any]]:
        def fetch():
            from .data import feeds
            from .options import chain_analytics
            c = feeds.chain(symbol)
            an = chain_analytics.analyse(c)
            an["prov"] = c.prov.to_dict()
            return an
        return self._once(("an", symbol), fetch)

    def iv_points(self, symbol: str, since: float) -> List[Tuple[float, float]]:
        def fetch():
            with _db() as con:
                return con.execute("SELECT ts, iv FROM atm_iv WHERE symbol=? AND ts>=? ORDER BY ts", (symbol, since)).fetchall()
        return self._once(("iv", symbol, int(since // 60)), fetch) or []

    def fii_rows(self) -> Optional[Dict[str, Any]]:
        from .data import feeds
        return self._once(("fii",), feeds.fii_dii)

    def inst(self, slug: str, query: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        from .api import _HANDLERS
        fn = _HANDLERS.get(f"/api/markets/inst/{slug}")
        if fn is None:
            return None
        q = {k: [v] for k, v in (query or {}).items()}
        return self._once(("inst", slug, tuple(sorted((query or {}).items()))), lambda: fn(q))

    def oi_spurts(self) -> Optional[Dict[str, Any]]:
        from .data import feeds
        return self._once(("spurts",), feeds.oi_spurts)

    def ledger_rows(self) -> List[Dict[str, Any]]:
        def fetch():
            from . import ledger
            with _db() as con:
                ledger._init(con)
                rows = con.execute("SELECT id, ts, symbol, strategy, expiry, status, exit_reason, pnl_per_lot, closed_ts FROM ledger "
                                   "ORDER BY ts DESC LIMIT 500").fetchall()
            cols = ["id", "ts", "symbol", "strategy", "expiry", "status", "exit_reason", "pnl_per_lot", "closed_ts"]
            return [dict(zip(cols, r)) for r in rows]
        return self._once(("ledger",), fetch) or []


# ---------------------------------------------------------------- rule checks
# Each returns (new_state, fired) where fired is (message, value, prov) or None.

Check = Tuple[Dict[str, Any], Optional[Tuple[str, Dict[str, Any], Dict[str, Any]]]]


def _edge(state: Dict[str, Any], cond: bool, fire_msg: Callable[[], Tuple[str, Dict[str, Any], Dict[str, Any]]]) -> Check:
    """Fire on the false→true transition (first observation counts); re-arm when false."""
    was = state.get("on", False)
    return {**state, "on": cond}, (fire_msg() if cond and not was else None)


def _cross(state: Dict[str, Any], side: str, want: str, fire_msg) -> Check:
    """Fire only when the observed side changes to `want`; the first observation just sets the side."""
    prev = state.get("side")
    return {**state, "side": side}, (fire_msg() if prev is not None and prev != side and side == want else None)


def _spot(an: Dict[str, Any]) -> float:
    return float(an.get("spot") or an.get("forward"))


def _level_cross(r, st, inp) -> Check:
    q = inp.quote(r["symbol"], r.get("market", "IN"))
    if not q:
        return st, None
    px = float(q["price"])
    side = "above" if px > r["level"] else "below"
    return _cross(st, side, r["direction"], lambda: (
        f"{r['symbol']} crossed {r['direction']} {r['level']:g} (last {px:g})", {"price": px, "level": r["level"]}, q["prov"]))


def _oi_wall_cross(r, st, inp) -> Check:
    an = inp.analytics(r["symbol"])
    if not an:
        return st, None
    walls = (an.get("walls") or {}).get("resistance" if r["side"] == "call" else "support") or []
    n = r.get("nth", 1)
    if len(walls) < n:
        return st, None
    k, spot = float(walls[n - 1]["strike"]), _spot(an)
    side = "above" if spot > k else "below"
    want = "above" if r["side"] == "call" else "below"
    return _cross(st, side, want, lambda: (
        f"{r['symbol']} spot {spot:g} crossed the #{n} {r['side']} OI wall at {k:g}",
        {"spot": spot, "wall_strike": k, "wall_oi": walls[n - 1].get("oi")}, an["prov"]))


def _pain_dist(an) -> Optional[float]:
    mp = an.get("max_pain")
    return abs(_spot(an) - mp) / _spot(an) * 100 if mp else None


def _max_pain_distance(r, st, inp) -> Check:
    an = inp.analytics(r["symbol"])
    d = _pain_dist(an) if an else None
    if d is None:
        return st, None
    return _edge(st, d <= r["pct"], lambda: (
        f"{r['symbol']} spot is {d:.2f}% from max pain {an['max_pain']:g}",
        {"spot": _spot(an), "max_pain": an["max_pain"], "distance_pct": round(d, 3)}, an["prov"]))


def _expiry_pin(r, st, inp) -> Check:
    an = inp.analytics(r["symbol"])
    if not an:
        return st, None
    is_expiry_day = an.get("expiry") == datetime.now(IST).strftime("%d-%b-%Y") or (an.get("days_to_expiry") or 99) < 1
    d = _pain_dist(an)
    if d is None:
        return st, None
    return _edge(st, is_expiry_day and d <= r["pct"], lambda: (
        f"{r['symbol']} expiry-day pin: spot {d:.2f}% from max pain {an['max_pain']:g}",
        {"spot": _spot(an), "max_pain": an["max_pain"], "distance_pct": round(d, 3), "expiry": an.get("expiry")}, an["prov"]))


def _pcr_cross(r, st, inp) -> Check:
    an = inp.analytics(r["symbol"])
    pcr = ((an or {}).get("pcr") or {}).get("oi")
    if pcr is None:
        return st, None
    side = "above" if pcr > r["threshold"] else "below"
    return _cross(st, side, r["direction"], lambda: (
        f"{r['symbol']} OI PCR crossed {r['direction']} {r['threshold']:g} (now {pcr:g})",
        {"pcr_oi": pcr, "threshold": r["threshold"]}, an["prov"]))


def _iv_change(r, st, inp) -> Check:
    an = inp.analytics(r["symbol"])
    now_iv = (an or {}).get("atm_iv")
    if now_iv is None:
        return st, None
    pts = inp.iv_points(r["symbol"], time.time() - r["window_min"] * 60)
    if not pts:
        return st, None  # no recorded history for the window yet
    then_ts, then_iv = pts[0]
    chg = now_iv - then_iv
    return _edge(st, abs(chg) >= r["points"], lambda: (
        f"{r['symbol']} ATM IV moved {chg:+.2f} pts in {r['window_min']} min ({then_iv:g} → {now_iv:g})",
        {"atm_iv": now_iv, "atm_iv_then": then_iv, "then_ts": then_ts, "change_pts": round(chg, 3)}, an["prov"]))


def _fii_flip(r, st, inp) -> Check:
    if r.get("participant"):
        return _participant_flip(r, st, inp)
    d = inp.fii_rows()
    rows = (d or {}).get("rows") or []
    row = next((x for x in rows if str(x.get("category", "")).upper().startswith(r["category"])), None)
    if not row:
        return st, None
    sign = "buy" if row["net_cr"] > 0 else "sell"
    prev = st.get("sign")
    new = {**st, "sign": sign}
    if prev is not None and prev != sign:
        return new, (f"{r['category']} cash flipped to net {sign} (₹{row['net_cr']:,.0f} cr on {row['date']})",
                     {"net_cr": row["net_cr"], "date": row["date"]}, d["prov"])
    return new, None


def _participant_flip(r, st, inp) -> Check:
    """FII index-futures net position sign, if the institutional participant-OI data exists."""
    d = inp.inst("participants", {"days": "5"})
    parts = (((d or {}).get("latest") or {}).get("participants") or {})
    cat = next((k for k in parts if k.upper() == str(r["category"]).upper()), None)
    if not cat or parts[cat].get("net_idx_fut") is None:
        return st, None
    net = float(parts[cat]["net_idx_fut"])
    sign = "long" if net > 0 else "short"
    prev = st.get("sign")
    new = {**st, "sign": sign}
    if prev is not None and prev != sign:
        return new, (f"{r['category']} index-futures net flipped to {sign} ({net:,.0f} contracts)",
                     {"net_contracts": net}, d.get("prov") or {})
    return new, None


def _buildup(price_chg: float, oi_chg: float) -> str:
    from .options.chain_analytics import buildup
    return buildup(price_chg, int(oi_chg))


def _futures_buildup_change(r, st, inp) -> Check:
    sym = r["symbol"]
    sp = inp.oi_spurts()
    row = next((x for x in ((sp or {}).get("rows") or []) if str(x.get("symbol", "")).upper() == sym), None)
    q = inp.quote(sym, "IN")
    if not row or row.get("changeInOI") is None or not q or q.get("change_pct") is None:
        return st, None
    cls = _buildup(float(q["change_pct"]), float(row["changeInOI"]))
    prev = st.get("class")
    new = {**st, "class": cls}
    if prev is not None and prev != cls:
        prov = dict(sp["prov"])
        prov["note"] = (prov.get("note", "") + "; OI change: NSE OI-spurts (futures+options); price change: underlying quote").strip("; ")
        return new, (f"{sym} buildup changed {prev} → {cls}",
                     {"oi_change": row["changeInOI"], "price_change_pct": q["change_pct"], "class": cls, "previous": prev}, prov)
    return new, None


_LEDGER_PROV = {"source": "markets.db ledger", "kind": "live", "note": "marked to live chain mids; settled on real closes"}


def _ledger_event(r, st, inp) -> Check:
    rows = [x for x in inp.ledger_rows() if x["status"] == "CLOSED" and (not r.get("symbol") or x["symbol"] == r["symbol"])]
    seen = set(st.get("seen") or [])
    ids = {x["id"] for x in rows}
    if "seen" not in st:
        return {**st, "seen": sorted(ids)}, None
    new = [x for x in rows if x["id"] not in seen]
    st = {**st, "seen": sorted(seen | ids)[-500:]}
    if not new:
        return st, None
    x = new[0]
    more = f" (+{len(new) - 1} more)" if len(new) > 1 else ""
    return st, (f"{x['symbol']} {x['strategy']} closed on {x['exit_reason']}: P&L/lot {x['pnl_per_lot']}{more}",
                {"closed": [{k: y[k] for k in ("id", "symbol", "strategy", "exit_reason", "pnl_per_lot")} for y in new]},
                _LEDGER_PROV)


def _new_recommendation(r, st, inp) -> Check:
    want = r.get("symbol", "ANY")
    rows = [x for x in inp.ledger_rows() if want in ("ANY", x["symbol"])]
    seen = set(st.get("seen") or [])
    if "seen" not in st:
        return {**st, "seen": sorted(x["id"] for x in rows)[-500:]}, None
    new = [x for x in rows if x["id"] not in seen]
    st = {**st, "seen": sorted(seen | {x["id"] for x in rows})[-500:]}
    if not new:
        return st, None
    x = new[0]
    return st, (f"New adviser recommendation: {x['symbol']} {x['strategy']} ({x['expiry']})",
                {"recommendations": [{k: y[k] for k in ("id", "symbol", "strategy", "expiry")} for y in new]}, _LEDGER_PROV)


def _parse_date(s: Any) -> Optional[datetime]:
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(str(s)[:11].strip(), fmt)
        except ValueError:
            continue
    return None


def _event_upcoming(r, st, inp) -> Check:
    d = inp.inst("events", {"symbol": r["symbol"]})
    rows = (d or {}).get("upcoming") or (d or {}).get("rows") or []
    today = datetime.now(IST).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    hits = []
    for x in rows:
        if str(x.get("symbol", r["symbol"])).upper() != r["symbol"]:
            continue
        dt = _parse_date(x.get("date") or x.get("bm_date") or x.get("exDate"))
        if dt is not None and 0 <= (dt - today).days <= r["days"]:
            hits.append(x)
    return _edge(st, bool(hits), lambda: (
        f"{r['symbol']}: {len(hits)} event(s) within {r['days']} days — {hits[0].get('purpose') or hits[0].get('event') or ''}".strip(" —"),
        {"events": hits[:5]}, d.get("prov") or {}))


CHECKS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any], Any], Check]] = {
    "level_cross": _level_cross, "oi_wall_cross": _oi_wall_cross, "max_pain_distance": _max_pain_distance,
    "iv_change": _iv_change, "pcr_cross": _pcr_cross, "fii_flip": _fii_flip,
    "futures_buildup_change": _futures_buildup_change, "ledger_event": _ledger_event,
    "new_recommendation": _new_recommendation, "expiry_pin": _expiry_pin, "event_upcoming": _event_upcoming,
}


def evaluate_all(inputs: Any = None) -> List[Dict[str, Any]]:
    """Evaluate every active rule once; persist new state and fired alerts. Returns the alerts fired now."""
    inp = inputs or LiveInputs()
    out: List[Dict[str, Any]] = []
    with _eval_lock:
        for rule in [r for r in list_rules() if r["active"]]:
            st = rule.pop("state")
            try:
                new_st, hit = CHECKS[rule["type"]](rule, st, inp)
            except Exception as exc:
                logger.info("alert %s (%s) skipped: %s", rule["id"], rule["type"], exc)
                continue
            with _lock, _db() as con:
                con.execute("UPDATE alert_rules SET state=? WHERE id=?", (json.dumps(new_st, default=str), rule["id"]))
                if hit:
                    msg, value, prov = hit
                    ts = time.time()
                    cur = con.execute("INSERT INTO alert_fired (rule_id, ts, type, message, value, prov) VALUES (?,?,?,?,?,?)",
                                      (rule["id"], ts, rule["type"], msg, json.dumps(value, default=str), json.dumps(prov, default=str)))
                    a = {"id": cur.lastrowid, "rule_id": rule["id"], "ts": ts, "type": rule["type"], "message": msg,
                         "value": value, "prov": prov, "acked": False}
                    _RECENT.append(a)
                    out.append(a)
    return out
