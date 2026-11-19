"""Plain-English meaning of a metric value: AI wording when a provider is configured, else static definitions."""
from __future__ import annotations

import math
import threading
from typing import Any, Dict, Optional, Tuple

from . import client
from .providers.base import Provider, ProviderError

DEFINITIONS: Dict[str, str] = {
    "pcr": "Put-call ratio of open interest: put OI divided by call OI; above 1 means more puts are open than calls, often read as put writers supporting the market.",
    "max_pain": "The settlement price at which option buyers' total intrinsic value is smallest; prices are sometimes drawn toward it into expiry, but it is not a forecast.",
    "gex": "Net dealer gamma exposure under the assumption that customers are net long options; positive tends to dampen moves, negative tends to amplify them.",
    "gamma_flip": "The strike where cumulative dealer gamma changes sign; above it moves tend to be dampened, below it amplified (under the same positioning assumption).",
    "rr25": "25-delta risk reversal: 25-delta put IV minus 25-delta call IV; positive means downside protection is priced richer than upside.",
    "iv_minus_rv": "Implied volatility minus realised volatility; positive means options price more movement than the underlying has actually shown.",
    "iv_percentile": "Share of recorded days on which ATM implied volatility was below today's; high means options are expensive relative to their own history.",
    "atm_iv": "Implied volatility of the at-the-money options, the market's annualised expected volatility for this expiry.",
    "expected_move": "One standard deviation move to expiry implied by ATM IV (about 68% of outcomes fall inside it if the IV is right).",
    "straddle": "Price of the ATM call plus ATM put; roughly 0.8 times the one-standard-deviation expected move.",
    "basis": "Futures price minus spot; reflects cost of carry, dividends and positioning demand.",
    "rollover": "Share of expiring futures positions carried into the next series; high rollover means traders are keeping positions.",
    "fii_long_pct": "FII long index-futures contracts as a share of their total long plus short; above 50% means FIIs are net long index futures.",
    "fii_net": "FII/FPI net cash-market buying minus selling in ₹ crore for the day (provisional NSE figure).",
    "dii_net": "Domestic institutions' net cash-market buying minus selling in ₹ crore for the day.",
    "delivery_pct": "Share of traded quantity that was taken for delivery rather than squared off intraday; high values suggest conviction buying or selling.",
    "long_buildup": "Price up with open interest up: new long positions are being added.",
    "short_buildup": "Price down with open interest up: new short positions are being added.",
    "short_covering": "Price up with open interest down: shorts are closing their positions.",
    "long_unwinding": "Price down with open interest down: longs are closing their positions.",
    "pop": "Probability of profit: model probability that the position ends with positive P&L at expiry, from the implied distribution.",
    "edge_after_costs": "Expected value per lot after brokerage, taxes and slippage, from the adviser's model; only positive edge passes the gate.",
    "oi_wall": "Strike with the largest open interest on one side; heavy call OI above spot is read as resistance, heavy put OI below as support.",
    "india_vix": "India VIX: NSE's 30-day implied volatility index for NIFTY options; higher means the market prices bigger moves.",
    "win_rate": "Share of closed recommendations in the ledger that ended with positive P&L, scored against real later prices.",
    "oi_change": "Change in open interest today: positive means new contracts were opened, negative means positions were closed.",
}
ALIASES = {"put_call_ratio": "pcr", "pcr_oi": "pcr", "skew": "rr25", "risk_reversal": "rr25", "ivp": "iv_percentile",
           "vix": "india_vix", "gamma_exposure": "gex", "net_gex": "gex", "edge": "edge_after_costs", "probability_of_profit": "pop"}

_cache: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
_lock = threading.Lock()


def _bucket(value: Any) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)[:40]
    if v == 0 or not math.isfinite(v):
        return str(v)
    mag = 10 ** (math.floor(math.log10(abs(v))) - 1)  # two significant figures
    return f"{round(v / mag) * mag:g}"


def _reading(metric: str, v: Optional[float]) -> str:
    """A rule-based second sentence for metrics with conventional thresholds."""
    if v is None:
        return ""
    if metric == "pcr":
        return "That is put-heavy positioning." if v > 1.2 else "That is call-heavy positioning." if v < 0.8 else "That is a balanced reading."
    if metric == "iv_percentile":
        return "Options are expensive versus their recorded history." if v >= 70 else "Options are cheap versus their recorded history." if v <= 30 else "Options are mid-range versus their recorded history."
    if metric == "rr25":
        return "Downside protection is bid." if v > 0 else "Upside calls are bid over puts." if v < 0 else ""
    if metric == "gex":
        return "Positive gamma regime: moves tend to be dampened." if v > 0 else "Negative gamma regime: moves tend to be amplified."
    if metric in ("fii_net", "dii_net"):
        return "They were net buyers." if v > 0 else "They were net sellers."
    if metric == "iv_minus_rv":
        return "Options are pricing more movement than realised." if v > 0 else "Options are pricing less movement than realised."
    return ""


def explain(metric: str, value: Any, context: Optional[Dict[str, Any]] = None, provider: Optional[Provider] = None) -> Dict[str, Any]:
    m = (metric or "").strip().lower().replace("-", "_").replace(" ", "_")
    m = ALIASES.get(m, m)
    definition = DEFINITIONS.get(m)
    sym = str((context or {}).get("symbol") or "").upper()
    key = (m, _bucket(value), sym)
    with _lock:
        if key in _cache:
            return _cache[key]
    try:
        fv: Optional[float] = float(value)
    except (TypeError, ValueError):
        fv = None
    text, source = None, "definitions"
    p = provider or client.get_provider()
    if p and definition:
        try:
            prompt = (f"Metric: {m}\nDefinition: {definition}\nValue: {value}" + (f"\nSymbol: {sym}" if sym else "") +
                      "\nIn exactly two plain-English sentences, say what this value means for a trader. Use only the value given; add no other numbers; give no trade advice.")
            res = p.chat([p.user(prompt)], [], "You explain market metrics briefly and accurately.", effort="low")
            if res.text and res.stop_reason != "refusal":
                text, source = res.text.strip(), p.name
        except ProviderError:
            pass
    if not text:
        if definition:
            text = f"{definition} Current value{(' for ' + sym) if sym else ''}: {value}. {_reading(m, fv)}".strip()
        else:
            text = f"No definition is available for '{metric}'."
            source = "none"
    out = {"metric": m, "value": value, "symbol": sym or None, "text": text, "source": source}
    with _lock:
        if len(_cache) > 2000:
            _cache.clear()
        _cache[key] = out
    return out
