"""Macro drivers from real daily series: dollar index, US yields, implied-vol indices, the 10-year real yield.

Sources (verified 2026-11-18):
  Yahoo chart API   DX-Y.NYB (ICE dollar index), ^TNX / ^FVX / ^IRX (10y / 5y / 13-week yields, in %),
                    ^VIX, ^GVZ (CBOE gold ETF vol). ^EVZ (euro FX vol) is delisted on Yahoo → unavailable.
  Deribit public    BTC / ETH DVOL (30-day implied vol index), /api/v2/public/get_volatility_index_data
  FRED fredgraph    DFII10 (10-year TIPS yield, daily) for the gold real-yield proxy
Trading symbols map to Yahoo tickers; XAUUSD uses COMEX front-month gold futures (GC=F) because Yahoo
serves no spot XAU — stated in the provenance note. Only closed daily bars are used.
"""
from __future__ import annotations

import calendar
import csv
import io
import math
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import yahoo
from .models import Provenance, unavailable
from .nse import SourceError

SERIES = {"DXY": "DX-Y.NYB", "US10Y": "^TNX", "US5Y": "^FVX", "US13W": "^IRX", "VIX": "^VIX", "GVZ": "^GVZ", "EVZ": "^EVZ"}
SYMBOL_TICKERS = {"EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "JPY=X", "USDCAD": "CAD=X", "XAUUSD": "GC=F",
                  "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD", "SOLUSD": "SOL-USD"}
# Implied-vol index per symbol: ("yahoo", ticker) or ("deribit", currency). Absent = no free real source.
IMPLIED = {"XAUUSD": ("yahoo", "^GVZ"), "EURUSD": ("yahoo", "^EVZ"), "BTCUSD": ("deribit", "BTC"), "ETHUSD": ("deribit", "ETH")}
CRYPTO = {"BTCUSD", "ETHUSD", "SOLUSD"}
CORR_DAYS, TREND_DAYS = 60, 20
DXY_TREND_PCT, YIELD_TREND_PTS = 1.0, 0.15   # 20-day thresholds for the regime labels (and the validation)
VOL_SPIKE_PCTL = 90
DERIBIT = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
_cache: Dict[str, Tuple[float, Any]] = {}
_lock = threading.Lock()


def _day(ts: float, fx: bool = False) -> str:
    """Bar date: Yahoo stamps daily bars at the session start (FX 23:00/00:00 UTC, US 13:30 UTC, DXY 05:00 UTC);
    +6 h puts each on its own date. Yahoo's "=X" FX daily bar dated D closes at the London-midnight price that
    ends the previous weekday (checked against hourly bars 2026-11-12..17, and EURUSD/DXY correlation is
    -0.83 one day shifted vs -0.1 unshifted), so FX bars are relabelled to the previous weekday."""
    d = datetime.fromtimestamp(ts + 6 * 3600, timezone.utc).date()
    if fx:
        d -= timedelta(days=3 if d.weekday() == 0 else 1)
    return d.isoformat()


def _epoch(iso: str) -> float:
    return float(calendar.timegm(date.fromisoformat(iso).timetuple()))


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    v = fn()
    with _lock:
        _cache[key] = (time.time(), v)
    return v


def daily(ticker: str, rng: str = "2y") -> Dict[str, Any]:
    """{"closes": {iso_date: close}, "prov"} from closed Yahoo daily bars (the forming bar is dropped)."""
    try:
        b = yahoo.bars(ticker, "US", "1d", rng)
    except SourceError as exc:
        return {"closes": {}, "prov": unavailable(f"yahoo:chart/{ticker}", str(exc)).to_dict()}
    bars = b["bars"][:-1] if b.get("last_bar_forming") else b["bars"]
    closes = {_day(x["time"], ticker.endswith("=X")): x["close"] for x in bars}
    prov = Provenance(source=f"yahoo:chart/{ticker}", kind="close", as_of=float(bars[-1]["time"]) if bars else None,
                      note=f"{len(closes)} closed daily bars" + ("; COMEX front-month futures as the XAUUSD proxy" if ticker == "GC=F" else ""))
    return {"closes": closes, "prov": prov.to_dict() if bars else unavailable(f"yahoo:chart/{ticker}", "no closed bars").to_dict()}


