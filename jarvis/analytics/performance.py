"""Server-side performance analytics over the canonical journal (executed_trades).

Groups CLOSED broker rows by account, symbol, strategy, style or exit reason and
reports the standard metrics (PerformanceMetricsCalculator) plus average R, where
R = realised P&L / the dollar risk at entry (|entry - initial stop| x volume x the
symbol's dollar value per price unit). Rows without a usable stop have no R.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Optional

GROUPS = ("account_login", "symbol", "strategy", "trade_style", "exit_reason", "symbol_style")
# SQL for groups that are not a single column.
_GROUP_SQL = {"symbol_style": "symbol || '|' || COALESCE(trade_style, '?')"}


def net_r_multiple(symbol: Any, entry: Any, sl: Any, volume: Any, pnl: Any) -> Optional[float]:
    """THE live R of a closed trade: net realised P&L over the dollar risk at the entry stop.

    The close event's P&L is the sum over EVERY deal of the position (partial closes, swap and
    both commissions included), and executed_trades keeps the entry volume and entry stop, so
    this is right for a position half-closed at +1R and trailed out, which a price R from the
    final exit misreads (+0.65R recorded as +0.3R). None when it cannot be measured.
    One definition for the performance report, AUTO, quarantine, drift, ML/bandit and probation.
    """
    try:
        if pnl is None or not entry or not sl or not volume:
            return None
        from jarvis.data.symbol_registry import get_dollar_risk_per_price_unit
        risk_usd = abs(float(entry) - float(sl)) * float(volume) * float(get_dollar_risk_per_price_unit(symbol, None) or 0.0)
        if not (risk_usd > 0):
            return None
        return float(pnl) / risk_usd
    except (TypeError, ValueError):
        return None


def performance_report(db, group_by: str = "symbol", execution_mode: Optional[str] = None,
                       account_login: Optional[int] = None) -> Dict[str, Any]:
    from jarvis.backtesting.metrics import PerformanceMetricsCalculator

    if group_by not in GROUPS:
        raise ValueError(f"group_by must be one of {GROUPS}")
    where = ["closed_at IS NOT NULL", "realized_pnl IS NOT NULL", "origin = 'broker'"]
    params: list = []
    if execution_mode:
        where.append("execution_mode = ?"); params.append(execution_mode)
    if account_login is not None:
        where.append("account_login = ?"); params.append(int(account_login))
    conn = db._get_conn()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(executed_trades)").fetchall()}
    xq = [c for c in ("requested_price", "fill_price", "spread_at_fill", "fill_latency_ms") if c in cols]
    key_sql = _GROUP_SQL.get(group_by, group_by)
    rows = conn.execute(
        f"SELECT {key_sql}, symbol, entry_price, sl, volume, realized_pnl, action"
        + "".join(f", {c}" for c in xq)
        + f" FROM executed_trades WHERE {' AND '.join(where)} ORDER BY closed_at", params,
    ).fetchall()

    buckets: Dict[str, list] = defaultdict(list)
    quality: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        key, sym, entry, sl, vol, pnl, action = row[:7]
        extra = dict(zip(xq, row[7:]))
        trade = {"pnl": float(pnl)}
        r = net_r_multiple(sym, entry, sl, vol, pnl)
        if r is not None:
            trade["r_multiple"] = r
        k = "UNKNOWN" if key is None else str(key)
        buckets[k].append(trade)
        req, fill = extra.get("requested_price"), extra.get("fill_price")
        if req and fill and sl and entry:
            # adverse slippage in R: positive = filled worse than requested
            sign = 1.0 if str(action or "BUY").upper().startswith("BUY") else -1.0
            quality[k]["slippage_r"].append(sign * (float(fill) - float(req)) / abs(float(entry) - float(sl)))
        for c in ("spread_at_fill", "fill_latency_ms"):
            if extra.get(c) is not None:
                quality[k][c].append(float(extra[c]))

    groups = {k: PerformanceMetricsCalculator.calculate_metrics(v, initial_balance=1.0)
              for k, v in sorted(buckets.items())}
    for k, m in groups.items():  # % figures need a real starting equity; report $ and R only
        for drop in ("max_drawdown_pct", "risk_of_ruin_pct", "multi_objective_fitness"):
            m.pop(drop, None)
        m["execution"] = {f"avg_{c}": round(sum(v) / len(v), 4) for c, v in quality[k].items() if v}
        m["execution"]["measured_fills"] = len(quality[k].get("slippage_r", []))
    return {"group_by": group_by, "execution_mode": execution_mode, "account_login": account_login,
            "closed_trades": len(rows), "groups": groups}
