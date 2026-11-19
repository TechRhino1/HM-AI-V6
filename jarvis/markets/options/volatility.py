"""Realised volatility from real closed bars, and where today's implied vol sits against it.

IV above recent realised vol is the volatility risk premium that option sellers are paid;
IV below it makes option buying cheaper than the moves the market has been making.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from ..data import store, yahoo
from ..data.nse import SourceError


def realised(closes: List[float], window: int) -> Optional[float]:
    """Annualised close-to-close volatility over the last `window` returns (252 trading days)."""
    if len(closes) < window + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - window, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * 252)


def regime(symbol: str, atm_iv_pct: Optional[float]) -> Dict[str, Any]:
    try:
        b = yahoo.bars(symbol, "IN", "1d", "1y")
    except SourceError as exc:
        return {"available": False, "reason": str(exc)}
    bars = b["bars"][:-1] if b.get("last_bar_forming") else b["bars"]  # closed bars only
    closes = [x["close"] for x in bars]
    rv10, rv20, rv60 = realised(closes, 10), realised(closes, 20), realised(closes, 60)
    hist = store.iv_history(symbol)
    iv_pct_rank = None
    if atm_iv_pct and len(hist) >= 20:
        ivs = [h["iv"] for h in hist]
        iv_pct_rank = round(sum(1 for v in ivs if v < atm_iv_pct) / len(ivs) * 100, 1)
    out = {
        "available": True, "rv10": _pct(rv10), "rv20": _pct(rv20), "rv60": _pct(rv60), "atm_iv": atm_iv_pct,
        "iv_minus_rv20": round(atm_iv_pct - rv20 * 100, 2) if (atm_iv_pct and rv20) else None,
        "iv_percentile": iv_pct_rank, "iv_history_days": len(hist),
        "forecast_vol": _forecast(rv10, rv20, rv60), "bars_prov": b["prov"],
        "last_close": closes[-1] if closes else None,
        "trend": trend(closes),
    }
    if out["iv_minus_rv20"] is not None:
        out["vol_view"] = ("options rich (IV well above realised): favours defined-risk selling" if out["iv_minus_rv20"] > 2
                           else "options cheap (IV below realised): favours buying" if out["iv_minus_rv20"] < -1
                           else "options fairly priced")
    return out


def _pct(v: Optional[float]) -> Optional[float]:
    return round(v * 100, 2) if v else None


def _forecast(rv10, rv20, rv60) -> Optional[float]:
    """Blend of recent realised vols (a standard, simple forecaster); annual fraction."""
    parts = [(rv10, 0.3), (rv20, 0.4), (rv60, 0.3)]
    have = [(v, w) for v, w in parts if v]
    if not have:
        return None
    return sum(v * w for v, w in have) / sum(w for _, w in have)


def trend(closes: List[float]) -> Dict[str, Any]:
    """Moving-average structure on real closes: the regime label the adviser starts from."""
    if len(closes) < 50:
        return {"label": "unknown", "reason": "fewer than 50 closed bars"}
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50
    last = closes[-1]
    slope20 = (sma20 - sum(closes[-25:-5]) / 20) / sma20 * 100
    if last > sma20 > sma50 and slope20 > 0:
        label = "uptrend"
    elif last < sma20 < sma50 and slope20 < 0:
        label = "downtrend"
    else:
        label = "range"
    return {"label": label, "close": last, "sma20": round(sma20, 2), "sma50": round(sma50, 2), "sma20_slope_pct": round(slope20, 3)}
