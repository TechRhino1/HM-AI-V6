"""TradingView scanner: quotes plus fundamentals/technicals Yahoo lacks (sector, RVOL, VWAP, earnings date).

The unauthenticated scanner is DELAYED 15 minutes for NSE, BSE and US exchanges
(`update_mode = delayed_streaming_900`, measured 2026-11-18), so its prices are
labelled delayed and are only a fallback for the live sources.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import requests

from .models import Provenance
from .nse import SourceError

COLUMNS = ["name", "description", "close", "change", "volume", "high", "low", "open", "update_mode", "exchange",
           "currency", "market_cap_basic", "sector", "industry", "relative_volume_10d_calc", "VWAP", "RSI", "ATR",
           "Perf.W", "Perf.1M", "Perf.3M", "earnings_release_next_date", "average_volume_10d_calc"]
_cache: Dict[str, Tuple[float, Any]] = {}


def scan(tickers: List[str], market: str) -> Dict[str, Dict[str, Any]]:
    """`tickers` are TradingView ids (NSE:RELIANCE, NASDAQ:AAPL). Returns id → fields with provenance."""
    endpoint = "india" if market == "IN" else "america"
    key = endpoint + "|" + ",".join(sorted(tickers))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    try:
        r = requests.post(f"https://scanner.tradingview.com/{endpoint}/scan",
                          json={"symbols": {"tickers": tickers}, "columns": COLUMNS},
                          headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        rows = r.json().get("data") or []
    except Exception as exc:
        raise SourceError(f"tradingview {endpoint}: {type(exc).__name__}") from exc
    out: Dict[str, Dict[str, Any]] = {}
    now = time.time()
    for row in rows:
        v = dict(zip(COLUMNS, row.get("d") or []))
        mode = str(v.get("update_mode") or "")
        delay = int(mode.rsplit("_", 1)[-1]) if mode.startswith("delayed_streaming_") and mode.rsplit("_", 1)[-1].isdigit() else None
        kind = "delayed" if delay else ("live" if mode == "streaming" else "close")
        v["prov"] = Provenance(source=f"tradingview:scanner/{endpoint}", kind=kind,
                               as_of=now - (delay or 0), delay_sec=delay, note=f"update_mode={mode}").to_dict()
        out[row["s"]] = v
    _cache[key] = (now, out)
    return out
