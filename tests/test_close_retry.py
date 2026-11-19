"""A close whose exit deal MT5 has not published yet is retried, not dropped (audit 2026-11-18)."""
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

from jarvis.execution.state_synchronizer import MT5StateSynchronizer


def _sync(deals_seq):
    client = SimpleNamespace(mode="live", _shared_lock=threading.Lock())
    bus = MagicMock()
    s = MT5StateSynchronizer(mt5_client=client, state_manager=MagicMock(), event_bus=bus)
    fake = ModuleType("MetaTrader5")
    fake.history_deals_get = MagicMock(side_effect=deals_seq)
    return s, bus, fake


def _deal(entry, price, profit=0.0):
    return SimpleNamespace(entry=entry, price=price, profit=profit, swap=0.0, commission=-0.1, symbol="EURUSD")


def test_lagging_exit_deal_is_retried(monkeypatch):
    s, bus, fake = _sync([[_deal(0, 1.1)], [_deal(0, 1.1), _deal(1, 1.2, profit=5.0)]])
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    s._pending_closes[42] = time.time()
    acct = SimpleNamespace(equity=500.0)
    assert s._emit_trade_closed(42, acct) is False  # entry deal only: wait
    bus.publish_sync.assert_not_called()
    assert s._emit_trade_closed(42, acct) is True
    payload = bus.publish_sync.call_args[0][1]
    assert payload["exit_price"] == 1.2 and round(payload["pnl"], 2) == 4.8 and payload["is_win"] == 1


def test_expired_close_is_emitted_unmeasured(monkeypatch):
    s, bus, fake = _sync([[]])
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    s._pending_closes[7] = time.time() - s.CLOSE_RETRY_SEC - 1
    assert s._emit_trade_closed(7, SimpleNamespace(equity=1.0)) is True
    assert "pnl" not in bus.publish_sync.call_args[0][1]


def test_position_that_reappears_is_not_closed(monkeypatch):
    # 2026-11-18 16:36:51: four open FT positions dropped out of one snapshot, sat in
    # _pending_closes, and were journaled closed with no P&L while still open at the broker.
    s, bus, fake = _sync([[_deal(0, 1.1)]] * 5)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    pos = SimpleNamespace(ticket=9, volume=0.01, symbol="EURUSD", current_price=1.1)
    acct = SimpleNamespace(equity=500.0, login=1)
    s.mt5_client.is_connected = True
    s.mt5_client.get_account_snapshot = lambda: acct
    s._last_position_tickets, s._last_position_volumes = {9}, {9: 0.01}
    s.mt5_client.get_open_positions = lambda: []          # transient empty snapshot
    s.sync_once()
    s._pending_closes[9] = time.time() - s.CLOSE_RETRY_SEC - 1   # retry window has expired
    s.mt5_client.get_open_positions = lambda: [pos]       # it is back
    s.sync_once()
    assert 9 not in s._pending_closes
    assert not [c for c in bus.publish_sync.call_args_list if c[0][0] == "trade_closed"]
