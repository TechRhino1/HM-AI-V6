"""Institutional read of one live option chain: forward, IV per strike, Greeks, max pain, PCR,
OI walls, OI build-up/unwinding, skew, expected move, liquidity and gamma exposure.

All inputs are the exchange's quotes; nothing is filled in. A strike without a usable
price gets no IV and is excluded from IV-based measures (and counted in `coverage`).
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Optional

from ..data.models import OptionChain, OptionSide
from .pricing import greeks, implied_vol, years_to_expiry


def mid(side: Optional[OptionSide]) -> Optional[float]:
    if not side:
        return None
    if side.bid and side.ask and side.ask >= side.bid:
        return (side.bid + side.ask) / 2
    return side.ltp or None


def spread_pct(side: Optional[OptionSide]) -> Optional[float]:
    m = mid(side)
    if not side or not side.bid or not side.ask or not m:
        return None
    return (side.ask - side.bid) / m * 100


def forward(chain: OptionChain) -> float:
    """Put-call parity F = K + C - P at the three strikes nearest spot; median for robustness."""
    near = sorted(chain.rows, key=lambda r: abs(r.strike - chain.spot))[:5]
    vals = [r.strike + mid(r.call) - mid(r.put) for r in near if mid(r.call) and mid(r.put)]
    return statistics.median(vals[:3]) if vals else chain.spot


def buildup(price_chg: float, oi_chg: int) -> str:
    """Standard F&O positioning table (applies to each option series)."""
    if oi_chg > 0:
        return "long_buildup" if price_chg > 0 else "short_buildup"
    if oi_chg < 0:
        return "short_covering" if price_chg > 0 else "long_unwinding"
    return "neutral"


def analyse(chain: OptionChain) -> Dict[str, Any]:
    t = years_to_expiry(chain.expiry)
    fwd = forward(chain)
    lot = chain.lot_size or 1
    strikes: List[Dict[str, Any]] = []
    for r in chain.rows:
        row: Dict[str, Any] = {"strike": r.strike}
        for name, side, is_call in (("call", r.call, True), ("put", r.put, False)):
            if not side:
                row[name] = None
                continue
            m = mid(side)
            iv_solved = implied_vol(m, fwd, r.strike, t, is_call) if m else None
            # IV solved from the live mid against the chain's own forward keeps pricing self-consistent;
            # the exchange's IV (computed on its own spot/rate) is only a fallback.
            iv = iv_solved or ((side.iv / 100.0) if side.iv else None)
            g = greeks(fwd, r.strike, t, iv, is_call) if iv else None
            row[name] = {
                "ltp": side.ltp, "bid": side.bid, "ask": side.ask, "mid": m, "spread_pct": spread_pct(side),
                "oi": side.oi, "oi_change": side.oi_change, "oi_change_pct": side.oi_change_pct, "volume": side.volume,
                "iv": round(iv * 100, 2) if iv else None, "iv_source": "solved_from_mid" if iv_solved else ("exchange" if side.iv else None), "exchange_iv": side.iv,
                "change": side.change, "buildup": buildup(side.change, side.oi_change),
                **({k: round(v, 5) for k, v in g.items()} if g else {}),
            }
        strikes.append(row)

    calls = [(s["strike"], s["call"]) for s in strikes if s.get("call")]
    puts = [(s["strike"], s["put"]) for s in strikes if s.get("put")]
    atm = min(strikes, key=lambda s: abs(s["strike"] - fwd))
    atm_iv_vals = [x["iv"] for x in (atm.get("call"), atm.get("put")) if x and x.get("iv")]
    atm_iv = sum(atm_iv_vals) / len(atm_iv_vals) / 100 if atm_iv_vals else None
    straddle = (atm["call"]["mid"] or 0) + (atm["put"]["mid"] or 0) if atm.get("call") and atm.get("put") else None

    tot_call_oi = sum(c["oi"] for _, c in calls)
    tot_put_oi = sum(p["oi"] for _, p in puts)
    tot_call_vol = sum(c["volume"] for _, c in calls)
    tot_put_vol = sum(p["volume"] for _, p in puts)
    d_call = sum(c["oi_change"] for _, c in calls)
    d_put = sum(p["oi_change"] for _, p in puts)

    return {
        "symbol": chain.symbol, "expiry": chain.expiry, "spot": chain.spot, "forward": round(fwd, 2),
        "years_to_expiry": t, "days_to_expiry": round(t * 365, 2), "lot_size": chain.lot_size,
        "atm_strike": atm["strike"], "atm_iv": round(atm_iv * 100, 2) if atm_iv else None,
        "atm_straddle": round(straddle, 2) if straddle else None,
        "expected_move": _expected_move(fwd, atm_iv, t, straddle),
        "max_pain": max_pain(chain), "pcr": {
            "oi": round(tot_put_oi / tot_call_oi, 3) if tot_call_oi else None,
            "volume": round(tot_put_vol / tot_call_vol, 3) if tot_call_vol else None,
            "oi_change": round(d_put / d_call, 3) if d_call > 0 and d_put > 0 else None,
            "call_oi": tot_call_oi, "put_oi": tot_put_oi, "call_oi_change": d_call, "put_oi_change": d_put,
        },
        "walls": walls(calls, puts, fwd),
        "skew": skew(strikes),
        "gex": gamma_exposure(strikes, fwd, lot),
        "positioning": positioning(calls, puts, fwd),
        "coverage": {"strikes": len(strikes), "with_iv": sum(1 for s in strikes for k in ("call", "put") if s.get(k) and s[k].get("iv"))},
        "strikes": strikes,
    }


def _expected_move(fwd: float, atm_iv: Optional[float], t: float, straddle: Optional[float]) -> Optional[Dict[str, float]]:
    if not atm_iv:
        return None
    one_sd = fwd * atm_iv * math.sqrt(t)
    out = {"one_sd": round(one_sd, 2), "one_sd_pct": round(atm_iv * math.sqrt(t) * 100, 3),
           "upper_1sd": round(fwd + one_sd, 2), "lower_1sd": round(fwd - one_sd, 2)}
    if straddle:
        out["straddle_implied"] = round(straddle, 2)  # ≈ 0.8 × 1σ for an ATM straddle
    return out


def max_pain(chain: OptionChain) -> Optional[float]:
    """Settlement price at which option buyers' aggregate intrinsic value (writers' payout) is smallest."""
    rows = [(r.strike, r.call.oi if r.call else 0, r.put.oi if r.put else 0) for r in chain.rows]
    if not rows:
        return None
    best, best_pay = None, math.inf
    for s, _, _ in rows:
        pay = sum(max(0.0, s - k) * c + max(0.0, k - s) * p for k, c, p in rows)
        if pay < best_pay:
            best, best_pay = s, pay
    return best


def walls(calls, puts, fwd: float, n: int = 3) -> Dict[str, Any]:
    above = sorted([(k, c) for k, c in calls if k >= fwd], key=lambda x: -x[1]["oi"])[:n]
    below = sorted([(k, p) for k, p in puts if k <= fwd], key=lambda x: -x[1]["oi"])[:n]
    fresh_calls = sorted([(k, c) for k, c in calls if k >= fwd], key=lambda x: -x[1]["oi_change"])[:n]
    fresh_puts = sorted([(k, p) for k, p in puts if k <= fwd], key=lambda x: -x[1]["oi_change"])[:n]
    f = lambda xs: [{"strike": k, "oi": v["oi"], "oi_change": v["oi_change"]} for k, v in xs]
    return {"resistance": f(above), "support": f(below), "fresh_call_writing": f(fresh_calls), "fresh_put_writing": f(fresh_puts)}


def skew(strikes) -> Dict[str, Any]:
    """25-delta risk reversal (put IV − call IV): positive = downside protection is bid."""
    calls = [(abs(s["call"]["delta"] - 0.25), s["call"]["iv"]) for s in strikes if s.get("call") and s["call"].get("delta") is not None and s["call"].get("iv")]
    puts = [(abs(s["put"]["delta"] + 0.25), s["put"]["iv"]) for s in strikes if s.get("put") and s["put"].get("delta") is not None and s["put"].get("iv")]
    if not calls or not puts:
        return {"rr25": None}
    c25, p25 = min(calls)[1], min(puts)[1]
    return {"call25_iv": c25, "put25_iv": p25, "rr25": round(p25 - c25, 2)}


def gamma_exposure(strikes, fwd: float, lot: int) -> Dict[str, Any]:
    """Dealer gamma under the common convention that customers are net long options (dealers short).
    That convention is an assumption about who holds the OI, so the sign is a positioning hint, not a fact."""
    per_strike, total = [], 0.0
    for s in strikes:
        g = 0.0
        if s.get("call") and s["call"].get("gamma"):
            g += s["call"]["gamma"] * s["call"]["oi"]
        if s.get("put") and s["put"].get("gamma"):
            g -= s["put"]["gamma"] * s["put"]["oi"]
        gex = g * lot * fwd * fwd * 0.01  # ₹ change in dealer delta per 1% move
        per_strike.append((s["strike"], gex))
        total += gex
    flip = None
    cum = 0.0
    for k, gx in sorted(per_strike):
        prev = cum
        cum += gx
        if prev < 0 <= cum or prev > 0 >= cum:
            flip = k
    return {"net_gex_cr": round(total / 1e7, 2), "regime": "positive (dampening)" if total > 0 else "negative (amplifying)",
            "gamma_flip_strike": flip, "assumption": "customers net long options; dealers short"}


def positioning(calls, puts, fwd: float) -> Dict[str, Any]:
    """Near-the-money OI change by side: who is adding risk today."""
    band = [(k, c) for k, c in calls if abs(k - fwd) / fwd <= 0.03]
    pband = [(k, p) for k, p in puts if abs(k - fwd) / fwd <= 0.03]
    cw = sum(c["oi_change"] for _, c in band if c["buildup"] == "short_buildup")
    pw = sum(p["oi_change"] for _, p in pband if p["buildup"] == "short_buildup")
    cu = sum(-c["oi_change"] for _, c in band if c["buildup"] in ("short_covering",))
    pu = sum(-p["oi_change"] for _, p in pband if p["buildup"] in ("short_covering",))
    bias = "neutral"
    if pw > 1.3 * cw and pw > 0:
        bias = "bullish (put writing dominates)"
    elif cw > 1.3 * pw and cw > 0:
        bias = "bearish (call writing dominates)"
    if cu > cw and cu > 0:
        bias += "; call short covering"
    if pu > pw and pu > 0:
        bias += "; put short covering"
    return {"call_writing_oi": cw, "put_writing_oi": pw, "call_short_covering_oi": cu, "put_short_covering_oi": pu, "bias": bias}
