"""Pure calculations on real market data: spark parsing, technicals, pivots, 12-1 momentum and its backtest.

No I/O here; every input is a payload or bar list fetched from a real source by service.py
(or, in tests, a recorded real payload / a bar list built by an explicit formula).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..data.models import grade

Bar = Dict[str, float]


# ---------------------------------------------------------------- live prices

def parse_spark(payload: Dict[str, Any], ticker_to_symbol: Dict[str, str], session_open: bool) -> Dict[str, Dict[str, Any]]:
    """Yahoo /v8/finance/spark → symbol → {price, change_pct, prev_close, prov}. Graded by the last trade timestamp."""
    out: Dict[str, Dict[str, Any]] = {}
    for t, d in payload.items():
        sym = ticker_to_symbol.get(t)
        if not sym or not isinstance(d, dict):
            continue
        pts = [(ts, c) for ts, c in zip(d.get("timestamp") or [], d.get("close") or []) if c is not None]
        if not pts:
            continue
        ts, price = pts[-1]
        prev = d.get("previousClose") or d.get("chartPreviousClose")
        out[sym] = {"price": float(price), "prev_close": prev,
                    "change_pct": round((price - prev) / prev * 100, 3) if prev else None,
                    "prov": grade(f"yahoo:spark/{t}", float(ts), session_open, fresh_sec=120).to_dict()}
    return out


# ---------------------------------------------------------------- technicals

def sma(closes: List[float], n: int) -> Optional[float]:
    return round(sum(closes[-n:]) / n, 4) if len(closes) >= n else None


def rsi(closes: List[float], n: int = 14) -> Optional[float]:
    """Wilder's RSI."""
    if len(closes) <= n:
        return None
    d = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    up = sum(max(x, 0) for x in d[:n]) / n
    dn = sum(max(-x, 0) for x in d[:n]) / n
    for x in d[n:]:
        up = (up * (n - 1) + max(x, 0)) / n
        dn = (dn * (n - 1) + max(-x, 0)) / n
    return 100.0 if dn == 0 else round(100 - 100 / (1 + up / dn), 2)


def atr(bars: List[Bar], n: int = 14) -> Optional[float]:
    """Wilder's ATR on true range."""
    if len(bars) <= n:
        return None
    tr = [max(b["high"] - b["low"], abs(b["high"] - p["close"]), abs(b["low"] - p["close"])) for p, b in zip(bars, bars[1:])]
    a = sum(tr[:n]) / n
    for x in tr[n:]:
        a = (a * (n - 1) + x) / n
    return round(a, 4)


def realised_vol(closes: List[float], n: int = 20) -> Optional[float]:
    """Annualised (252) stdev of the last n daily log returns, in %."""
    if len(closes) <= n:
        return None
    r = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - n, len(closes))]
    m = sum(r) / n
    return round(math.sqrt(sum((x - m) ** 2 for x in r) / (n - 1) * 252) * 100, 2)


def technicals(bars: List[Bar], price: Optional[float]) -> Dict[str, Any]:
    """From closed daily bars. `price` (the live quote) is only used for distances; None → last close."""
    closes = [b["close"] for b in bars]
    px = price or (closes[-1] if closes else None)
    a = atr(bars)
    yr = bars[-252:]
    hi = max((b["high"] for b in yr), default=None)
    lo = min((b["low"] for b in yr), default=None)
    pct = lambda x: round((px - x) / x * 100, 2) if px and x else None  # noqa: E731
    s20, s50, s200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    return {"sma20": s20, "sma50": s50, "sma200": s200, "vs_sma20_pct": pct(s20), "vs_sma50_pct": pct(s50), "vs_sma200_pct": pct(s200),
            "rsi14": rsi(closes), "atr14": a, "atr_pct": round(a / px * 100, 2) if a and px else None,
            "high_52w": hi, "low_52w": lo, "from_high_52w_pct": pct(hi), "from_low_52w_pct": pct(lo),
            "realised_vol_20d": realised_vol(closes), "bars_used": len(bars)}


def pivots(bar: Bar) -> Dict[str, float]:
    """Classic floor pivots from one completed day's high/low/close."""
    h, l, c = bar["high"], bar["low"], bar["close"]
    p = (h + l + c) / 3
    lv = {"P": p, "R1": 2 * p - l, "S1": 2 * p - h, "R2": p + (h - l), "S2": p - (h - l), "R3": h + 2 * (p - l), "S3": l - 2 * (h - p)}
    return {k: round(v, 2) for k, v in lv.items()}


