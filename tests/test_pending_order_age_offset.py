"""Limit orders were cancelled ~1 s after placement (2026-11-23): "TTL expired (120.0m > 40.0m)"
on EURUSD #2004134695/#2004136695/#2004141637, which broker history shows lived exactly 1 s.
An age of exactly 7200 s means the converted UTC setup time was off by the broker offset again,
so the age must not depend on the derived offset: compare the raw broker time to the broker clock."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from jarvis.data.broker_time import pending_order_age
from jarvis.execution.order_manager import OrderManager

RAW = 1795456656          # time_setup of #2004134695 on the broker clock (UTC+2h)
OFFSET = 7200
SERVER_NOW = RAW + 1      # broker tick clock one second later
NOW = RAW - OFFSET + 1    # real UTC one second later


def test_correct_offset_age_is_one_second():
    assert pending_order_age(RAW - OFFSET, NOW, SERVER_NOW, raw_setup=RAW) == 1


def test_doubled_offset_does_not_age_the_order():
    assert pending_order_age(RAW - 2 * OFFSET, NOW, SERVER_NOW, raw_setup=RAW) == 1


def test_legacy_two_clock_behaviour_without_raw():
    now, server_now = 1_000_000.0, 1_000_000.0 + OFFSET
    assert pending_order_age(now - 31 * 60, now, server_now) == 31 * 60
    assert pending_order_age(server_now - 35 * 60, now, server_now) == 35 * 60
    assert pending_order_age(0, now, server_now) == 0.0


def test_order_manager_keeps_fresh_order_despite_doubled_offset():
    client = MagicMock()
    client.get_pending_orders.return_value = [{
        "ticket": 2004134695, "symbol": "EURUSD#", "type": "SELL_LIMIT", "price_open": 1.1,
        "sl": 1.11, "tp": 1.08, "comment": "HMA2_SWNG_TREN_DEMO",
        "time_setup": RAW - 2 * OFFSET, "time_setup_raw": RAW}]
    client.get_broker_time.return_value = float(SERVER_NOW)
    om = OrderManager(mt5_client=client)
    om._now = lambda: float(NOW)
    assert om.cleanup_stale_pending_orders(max_age_sec=600) == []
    client.cancel_pending_order.assert_not_called()
