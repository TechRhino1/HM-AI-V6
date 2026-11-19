"""The one entry point for market data. Tries sources in accuracy order, labels which one answered,
and returns `unavailable` (never a substitute value) when none does.

    quotes:  Yahoo (real time, graded by exchange timestamp) → TradingView (15-min delayed) → unavailable
    chains:  NSE (nseindia.in → nseindia.com); SENSEX/BANKEX from BSE
    VIX, indices, FII/DII, OI spurts: NSE
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from . import bse, nse, tradingview, yahoo
from .models import OptionChain, Provenance, Quote, unavailable
from .nse import SourceError

logger = logging.getLogger(__name__)
BSE_CHAINS = {"SENSEX", "BANKEX"}
_NY = ZoneInfo("America/New_York")  # DST-aware; Windows needs the tzdata package
US_HOLIDAYS_URL = "https://www.nasdaqtrader.com/trader.aspx?id=calendar"
_us_hol: Dict[str, Any] = {}


def us_holidays() -> Dict[str, Any]:
    """US equity-market closures and early closes from Nasdaq Trader's published calendar; cached 24 h.
    Returns {"closed": {iso: name}, "early": {iso: "1:00 p.m."}}; raises SourceError when unreachable."""
    if _us_hol and time.time() - _us_hol["at"] < 86400:
        return _us_hol["v"]
    try:
        from curl_cffi import requests as cffi
        html = cffi.get(US_HOLIDAYS_URL, impersonate="chrome", timeout=15).text
    except Exception as exc:
        raise SourceError(f"nasdaqtrader calendar: {type(exc).__name__}") from exc
    v = parse_us_holidays(html)
    if not v["closed"]:
        raise SourceError("nasdaqtrader calendar: no holidays parsed")
    _us_hol.update(at=time.time(), v=v)
    return v


def parse_us_holidays(html: str) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {"closed": {}, "early": {}}
    for d, name, status in re.findall(r"<td>\s*([A-Z][a-z]+ \d{1,2}, \d{4})\s*</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>", html):
        iso = datetime.strptime(d, "%B %d, %Y").date().isoformat()
        if status.strip().lower() == "closed":
            out["closed"][iso] = name.strip()
        else:
            out["early"][iso] = status.strip()
    return out


def session(market: str) -> Dict[str, Any]:
    """Is the market open right now? India asks NSE (holidays included); US uses exchange hours."""
    if market == "IN":
        try:
            return nse.market_status()
        except SourceError as exc:
            now = datetime.now(nse.IST)
            in_hours = now.weekday() < 5 and (9, 15) <= (now.hour, now.minute) < (15, 30)
            src = "clock (NSE status unavailable; holidays not known)"
            try:
                hol = nse.trading_holidays()
                src = "clock + NSE holiday master (NSE status unavailable)"
                if now.date().isoformat() in hol["days"]:
                    in_hours = False
                    src += f"; holiday: {hol['days'][now.date().isoformat()]}"
            except SourceError:
                pass
            return {"open": in_hours, "status": "unknown", "source": src, "message": str(exc)}
    now = datetime.now(_NY)
    close = (16, 0)
    src = "clock (NYSE hours, holidays not known)"
    try:
        hol = us_holidays()
        src = "clock (NYSE hours) + nasdaqtrader holiday calendar"
        iso = now.date().isoformat()
        if iso in hol["closed"]:
            return {"open": False, "status": "Closed", "source": f"{src}; holiday: {hol['closed'][iso]}"}
        if iso in hol["early"]:
            close = (13, 0)
            src += f"; early close {hol['early'][iso]}"
    except SourceError:
        pass
    open_ = now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) < close
    return {"open": open_, "status": "Open" if open_ else "Closed", "source": src}


NSE_INDEX_NAMES = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "FINNIFTY": "NIFTY FINANCIAL SERVICES",
                   "MIDCPNIFTY": "NIFTY MIDCAP SELECT", "INDIAVIX": "INDIA VIX"}


def _exchange_index_quote(symbol: str, is_open: bool) -> Optional[Dict[str, Any]]:
    """Indices straight from the exchange that computes them (NSE allIndices, BSE for SENSEX/BANKEX)."""
    s = symbol.upper()
    try:
        if s in NSE_INDEX_NAMES:
            ai = nse.all_indices()
            r = next((x for x in ai["rows"] if x.get("index") == NSE_INDEX_NAMES[s]), None)
            if not r:
                return None
            prov = nse.grade(ai["source"], ai["as_of"], is_open, fresh_sec=120)
            return Quote(symbol=s, price=float(r["last"]), change_pct=r.get("percentChange"), prev_close=r.get("previousClose"),
                         day_high=r.get("high"), day_low=r.get("low"), volume=None, currency="INR", prov=prov).to_dict()
        if s in bse.SCRIP:
            spot = bse.expiries(s)["spot"]
            if spot > 0:
                prov = Provenance(source="bse:ddlExpiry_IV@api.bseindia.com", kind="live" if is_open else "close",
                                  as_of=time.time(), note="BSE payload has no timestamp; as_of is our fetch time")
                return Quote(symbol=s, price=spot, change_pct=None, prev_close=None, day_high=None, day_low=None,
                             volume=None, currency="INR", prov=prov).to_dict()
    except SourceError:
        return None
    return None


def quote(symbol: str, market: str) -> Dict[str, Any]:
    is_open = session(market)["open"]
    if market == "IN":
        q = _exchange_index_quote(symbol, is_open)
        if q:
            return q
    try:
        q = yahoo.quote(symbol, market, is_open).to_dict()
        if q["prov"]["kind"] in ("live", "close"):
            return q
        stale = q  # keep as a last resort, labelled stale
    except SourceError as exc:
        logger.info("quote %s: yahoo failed (%s), trying TradingView", symbol, exc)
        stale = None
    if stale:
        return stale
    tv_id = tv_ticker(symbol, market)
    try:
        v = tradingview.scan([tv_id], market).get(tv_id)
        if v and v.get("close"):
            return Quote(symbol=symbol.upper(), price=float(v["close"]), change_pct=v.get("change"), prev_close=None,
                         day_high=v.get("high"), day_low=v.get("low"), volume=v.get("volume"),
                         currency=v.get("currency") or "", prov=Provenance(**{k: v["prov"][k] for k in ("source", "kind", "as_of", "fetched_at", "delay_sec", "note")})).to_dict()
    except SourceError:
        pass
    return {"symbol": symbol.upper(), "price": None, "prov": unavailable("yahoo,tradingview", "no source answered").to_dict()}


def tv_ticker(symbol: str, market: str) -> str:
    s = symbol.upper()
    special = {"NIFTY": "NSE:NIFTY", "BANKNIFTY": "NSE:BANKNIFTY", "FINNIFTY": "NSE:CNXFINANCE", "MIDCPNIFTY": "NSE:NIFTY_MID_SELECT",
               "SENSEX": "BSE:SENSEX", "BANKEX": "BSE:BANKEX", "INDIAVIX": "NSE:INDIAVIX"}
    if s in special:
        return special[s]
    return f"NSE:{s}" if market == "IN" else s if ":" in s else f"NASDAQ:{s}"


def chain(symbol: str, expiry: Optional[str] = None) -> OptionChain:
    is_open = session("IN")["open"]
    if symbol.upper() in BSE_CHAINS:
        return bse.option_chain(symbol, expiry, is_open)
    return nse.option_chain(symbol, expiry, is_open)


def vix() -> Dict[str, Any]:
    """India VIX from NSE (live), with its real 52-week range for regime context."""
    try:
        ai = nse.all_indices()
        row = next(r for r in ai["rows"] if r.get("index") == "INDIA VIX")
        is_open = session("IN")["open"]
        prov = nse.grade(ai["source"], ai["as_of"], is_open, fresh_sec=120)
        lo, hi, last = float(row["yearLow"]), float(row["yearHigh"]), float(row["last"])
        return {"value": last, "change_pct": row.get("percentChange"), "year_low": lo, "year_high": hi,
                "range_position": round((last - lo) / (hi - lo), 3) if hi > lo else None, "prov": prov.to_dict()}
    except (SourceError, StopIteration, KeyError, ValueError) as exc:
        return {"value": None, "prov": unavailable("nse:allIndices", str(exc)).to_dict()}


def indices(names: Optional[List[str]] = None) -> Dict[str, Any]:
    want = names or ["NIFTY 50", "NIFTY BANK", "NIFTY FINANCIAL SERVICES", "NIFTY MIDCAP SELECT", "INDIA VIX",
                     "NIFTY IT", "NIFTY AUTO", "NIFTY PHARMA", "NIFTY FMCG", "NIFTY METAL", "NIFTY ENERGY", "NIFTY REALTY", "NIFTY PSU BANK"]
    try:
        ai = nse.all_indices()
    except SourceError as exc:
        return {"rows": [], "prov": unavailable("nse:allIndices", str(exc)).to_dict()}
    is_open = session("IN")["open"]
    prov = nse.grade(ai["source"], ai["as_of"], is_open, fresh_sec=120).to_dict()
    rows = [{"name": r["index"], "last": r.get("last"), "change_pct": r.get("percentChange"), "open": r.get("open"),
             "high": r.get("high"), "low": r.get("low"), "prev_close": r.get("previousClose"),
             "advances": r.get("advances"), "declines": r.get("declines"), "year_high": r.get("yearHigh"), "year_low": r.get("yearLow")}
            for r in ai["rows"] if r.get("index") in want]
    return {"rows": rows, "prov": prov}


def fii_dii() -> Dict[str, Any]:
    try:
        d = nse.fii_dii()
        d["prov"] = Provenance(source=d.pop("source"), kind="eod", as_of=d.pop("as_of"),
                               note="NSE provisional figures, published after the close").to_dict()
        return d
    except SourceError as exc:
        return {"rows": [], "prov": unavailable("nse:fiidiiTradeReact", str(exc)).to_dict()}


def oi_spurts() -> Dict[str, Any]:
    try:
        d = nse.oi_spurts()
        is_open = session("IN")["open"]
        d["prov"] = Provenance(source=d.pop("source"), kind="live" if is_open else "close", as_of=time.time(),
                               note=f"NSE timestamp {d.pop('as_of_text', '')}").to_dict()
        return d
    except SourceError as exc:
        return {"rows": [], "prov": unavailable("nse:oi-spurts", str(exc)).to_dict()}
