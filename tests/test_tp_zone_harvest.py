"""The TP must not run away from price once price is inside the broker's stop zone (2026-11-16).

ETH #995270444: the TP stepped 1785.37 -> 1784.02 -> 1782.59 -> 1782.53 -> 1782.45 (2 x spread
each tick) as price approached, never filled, and the trade ended on its trailed stop instead.
"""
from datetime import datetime, timedelta, timezone

from tests.test_exit_state_and_clamp_fixes import _monitor
from jarvis.data.schemas import PositionSnapshot
from jarvis.execution.position_monitor import JARVIS_MAGIC_NUMBER


import pytest as _pytest


@_pytest.fixture(autouse=True)
def _registry_layers_enforced(monkeypatch):
    """These tests check the layer MECHANICS; production defaults them to shadow
    (config monitor_layers, 2026-11-25), so enforce them here."""
    from jarvis.config.settings import SETTINGS
    for _layer in ("news_floor", "news_bank", "weekend_floor", "weekend_bank", "tp_zone_harvest", "scalp_stagnation"):
        monkeypatch.setattr(SETTINGS.monitor_layers, _layer, "enforce")



def _sell(current_price):
    # Entry 2400, stop 2410 (1R = 10), target 2380.
    return PositionSnapshot(
        ticket=401, symbol="XAUUSD", type="SELL", volume=1.0, open_price=2400.0,
        current_price=current_price, sl=2410.0, tp=2380.0, profit=0.0, swap=0.0, commission=0.0,
        # recent open: an old one trips the time stop before the TP logic is reached
        open_time=(datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(), magic=JARVIS_MAGIC_NUMBER,
    )


def _at(mon, price):
    # the monitor prices from the cached market context, not the snapshot
    ctx = mon._ctx_cache["XAUUSD"][0]
    ctx.current_price, ctx.bid, ctx.ask = price, price - 0.05, price + 0.05
    ctx.structure.bias = "BEARISH"
    return _sell(price)


def _tps_sent(client):
    return [c.kwargs.get("tp", c.args[2] if len(c.args) > 2 else None) for c in client.modify_position.call_args_list]


def test_price_at_the_target_banks_it_instead_of_moving_the_tp_away():
    mon, client = _monitor({"sl": 2410.0, "volume_initial": 1.0})
    client.close_position.return_value = {"status": "CLOSED"}
    client.get_symbol_trading_spec.return_value = {"point": 0.01, "trade_stops_level": 0,
                                                   "trade_freeze_level": 0, "spread": 50}
    mon._manage_single_position(_at(mon, 2380.5))  # 0.5 from TP < 2 x spread (1.0)
    client.close_position.assert_called()
    assert all(tp is None or tp >= 2380.0 for tp in _tps_sent(client))  # never pushed below the target


def test_price_far_from_the_target_leaves_the_tp_alone():
    mon, client = _monitor({"sl": 2410.0, "volume_initial": 1.0})
    client.get_symbol_trading_spec.return_value = {"point": 0.01, "trade_stops_level": 0,
                                                   "trade_freeze_level": 0, "spread": 50}
    mon._manage_single_position(_at(mon, 2399.0))
    assert all(tp is None or tp == 2380.0 for tp in _tps_sent(client))