def deribit_dvol(currency: str, days: int = 400) -> Dict[str, Any]:
    src = f"deribit:public/get_volatility_index_data/{currency}"

    def get():
        end = int(time.time() * 1000)
        r = requests.get(DERIBIT, params={"currency": currency, "resolution": "1D", "start_timestamp": end - days * 86400000,
                                          "end_timestamp": end}, timeout=15)
        r.raise_for_status()
        return r.json()["result"]["data"]
    try:
        data = _cached(src, 900, get)
    except Exception as exc:
        return {"closes": {}, "prov": unavailable(src, f"{type(exc).__name__}: {exc}").to_dict()}
    # [ts_ms, open, high, low, close]; the last candle is today's, still forming → dropped
    rows = [d for d in data if d[0] / 1000 + 86400 <= time.time()]
    closes = {datetime.fromtimestamp(d[0] / 1000, timezone.utc).date().isoformat(): float(d[4]) for d in rows}
    if not closes:
        return {"closes": {}, "prov": unavailable(src, "no closed daily candles").to_dict()}
    return {"closes": closes, "prov": Provenance(source=src, kind="close", as_of=rows[-1][0] / 1000 + 86400,
                                                  note=f"{len(closes)} daily DVOL closes (30-day implied vol, %)").to_dict()}


def parse_fred(text: str) -> Dict[str, float]:
    """fredgraph CSV → {iso_date: value}; '.' (no observation) rows are skipped."""
    rd = csv.reader(io.StringIO(text))
    next(rd)
    return {d: float(v) for d, v in (row[:2] for row in rd if len(row) >= 2) if v not in (".", "")}


def fred(series_id: str) -> Dict[str, Any]:
    src = f"fred:fredgraph/{series_id}"

    def get():
        r = requests.get(FRED.format(series_id), timeout=30)  # FRED resets connections from browser-like UAs
        r.raise_for_status()
        return parse_fred(r.text)
    try:
        closes = _cached(src, 3600, get)
    except Exception as exc:
        return {"closes": {}, "prov": unavailable(src, f"{type(exc).__name__}: {exc}").to_dict()}
    if not closes:
        return {"closes": {}, "prov": unavailable(src, "no observations").to_dict()}
    last = max(closes)
    return {"closes": closes, "prov": Provenance(source=src, kind="eod", as_of=_epoch(last),
                                                  note=f"FRED daily series, last observation {last}").to_dict()}


# ---------------------------------------------------------------- pure math

def corr(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return round(sxy / (sx * sy), 3) if sx and sy else None


def aligned_changes(a: Dict[str, float], b: Dict[str, float], days: int, a_log: bool = True, b_log: bool = True
                    ) -> Tuple[List[float], List[float]]:
    """Changes between consecutive common dates over the last `days` intervals: log returns, or differences
    (yields) when *_log is False."""
    common = sorted(set(a) & set(b))[-(days + 1):]

    def ch(s, log):
        return [math.log(s[common[i]] / s[common[i - 1]]) if log else s[common[i]] - s[common[i - 1]] for i in range(1, len(common))]
    return ch(a, a_log), ch(b, b_log)


def realised_vol(closes: List[float], window: int, periods: int) -> Optional[float]:
    if len(closes) < window + 1:
        return None
    r = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - window, len(closes))]
    m = sum(r) / window
    return round(math.sqrt(sum((x - m) ** 2 for x in r) / (window - 1) * periods) * 100, 2)


def percentile_of_last(values: List[float]) -> Optional[float]:
    """Share of the earlier values strictly below the last one, 0..100."""
    if len(values) < 30:
        return None
    last, prior = values[-1], values[:-1]
    return round(sum(1 for v in prior if v < last) / len(prior) * 100, 1)


def trend(closes: Dict[str, float], days: int, pct: bool) -> Optional[float]:
    ds = sorted(closes)
    if len(ds) <= days:
        return None
    a, b = closes[ds[-days - 1]], closes[ds[-1]]
    return round((b / a - 1) * 100, 3) if pct else round(b - a, 3)


def dollar_label(chg_pct: Optional[float]) -> Optional[str]:
    if chg_pct is None:
        return None
    return "dollar strengthening" if chg_pct > DXY_TREND_PCT else "dollar weakening" if chg_pct < -DXY_TREND_PCT else "dollar range-bound"


def yield_label(chg_pts: Optional[float]) -> Optional[str]:
    if chg_pts is None:
        return None
    return "yields rising" if chg_pts > YIELD_TREND_PTS else "yields falling" if chg_pts < -YIELD_TREND_PTS else "yields flat"


# ---------------------------------------------------------------- payloads

