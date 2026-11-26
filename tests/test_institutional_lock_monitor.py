"""The live monitor on trading.exit_mode="institutional_lock": banks half at +1R when the position can
be split, floors a min-lot position at +0.3R, and runs no discretionary layer (2026-11-24 replay)."""
import pytest

from jarvis.execution.exit_policy import ExitPolicy, institutional_lock
from tests.test_exit_state_and_clamp_fixes import _monitor
from jarvis.data.schemas import PositionSnapshot
from jarvis.execution.position_monitor import JARVIS_MAGIC_NUMBER

pytestmark = pytest.mark.usefixtures("managed_gold_exit")


def _buy(volume, price):
    # entry 2400, original stop 2390 -> 1R = 10
    return PositionSnapshot(ticket=401, symbol="XAUUSD", type="BUY", volume=volume, open_price=2400.0,
                            current_price=price, sl=2390.0, tp=2440.0, profit=(price - 2400.0) * volume,
                            swap=0.0, commission=0.0, open_time="2020-01-01T00:00:00+00:00", magic=JARVIS_MAGIC_NUMBER)


def _run(volume, price):
    mon, client = _monitor({"sl": 2390.0, "volume_initial": volume})
    client.get_symbol_trading_spec.return_value = {"volume_min": 0.01, "volume_step": 0.01}
    ctx, ts = mon._ctx_cache["XAUUSD"]
    ctx.current_price, ctx.bid, ctx.ask = price, price - 0.1, price + 0.1   # the monitor prices off the context
    mon._exit_policy[401] = institutional_lock(ExitPolicy.for_symbol("XAUUSD", trade_style="SWING"))
    mon._manage_single_position(_buy(volume, price))
    return client


def test_splittable_position_banks_half_and_locks_above_entry():
    client = _run(1.0, 2411.0)  # +1.1R
    vols = [c.kwargs.get("volume") for c in client.close_position.call_args_list]
    assert 0.5 in vols
    sls = [c.kwargs.get("sl", c.args[1] if len(c.args) > 1 else None) for c in client.modify_position.call_args_list]
    assert any(s and s > 2400.0 for s in sls)


def test_min_lot_position_is_floored_not_split():
    client = _run(0.01, 2411.0)
    assert not [c for c in client.close_position.call_args_list if c.kwargs.get("volume")]
    sls = [c.kwargs.get("sl", c.args[1] if len(c.args) > 1 else None) for c in client.modify_position.call_args_list]
    assert any(s and s >= 2403.0 for s in sls)   # +0.3R floor (or the 0.7R trail above it)


def test_legacy_partial_still_banks_half_of_a_splittable_lot():
    """The 0.02 hardcode is gone; the broker min lot/step below it decides (2026-11-26)."""
    import dataclasses
    mon, client = _monitor({"sl": 2390.0, "volume_initial": 0.02})
    client.get_symbol_trading_spec.return_value = {"volume_min": 0.01, "volume_step": 0.01}
    ctx, _ = mon._ctx_cache["XAUUSD"]
    ctx.current_price, ctx.bid, ctx.ask = 2411.0, 2410.9, 2411.1
    mon._exit_policy[401] = dataclasses.replace(ExitPolicy.for_symbol("XAUUSD", trade_style="SWING"),
                                                profit_locks=True, fast_cash_r=1.0, fast_cash_volume_pct=0.5)
    mon._manage_single_position(_buy(0.02, 2411.0))
    assert 0.01 in [c.kwargs.get("volume") for c in client.close_position.call_args_list]


def test_legacy_partial_skips_an_unsplittable_min_lot():
    import dataclasses
    mon, client = _monitor({"sl": 2390.0, "volume_initial": 0.01})
    client.get_symbol_trading_spec.return_value = {"volume_min": 0.01, "volume_step": 0.01}
    ctx, _ = mon._ctx_cache["XAUUSD"]
    ctx.current_price, ctx.bid, ctx.ask = 2411.0, 2410.9, 2411.1
    mon._exit_policy[401] = dataclasses.replace(ExitPolicy.for_symbol("XAUUSD", trade_style="SWING"),
                                                profit_locks=True, fast_cash_r=1.0, fast_cash_volume_pct=0.5)
    mon._manage_single_position(_buy(0.01, 2411.0))
    assert not [c for c in client.close_position.call_args_list if c.kwargs.get("volume")]
