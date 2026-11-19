"""Expiry-day desk: pin and gamma risk, how fast the ATM straddle decays, and how OI has shifted today.

Uses the chain's own expiry date (NSE weeklies moved off Thursday; SENSEX expires on its own
day), so nothing here assumes a weekday.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List

from ..data import store
from ..data.nse import IST
from .pricing import black76


def desk(an: Dict[str, Any]) -> Dict[str, Any]:
    days = an["days_to_expiry"]
    fwd, atm_iv = an["forward"], (an["atm_iv"] or 0) / 100
    out: Dict[str, Any] = {"expiry": an["expiry"], "days_to_expiry": days, "is_expiry_week": days <= 7, "is_expiry_day": days <= 1}
    if not atm_iv:
        out["available"] = False
        return out
    k = an["atm_strike"]
    t = an["years_to_expiry"]
    decay: List[Dict[str, float]] = []
    for hours in (0, 1, 2, 3, 6, 24):
        tl = max(t - hours / (365 * 24), 1 / (365 * 24 * 60))
        if hours / 24 > days:
            break
        straddle = black76(fwd, k, tl, atm_iv, True) + black76(fwd, k, tl, atm_iv, False)
        decay.append({"after_hours": hours, "atm_straddle": round(straddle, 2)})
    mp = an.get("max_pain")
    walls = an["walls"]
    big = [w["strike"] for w in walls["resistance"][:1] + walls["support"][:1]]
    out.update({
        "available": True,
        "straddle_decay_if_spot_and_iv_unchanged": decay,
        "distance_to_max_pain_pct": round((fwd - mp) / fwd * 100, 3) if mp else None,
        "pin_candidates": sorted(set(([mp] if mp else []) + big)),
        "atm_gamma_per_lot": _atm_gamma_per_lot(an),
        "oi_shift_today": oi_shift(an["symbol"], an["expiry"]),
        "guidance": _guidance(days, an),
    })
    return out


def _atm_gamma_per_lot(an: Dict[str, Any]):
    row = next((s for s in an["strikes"] if s["strike"] == an["atm_strike"]), None)
    if not row or not row.get("call") or not row["call"].get("gamma") or not an.get("lot_size"):
        return None
    return round(row["call"]["gamma"] * an["lot_size"], 4)


def oi_shift(symbol: str, expiry: str) -> Dict[str, Any]:
    """Change in OI per strike between today's first recorded snapshot and the latest one."""
    start = datetime.now(IST).replace(hour=9, minute=0, second=0, microsecond=0).timestamp()
    snaps = store.snapshots(symbol, expiry, start)
    if len(snaps) < 2:
        return {"available": False, "reason": f"{len(snaps)} snapshot(s) recorded today; need 2+ (recorder runs every 3 min in market hours)"}
    first, last = snaps[0], snaps[-1]

    def oi_map(s):
        return {r["strike"]: ((r["call"] or {}).get("oi", 0), (r["put"] or {}).get("oi", 0)) for r in s["rows"]}
    a, b = oi_map(first), oi_map(last)
    moves = [{"strike": k, "call_oi_delta": b[k][0] - a.get(k, (0, 0))[0], "put_oi_delta": b[k][1] - a.get(k, (0, 0))[1]} for k in b]
    moves.sort(key=lambda m: -(abs(m["call_oi_delta"]) + abs(m["put_oi_delta"])))
    return {"available": True, "from": first["ts"], "to": last["ts"], "snapshots": len(snaps), "largest": moves[:8]}


def _guidance(days: float, an: Dict[str, Any]) -> List[str]:
    g = []
    if days <= 1:
        g.append("Expiry day: OTM premiums decay fastest after midday; naked long OTM options need a fast move to pay.")
        g.append("Gamma is at its peak: a small spot move swings ATM deltas sharply, so prefer defined-risk spreads over naked shorts.")
    elif days <= 3:
        g.append("Final days to expiry: theta is accelerating; time decay favours sellers if spot holds inside the expected move.")
    if an.get("max_pain") and abs(an["forward"] - an["max_pain"]) / an["forward"] < 0.005:
        g.append("Spot is within 0.5% of max pain: pinning toward it is plausible if OI stays put.")
    return g
