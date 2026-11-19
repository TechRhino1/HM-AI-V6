"""Build and evaluate option strategies at executable prices (buy at ask, sell at bid).

Each strategy is scored under two distributions, both lognormal and integrated on a fine
deterministic price grid (no simulation):
  market  — the chain's own ATM IV, zero drift: what the market is pricing
  view    — forecast realised vol (and a validated drift, when a model has earned one)
Under `market`, expected value is ~minus costs by construction; an edge only exists where
the `view` differs from the market for a measurable reason.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .pricing import black76, ncdf


def leg(chain_row: Dict[str, Any], kind: str, side: str, lots: int = 1) -> Optional[Dict[str, Any]]:
    """kind 'CE'/'PE', side 'BUY'/'SELL'. Fill price is the touch you would actually trade at."""
    q = chain_row.get("call" if kind == "CE" else "put")
    if not q:
        return None
    price = q["ask"] if side == "BUY" else q["bid"]
    if not price:
        return None
    return {"strike": chain_row["strike"], "type": kind, "side": side, "lots": lots, "price": price,
            "mid": q["mid"], "iv": q.get("iv"), "delta": q.get("delta"), "oi": q["oi"], "volume": q["volume"],
            "spread_pct": q.get("spread_pct")}


def payoff_at(legs: List[Dict[str, Any]], s: float) -> float:
    """Per-unit P&L at expiry for settlement price s."""
    total = 0.0
    for l in legs:
        intrinsic = max(0.0, s - l["strike"]) if l["type"] == "CE" else max(0.0, l["strike"] - s)
        sign = 1 if l["side"] == "BUY" else -1
        total += sign * (intrinsic - l["price"]) * l["lots"]
    return total


def evaluate(legs: List[Dict[str, Any]], fwd: float, t: float, market_vol: float, view_vol: Optional[float],
             lot_size: int, view_drift: float = 0.0) -> Dict[str, Any]:
    strikes = sorted({l["strike"] for l in legs})
    lo, hi = fwd * math.exp(-6 * market_vol * math.sqrt(t)), fwd * math.exp(6 * market_vol * math.sqrt(t))
    lo, hi = min(lo, strikes[0] * 0.9), max(hi, strikes[-1] * 1.1)
    n = 2000
    grid = [lo + (hi - lo) * i / n for i in range(n + 1)]
    pnl = [payoff_at(legs, s) for s in grid]

    # Unbounded tails: a net short call beyond the grid keeps losing.
    net_calls = sum((1 if l["side"] == "BUY" else -1) * l["lots"] for l in legs if l["type"] == "CE")
    net_puts = sum((1 if l["side"] == "BUY" else -1) * l["lots"] for l in legs if l["type"] == "PE")
    unlimited_loss = net_calls < 0
    unlimited_gain = net_calls > 0
    max_loss = None if unlimited_loss else min(min(pnl), payoff_at(legs, 0.0) if net_puts < 0 else min(pnl))
    max_gain = None if unlimited_gain else max(pnl)
    breakevens = [round((grid[i] + grid[i + 1]) / 2, 2) for i in range(n) if (pnl[i] <= 0 < pnl[i + 1]) or (pnl[i] >= 0 > pnl[i + 1])]
    debit = sum((1 if l["side"] == "BUY" else -1) * l["price"] * l["lots"] for l in legs)

    def stats(vol: float, drift: float) -> Dict[str, float]:
        sd = vol * math.sqrt(t)
        mu = math.log(fwd) + (drift - 0.5 * vol * vol) * t
        cdf = [ncdf((math.log(s) - mu) / sd) for s in grid]
        ev = pop = 0.0
        for i in range(n):
            p = cdf[i + 1] - cdf[i]
            mid_pnl = 0.5 * (pnl[i] + pnl[i + 1])
            ev += p * mid_pnl
            if mid_pnl > 0:
                pop += p
        return {"pop": round(pop * 100, 1), "ev_per_unit": round(ev, 2), "ev_per_lot": round(ev * lot_size, 0)}

    # Expected value per leg, smile-consistent: each strike keeps its own market IV, scaled by
    # forecast realised / ATM implied vol. With view_vol == market_vol the edge is exactly minus
    # the trading costs, so skew alone can never masquerade as an edge.
    scale = (view_vol / market_vol) if (view_vol and market_vol) else None
    cost = sum(abs(l["price"] - (l["mid"] or l["price"])) * l["lots"] for l in legs)
    market = {**stats(market_vol, 0.0), "ev_per_unit": round(-cost, 2), "ev_per_lot": round(-cost * lot_size, 0)}
    view = None
    if scale and all(l.get("iv") for l in legs):
        ev = 0.0
        fwd_view = fwd * math.exp(view_drift * t)
        for l in legs:
            fair = black76(fwd_view, l["strike"], t, l["iv"] / 100 * scale, l["type"] == "CE")
            ev += (1 if l["side"] == "BUY" else -1) * (fair - l["price"]) * l["lots"]
        view = {**stats(view_vol, view_drift), "ev_per_unit": round(ev, 2), "ev_per_lot": round(ev * lot_size, 0)}
    risk = abs(max_loss) if max_loss is not None else None
    return {
        "legs": legs, "net_debit": round(debit, 2), "max_gain_per_lot": round(max_gain * lot_size) if max_gain is not None else None,
        "max_loss_per_lot": round(max_loss * lot_size) if max_loss is not None else None,
        "unlimited_loss": unlimited_loss, "unlimited_gain": unlimited_gain, "breakevens": breakevens,
        "reward_risk": round(max_gain / risk, 2) if (max_gain and risk) else None,
        "market": market, "view": view,
        "edge_per_lot": round((view["ev_per_unit"]) * lot_size) if view else None,
        "cost_per_lot": round(cost * lot_size),
        "payoff_curve": [{"s": round(grid[i], 2), "pnl": round(pnl[i] * lot_size, 1)} for i in range(0, n + 1, 40)],
    }


def candidates(an: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Standard structures around the live ATM and the market's own 1σ move."""
    rows = {r["strike"]: r for r in an["strikes"]}
    ks = sorted(rows)
    if not ks or not an.get("expected_move"):
        return []
    atm = an["atm_strike"]
    i_atm = ks.index(atm)
    em = an["expected_move"]["one_sd"]
    step = min(b - a for a, b in zip(ks, ks[1:])) if len(ks) > 1 else 1

    def near(x: float) -> float:
        return min(ks, key=lambda k: abs(k - x))

    def off(n: int) -> float:
        return ks[max(0, min(len(ks) - 1, i_atm + n))]

    up1, dn1 = near(atm + em), near(atm - em)
    wing = max(step, round(em * 0.5 / step) * step)
    specs = [
        ("Long call", "bullish", [(atm, "CE", "BUY")]),
        ("Long put", "bearish", [(atm, "PE", "BUY")]),
        ("Bull call spread", "bullish", [(atm, "CE", "BUY"), (up1, "CE", "SELL")]),
        ("Bear put spread", "bearish", [(atm, "PE", "BUY"), (dn1, "PE", "SELL")]),
        ("Bull put credit spread", "bullish", [(dn1, "PE", "SELL"), (near(dn1 - wing), "PE", "BUY")]),
        ("Bear call credit spread", "bearish", [(up1, "CE", "SELL"), (near(up1 + wing), "CE", "BUY")]),
        ("Iron condor", "range", [(dn1, "PE", "SELL"), (near(dn1 - wing), "PE", "BUY"), (up1, "CE", "SELL"), (near(up1 + wing), "CE", "BUY")]),
        ("Long straddle", "high-volatility", [(atm, "CE", "BUY"), (atm, "PE", "BUY")]),
        ("Long strangle", "high-volatility", [(off(2), "CE", "BUY"), (off(-2), "PE", "BUY")]),
        ("Call butterfly", "range", [(near(atm - wing), "CE", "BUY"), (atm, "CE", "SELL"), (atm, "CE", "SELL"), (near(atm + wing), "CE", "BUY")]),
    ]
    out = []
    for name, view, spec in specs:
        legs = [leg(rows[k], kind, side) for k, kind, side in spec]
        if any(l is None for l in legs) or len({(l["strike"], l["type"]) for l in legs}) < len({(k, t) for k, t, _ in spec}):
            continue
        merged: Dict[tuple, Dict[str, Any]] = {}
        for l in legs:
            key = (l["strike"], l["type"], l["side"])
            if key in merged:
                merged[key]["lots"] += 1
            else:
                merged[key] = l
        sides = {}
        for (k, kind, side) in merged:
            sides.setdefault((k, kind), set()).add(side)
        if any(len(s) > 1 for s in sides.values()):
            continue  # rounding collapsed a spread onto one strike: not a real structure
        out.append({"name": name, "view": view, "legs": list(merged.values())})
    return out