def _last(d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    c = d["closes"]
    if not c:
        return None
    k = max(c)
    return {"date": k, "value": round(c[k], 4)}


def series() -> Dict[str, Dict[str, Any]]:
    def build():
        out = {name: daily(t) for name, t in SERIES.items()}
        out["REAL10Y"] = fred("DFII10")
        return out
    return _cached("series", 900, build)


def snapshot() -> Dict[str, Any]:
    """Current macro values and regime labels, each series with its own provenance."""
    def build():
        series_ = series()
        out: Dict[str, Any] = {}
        for name, s in series_.items():
            out[name.lower()] = {**(_last(s) or {"date": None, "value": None}), "prov": s["prov"]}
        dxy_chg = trend(series_["DXY"]["closes"], TREND_DAYS, True)
        y_chg = trend(series_["US10Y"]["closes"], TREND_DAYS, False)
        r_chg = trend(series_["REAL10Y"]["closes"], TREND_DAYS, False)
        c10, c13 = _last(series_["US10Y"]), _last(series_["US13W"])
        out["regime"] = {
            "dxy_chg_20d_pct": dxy_chg, "dollar": dollar_label(dxy_chg),
            "us10y_chg_20d_pts": y_chg, "yields": yield_label(y_chg),
            "real10y_chg_20d_pts": r_chg, "real_yields": yield_label(r_chg),
            "curve_10y_13w_pts": round(c10["value"] - c13["value"], 3) if c10 and c13 else None,
            "rule": f"20-day change: dollar ±{DXY_TREND_PCT}%, yields ±{YIELD_TREND_PTS} pts; labels describe, they do not predict",
            "prov": series_["DXY"]["prov"],
        }
        return out
    return _cached("snapshot", 900, build)


def implied(symbol: str) -> Dict[str, Any]:
    spec = IMPLIED.get(symbol)
    if not spec:
        return {"closes": {}, "prov": unavailable("implied vol index", f"no free real implied-vol index for {symbol}").to_dict()}
    if spec[0] == "deribit":
        return deribit_dvol(spec[1])
    return series()[next(k for k, v in SERIES.items() if v == spec[1])]


def drivers(symbol: str) -> Dict[str, Any]:
    """Per trading symbol: 60-day correlations of daily returns to DXY and to 10y-yield changes, and the
    volatility regime (realised 20d vs its own 1-year history and vs the implied index where one exists)."""
    sym = symbol.upper()
    t = SYMBOL_TICKERS.get(sym)
    if not t:
        return {"symbol": sym, "prov": unavailable("yahoo", f"no macro mapping for {sym}").to_dict()}
    ser = series()
    px = daily(t)
    if not px["closes"]:
        return {"symbol": sym, "prov": px["prov"]}
    dxy, y10 = ser["DXY"]["closes"], ser["US10Y"]["closes"]
    a, b = aligned_changes(px["closes"], dxy, CORR_DAYS)
    c, d = aligned_changes(px["closes"], y10, CORR_DAYS, True, False)
    closes = [px["closes"][k] for k in sorted(px["closes"])]
    periods = 365 if sym in CRYPTO else 252
    rv_series = [realised_vol(closes[: i + 1], TREND_DAYS, periods) for i in range(max(TREND_DAYS, len(closes) - periods), len(closes))]
    rv_series = [v for v in rv_series if v is not None]
    rv = rv_series[-1] if rv_series else None
    iv = implied(sym)
    iv_last = _last(iv)
    iv_pctl = percentile_of_last([iv["closes"][k] for k in sorted(iv["closes"])][-periods:]) if iv["closes"] else None
    rv_pctl = percentile_of_last(rv_series)
    spike = (rv_pctl is not None and rv_pctl >= VOL_SPIKE_PCTL) or (iv_pctl is not None and iv_pctl >= VOL_SPIKE_PCTL)
    return {
        "symbol": sym, "ticker": t,
        "correlation_60d": {"dxy": corr(a, b), "us10y_change": corr(c, d), "days": len(a),
                            "note": "Pearson on daily log returns (yield: daily change in pts), common dates only"},
        "volatility": {"realised_20d_pct": rv, "realised_pctl_1y": rv_pctl,
                       "implied": {**(iv_last or {"date": None, "value": None}), "pctl_1y": iv_pctl, "prov": iv["prov"]},
                       "implied_minus_realised": round(iv_last["value"] - rv, 2) if iv_last and rv is not None else None,
                       "regime": None if rv_pctl is None else "spike" if spike else "elevated" if rv_pctl >= 70 else "normal" if rv_pctl >= 30 else "quiet",
                       "rule": f"spike = realised or implied at or above its {VOL_SPIKE_PCTL}th 1-year percentile"},
        "prov": px["prov"],
    }


def live(name: str) -> Dict[str, Any]:
    """Latest quote of a macro series (graded by its own timestamp; DXY trades ~23 h on weekdays)."""
    t = SERIES[name]
    try:
        q = yahoo.quote(t, "US", session_open=datetime.now(timezone.utc).weekday() < 5)
    except SourceError as exc:
        return {"value": None, "prov": unavailable(f"yahoo:chart/{t}", str(exc)).to_dict()}
    return {"value": q.price, "change_pct": q.change_pct, "prov": q.prov.to_dict()}
