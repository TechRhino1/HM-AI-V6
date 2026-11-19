"""Where an option's premium goes under explicit scenarios: spot move × IV change × time passed.

This is repricing, not a point prediction: each cell is what Black-76 gives for that
scenario from today's live forward, strike and IV.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from .pricing import black76

SPOT_SIGMAS = (-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0)
IV_SHIFTS = (-3.0, 0.0, 3.0)  # vol points


def forecast(fwd: float, strike: float, is_call: bool, iv_pct: float, t_years: float, horizon_days: float,
             premium_now: float) -> Dict[str, Any]:
    h = min(horizon_days / 365.0, t_years)
    t_left = max(t_years - h, 1 / (365 * 24 * 60))
    move_sd = fwd * (iv_pct / 100) * math.sqrt(h) if h > 0 else 0.0
    rows: List[Dict[str, Any]] = []
    for k in SPOT_SIGMAS:
        s = fwd + k * move_sd
        cells = {}
        for dv in IV_SHIFTS:
            p = black76(s, strike, t_left, max(0.01, (iv_pct + dv) / 100), is_call)
            cells[f"iv{dv:+.0f}"] = {"premium": round(p, 2), "pct": round((p - premium_now) / premium_now * 100, 1) if premium_now else None}
        rows.append({"spot_sigma": k, "spot": round(s, 2), **cells})
    theta_only = black76(fwd, strike, t_left, iv_pct / 100, is_call)
    return {"horizon_days": horizon_days, "premium_now": premium_now, "move_1sd": round(move_sd, 2),
            "unchanged_spot_and_iv": round(theta_only, 2), "time_decay": round(theta_only - premium_now, 2), "grid": rows}
