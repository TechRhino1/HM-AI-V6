"""Every engine-initiated close records why (2026-11-24: 25 closes showed only MT5 reason 'ENGINE')."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jarvis.application.orchestrator import JarvisOrchestrator
from jarvis.data.schemas import PositionSnapshot


def _orch():
    o = object.__new__(JarvisOrchestrator)
    o.mode = "demo"
    o.mt5_client = MagicMock()
    return o


def _pos(ticket=999111):
    return PositionSnapshot(
        ticket=ticket, symbol="XAUUSD", type="BUY", volume=0.01,
        open_price=4000.0, current_price=4010.0, sl=3980.0, tp=4050.0,
        profit=10.0, swap=0.0, commission=0.0, open_time=datetime.now(timezone.utc).isoformat(), magic=1,
    )


def test_stop_and_reverse_labels_the_closed_position():
    o = _orch()
    o.risk_engine = MagicMock()
    o._last_execution_time = {}
    o.mt5_client.close_position.return_value = {"status": "CLOSED", "ticket": 999111}
    dec = MagicMock(bias="SELL", decision="EXECUTE", trade_style="DAY_TRADING", order_type="MARKET",
                    model_confidence=0.72, expected_value=1.5, risk_reward_ratio=2.4, adversarial_penalty=10.0)
    ctx = SimpleNamespace(current_price=4010.0, volatility=SimpleNamespace(atr=10.0),
                          session=SimpleNamespace(is_prime_session=True))
    with patch("jarvis.data.database.TRADE_DB") as db:
        _, _, flipped = o._apply_stop_and_reverse_if_eligible(dec, ctx, [_pos()], [_pos()], "XAUUSD")
    assert flipped
    db.set_exit_reason.assert_called_once_with(999111, "STOP_AND_REVERSE")


def test_inline_time_stop_labels_only_a_successful_close():
    o = _orch()
    o.order_manager = MagicMock()
    o.order_manager.manage_position.return_value = {"should_close": True, "close_reason": "stale"}
    o.mt5_client.close_position.return_value = {"status": "CLOSED", "ticket": 42}
    with patch("jarvis.data.database.TRADE_DB") as db:
        o._manage_inline_trailing([_pos(42)], None)
    db.set_exit_reason.assert_called_once_with(42, "INLINE_TIME_STOP")

    o.mt5_client.close_position.return_value = {"status": "FAILED", "reason": "x"}
    with patch("jarvis.data.database.TRADE_DB") as db:
        o._manage_inline_trailing([_pos(43)], None)
    db.set_exit_reason.assert_not_called()


def test_emergency_stop_labels_every_closed_position():
    o = _orch()
    o.circuit_breaker = MagicMock()
    o.risk_engine = MagicMock()
    o.mt5_client.cancel_all_pending_orders.return_value = []
    o.mt5_client.close_all_positions.return_value = [
        {"status": "CLOSED", "ticket": 1}, {"status": "FAILED", "reason": "no tick"}, {"status": "CLOSED", "ticket": 2}]
    with patch("jarvis.data.database.TRADE_DB") as db:
        res = o.emergency_stop("TEST", close_positions=True)
    assert res["positions_closed"] == 3
    assert [c.args for c in db.set_exit_reason.call_args_list] == [(1, "EMERGENCY_STOP"), (2, "EMERGENCY_STOP")]
