"""Institutional view per trading symbol: CFTC positioning, macro drivers and volatility regime for forex /
gold / crypto (jarvis/markets/data/cftc.py, data/macro.py); Indian symbols delegate to inst.py.

    view(symbol)               one symbol (engine names with broker suffixes are canonicalised)
    all_views()                every engine symbol + NIFTY / BANKNIFTY
    adverse_flags(symbol, side) threats to a BUY / SELL, for the devil's advocate (not wired here)
    daily_job()                idempotent; refreshes CFTC COT when a new weekly report can exist (Friday
                               15:30 ET release; on Fri/Sat, or whenever the stored week is > 10 days old) and
                               rebuilds the macro views (Yahoo daily closes, FRED DFII10, Deribit DVOL).
                               Call once a day; the recorder wiring is done elsewhere.

Everything here is context unless tools/markets_model_validation.py published the matching walk-forward
test under "institutional_global" in config/markets_models.json; otherwise it is labelled
"context · not validated".
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .data import cftc, macro
from .data.models import unavailable

logger = logging.getLogger(__name__)
ENGINE_SYMBOLS = ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCAD", "BTCUSD", "ETHUSD", "SOLUSD")
INDIA_SYMBOLS = ("NIFTY", "BANKNIFTY")
CORR_MIN = 0.3   # |60-day correlation| below this: the driver is not treated as relevant to the symbol
NOT_VALIDATED = "context · not validated"
_all_cache: Dict[str, Any] = {}


def canonical(symbol: str) -> str:
    s = (symbol or "").upper().strip()
    if s in macro.SYMBOL_TICKERS:
        return s
    try:
        from jarvis.data import symbol_registry as sr
        if sr.is_registered(s):
            return sr.resolve(s).canonical.upper()
    except Exception:
        pass
    return next((k for k in macro.SYMBOL_TICKERS if s.startswith(k)), s)  # broker suffixes like "USDJPY.m"


def validation() -> Dict[str, Any]:
    from .signals import direction
    reg = (direction.registry() or {}).get("institutional_global") or {}
    out = {}
    for key, rec in reg.items():
        if isinstance(rec, dict) and "published" in rec:
            out[key] = {"published": bool(rec["published"]), "reason": rec.get("reason")}
    return out


def _label(keys: List[str], val: Dict[str, Any]) -> str:
    ok = [k for k in keys if (val.get(k) or {}).get("published")]
    return f"validated: {', '.join(ok)}" if ok else NOT_VALIDATED


def _usable(block: Optional[Dict[str, Any]]) -> bool:
    return bool(block) and (block.get("prov") or {}).get("kind") not in (None, "unavailable")


def view(symbol: str) -> Dict[str, Any]:
    sym = canonical(symbol)
    if sym not in macro.SYMBOL_TICKERS:
        return _india(sym)
    cot = cftc.positioning(sym)
    snap = macro.snapshot()
    drv = macro.drivers(sym)
    idx = (cot.get("for_symbol") or {}).get("cot_index_3y")
    extreme = None if idx is None else "crowded long" if idx > cftc.EXTREME_HI else "crowded short" if idx < cftc.EXTREME_LO else None
    keys = ["cot_extremes"] + ([f"dxy_trend_{sym}"] if sym in ("EURUSD", "XAUUSD") else []) + (["yields_gold"] if sym == "XAUUSD" else [])
    val = validation()
    mac = {k: snap[k] for k in ("dxy", "us10y", "us5y", "us13w", "vix", "regime")}
    mac["dxy_live"] = macro.live("DXY")
    if sym == "XAUUSD":
        mac["real10y"] = snap["real10y"]
        mac["gvz"] = snap["gvz"]
    base = drv.get("prov") if _usable(drv) else cot.get("prov") or unavailable("inst_global", "no source answered")
    prov = dict(base)
    prov["note"] = "summary: each block carries its own provenance (CFTC eod weekly, Yahoo daily closes, FRED, Deribit)"
    return {"symbol": sym, "market": "global", "cot": cot, "cot_extreme": extreme, "macro": mac, "drivers": drv,
            "validation": {k: val.get(k) or {"published": False, "reason": "not run yet (tools/markets_model_validation.py)"} for k in keys},
            "label": _label(keys, val), "prov": prov}


def _india(sym: str) -> Dict[str, Any]:
    """NSE institutional context (participant OI, futures, ban, events; delivery for stocks) via inst.py."""
    from . import inst
    from .adviser import fno
    kind = "index" if sym in inst.INDEX_UNDERLYINGS or sym in inst.TERM_SYMBOLS else "stock"
    block = fno._institutional(sym, kind, {"days_to_expiry": 30})
    if kind == "stock":
        try:
            d = inst.delivery(0.0, [sym])
            row = next((r for r in d.get("rows") or [] if r["symbol"] == sym), None)
            block["delivery"] = {**row, "prov": d["prov"]} if row else {"prov": d["prov"]}
        except Exception as exc:
            block["delivery_error"] = str(exc)
    provs = [v["prov"] for v in block.values() if isinstance(v, dict) and _usable(v)]
    prov = dict(provs[0]) if provs else unavailable("nse institutional", "no NSE institutional source answered").to_dict()
    prov["note"] = "summary: each block carries its own NSE provenance"
    return {"symbol": sym, "market": "IN", "kind": kind, **block, "label": NOT_VALIDATED if not block.get("validated") else "validated",
            "prov": prov}


def all_views(max_age: float = 300) -> Dict[str, Any]:
    hit = _all_cache.get("all")
    if hit and time.time() - hit[0] < max_age:
        return hit[1]

    def one(s):
        try:
            return view(s)
        except Exception as exc:
            logger.warning("inst_global %s: %s", s, exc)
            return {"symbol": s, "error": f"{type(exc).__name__}: {exc}", "prov": unavailable("inst_global", str(exc)).to_dict()}
    with ThreadPoolExecutor(max_workers=5) as ex:
        rows = list(ex.map(one, ENGINE_SYMBOLS + INDIA_SYMBOLS))
    ok = [r for r in rows if _usable(r)]
    prov = dict(ok[0]["prov"]) if ok else unavailable("inst_global", "no symbol answered").to_dict()
    prov["note"] = f"{len(ok)} of {len(rows)} symbols answered; each row carries its own provenance"
    out = {"rows": rows, "built_at": time.time(), "prov": prov}
    _all_cache["all"] = (time.time(), out)
    return out


# ---------------------------------------------------------------- threats for the devil's advocate

def _side(side: str) -> int:
    s = (side or "").upper()
    return 1 if s in ("BUY", "LONG") else -1 if s in ("SELL", "SHORT") else 0


def adverse_flags(symbol: str, side: str, v: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """[{flag, detail, value, prov}] of institutional/macro facts against a BUY or SELL. Pure over `view()`
    (pass `v` to reuse one). A missing source contributes nothing; never raises on missing data."""
    s = _side(side)
    if not s:
        return []
    try:
        v = v or view(symbol)
    except Exception as exc:
        logger.info("adverse_flags %s: %s", symbol, exc)
        return []
    word = "buying" if s > 0 else "selling"
    flags: List[Dict[str, Any]] = []
    if v.get("market") == "IN":
        if v.get("in_ban"):
            flags.append({"flag": "fno_ban", "detail": f"{v['symbol']} is in the NSE F&O ban list for {v.get('ban_trade_date')}",
                          "value": True, "prov": v["prov"]})
        if v.get("event_risk"):
            ev = v.get("events") or []
            flags.append({"flag": "event_risk", "detail": "; ".join(f"{e['purpose']} on {e['date']}" for e in ev)[:300],
                          "value": len(ev), "prov": v["prov"]})
        return flags
    cot = v.get("cot") or {}
    idx = (cot.get("for_symbol") or {}).get("cot_index_3y")
    if _usable(cot) and idx is not None:
        if s > 0 and idx > cftc.EXTREME_HI:
            flags.append({"flag": "cot_extreme_against", "value": idx, "prov": cot["prov"],
                          "detail": f"speculators at the {idx:.0f}th pct of their 3-year net-long range for {v['symbol']} "
                                    f"(CFTC {cot['contract']}, {cot['report_date']}); you're {word} into a crowded long"})
        elif s < 0 and idx < cftc.EXTREME_LO:
            flags.append({"flag": "cot_extreme_against", "value": idx, "prov": cot["prov"],
                          "detail": f"speculators at the {idx:.0f}th pct of their 3-year range for {v['symbol']} (crowded short; "
                                    f"CFTC {cot['contract']}, {cot['report_date']}); you're {word} into it"})
    mac, drv = v.get("macro") or {}, v.get("drivers") or {}
    reg = mac.get("regime") or {}
    corr = drv.get("correlation_60d") or {}
    if _usable(reg) and _usable(drv):
        trend = {"dollar strengthening": 1, "dollar weakening": -1}.get(reg.get("dollar"))
        c = corr.get("dxy")
        if trend and c is not None and abs(c) >= CORR_MIN and (1 if c > 0 else -1) * trend == -s:
            flags.append({"flag": "dollar_trend_against", "value": reg.get("dxy_chg_20d_pct"), "prov": reg["prov"],
                          "detail": f"{reg['dollar']} (DXY {reg['dxy_chg_20d_pct']:+.2f}% over 20d) and {v['symbol']} moves "
                                    f"{'with' if c > 0 else 'against'} the dollar (60d corr {c:+.2f}); you're {word}"})
        ytrend = {"yields rising": 1, "yields falling": -1}.get(reg.get("yields"))
        cy = corr.get("us10y_change")
        gold = v["symbol"] == "XAUUSD"
        if ytrend and ((gold and ytrend == s) or (not gold and cy is not None and abs(cy) >= CORR_MIN and (1 if cy > 0 else -1) * ytrend == -s)):
            flags.append({"flag": "yields_against", "value": reg.get("us10y_chg_20d_pts"), "prov": mac["us10y"]["prov"],
                          "detail": f"{reg['yields']} (10y {reg['us10y_chg_20d_pts']:+.2f} pts over 20d) against a "
                                    f"{v['symbol']} {'long' if s > 0 else 'short'} (60d corr to yield changes {cy if cy is not None else 'n/a'})"})
        rtrend = {"yields rising": 1, "yields falling": -1}.get(reg.get("real_yields"))
        if gold and rtrend == s and _usable(mac.get("real10y")):
            flags.append({"flag": "real_yields_against", "value": reg.get("real10y_chg_20d_pts"), "prov": mac["real10y"]["prov"],
                          "detail": f"10y TIPS real yield {reg['real_yields'].split()[-1]} ({reg['real10y_chg_20d_pts']:+.2f} pts over 20d) "
                                    f"against a gold {'long' if s > 0 else 'short'}"})
    vol = drv.get("volatility") or {}
    if _usable(drv) and vol.get("regime") == "spike":
        flags.append({"flag": "volatility_spike", "value": vol.get("realised_pctl_1y"), "prov": drv["prov"],
                      "detail": f"realised 20d vol {vol.get('realised_20d_pct')}% at the {vol.get('realised_pctl_1y')}th 1-year pct"
                                + (f"; implied {vol['implied']['value']} at the {vol['implied']['pctl_1y']}th pct" if vol.get("implied", {}).get("value") is not None else "")})
    return flags


# ---------------------------------------------------------------- daily job

def daily_job(now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    out: Dict[str, Any] = {}
    last = cftc.latest_stored()
    stale = not last or (now.date() - datetime.fromisoformat(last).date()).days > 10
    if now.weekday() in (4, 5) or stale:
        try:
            out["cot"] = cftc.refresh()
        except Exception as exc:
            out["cot"] = {"error": f"{type(exc).__name__}: {exc}"}
    macro._cache.clear()
    _all_cache.clear()
    try:
        rows = all_views()["rows"]
        out["views"] = {"symbols": len(rows), "ok": sum(1 for r in rows if _usable(r))}
    except Exception as exc:
        out["views"] = {"error": f"{type(exc).__name__}: {exc}"}
    return out
