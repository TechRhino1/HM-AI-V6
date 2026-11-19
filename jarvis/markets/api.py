"""/api/markets/* — market data and adviser endpoints for the React Markets sections.

Every response passes `require_provenance`: a payload that carries market values
without saying where they came from is refused with 500 rather than served.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any, Callable, Dict, List

from .data import feeds, nse, yahoo
from .data.nse import SourceError

logger = logging.getLogger(__name__)
_HANDLERS: Dict[str, Callable[[Dict[str, List[str]]], Any]] = {}


def route(path: str):
    def deco(fn):
        _HANDLERS[path] = fn
        return fn
    return deco


def q1(query: Dict[str, List[str]], key: str, default: str = "") -> str:
    return (query.get(key) or [default])[0].strip()


class ProvenanceMissing(RuntimeError):
    pass


def require_provenance(obj: Any, where: str = "$") -> None:
    """Every dict that carries a price-like field must have `prov` itself or inherit it from an ancestor."""
    _check(obj, where, inherited=False)


_PRICE_KEYS = {"price", "spot", "ltp", "last", "close", "value", "net_cr", "iv"}


def _check(obj: Any, where: str, inherited: bool) -> None:
    if isinstance(obj, dict):
        has = inherited or "prov" in obj
        if not has and _PRICE_KEYS & set(obj) and any(isinstance(obj[k], (int, float)) for k in _PRICE_KEYS & set(obj)):
            raise ProvenanceMissing(f"{where} has market values but no provenance")
        for k, v in obj.items():
            if k != "prov":
                _check(v, f"{where}.{k}", has)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _check(v, f"{where}[{i}]", inherited)


# ---------------------------------------------------------------- data routes

@route("/api/markets/status")
def _status(q):
    """Which sources answer right now, how fast, and what each is labelled (live / delayed / unavailable)."""
    checks = {
        "nse (nseindia.in / .com)": lambda: nse.market_status()["source"],
        "bse (api.bseindia.com)": lambda: f"SENSEX spot {feeds.bse.expiries('SENSEX')['spot']}",
        "yahoo (quotes, bars)": lambda: f"{yahoo.quote('NIFTY', 'IN', True).prov.kind} NIFTY",
        "tradingview (delayed 15 min)": lambda: f"{len(feeds.tradingview.scan(['NSE:RELIANCE'], 'IN'))} row",
    }
    out = []
    for name, fn in checks.items():
        t = time.time()
        try:
            detail = fn()
            out.append({"source": name, "ok": True, "detail": detail, "latency_ms": round((time.time() - t) * 1000)})
        except Exception as exc:
            out.append({"source": name, "ok": False, "detail": str(exc)[:200], "latency_ms": round((time.time() - t) * 1000)})
    from .data import store
    rec = store.RECORDER
    return {"sessions": {"IN": feeds.session("IN"), "US": feeds.session("US")}, "sources": out,
            "recorder": {"running": bool(rec and rec.is_alive()), "last": rec.last if rec else {}}}


@route("/api/markets/quote")
def _quote(q):
    syms = [s for s in q1(q, "symbols", q1(q, "symbol")).split(",") if s]
    market = q1(q, "market", "IN").upper()
    return {"quotes": [feeds.quote(s, market) for s in syms[:40]]}


@route("/api/markets/bars")
def _bars(q):
    try:
        return yahoo.bars(q1(q, "symbol"), q1(q, "market", "IN").upper(), q1(q, "interval", "1d"), q1(q, "range", "1y"))
    except SourceError as exc:
        return {"bars": [], "prov": feeds.unavailable("yahoo", str(exc)).to_dict()}


@route("/api/markets/chain")
def _chain(q):
    try:
        c = feeds.chain(q1(q, "symbol", "NIFTY"), q1(q, "expiry") or None)
        d = asdict(c)
        d["prov"] = c.prov.to_dict()
        return d
    except SourceError as exc:
        return {"symbol": q1(q, "symbol"), "rows": [], "prov": feeds.unavailable("nse/bse option chain", str(exc)).to_dict()}


@route("/api/markets/indices")
def _indices(q):
    return feeds.indices()


@route("/api/markets/vix")
def _vix(q):
    return feeds.vix()


@route("/api/markets/fii-dii")
def _fii(q):
    from .data import store
    d = feeds.fii_dii()
    d["history"] = store.fii_dii_history()
    return d


@route("/api/markets/oi-spurts")
def _spurts(q):
    return feeds.oi_spurts()


# ---------------------------------------------------------------- F&O routes

@route("/api/markets/fno/analytics")
def _fno_analytics(q):
    from .options import chain_analytics
    try:
        c = feeds.chain(q1(q, "symbol", "NIFTY"), q1(q, "expiry") or None)
    except SourceError as exc:
        return {"symbol": q1(q, "symbol"), "strikes": [], "prov": feeds.unavailable("option chain", str(exc)).to_dict()}
    an = chain_analytics.analyse(c)
    an["expiries"] = c.expiries
    an["prov"] = c.prov.to_dict()
    return an


@route("/api/markets/fno/advise")
def _fno_advise(q):
    from .adviser import fno
    return fno.advise(q1(q, "symbol", "NIFTY"), q1(q, "expiry") or None)


@route("/api/markets/fno/scan")
def _fno_scan(q):
    from .adviser import fno
    syms = [s for s in q1(q, "symbols").split(",") if s] or None
    out = fno.scan(syms)
    out["prov"] = {"source": "adviser over live chains", "kind": "live", "note": "each row carries its own chain provenance"}
    return out


@route("/api/markets/fno/evaluate")
def _fno_evaluate(q):
    """Strategy builder: evaluate user legs `legs=strike:CE:BUY:1,strike:PE:SELL:1` on the live chain."""
    from .options import chain_analytics, strategies, volatility
    sym = q1(q, "symbol", "NIFTY")
    c = feeds.chain(sym, q1(q, "expiry") or None)
    an = chain_analytics.analyse(c)
    rows = {r["strike"]: r for r in an["strikes"]}
    legs = []
    for part in [p for p in q1(q, "legs").split(",") if p]:
        k, kind, side, lots = part.split(":")
        row = rows.get(float(k))
        lg = strategies.leg(row, kind.upper(), side.upper(), int(lots)) if row else None
        if lg is None:
            return {"error": f"no tradable quote for {k} {kind} {side}", "prov": c.prov.to_dict()}
        legs.append(lg)
    if not legs or not an["atm_iv"]:
        return {"error": "need at least one leg and a live ATM IV", "prov": c.prov.to_dict()}
    vol = volatility.regime(sym, an["atm_iv"])
    res = strategies.evaluate(legs, an["forward"], an["years_to_expiry"], an["atm_iv"] / 100, vol.get("forecast_vol"), an["lot_size"] or 1)
    res["prov"] = c.prov.to_dict()
    return res


@route("/api/markets/fno/premium-forecast")
def _fno_premium(q):
    from .options import chain_analytics, premium_forecast
    c = feeds.chain(q1(q, "symbol", "NIFTY"), q1(q, "expiry") or None)
    an = chain_analytics.analyse(c)
    try:
        k = float(q1(q, "strike"))
    except ValueError:
        return {"error": "strike is required (e.g. strike=25300&type=CE)", "prov": c.prov.to_dict()}
    kind = q1(q, "type", "CE").upper()
    row = next((r for r in an["strikes"] if r["strike"] == k), None)
    side = row and row.get("call" if kind == "CE" else "put")
    if not side or not side.get("iv"):
        return {"error": f"no live IV for {k:g} {kind}", "prov": c.prov.to_dict()}
    out = premium_forecast.forecast(an["forward"], k, kind == "CE", side["iv"], an["years_to_expiry"],
                                    float(q1(q, "horizon_days", "1")), side["mid"])
    out["prov"] = c.prov.to_dict()
    return out


@route("/api/markets/ledger")
def _ledger(q):
    from . import ledger
    out = ledger.summary()
    out["prov"] = {"source": "markets.db ledger", "kind": "live", "note": "marked to live chain mids; settled on real closes"}
    return out


def handle_request(path: str, query: Dict[str, List[str]], handler: Any) -> bool:
    fn = _HANDLERS.get(path)
    if fn is None:
        return False
    try:
        payload = fn(query)
        require_provenance(payload)
        handler._send_json(payload)
    except ProvenanceMissing as exc:
        logger.error("refused to serve %s: %s", path, exc)
        handler._send_json({"status": "ERROR", "error": f"provenance missing: {exc}"}, status_code=500)
    except Exception as exc:
        logger.exception("markets %s failed", path)
        handler._send_json({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, status_code=500)
    return True


# ---------------------------------------------------------------- equities routes

def _f(q, key: str):
    """Optional numeric query param; a malformed or non-positive value is treated as absent, not a 500."""
    try:
        v = float(q1(q, key))
    except ValueError:
        return None
    return v if v > 0 and v == v else None


@route("/api/markets/equities/scan")
def _eq_scan(q):
    from .equities import service
    return service.scan(q1(q, "market", "IN").upper())


@route("/api/markets/equities/detail")
def _eq_detail(q):
    from .equities import service
    return service.detail(q1(q, "symbol"), q1(q, "market", "IN").upper(), equity=_f(q, "equity"),
                          risk_pct=_f(q, "risk_pct"), atr_mult=_f(q, "atr_mult") or 2.0)


@route("/api/markets/equities/news")
def _eq_news(q):
    from .equities import service
    return service.news(q1(q, "symbol"), q1(q, "market", "IN").upper())


@route("/api/markets/equities/compare")
def _eq_compare(q):
    from .equities import service
    return service.compare(q1(q, "a"), q1(q, "b"), q1(q, "market", "IN").upper())


# ---------------------------------------------------------------- institutional routes (jarvis/markets/inst.py)

def _int(q, key: str, default: int, hi: int) -> int:
    try:
        return max(1, min(hi, int(q1(q, key, str(default)))))
    except ValueError:
        return default


@route("/api/markets/inst/participants")
def _inst_participants(q):
    from . import inst
    return inst.participants(_int(q, "days", 60, 2000))


@route("/api/markets/inst/futures")
def _inst_futures(q):
    from . import inst
    return inst.futures("stock" if q1(q, "scope", "index").lower() == "stock" else "index")


@route("/api/markets/inst/deals")
def _inst_deals(q):
    from . import inst
    return inst.deals()


@route("/api/markets/inst/events")
def _inst_events(q):
    from . import inst
    return inst.events(q1(q, "symbol"))


@route("/api/markets/inst/announcements")
def _inst_announcements(q):
    from . import inst
    return inst.announcements(q1(q, "symbol"), _int(q, "limit", 30, 200))


@route("/api/markets/inst/delivery")
def _inst_delivery(q):
    from . import inst
    syms = [s.strip().upper() for s in q1(q, "symbols").split(",") if s.strip()] or None
    return inst.delivery(_f(q, "min_pct") or 0.0, syms)


@route("/api/markets/inst/52week")
def _inst_52w(q):
    from . import inst
    return inst.week52()


@route("/api/markets/inst/most-active")
def _inst_active(q):
    from . import inst
    return inst.most_active(_int(q, "limit", 20, 50))


@route("/api/markets/inst/ban")
def _inst_ban(q):
    from . import inst
    return inst.ban()


@route("/api/markets/inst/term-structure")
def _inst_term(q):
    from . import inst
    syms = [s.strip().upper() for s in q1(q, "symbols").split(",") if s.strip()] or None
    return inst.term_structure(syms)


# ---------------------------------------------------------------- global institutional (jarvis/markets/inst_global.py)

@route("/api/markets/inst/global")
def _inst_global(q):
    """Institutional view for one symbol: CFTC COT positioning, macro drivers (DXY, yields, real yield), volatility regime; Indian symbols use NSE data."""
    from . import inst_global
    return inst_global.view(q1(q, "symbol", "XAUUSD"))


@route("/api/markets/inst/global/all")
def _inst_global_all(q):
    """Institutional view for every trading-engine symbol plus NIFTY and BANKNIFTY (COT, macro drivers, vol regime)."""
    from . import inst_global
    return inst_global.all_views()


@route("/api/markets/inst/fno-universe")
def _inst_fno_universe(q):
    """Every NSE F&O stock, precomputed daily: futures build-up, basis, rollover (expiry week), delivery accumulation, upcoming results, ban."""
    from . import inst
    out = inst.fno_universe()
    sym = q1(q, "symbol").upper()
    return {**out, "rows": [r for r in out.get("rows", []) if r["symbol"] == sym]} if sym else out


# ---------------------------------------------------------------- chart intelligence (jarvis/markets/levels.py)

def _chart_args(q):
    market = q1(q, "market", "FX").upper()
    if market not in ("FX", "IN", "US"):
        raise ValueError("market must be FX, IN or US")
    return q1(q, "symbol", "XAUUSD"), market, q1(q, "interval", "H1").upper()


@route("/api/markets/chart/levels")
def _chart_levels(q):
    """Support/resistance zones from real bars (swings, volume profile, prior day/week, floor pivots, VWAP, OI walls) with measured hold rates."""
    from . import levels
    return levels.levels(*_chart_args(q))


@route("/api/markets/chart/patterns")
def _chart_patterns(q):
    """Breakouts, false breakouts, liquidity sweeps, BOS/CHoCH with each pattern's prior forward-return record on this symbol."""
    from . import levels
    return levels.patterns(*_chart_args(q))


