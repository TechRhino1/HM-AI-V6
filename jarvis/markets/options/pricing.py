"""Black-76 on the chain's own forward. No assumed rate: the forward comes from put-call parity
on the live quotes, so every price and Greek here is anchored to the market.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, Optional

from ..data.nse import IST

SQRT2 = math.sqrt(2.0)


def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT2))


def npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def years_to_expiry(expiry: str, now: Optional[datetime] = None) -> float:
    """Exchange expiry "23-Nov-2026" settles at 15:30 IST. Floors at one minute so Greeks stay finite on expiry day."""
    end = datetime.strptime(expiry, "%d-%b-%Y").replace(hour=15, minute=30, tzinfo=IST)
    now = now or datetime.now(IST)
    return max((end - now).total_seconds(), 60.0) / (365.0 * 86400.0)


def black76(fwd: float, k: float, t: float, vol: float, is_call: bool) -> float:
    if vol <= 0 or t <= 0:
        return max(0.0, (fwd - k) if is_call else (k - fwd))
    sd = vol * math.sqrt(t)
    d1 = (math.log(fwd / k) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    return fwd * ncdf(d1) - k * ncdf(d2) if is_call else k * ncdf(-d2) - fwd * ncdf(-d1)


def greeks(fwd: float, k: float, t: float, vol: float, is_call: bool) -> Dict[str, float]:
    """Delta, gamma (per 1 point), vega (per 1 vol point), theta (per calendar day)."""
    sd = vol * math.sqrt(t)
    d1 = (math.log(fwd / k) + 0.5 * sd * sd) / sd
    pdf = npdf(d1)
    return {
        "delta": ncdf(d1) if is_call else ncdf(d1) - 1.0,
        "gamma": pdf / (fwd * sd),
        "vega": fwd * pdf * math.sqrt(t) / 100.0,
        "theta": -(fwd * pdf * vol) / (2 * math.sqrt(t)) / 365.0,
    }


def implied_vol(price: float, fwd: float, k: float, t: float, is_call: bool) -> Optional[float]:
    """Bisection on Black-76. None when the price sits below intrinsic or above the forward (no valid IV)."""
    intrinsic = max(0.0, (fwd - k) if is_call else (k - fwd))
    if price <= intrinsic + 1e-9 or price >= (fwd if is_call else k):
        return None
    lo, hi = 1e-4, 5.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if black76(fwd, k, t, mid, is_call) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-6:
            break
    return 0.5 * (lo + hi)


def prob_above(fwd: float, level: float, t: float, vol: float, drift: float = 0.0) -> float:
    """P(S_T > level) for a lognormal with the given annual vol; drift is an annual log-return view (0 = market-neutral)."""
    if level <= 0:
        return 1.0
    sd = vol * math.sqrt(t)
    if sd <= 0:
        return 1.0 if fwd > level else 0.0
    mu = math.log(fwd) + (drift - 0.5 * vol * vol) * t
    return 1.0 - ncdf((math.log(level) - mu) / sd)
