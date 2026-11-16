"""Server-side performance analytics over the canonical journal (executed_trades).

Groups CLOSED broker rows by account, symbol, strategy, style or exit reason and
reports the standard metrics (PerformanceMetricsCalculator) plus average R, where
R = realised P&L / the dollar risk at entry (|entry - initial stop| x volume x the
symbol's dollar value per price unit). Rows without a usable stop have no R.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Optional

GROUPS = ("account_login", "symbol", "strategy", "trade_style", "exit_reason")


def performance_report(db, group_by: str = "symbol", execution_mode: Optional[str] = None,
                       account_login: Optional[int] = None) -> Dict[str, Any]:
    from jarvis.backtesting.metrics import PerformanceMetricsCalculator
    from jarvis.data.symbol_registry import get_dollar_risk_per_price_unit

    if group_by not in GROUPS:
        raise ValueError(f"group_by must be one of {GROUPS}")
    where = ["closed_at IS NOT NULL", "realized_pnl IS NOT NULL", "origin = 'broker'"]
    params: list = []
    if execution_mode:
        where.append("execution_mode = ?"); params.append(execution_mode)
    if account_login is not None:
        where.append("account_login = ?"); params.append(int(account_login))
    rows = db._get_conn().execute(
        f"SELECT {group_by}, symbol, entry_price, sl, volume, realized_pnl FROM executed_trades "
        f"WHERE {' AND '.join(where)} ORDER BY closed_at", params,
    ).fetchall()

    buckets: Dict[str, list] = defaultdict(list)
    for key, sym, entry, sl, vol, pnl in rows:
        trade = {"pnl": float(pnl)}
        try:
            risk_usd = abs(float(entry) - float(sl)) * float(vol) * get_dollar_risk_per_price_unit(sym, None)
            if sl and risk_usd > 0:
                trade["r_multiple"] = float(pnl) / risk_usd
        except Exception:
            pass
        buckets["UNKNOWN" if key is None else str(key)].append(trade)

    groups = {k: PerformanceMetricsCalculator.calculate_metrics(v, initial_balance=1.0)
              for k, v in sorted(buckets.items())}
    for m in groups.values():  # % figures need a real starting equity; report $ and R only
        for k in ("max_drawdown_pct", "risk_of_ruin_pct", "multi_objective_fitness"):
            m.pop(k, None)
    return {"group_by": group_by, "execution_mode": execution_mode, "account_login": account_login,
            "closed_trades": len(rows), "groups": groups}
