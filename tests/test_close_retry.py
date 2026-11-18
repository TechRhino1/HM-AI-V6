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