@route("/api/markets/chart/signal")
def _chart_signal(q):
    """The engine's live decision, gates, devil's-advocate breakdown, adverse institutional flags and open positions for one symbol."""
    from . import levels
    return levels.signal_overlay(q1(q, "symbol", "XAUUSD"))


@route("/api/markets/chart/read")
def _chart_read(q):
    """Five-bullet AI read of the chart grounded only on levels, patterns, the engine signal and the quote (template when AI is unavailable)."""
    from . import levels
    sym, market, interval = _chart_args(q)
    return levels._cached(("read", levels.canonical(sym), market, interval), 60, lambda: levels.chart_read(sym, market, interval))


# ---------------------------------------------------------------- overview (jarvis/markets/overview.py)

def _since(q):
    """`since` as epoch seconds (ms accepted); absent or malformed → start of today (00:00 IST)."""
    from . import overview
    try:
        v = overview.epoch(float(q1(q, "since")))
    except ValueError:
        v = None
    return v if v and v > 0 else overview.day_start()


@route("/api/markets/overview/timeline")
def _ov_timeline(q):
    """Today's events newest first (window from 00:00 IST by default): trades opened/closed, fired alerts, AI briefs, engine verdict/gate changes, dispatch outcomes, adviser recommendations. Each has ts, kind, symbol, title, detail, link, prov."""
    from . import overview
    return overview.timeline(_since(q), _int(q, "limit", 200, 1000))


