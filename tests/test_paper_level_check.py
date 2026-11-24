"""Paper fills must accept tp=0 ("no take-profit"), as the live path does.

Signal-exit strategies (trend router, Donchian ETH) send tp_price=0.0; the paper
check used to reject every one of them.
"""
import math

from jarvis.execution.mt5_client import MT5Client

check = MT5Client._level_error


def test_no_take_profit_is_accepted():
    assert check("BUY", 100.0, 95.0, 0.0) is None
    assert check("SELL", 100.0, 105.0, 0.0) is None


def test_wrong_side_take_profit_still_rejected():
    assert "not above" in check("BUY", 100.0, 95.0, 99.0)
    assert "not below" in check("SELL", 100.0, 105.0, 101.0)


def test_bad_values_still_rejected():
    assert check("BUY", 100.0, 95.0, -1.0)
    assert check("BUY", 100.0, 95.0, math.nan)
    assert check("BUY", 100.0, 0.0, 110.0)      # stop-loss stays mandatory
    assert check("BUY", 100.0, 101.0, 0.0)      # SL on wrong side, even with no TP
