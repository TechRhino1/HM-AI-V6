"""Institutional trail mode of exit_policy.evaluate_exit (2026-11-17)."""
import dataclasses

from jarvis.execution.exit_policy import ExitPolicy, evaluate_exit

POL = dataclasses.replace(ExitPolicy(digits=2, pip_size=0.01), trail_mode="institutional", chandelier_atr_mult=3.0)


def _buy(peak, price, current_sl=90.0, struct=None, atr=2.0):
    # Entry 100, initial stop 90: 1R = 10.
    return evaluate_exit(side="BUY", entry=100.0, initial_sl=90.0, current_sl=current_sl, tp=0.0, price=price,
                         favorable_dist=max(0.0, price - 100.0), atr=atr, policy=POL, struct_level=struct,
                         peak_favorable_dist=peak)


def test_the_default_is_still_the_legacy_stack():
    assert ExitPolicy().trail_mode == "legacy"


def test_the_initial_stop_is_untouched_before_one_r():
    assert _buy(peak=9.0, price=108.0).new_sl == 90.0


def test_the_chandelier_follows_the_best_price_since_entry():
    # Best 120 (2R), ATR 2, k 3 -> 114; tighter than breakeven.
    dec = _buy(peak=20.0, price=118.0)
    assert dec.new_sl == 114.0 and any(a.startswith("CHANDELIER") for a in dec.actions)


def test_it_never_loosens():
    assert _buy(peak=20.0, price=118.0, current_sl=116.0).new_sl == 116.0


def test_a_swing_above_entry_trails_when_tighter_and_one_below_entry_is_ignored():
    assert _buy(peak=20.0, price=118.5, struct=117.0).new_sl == 116.5
    assert _buy(peak=20.0, price=118.0, struct=99.0).new_sl == 114.0


def test_breakeven_plus_buffer_when_the_chandelier_is_still_below_entry():
    # Best 110 (1R), ATR 5 -> chandelier 95 < entry: breakeven + buffer wins.
    dec = _buy(peak=10.0, price=109.0, atr=5.0)
    assert 100.0 < dec.new_sl < 101.0 and dec.be_locked


def test_sell_is_mirrored():
    dec = evaluate_exit(side="SELL", entry=100.0, initial_sl=110.0, current_sl=110.0, tp=0.0, price=82.0,
                        favorable_dist=18.0, atr=2.0, policy=POL, peak_favorable_dist=20.0)
    assert dec.new_sl == 86.0   # best 80 + 3 x 2


def test_live_and_backtest_share_one_structural_filter():
    from types import SimpleNamespace
    from jarvis.execution.exit_policy import struct_level_for
    st = SimpleNamespace(higher_lows=True, lower_highs=False, swing_low=105.0, demand_zone=(103.0, 104.0))
    assert struct_level_for("BUY", 100.0, st) == 105.0
    assert struct_level_for("BUY", 106.0, st) is None                       # nothing above entry
    assert struct_level_for("BUY", 100.0, SimpleNamespace(**{**vars(st), "higher_lows": False})) is None
