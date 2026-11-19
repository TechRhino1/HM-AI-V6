"""India F&O adviser: reads the live chain like a derivatives desk, compares every standard
strategy at executable prices, and recommends one only when the evidence clears the gates.

Edge, honestly stated: under the market's own implied distribution every option strategy is
worth about minus its trading costs. A recommendation therefore needs a *measurable* reason
the market is mispricing: implied vol vs realised vol (the volatility risk premium), or a
direction model that has passed out-of-sample validation. Indicators that have not been
validated (trend, PCR, OI positioning) are shown as context and only choose which family of
strategies to consider; they never inflate expected value.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from ..data import feeds
from ..data.models import TRUSTED_KINDS
from ..data.nse import SourceError
from ..options import chain_analytics, expiry, premium_forecast, strategies, volatility

logger = logging.getLogger(__name__)
INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
MAX_LEG_SPREAD_PCT = {"index": 2.0, "stock": 5.0}


def _direction_evidence(an: Dict[str, Any], vol: Dict[str, Any]) -> Dict[str, Any]:
    """Unvalidated context, kept separate from expected value. Score in [-3, 3]."""
    notes, score = [], 0
    tr = (vol.get("trend") or {}).get("label")
    if tr == "uptrend":
        score += 1; notes.append("Daily trend up (close > SMA20 > SMA50, SMA20 rising)")
    elif tr == "downtrend":
        score -= 1; notes.append("Daily trend down (close < SMA20 < SMA50, SMA20 falling)")
    else:
        notes.append("No daily trend: price is ranging around its moving averages")
    pos = an["positioning"]["bias"]
    if pos.startswith("bullish"):
        score += 1; notes.append(f"Option writers lean bullish today: {pos}")
    elif pos.startswith("bearish"):
        score -= 1; notes.append(f"Option writers lean bearish today: {pos}")
    pcr = an["pcr"]["oi"]
    if pcr is not None:
        if pcr >= 1.2:
            score += 1; notes.append(f"PCR (OI) {pcr}: heavy put writing under the market")
        elif pcr <= 0.7:
            score -= 1; notes.append(f"PCR (OI) {pcr}: heavy call writing above the market")
        else:
            notes.append(f"PCR (OI) {pcr}: balanced")
    lean = "bullish" if score >= 2 else "bearish" if score <= -2 else "neutral"
    return {"score": score, "lean": lean, "notes": notes, "validated": False}


def _family_allowed(view: str, lean: str, vol: Dict[str, Any]) -> Optional[str]:
    """Returns a rejection reason, or None when the strategy family fits the evidence."""
    rich = (vol.get("iv_minus_rv20") or 0) > 2
    cheap = (vol.get("iv_minus_rv20") or 0) < -1
    if view == "bullish" and lean == "bearish":
        return "contradicts the bearish evidence"
    if view == "bearish" and lean == "bullish":
        return "contradicts the bullish evidence"
    if view == "high-volatility" and not cheap:
        return "buying volatility needs IV below realised volatility"
    if view == "range" and lean != "neutral":
        return f"range strategies need neutral evidence (lean is {lean})"
    if view in ("bullish", "bearish") and lean == "neutral" and not rich and not cheap:
        return "no directional evidence and options fairly priced"
    return None


def advise(symbol: str, expiry_date: Optional[str] = None) -> Dict[str, Any]:
    sym = symbol.upper()
    try:
        chain = feeds.chain(sym, expiry_date)
    except SourceError as exc:
        return {"symbol": sym, "status": "UNAVAILABLE", "reason": str(exc),
                "prov": feeds.unavailable("nse/bse option chain", str(exc)).to_dict()}
    an = chain_analytics.analyse(chain)
    prov = chain.prov.to_dict()
    vol = volatility.regime(sym, an["atm_iv"])
    evidence = _direction_evidence(an, vol)
    kind = "index" if sym in INDICES else "stock"
    base = {"symbol": sym, "kind": kind, "prov": prov, "analytics": {k: v for k, v in an.items() if k != "strikes"},
            "volatility": vol, "evidence": evidence, "expiry_desk": expiry.desk(an)}
    base["institutional"] = _institutional(sym, kind, an)

    if base["institutional"].get("in_ban"):
        return {**base, "status": "NO_TRADE", "reason": f"in F&O ban (NSE ban list for {base['institutional']['ban_trade_date']}): no new positions allowed"}
    if prov["kind"] not in TRUSTED_KINDS:
        return {**base, "status": "NO_TRADE", "reason": f"chain data is {prov['kind']}: recommendations need live or closing data"}
    if not an["atm_iv"] or not vol.get("available") or not vol.get("forecast_vol"):
        return {**base, "status": "NO_TRADE", "reason": "implied or realised volatility unavailable, so expected value cannot be measured"}

    market_vol = an["atm_iv"] / 100
    view_vol = vol["forecast_vol"]
    lot = an["lot_size"] or 1
    from ..signals import direction
    dv = direction.validated_view(sym, "IN", view_vol)
    base["direction_model"] = {k: v for k, v in dv.items() if k != "record"}
    base["vrp_history"] = direction.registry().get("vrp", {}).get("IN:NIFTY")
    evaluated, chosen = [], None
    for c in strategies.candidates(an):
        r = strategies.evaluate(c["legs"], an["forward"], an["years_to_expiry"], market_vol, view_vol, lot,
                                view_drift=dv["drift"] if dv.get("validated") else 0.0)
        reasons = []
        fam = _family_allowed(c["view"], evidence["lean"], vol)
        if fam:
            reasons.append(fam)
        if r["unlimited_loss"]:
            reasons.append("unlimited loss: the adviser only recommends defined-risk trades")
        wide = [l for l in c["legs"] if (l["spread_pct"] or 99) > MAX_LEG_SPREAD_PCT[kind]]
        if wide:
            reasons.append(f"illiquid leg: {wide[0]['type']} {wide[0]['strike']:g} spread {wide[0]['spread_pct'] or 0:.1f}%")
        if r["edge_per_lot"] is None or r["edge_per_lot"] <= 0:
            reasons.append(f"no edge after costs: expected ₹{r['edge_per_lot']}/lot under the realised-vol view")
        elif r["edge_per_lot"] < 2 * r["cost_per_lot"] or (r["max_loss_per_lot"] and r["edge_per_lot"] < 0.01 * abs(r["max_loss_per_lot"])):
            reasons.append(f"edge too thin: ₹{r['edge_per_lot']}/lot vs cost ₹{r['cost_per_lot']} and max loss ₹{abs(r['max_loss_per_lot'] or 0)}")
        row = {"name": c["name"], "view": c["view"], **r, "rejected": reasons}
        evaluated.append(row)
        if not reasons:
            ret = r["edge_per_lot"] / abs(r["max_loss_per_lot"]) if r["max_loss_per_lot"] else 0
            if chosen is None or ret > chosen[0]:
                chosen = (ret, row)

    evaluated.sort(key=lambda x: (len(x["rejected"]), -(x["edge_per_lot"] or -1e18)))
    if not chosen:
        return {**base, "status": "NO_TRADE", "strategies": evaluated,
                "reason": "no strategy passed every gate (edge after costs, defined risk, liquidity, fit with the evidence)"}

    best = chosen[1]
    plan = _plan(best, an, lot)
    return {**base, "status": "RECOMMEND", "recommendation": best, "plan": plan, "strategies": evaluated,
            "reasoning": _reasoning(best, an, vol, evidence)}


def _institutional(sym: str, kind: str, an: Dict[str, Any]) -> Dict[str, Any]:
    """Exchange-published institutional context (jarvis/markets/inst.py). Unvalidated: shown, never used in
    expected value. Each part is independent; a failed source leaves that part out with its error."""
    from .. import inst
    from datetime import datetime, timedelta
    from ..data.nse import IST
    out: Dict[str, Any] = {"validated": False, "notes": []}
    reg = _inst_registry()
    out["validated"] = bool(reg.get("published"))
    out["validation"] = reg.get("reason") or "not validated yet (tools/markets_model_validation.py)"
    try:
        p = inst.participants(5)
        fii = ((p.get("latest") or {}).get("participants") or {}).get("FII")
        if fii:
            out["fii_index_futures"] = {"date": p["latest"]["date"], "long_pct": fii["fut_idx_long_pct"],
                                        "long_pct_chg": fii.get("fut_idx_long_pct_chg"), "net_contracts": fii["net_idx_fut"],
                                        "net_chg": fii.get("net_idx_fut_chg"), "prov": p["prov"]}
            out["notes"].append(f"FII index futures {fii['fut_idx_long_pct']}% long on {p['latest']['date']}"
                                + (f" ({fii['fut_idx_long_pct_chg']:+.2f} pts d/d)" if fii.get("fut_idx_long_pct_chg") is not None else ""))
    except Exception as exc:
        out["fii_index_futures_error"] = str(exc)
    try:
        f = inst.futures_for(sym)
        if f:
            n = f["near"]
            out["futures"] = {"expiry": n["expiry"], "ltp": n["ltp"], "spot": n["spot"], "basis": n["basis"],
                              "basis_ann_pct": n["basis_ann_pct"], "oi": n["oi"], "oi_change": n["oi_change"],
                              "buildup": n["buildup"], "rollover_pct": f["rollover_pct"], "prov": f["prov"]}
            out["notes"].append(f"Near future {n['expiry']} basis {n['basis']:+.2f} ({n['basis_ann_pct']:+.2f}% annualised)"
                                + (f", {n['buildup'].replace('_', ' ')}" if n.get("buildup") else ""))
            if n["days_to_expiry"] <= 7 and f["rollover_pct"] is not None:  # futures expiry week
                out["notes"].append(f"Expiry week: rollover {f['rollover_pct']}% of futures OI already in later months")
    except Exception as exc:
        out["futures_error"] = str(exc)
    if kind == "stock":
        try:
            b = inst.ban()
            if b.get("trade_date"):
                out["ban_trade_date"] = b["trade_date"]
                out["in_ban"] = sym in b["symbols"]
        except Exception as exc:
            out["ban_error"] = str(exc)
        try:
            until = (datetime.now(IST) + timedelta(days=float(an.get("days_to_expiry") or 0) + 1)).date().isoformat()
            ev = inst.events_for(sym, until)
            out["events"] = ev
            if ev:
                out["event_risk"] = True
                out["notes"].append("Event risk before expiry: " + "; ".join(f"{e['purpose']} on {e['date']}" for e in ev))
        except Exception as exc:
            out["events_error"] = str(exc)
    return out


def _inst_registry() -> Dict[str, Any]:
    from ..signals import direction
    return (direction.registry() or {}).get("institutional") or {}


def _plan(best: Dict[str, Any], an: Dict[str, Any], lot: int) -> Dict[str, Any]:
    debit = best["net_debit"]
    is_credit = debit < 0
    first_long = next((l for l in best["legs"] if l["side"] == "BUY"), best["legs"][0])
    pf = None
    if first_long.get("iv"):
        pf = premium_forecast.forecast(an["forward"], first_long["strike"], first_long["type"] == "CE", first_long["iv"],
                                       an["years_to_expiry"], min(1.0, an["days_to_expiry"]), first_long["price"])
    if is_credit:
        credit = -debit
        target = {"close_at_net_debit": round(credit * 0.5, 2), "rule": "buy back at 50% of the credit received"}
        stop = {"close_at_net_debit": round(credit * 2.0, 2), "rule": "exit if the spread costs 2× the credit, or spot closes beyond a short strike"}
        trail = "after 50% of max profit, tighten the stop to break-even on the spread"
    else:
        target = {"close_at_net_credit": round(debit + (best["max_gain_per_lot"] or debit * lot) / lot * 0.6, 2) if best["max_gain_per_lot"] else round(debit * 2, 2),
                  "rule": "take profit at 60% of the maximum gain (spreads) or 2× premium (single options)"}
        stop = {"close_at_net_credit": round(debit * 0.5, 2), "rule": "exit if the position loses half its premium"}
        trail = "once at +50%, trail the stop to entry; at +100%, trail to +50%"
    return {
        "entry": {"net": round(abs(debit), 2), "type": "credit" if is_credit else "debit",
                  "zone": [round(abs(debit) * 0.98, 2), round(abs(debit) * 1.02, 2)],
                  "orders": [{"side": l["side"], "lots": l["lots"], "contract": f"{an['symbol']} {an['expiry']} {l['strike']:g} {l['type']}",
                              "limit": l["price"]} for l in best["legs"]]},
        "target": target, "stop": stop, "trailing": trail,
        "max_loss_per_lot": best["max_loss_per_lot"], "max_gain_per_lot": best["max_gain_per_lot"],
        "breakevens": best["breakevens"], "reward_risk": best["reward_risk"],
        "premium_forecast": pf,
    }


def _reasoning(best, an, vol, evidence) -> List[str]:
    out = [
        f"{best['name']} chosen: expected ₹{best['edge_per_lot']}/lot after costs under realised volatility "
        f"({vol['forecast_vol'] * 100:.1f}%) vs the market's implied {an['atm_iv']:.1f}%.",
        f"Probability of profit {best['view']['pop'] if best['view'] else '—'}% under that view; {best['market']['pop']}% under the market's own pricing.",
        f"Max loss ₹{best['max_loss_per_lot']}/lot; breakevens {', '.join(f'{b:g}' for b in best['breakevens'])}.",
        f"Market expects ±{an['expected_move']['one_sd']:.0f} ({an['expected_move']['one_sd_pct']:.2f}%) by expiry; "
        f"max pain {an['max_pain']:g}; resistance {an['walls']['resistance'][0]['strike']:g}, support {an['walls']['support'][0]['strike']:g}.",
    ]
    if vol.get("vol_view"):
        out.append(f"Volatility: {vol['vol_view']} (IV − RV20 = {vol['iv_minus_rv20']:+.1f} pts).")
    from ..signals import direction
    vrp = direction.registry().get("vrp", {}).get("IN:NIFTY") or {}
    if vrp.get("available"):
        out.append(f"History: India VIX exceeded the next month's realised NIFTY volatility on {vrp['iv_above_rv_pct']}% of "
                   f"{vrp['days']} days since {vrp['from']} (mean {vrp['mean_iv_minus_rv']:+.1f} pts; worst 5% {vrp['worst_5pct']:+.1f}).")
    out.append("No price-direction model has beaten the base rate out of sample, so no directional forecast is used.")
    out.append("Context (not validated, used only to pick the strategy family): " + "; ".join(evidence["notes"]))
    return out


def scan(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run the adviser across the indices plus today's most active F&O stocks (by NSE OI spurts)."""
    syms = list(symbols or INDICES)
    if not symbols:
        spurts = feeds.oi_spurts().get("rows") or []
        stocks = [r["symbol"] for r in spurts if r.get("symbol") and r["symbol"] not in INDICES and r["symbol"] != "NIFTYNXT50"]
        syms += stocks[:10]
    t = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(lambda s: _safe(s), syms))
    recs = [r for r in results if r.get("status") == "RECOMMEND"]
    from .. import ledger
    for r in recs:
        try:
            ledger.record(r)
        except Exception as exc:
            logger.warning("ledger record %s failed: %s", r["symbol"], exc)
    recs.sort(key=lambda r: -(r["recommendation"]["edge_per_lot"] / max(1, abs(r["recommendation"]["max_loss_per_lot"] or 1))))
    summary = [{"symbol": r["symbol"], "status": r["status"], "reason": r.get("reason"),
                "recommendation": (r.get("recommendation") or {}).get("name"),
                "edge_per_lot": (r.get("recommendation") or {}).get("edge_per_lot"),
                "lean": (r.get("evidence") or {}).get("lean"), "prov": r.get("prov")} for r in results]
    return {"scanned": len(results), "seconds": round(time.time() - t, 1), "opportunities": recs, "summary": summary}


def _safe(sym: str) -> Dict[str, Any]:
    try:
        return advise(sym)
    except Exception as exc:
        logger.warning("adviser %s failed: %s", sym, exc)
        return {"symbol": sym, "status": "ERROR", "reason": f"{type(exc).__name__}: {exc}",
                "prov": feeds.unavailable("adviser", str(exc)).to_dict()}