@route("/api/markets/overview/changes")
def _ov_changes(q):
    """Fact sheet of what changed since an epoch time: equity/P&L, positions opened/closed, alerts fired, per-symbol engine gate changes, NIFTY/BANKNIFTY/VIX/S&P/DXY/US10Y moves, new recommendations and briefs."""
    from . import overview
    return overview.changes(_since(q), _f(q, "equity_then"))


@route("/api/markets/overview/changes/summary")
def _ov_summary(q):
    """3-5 bullet 'what changed since you last looked', written by the AI from the changes fact sheet only (every number checked against it), or a deterministic template when the AI is unavailable."""
    from . import levels, overview
    since = _since(q)
    eq = _f(q, "equity_then")
    return levels._cached(("ov_summary", int(since // 60), eq), 60, lambda: overview.summary(since, eq))


@route("/api/markets/overview/sparklines")
def _ov_sparklines(q):
    """Intraday closes for many symbols in one call: market FX = MT5 M15 (24 h), IN/US = Yahoo spark 5m (today). Unavailable symbols are listed."""
    from . import levels, overview
    syms = tuple(s.strip() for s in q1(q, "symbols").split(",") if s.strip())
    market = q1(q, "market", "FX").upper()
    return levels._cached(("ov_spark", market, syms), 60, lambda: overview.sparklines(list(syms), market))