def risk_sizing(equity: float, risk_pct: float, atr_value: float, atr_mult: float, price: float) -> Dict[str, Any]:
    """Shares such that a stop atr_mult × ATR away loses risk_pct of equity. A calculator, not a recommendation."""
    dist = atr_mult * atr_value
    budget = equity * risk_pct / 100
    shares = int(budget // dist) if dist > 0 else 0
    return {"kind": "calculator", "note": "position-size arithmetic for your inputs; not a trade recommendation",
            "equity": equity, "risk_pct": risk_pct, "atr_mult": atr_mult, "stop_distance": round(dist, 4),
            "risk_budget": round(budget, 2), "shares": shares, "position_value": round(shares * price, 2),
            "position_pct_of_equity": round(shares * price / equity * 100, 2) if equity else None}


# ---------------------------------------------------------------- 12-1 momentum

def month_end_closes(bars: List[Bar], before_month: str) -> Dict[str, float]:
    """'YYYY-MM' → last daily close of that month, for completed months strictly before `before_month`."""
    out: Dict[str, float] = {}
    for b in bars:
        m = datetime.fromtimestamp(b["time"], timezone.utc).strftime("%Y-%m")
        if m < before_month:
            out[m] = b["close"]  # bars are time-ordered, so the last write is the month-end close
    return out


def momentum_12_1(series: List[float]) -> Optional[float]:
    """series = month-end closes ending at the formation month. Return over months t-12 → t-1 (skips the last month)."""
    if len(series) < 13 or not series[-13]:
        return None
    return series[-2] / series[-13] - 1


def rank(scores: Dict[str, float]) -> Dict[str, Dict[str, Any]]:
    """1 = strongest. percentile 100 = strongest, 0 = weakest."""
    order = sorted(scores, key=lambda s: -scores[s])
    n = len(order)
    return {s: {"rank": i + 1, "percentile": round((n - 1 - i) / (n - 1) * 100, 1) if n > 1 else 100.0,
                "top_quintile": i < top_n(n)} for i, s in enumerate(order)}


def top_n(n: int) -> int:
    return max(1, round(n / 5))


def momentum_backtest(monthly: Dict[str, Dict[str, float]], min_names: int = 10) -> List[Tuple[str, float, int]]:
    """Each month m (formation): rank by 12-1 momentum, hold the top quintile over month m+1, equal weight,
    vs the equal-weight eligible universe. Returns (holding month, excess return, names eligible).
    A symbol is eligible only if it has a real close at every month the signal and the holding need."""
    months = sorted({m for s in monthly.values() for m in s})
    out = []
    for i in range(12, len(months) - 1):
        need = months[i - 12:i + 2]
        elig = {s: c for s, c in monthly.items() if all(m in c for m in need)}
        if len(elig) < min_names:
            continue
        score = {s: c[months[i - 1]] / c[months[i - 12]] - 1 for s, c in elig.items()}
        fwd = {s: c[months[i + 1]] / c[months[i]] - 1 for s, c in elig.items()}
        top = sorted(score, key=lambda s: -score[s])[:top_n(len(elig))]
        out.append((months[i + 1], sum(fwd[s] for s in top) / len(top) - sum(fwd.values()) / len(fwd), len(elig)))
    return out


def excess_stats(rows: List[Tuple[str, float, int]]) -> Dict[str, Any]:
    ex = [r[1] for r in rows]
    n = len(ex)
    if n < 2:
        return {"months": n}
    m = sum(ex) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in ex) / (n - 1))
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in ex:
        eq *= 1 + x
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    return {"months": n, "from": rows[0][0], "to": rows[-1][0], "mean_excess_pct": round(m * 100, 3),
            "t_stat": round(m / (sd / math.sqrt(n)), 2) if sd else None,
            "pct_months_positive": round(sum(x > 0 for x in ex) / n * 100, 1),
            "max_drawdown_excess_pct": round(mdd * 100, 2), "cum_excess_pct": round((eq - 1) * 100, 2),
            "avg_names": round(sum(r[2] for r in rows) / n, 1)}
