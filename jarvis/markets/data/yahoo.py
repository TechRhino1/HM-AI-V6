"""Yahoo Finance chart API: real-time NSE/BSE quotes (measured 2-12 s old) and historical bars.

Freshness is graded from the exchange timestamp Yahoo returns (`regularMarketTime`),
never assumed.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from .models import Provenance, Quote, grade
from .nse import SourceError

BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_session = requests.Session()
_cache: Dict[str, Tuple[float, Any]] = {}
_lock = threading.Lock()

# Canonical symbol → Yahoo ticker for indices; plain NSE equities get ".NS", US tickers stay as-is.
INDEX_TICKERS = {
    "NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS", "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",
    "SENSEX": "^BSESN", "BANKEX": "BSE-BANK.BO", "INDIAVIX": "^INDIAVIX", "SPX": "^GSPC", "NDX": "^NDX", "DJI": "^DJI",
    "VIX": "^VIX",
}


def ticker(symbol: str, market: str) -> str:
    s = symbol.upper()
    if s in INDEX_TICKERS:
        return INDEX_TICKERS[s]
    return f"{s}.NS" if market == "IN" else s


def _chart(t: str, interval: str, rng: str, ttl: float) -> Dict[str, Any]:
    key = f"{t}|{interval}|{rng}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        r = _session.get(BASE + t, params={"interval": interval, "range": rng, "includePrePost": "false"},
                         headers=_HEADERS, timeout=12)
        res = (r.json().get("chart") or {}).get("result") or []
    except Exception as exc:
        raise SourceError(f"yahoo {t}: {type(exc).__name__}") from exc
    if not res:
        raise SourceError(f"yahoo {t}: no data")
    with _lock:
        _cache[key] = (time.time(), res[0])
    return res[0]


def quote(symbol: str, market: str, session_open: bool) -> Quote:
    t = ticker(symbol, market)
    m = _chart(t, "1m", "1d", ttl=5)["meta"]
    price = m.get("regularMarketPrice")
    if not price:
        raise SourceError(f"yahoo {t}: no price")
    prev = m.get("chartPreviousClose") or m.get("previousClose")
    delay = int(m.get("exchangeDataDelayedBy") or 0) * 60 or None
    prov = grade(f"yahoo:chart/{t}", m.get("regularMarketTime"), session_open, fresh_sec=60, delay_sec=delay)
    return Quote(symbol=symbol.upper(), price=float(price),
                 change_pct=round((price - prev) / prev * 100, 3) if prev else None, prev_close=prev,
                 day_high=m.get("regularMarketDayHigh"), day_low=m.get("regularMarketDayLow"),
                 volume=m.get("regularMarketVolume"), currency=m.get("currency") or ("INR" if market == "IN" else "USD"),
                 prov=prov, extra={"exchange": m.get("exchangeName"), "name": m.get("longName") or m.get("shortName")})


def bars(symbol: str, market: str, interval: str = "1d", rng: str = "2y") -> Dict[str, Any]:
    """Closed, real OHLCV bars. Rows with any missing field are dropped, not filled."""
    t = ticker(symbol, market)
    res = _chart(t, interval, rng, ttl=60 if interval.endswith("m") else 900)
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    out: List[Dict[str, float]] = []
    for i, tm in enumerate(ts):
        row = {k: (q.get(k) or [None] * len(ts))[i] for k in ("open", "high", "low", "close", "volume")}
        if any(row[k] is None for k in ("open", "high", "low", "close")):
            continue
        out.append({"time": int(tm), **{k: float(v or 0) for k, v in row.items()}})
    if not out:
        raise SourceError(f"yahoo {t}: no bars for {interval}/{rng}")
    # The last bar is still forming if the exchange's current period contains it; models must drop it.
    step = {"1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1h": 3600}.get(interval)
    if step:
        forming = time.time() < out[-1]["time"] + step
    else:
        period = (res.get("meta") or {}).get("currentTradingPeriod", {}).get("regular", {})
        forming = bool(period) and period.get("start", 0) <= out[-1]["time"] < period.get("end", 0) and time.time() < period.get("end", 0)
    return {"symbol": symbol.upper(), "interval": interval, "bars": out, "last_bar_forming": forming,
            "prov": Provenance(source=f"yahoo:chart/{t}", kind="close" if interval in ("1d", "1wk", "1mo") and not forming else "live",
                               as_of=float(out[-1]["time"]),
                               note=f"{len(out)} real bars" + ("; last bar forming" if forming else "")).to_dict()}
