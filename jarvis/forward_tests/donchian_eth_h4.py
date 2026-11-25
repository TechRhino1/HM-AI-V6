"""Demo-only forward test: ETHUSD Donchian ensemble on H4.

Source: reports/CRYPTO_GOLD_RESEARCH_2026-11-16.md (rank 1: +0.22R over 1,042
trades after costs and swaps; beat always-long and flipped since 2023). The
rules are identical to ``donchian()`` in tools/strategy_research.py, unchanged:

* three independent sub-systems, one position each, with (entry, exit) lookbacks
  (20, 10), (55, 20), (100, 20);
* on a COMPLETED H4 bar: long when the close is above the prior n_in-bar high,
  short when it is below the prior n_in-bar low;
* initial stop 3 x ATR(14); trailed at 3 x ATR from each later close, never loosened;
* exit when the close crosses the opposite prior n_out-bar channel; no take-profit.

Sizing follows the risk policy: the 1% target is split across the three
sub-systems; a broker-minimum lot is allowed up to the 2.5% min-lot ceiling,
otherwise the entry is skipped. Daily/weekly/drawdown halts and the circuit
breaker are honoured. The position monitor leaves these positions to this module.

Pre-registered promotion rule: >= 100 closed trades and a live mean of
>= +0.05R after costs and swaps (GET /api/analytics/performance?by=strategy).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np
import pandas as pd

logger = logging.getLogger("JARVIS_ForwardTest")

SYMBOL = "ETHUSD"
TAG = "FT_DCH_H4"
STRATEGY = "DONCHIAN_ENSEMBLE_H4"
STYLE = "H4_TREND"
SYSTEMS = ((20, 10), (55, 20), (100, 20))
STOP_ATR = 3.0
ENABLED_MODES = ("demo",)


def evaluate(df: pd.DataFrame) -> Dict[str, Any]:
    """Signals on the LAST bar of ``df`` (completed H4 bars, oldest first)."""
    h, l, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.c_[h - l, np.abs(h - pc), np.abs(l - pc)], axis=1)
    atr = float(pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
    out = {"close": float(c[-1]), "atr": atr, "systems": {}}
    for n_in, n_out in SYSTEMS:
        prior_hi_in, prior_lo_in = h[-n_in - 1:-1].max(), l[-n_in - 1:-1].min()
        prior_hi_out, prior_lo_out = h[-n_out - 1:-1].max(), l[-n_out - 1:-1].min()
        out["systems"][n_in] = {
            "entry": 1 if c[-1] > prior_hi_in else (-1 if c[-1] < prior_lo_in else 0),
            "exit_long": bool(c[-1] < prior_lo_out),
            "exit_short": bool(c[-1] > prior_hi_out),
        }
    return out


class DonchianForwardTest:
    def __init__(self, orchestrator):
        self.orch = orchestrator
        self._last_bar = None

    def step(self) -> None:
        """Act once per newly completed H4 bar. Never raises into the trading loop."""
        try:
            from jarvis.forward_tests.research_leads import forward_test_enabled
            if not forward_test_enabled(self.orch):
                return
            df = self.orch.data_feed.fetch_rates(SYMBOL, timeframe="H4", num_bars=300, include_current_bar=False)
            if df is None or len(df) < 150 or "SYNTHETIC" in str(getattr(df, "attrs", {}).get("data_source", "")).upper():
                return
            bar = df["time"].iloc[-1] if "time" in df.columns else df.index[-1]
            if bar == self._last_bar:
                return
            self._last_bar = bar
            self._on_bar(evaluate(df))
        except Exception as e:
            logger.warning("Forward test %s step failed: %s", TAG, e)

    def _mine(self) -> Dict[int, Any]:
        out = {}
        for p in self.orch.mt5_client.get_open_positions() or []:
            com = str(getattr(p, "comment", "") or "")
            if com.startswith(TAG + "_"):
                try:
                    out[int(com.rsplit("_", 1)[1])] = p
                except ValueError:
                    pass
        return out

    def _halted(self) -> bool:
        acct = self.orch.mt5_client.get_account_snapshot()
        if self.orch.circuit_breaker.check_status().get("active"):
            return True
        return not self.orch.drawdown_guard.check_limits(acct.equity, acct.balance).get("passed", False)

    def _on_bar(self, sig: Dict[str, Any]) -> None:
        client, close, atr = self.orch.mt5_client, sig["close"], sig["atr"]
        mine = self._mine()
        for n_in, s in sig["systems"].items():
            pos = mine.get(n_in)
            if pos is not None:
                is_buy = str(pos.type).upper() == "BUY"
                if (is_buy and s["exit_long"]) or (not is_buy and s["exit_short"]):
                    res = client.close_position(pos.ticket)
                    if res and res.get("status") in ("CLOSED", "PARTIALLY_CLOSED"):
                        from jarvis.data import database
                        database.TRADE_DB.set_exit_reason(pos.ticket, f"{TAG}_CHANNEL_EXIT")
                    logger.info("%s_%s channel exit #%s: %s", TAG, n_in, pos.ticket, res)
                    continue
                trail = close - STOP_ATR * atr if is_buy else close + STOP_ATR * atr
                new_sl = max(pos.sl, trail) if is_buy else (min(pos.sl, trail) if pos.sl > 0 else trail)
                if abs(new_sl - pos.sl) > 1e-9:
                    client.modify_position(pos.ticket, sl=new_sl, tp=0.0)
                continue
            if s["entry"] == 0 or self._halted():
                continue
            self._enter(n_in, s["entry"], close, atr)

    def _enter(self, n_in: int, side: int, close: float, atr: float) -> None:
        from jarvis.config.settings import SETTINGS
        from jarvis.risk.position_sizing import PositionSizer

        client = self.orch.mt5_client
        acct = client.get_account_snapshot()
        spec = client.get_symbol_trading_spec(SYMBOL) or {}
        stop = close - STOP_ATR * atr if side == 1 else close + STOP_ATR * atr
        lots = PositionSizer.calculate_lot_size(
            account_balance=acct.equity, entry_price=close, sl_price=stop,
            risk_pct=float(SETTINGS.risk.max_risk_per_trade_pct) / len(SYSTEMS),
            symbol_info={**spec, "name": SYMBOL},
        )
        if lots <= 0:
            logger.info("%s_%s entry skipped: minimum lot exceeds the risk policy.", TAG, n_in)
            return
        order = "BUY" if side == 1 else "SELL"
        from jarvis.forward_tests.research_leads import gated_forward_entry
        res = gated_forward_entry(self.orch, SYMBOL, order, lots, stop, 0.0, close,
                                  comment=f"{TAG}_{n_in}", style=STYLE, strategy=STRATEGY)
        logger.info("%s_%s %s %.2f lots @~%.2f stop %.2f: %s", TAG, n_in, order, lots, close, stop, res)
        if res and res.get("status") in ("FILLED", "PARTIAL", "POSITION_CONFIRMED"):
            from jarvis.data import database
            database.TRADE_DB.log_trade(
                ticket=res.get("ticket"), position_id=res.get("position_id"), symbol=SYMBOL, action=order,
                entry=float(res.get("price") or close), sl=stop, tp=0.0, volume=lots, score=0.0,
                regime="FORWARD_TEST", ev=None, origin="broker",
                execution_mode=str(getattr(self.orch, "mode", "demo")).lower(),
                account_login=getattr(acct, "login", None), server=getattr(acct, "server", None),
                strategy=STRATEGY, trade_style=STYLE, planned_rr=None,
            )
