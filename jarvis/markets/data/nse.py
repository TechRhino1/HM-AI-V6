"""NSE public data over both official hosts (www.nseindia.in, www.nseindia.com).

NSE's API needs a browser-like TLS fingerprint and a cookie from a page visit, so
requests go through a curl_cffi Chrome-impersonating session that is warmed once
per host and re-warmed on 401/403. Each endpoint tries the hosts in order and
records which one answered. Nothing here invents a value: a failed fetch raises
`SourceError`, and callers report the field as unavailable.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import reduce
from math import gcd
from typing import Any, Dict, List, Optional, Tuple

from .models import ChainRow, OptionChain, OptionSide, grade

logger = logging.getLogger(__name__)

HOSTS = ("https://www.nseindia.in", "https://www.nseindia.com")
# Report archives (CSV/ZIP), each served to a session warmed on its sibling www host.
ARCHIVE_HOSTS = (("https://nsearchives.nseindia.in", "https://www.nseindia.in"),
                 ("https://nsearchives.nseindia.com", "https://www.nseindia.com"))
IST = timezone(timedelta(hours=5, minutes=30))
INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
_TIMEOUT = 12


class SourceError(RuntimeError):
    pass


class NotPublished(SourceError):
    """The archive answered 404: no file for that day (weekend, holiday, or not published yet)."""


class _Client:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, Any] = {}
        self._cache: Dict[str, Tuple[float, Any, str]] = {}

    def _session(self, host: str, rewarm: bool = False):
        with self._lock:
            s = self._sessions.get(host)
            if s is None or rewarm:
                from curl_cffi import requests as cffi
                s = cffi.Session(impersonate="chrome")
                s.get(host + "/option-chain", timeout=_TIMEOUT)
                self._sessions[host] = s
            return s

    def get_json(self, path: str, ttl: float, referer: str = "/option-chain") -> Tuple[Any, str]:
        """GET `path` from the first host that answers with JSON. Returns (payload, host)."""
        hit = self._cache.get(path)
        if hit and time.time() - hit[0] < ttl:
            return hit[1], hit[2]
        errors = []
        for host in HOSTS:
            for attempt in (0, 1):
                try:
                    s = self._session(host, rewarm=attempt == 1)
                    r = s.get(host + path, timeout=_TIMEOUT, headers={"Referer": host + referer})
                    if r.status_code in (401, 403) and attempt == 0:
                        continue
                    if r.status_code != 200:
                        errors.append(f"{host} {r.status_code}")
                        break
                    data = r.json()
                    self._cache[path] = (time.time(), data, host)
                    return data, host
                except Exception as exc:  # network, TLS, JSON
                    errors.append(f"{host} {type(exc).__name__}")
                    if attempt == 1:
                        break
        raise SourceError(f"NSE {path}: " + "; ".join(errors))

    def get_archive(self, path: str, ttl: float = 0) -> Tuple[bytes, str]:
        """GET a report file from the NSE archives. A 404 means the file does not exist (raises NotPublished)."""
        key = "archive:" + path
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1], hit[2]
        errors = []
        for arch, host in ARCHIVE_HOSTS:
            for attempt in (0, 1):
                try:
                    s = self._session(host, rewarm=attempt == 1)
                    r = s.get(arch + path, timeout=_TIMEOUT * 2, headers={"Referer": host + "/"})
                    if r.status_code in (401, 403) and attempt == 0:
                        continue
                    if r.status_code == 404:
                        raise NotPublished(f"NSE archive {path}: not published (404 at {arch})")
                    if r.status_code != 200:
                        errors.append(f"{arch} {r.status_code}")
                        break
                    if ttl:
                        self._cache[key] = (time.time(), r.content, arch)
                    return r.content, arch
                except NotPublished:
                    raise
                except Exception as exc:  # network, TLS
                    errors.append(f"{arch} {type(exc).__name__}")
                    if attempt == 1:
                        break
        raise SourceError(f"NSE archive {path}: " + "; ".join(errors))


CLIENT = _Client()


def _src(host: str, endpoint: str) -> str:
    return f"nse:{endpoint}@{host.split('//')[1]}"


def _ist_epoch(text: str, fmt: str) -> Optional[float]:
    try:
        return datetime.strptime(text.strip(), fmt).replace(tzinfo=IST).timestamp()
    except (ValueError, AttributeError):
        return None


def market_status() -> Dict[str, Any]:
    """Capital-market session state as NSE reports it (handles holidays and special sessions)."""
    data, host = CLIENT.get_json("/api/marketStatus", ttl=30, referer="/")
    cm = next((m for m in data.get("marketState", []) if m.get("market") == "Capital Market"), {})
    return {
        "open": str(cm.get("marketStatus", "")).lower() == "open",
        "status": cm.get("marketStatus"),
        "trade_date": cm.get("tradeDate"),
        "message": cm.get("marketStatusMessage"),
        "source": _src(host, "marketStatus"),
    }


def _side(d: Optional[Dict[str, Any]]) -> Optional[OptionSide]:
    if not d:
        return None
    iv = float(d.get("impliedVolatility") or 0.0)
    bid = float(d.get("buyPrice1") or 0.0)
    ask = float(d.get("sellPrice1") or 0.0)
    return OptionSide(
        ltp=float(d.get("lastPrice") or 0.0),
        bid=bid if bid > 0 else None,
        ask=ask if ask > 0 else None,
        bid_qty=int(d.get("buyQuantity1") or 0),
        ask_qty=int(d.get("sellQuantity1") or 0),
        oi=int(d.get("openInterest") or 0),
        oi_change=int(d.get("changeinOpenInterest") or 0),
        oi_change_pct=float(d.get("pchangeinOpenInterest") or 0.0),
        volume=int(d.get("totalTradedVolume") or 0),
        iv=iv if iv > 0 else None,
        change=float(d.get("change") or 0.0),
        change_pct=float(d.get("pChange") or 0.0),
    )


def _lot_from_book(rows: List[ChainRow]) -> Optional[int]:
    """Order-book quantities are whole lots, so their GCD across the chain is the lot size."""
    qty = [q for r in rows for side in (r.call, r.put) if side for q in (side.bid_qty, side.ask_qty) if q > 0]
    if len(qty) < 8:
        return None
    lot = reduce(gcd, qty)
    return lot if lot > 1 else None


def parse_chain(symbol: str, contract_info: Dict[str, Any], v3: Dict[str, Any], expiry: str, host: str,
                session_open: bool) -> OptionChain:
    rec = v3.get("records") or {}
    raw = (v3.get("filtered") or {}).get("data") or rec.get("data") or []
    rows = [ChainRow(strike=float(i.get("strikePrice") or 0.0), call=_side(i.get("CE")), put=_side(i.get("PE")))
            for i in raw if i.get("CE") or i.get("PE")]
    if not rows:
        raise SourceError(f"NSE chain {symbol} {expiry}: empty")
    rows.sort(key=lambda r: r.strike)
    spot = float(rec.get("underlyingValue") or 0.0)
    if spot <= 0:
        raise SourceError(f"NSE chain {symbol}: no underlying value")
    as_of = _ist_epoch(str(rec.get("timestamp") or ""), "%d-%b-%Y %H:%M:%S")
    # NSE republishes the chain about once a minute and its timestamp lags 40-80 s (measured
    # 2026-11-18); 150 s = two publication cycles, so only a genuinely stopped feed reads stale.
    prov = grade(_src(host, "option-chain-v3"), as_of, session_open, fresh_sec=150)
    return OptionChain(symbol=symbol, expiry=expiry, expiries=list(contract_info.get("expiryDates") or []),
                       spot=spot, rows=rows, lot_size=_lot_from_book(rows), prov=prov)


def option_chain(symbol: str, expiry: Optional[str] = None, session_open: bool = True) -> OptionChain:
    sym = symbol.upper().strip()
    info, _ = CLIENT.get_json(f"/api/option-chain-contract-info?symbol={sym}", ttl=600)
    expiries = info.get("expiryDates") or []
    if not expiries:
        raise SourceError(f"NSE {sym}: no expiries listed")
    exp = expiry if expiry in expiries else expiries[0]
    kind = "Indices" if sym in INDEX_SYMBOLS else "Equity"
    v3, host = CLIENT.get_json(f"/api/option-chain-v3?type={kind}&symbol={sym}&expiry={exp}", ttl=20)
    return parse_chain(sym, info, v3, exp, host, session_open)


def all_indices() -> Dict[str, Any]:
    data, host = CLIENT.get_json("/api/allIndices", ttl=10, referer="/")
    as_of = _ist_epoch(str(data.get("timestamp") or ""), "%d-%b-%Y %H:%M")
    return {"rows": data.get("data") or [], "as_of": as_of, "source": _src(host, "allIndices")}


def fii_dii() -> Dict[str, Any]:
    """Provisional FII/FPI and DII cash-market activity, published by NSE once per trading day (₹ crore)."""
    data, host = CLIENT.get_json("/api/fiidiiTradeReact", ttl=900, referer="/")
    out: Dict[str, Any] = {"source": _src(host, "fiidiiTradeReact"), "rows": []}
    for row in data or []:
        out["rows"].append({
            "category": row.get("category"), "date": row.get("date"),
            "buy_cr": float(row.get("buyValue") or 0), "sell_cr": float(row.get("sellValue") or 0),
            "net_cr": float(row.get("netValue") or 0),
        })
    dates = {r["date"] for r in out["rows"]}
    out["as_of"] = _ist_epoch(next(iter(dates)), "%d-%b-%Y") if len(dates) == 1 else None
    return out


def oi_spurts() -> Dict[str, Any]:
    """Underlyings with the largest open-interest change today (futures + options), from NSE."""
    data, host = CLIENT.get_json("/api/live-analysis-oi-spurts-underlyings", ttl=60, referer="/market-data/oi-spurts")
    return {"rows": data.get("data") or [], "as_of_text": data.get("timestamp"), "source": _src(host, "oi-spurts")}


def trading_holidays() -> Dict[str, Any]:
    """NSE capital-market trading holidays (ISO dates) from the exchange's holiday master; cached 24 h."""
    data, host = CLIENT.get_json("/api/holiday-master?type=trading", ttl=86400, referer="/resources/exchange-communication-holidays")
    days = {}
    for r in data.get("CM") or []:
        try:
            days[datetime.strptime(r["tradingDate"], "%d-%b-%Y").date().isoformat()] = r.get("description")
        except (KeyError, ValueError):
            continue
    if not days:
        raise SourceError("NSE holiday-master: no CM holidays listed")
    return {"days": days, "source": _src(host, "holiday-master")}
