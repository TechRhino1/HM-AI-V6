"""Regressions for exit-management defects confirmed in the 2026-11-16 audit."""
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from jarvis.data.schemas import (
    LiquidityContext, MarketContext, MomentumContext, PositionSnapshot,
    SessionContext, StructureContext, VolatilityContext,
)
from jarvis.execution.position_monitor import JARVIS_MAGIC_NUMBER, PositionMonitorEngine
from tests.test_live_readiness_fixes import _demo_client, _order_mt5

pytestmark = pytest.mark.usefixtures("managed_gold_exit")


def _monitor(opening_order):
    client = MagicMock()
    client.get_opening_order.return_value = opening_order
    client.modify_position.return_value = {"status": "MODIFIED"}
    client.close_position.return_value = {"status": "PARTIALLY_CLOSED"}
    mon = PositionMonitorEngine(
        mt5_client=client, data_feed=MagicMock(), context_engine=MagicMock(),
        state_manager=MagicMock(), event_bus=MagicMock(),
    )
    ctx = MarketContext(
        symbol="XAUUSD", timestamp=datetime.now(timezone.utc), current_price=2406.0,
        bid=2405.9, ask=2406.1, structure=StructureContext(bias="BULLISH"),
        liquidity=LiquidityContext(), volatility=VolatilityContext(atr=10.0, current_spread_pips=2.0),
        momentum=MomentumContext(trend_score=50.0, adx=25.0), session=SessionContext(is_prime_session=True),
    )
    mon._ctx_cache["XAUUSD"] = (ctx, time.monotonic())
    mon.state_manager.latest_decisions = {}  # a MagicMock decision floats to 1.0 as a target
    return mon, client


def _ratcheted_buy(volume=1.0):
    # Entry 2400, ORIGINAL stop 2390 (1R = 10). Live stop already ratcheted to 2398.
    return PositionSnapshot(
        ticket=301, symbol="XAUUSD", type="BUY", volume=volume, open_price=2400.0,
        current_price=2406.0, sl=2398.0, tp=2440.0, profit=6.0, swap=0.0, commission=0.0,
        open_time="2020-01-01T00:00:00+00:00", magic=JARVIS_MAGIC_NUMBER,
    )


def test_restart_recovers_original_1r_from_the_opening_order():
    mon, _ = _monitor({"sl": 2390.0, "volume_initial": 1.0})
    mon._manage_single_position(_ratcheted_buy())
    assert mon._initial_sl[301] == 2390.0
    assert mon._initial_risk_dist[301] == pytest.approx(10.0)


def test_partial_is_not_taken_early_against_the_ratcheted_stop():
    # +0.6R of the real 1R is below every fast-cash trigger (>= 1.0R); against the
    # ratcheted stop (R = 2) it read as +3R and the partial fired.
    mon, client = _monitor({"sl": 2390.0, "volume_initial": 1.0})
    mon._manage_single_position(_ratcheted_buy())
    client.close_position.assert_not_called()


def test_restart_does_not_repeat_a_partial_already_taken():
    mon, _ = _monitor({"sl": 2390.0, "volume_initial": 1.0})
    mon._recover_open_state(_ratcheted_buy(volume=0.6), atr=10.0, pip_size=0.1)
    assert 301 in mon._partially_closed_tickets


def test_unknown_opening_order_falls_back_to_the_old_behaviour():
    mon, _ = _monitor(None)
    mon._recover_open_state(_ratcheted_buy(), atr=10.0, pip_size=0.1)
    assert 301 not in mon._initial_risk_dist


@pytest.mark.parametrize("is_buy,resting,requested,bid,ask", [
    (False, 1.09532, 1.09530, 1.09500, 1.09505),  # SELL: clamp would push SL up to 1.09535
    (True, 1.09473, 1.09475, 1.09500, 1.09505),   # BUY mirror: clamp would pull SL down to 1.09470
])
def test_stop_level_clamp_never_loosens_the_resting_stop(is_buy, resting, requested, bid, ask):
    fake = _order_mt5(10009, 0.1)
    fake.POSITION_TYPE_BUY = 0
    fake.TRADE_ACTION_SLTP = 6
    fake.symbol_info.return_value.trade_stops_level = 30
    fake.symbol_info_tick.return_value = SimpleNamespace(bid=bid, ask=ask)
    fake.positions_get.return_value = [SimpleNamespace(
        ticket=7, symbol="EURUSD", type=0 if is_buy else 1, sl=resting, tp=0.0, price_current=bid,
    )]
    with patch("jarvis.execution.mt5_client.mt5", fake), \
         patch("jarvis.execution.mt5_client.MT5_AVAILABLE", True):
        _demo_client().modify_position(7, sl=requested, tp=0.0)
    assert fake.order_send.call_args[0][0]["sl"] == pytest.approx(resting)
