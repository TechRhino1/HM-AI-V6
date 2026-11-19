"""Trade Style AUTO: pick, per symbol, the style+strategy that has actually earned its keep.

Score per (style, strategy) on a symbol = the backtest trust weight (ModeReliabilityModel) pulled
toward this symbol's live record by sample size, with the same tanh/K=30 shape mode_aggregator uses.
A combination with >= EXCLUDE_MIN_TRADES live trades and negative expectancy is excluded outright.
"""
from __future__ import annotations

import json
import math
import os
import time
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

SHRINK_K = 30            # same shrinkage constant as mode_aggregator
EXCLUDE_MIN_TRADES = 20
REGIME_MIN_TRADES = 10   # use the regime-specific record only once it has this many trades
_CACHE_TTL = 60.0


def auto_style_live() -> bool:
    """AUTO trades on its own picks only when JARVIS_AUTO_STYLE_LIVE is set; otherwise it is shadow-only."""
    return os.environ.get("JARVIS_AUTO_STYLE_LIVE", "").strip().lower() in ("1", "true", "yes", "on")


def strat_name(x: Any) -> str:
    """Strategy enums and their stored str() forms ("StrategyType.X") compare as the bare name."""
    return str(getattr(x, "value", x) or "UNKNOWN").split(".")[-1].upper()


def _style_of(row: Dict[str, Any]) -> str:
    r = row.get("reasoning")
    try:
        r = json.loads(r) if isinstance(r, str) else (r or {})
    except (TypeError, ValueError):
        r = {}
    return str((r or {}).get("trade_style") or "").upper() if isinstance(r, dict) else ""


def r_multiple(row: Dict[str, Any]) -> Optional[float]:
    """Realised R of a closed trade from its own entry/exit/stop; None when it can't be measured."""
    try:
        entry, exit_, sl = float(row["entry_price"]), float(row["exit_price"]), float(row["sl"])
    except (KeyError, TypeError, ValueError):
        return None
    risk = abs(entry - sl)
    if not (risk > 0 and math.isfinite(exit_)):
        return None
    sign = 1.0 if str(row.get("trade_type", "")).upper() == "BUY" else -1.0
    return sign * (exit_ - entry) / risk


def _stats(rs: List[float]) -> Tuple[int, float, float]:
    n = len(rs)
    if not n:
        return 0, 0.0, 0.0
    wins, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    return n, sum(rs) / n, (wins / losses if losses > 0 else float("inf") if wins > 0 else 0.0)


def score(symbol: str, style: str, strategy: str, rs: List[float], prior=None, source: str = "symbol") -> Dict[str, Any]:
    p = float(prior.weight(style, symbol)) if prior is not None else 0.5
    n, exp, pf = _stats(rs)
    raw = 0.5 + 0.5 * math.tanh(exp / 0.25)
    s = p + (raw - p) * n / (n + SHRINK_K)
    return {"style": style, "strategy": strategy, "score": round(s, 4), "n": n, "expectancy_r": round(exp, 3),
            "profit_factor": None if math.isinf(pf) else round(pf, 2), "prior": round(p, 4),
            "source": source if n else "backtest", "excluded": n >= EXCLUDE_MIN_TRADES and exp < 0}


def rank(symbol: str, regime: Optional[str], trades: Iterable[Dict[str, Any]], prior=None) -> List[Dict[str, Any]]:
    """Every (style, strategy) seen live for `symbol`, best score first."""
    sym = str(symbol).upper()
    pooled: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    by_regime: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    for t in trades:
        if str(t.get("symbol", "")).upper() != sym:
            continue
        r, style = r_multiple(t), _style_of(t)
        if r is None or not style:
            continue
        key = (style, strat_name(t.get("strategy")))
        pooled[key].append(r)
        if regime and str(t.get("regime") or "") == regime:
            by_regime[key].append(r)
    out = []
    for (style, strat), rs in pooled.items():
        reg = by_regime[(style, strat)]
        use_regime = len(reg) >= REGIME_MIN_TRADES
        out.append(score(sym, style, strat, reg if use_regime else rs, prior, "regime" if use_regime else "symbol"))
    return sorted(out, key=lambda d: d["score"], reverse=True)


def choose(symbol: str, candidates: List[Any], ranking: List[Dict[str, Any]], prior=None) -> Dict[str, Any]:
    """Among this cycle's actionable candidates for `symbol`, keep the one with the best
    arbiter utility x earned score. Returns {"pick": candidate|None, "detail": {...}}."""
    by_key = {(r["style"], r["strategy"]): r for r in ranking}
    best, best_val, best_info, considered = None, -1.0, None, 0
    for c in candidates:
        if c.symbol.upper() != symbol.upper() or not c.is_actionable or c.bias not in ("BUY", "SELL"):
            continue
        considered += 1
        st = strat_name(c.strategy)
        info = by_key.get((c.trade_style.upper(), st)) or score(symbol, c.trade_style.upper(), st, [], prior)
        if info["excluded"]:
            continue
        val = max(0.0, float(c.utility_score or 0.0)) * info["score"]
        if val > best_val:
            best, best_val, best_info = c, val, info
    if best is None:
        why = "no actionable setup" if not considered else "every actionable style/strategy is excluded by its live record"
        return {"pick": None, "detail": {"reason": why, "considered": considered}}
    return {"pick": best, "detail": dict(best_info, bias=best.bias, utility=round(float(best.utility_score or 0.0), 3),
                                         considered=considered, reason="best utility x earned score")}


class AutoStyleSelector:
    """Holds the closed-trade history and backtest prior, refreshed at most once a minute."""

    def __init__(self, trade_memory=None, prior=None):
        self._memory, self._prior, self._trades, self._at = trade_memory, prior, [], 0.0

    def _load(self) -> List[Dict[str, Any]]:
        if time.time() - self._at > _CACHE_TTL:
            try:
                self._trades = [t for t in (self._memory.fetch_all_trades() if self._memory else [])
                                if t.get("exit_price") is not None]
            except Exception:
                self._trades = []
            if self._prior is None:
                try:
                    from jarvis.intelligence.mode_aggregator import ModeReliabilityModel
                    self._prior = ModeReliabilityModel.from_report()
                except Exception:
                    self._prior = None
            self._at = time.time()
        return self._trades

    def choose(self, symbol: str, candidates: List[Any]) -> Dict[str, Any]:
        trades = self._load()
        regime = next((c.regime for c in candidates if c.symbol.upper() == symbol.upper() and c.is_actionable), None)
        return choose(symbol, candidates, rank(symbol, regime, trades, self._prior), self._prior)
