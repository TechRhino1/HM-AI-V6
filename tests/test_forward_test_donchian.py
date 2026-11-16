"""Demo-only ETHUSD Donchian H4 forward test (2026-11-16)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from jarvis.forward_tests.donchian_eth_h4 import DonchianForwardTest, evaluate, TAG


def _bars(closes):
    c = np.asarray(closes, float)
    return pd.DataFrame({"time": pd.date_range("2026-01-01", periods=len(c), freq="4h"),
                         "open": c, "high": c + 1, "low": c - 1, "close": c})


def test_breakout_above_every_channel_is_long_on_all_three_systems():
    sig = evaluate(_bars(list(np.full(150, 100.0)) + [110.0]))
    assert all(s["entry"] == 1 for s in sig["systems"].values())
    assert sig["atr"] > 0


def test_a_close_below_the_exit_channel_flags_a_long_exit():
    sig = evaluate(_bars(list(np.full(150, 100.0)) + [90.0]))
    assert all(s["exit_long"] and s["entry"] == -1 for s in sig["systems"].values())


def _orch(mode="demo", positions=()):
    o = SimpleNamespace(mode=mode, mt5_client=MagicMock(), data_feed=MagicMock(),
                        circuit_breaker=MagicMock(), drawdown_guard=MagicMock())
    o.mt5_client.get_open_positions.return_value = list(positions)
    o.mt5_client.get_account_snapshot.return_value = SimpleNamespace(equity=545.0, balance=545.0, login=1, server="s")
    o.mt5_client.get_symbol_trading_spec.return_value = {"volume_min": 0.02, "volume_step": 0.01, "volume_max": 100,
                                                         "trade_contract_size": 1.0, "trade_tick_value": 0.01,
                                                         "trade_tick_size": 0.01}
    o.mt5_client.send_market_order.return_value = {"status": "FILLED", "ticket": 1, "position_id": 1, "price": 110.0}
    o.circuit_breaker.check_status.return_value = {"active": False}
    o.drawdown_guard.check_limits.return_value = {"passed": True}
    o.data_feed.fetch_rates.return_value = _bars(list(np.full(150, 100.0)) + [110.0])
    return o


def test_only_runs_in_demo():
    o = _orch(mode="live")
    DonchianForwardTest(o).step()
    o.data_feed.fetch_rates.assert_not_called()


def test_enters_tagged_orders_once_per_bar_and_respects_halts():
    o = _orch()
    ft = DonchianForwardTest(o)
    with patch("jarvis.data.database.TRADE_DB"):
        ft.step(); ft.step()                      # same bar twice -> acts once
    comments = [c.kwargs["comment"] for c in o.mt5_client.send_market_order.call_args_list]
    assert comments == [f"{TAG}_20", f"{TAG}_55", f"{TAG}_100"]
    o2 = _orch(); o2.drawdown_guard.check_limits.return_value = {"passed": False}
    DonchianForwardTest(o2).step()
    o2.mt5_client.send_market_order.assert_not_called()


def test_trails_never_loosens_and_exits_on_the_channel():
    long_pos = SimpleNamespace(ticket=7, type="BUY", sl=50.0, comment=f"{TAG}_20")
    o = _orch(positions=[long_pos])
    ft = DonchianForwardTest(o)
    ft._on_bar({"close": 110.0, "atr": 2.0, "systems": {20: {"entry": 1, "exit_long": False, "exit_short": False}}})
    assert o.mt5_client.modify_position.call_args.kwargs["sl"] == 104.0       # 110 - 3*2, up from 50
    long_pos.sl = 104.0
    o.mt5_client.modify_position.reset_mock()
    ft._on_bar({"close": 105.0, "atr": 2.0, "systems": {20: {"entry": 0, "exit_long": False, "exit_short": False}}})
    o.mt5_client.modify_position.assert_not_called()                           # 99 < 104: never loosens
    with patch("jarvis.data.database.TRADE_DB"):
        ft._on_bar({"close": 95.0, "atr": 2.0, "systems": {20: {"entry": -1, "exit_long": True, "exit_short": False}}})
    o.mt5_client.close_position.assert_called_once_with(7)


def test_the_position_monitor_leaves_forward_test_positions_alone():
    from jarvis.execution.position_monitor import PositionMonitorEngine
    mon = object.__new__(PositionMonitorEngine)
    mon._is_manual_trade = MagicMock(side_effect=AssertionError("must return before any management"))
    mon._manage_single_position(SimpleNamespace(comment=f"{TAG}_55", symbol="ETHUSD", ticket=9))
