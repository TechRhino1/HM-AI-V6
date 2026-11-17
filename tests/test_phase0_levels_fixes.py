"""Phase-0 regression tests for level defects (plan v3, Part A1 #6, #7, #10, #11)."""
from types import SimpleNamespace as NS

from jarvis.intelligence.dynamic_levels import _liquidity_stop_floor


def test_buy_stop_floor_is_beyond_the_pool():
    liq = NS(sweep_detected=False, sell_side_liquidity=3990.0, buy_side_liquidity=0.0)
    assert _liquidity_stop_floor(liq, 4005.0, 8.0, "BUY") == 3986.0          # 3990 - 0.5 ATR


def test_buy_stop_floor_is_beyond_the_sweep_wick():
    liq = NS(sweep_detected=True, sweep_level=3990.0, sweep_magnitude=0.8)
    assert abs(_liquidity_stop_floor(liq, 4005.0, 8.0, "BUY") - 3983.6) < 1e-9  # wick 0.8 ATR below


def test_sell_mirror_and_none_cases():
    liq = NS(sweep_detected=False, sell_side_liquidity=0.0, buy_side_liquidity=1.1050)
    assert abs(_liquidity_stop_floor(liq, 1.1000, 0.0010, "SELL") - 1.1055) < 1e-12
    assert _liquidity_stop_floor(NS(sweep_detected=False, sell_side_liquidity=0.0), 1.1, 0.001, "BUY") is None


def test_htf_order_block_skips_mitigated_and_wrong_side():
    from jarvis.intelligence.institutional_entry_engine import InstitutionalEntryEngine
    eng = InstitutionalEntryEngine.__new__(InstitutionalEntryEngine)
    st = NS(order_blocks=[
        {"type": "BULLISH_ORDER_BLOCK", "high": 4010.0, "low": 4005.0, "mitigated": False},  # above price
        {"type": "BULLISH_ORDER_BLOCK", "high": 3995.0, "low": 3990.0, "mitigated": True},   # consumed
        {"type": "BULLISH_ORDER_BLOCK", "high": 3985.0, "low": 3980.0, "mitigated": False},
    ], demand_zone=(0.0, 0.0), supply_zone=(0.0, 0.0))
    ctx = NS(structure=st, current_price=4000.0)
    assert eng._find_htf_order_block(None, None, ctx, "BUY") == 3985.0
