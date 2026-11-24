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



# ---- institutional lock (trading.exit_mode="institutional_lock"; measured on 173 live trades) ----
from jarvis.execution.exit_policy import ExitPolicy as _EP, evaluate_exit as _ev, institutional_lock as _lock


def _lk():
    return _lock(_EP(digits=2, pip_size=0.01))


def _run(price, peak, *, split=False, taken=False, sl=95.0):
    # BUY at 100, stop 95 -> 1R = 5
    return _ev(side="BUY", entry=100.0, initial_sl=95.0, current_sl=sl, tp=125.0, price=price,
               favorable_dist=peak, atr=2.0, policy=_lk(), partial_already_taken=taken, partial_executable=split)


def test_lock_does_nothing_before_1r():
    d = _run(104.5, 4.5)
    assert d.new_sl in (0, 95.0) and not d.partial_close_pct


def test_min_lot_floors_at_0_3r_then_trails_0_7r():
    assert _run(105.0, 5.0).new_sl == 101.5          # +0.3R floor beats the trail (100+5-3.5)
    assert _run(109.0, 10.0).new_sl == 106.5         # peak 2R -> 100+10-3.5


def test_splittable_banks_half_and_floors_at_breakeven():
    d = _run(105.0, 5.0, split=True)
    assert d.partial_close_pct == 0.5 and d.partial_price == 105.0
    assert d.new_sl == 101.5 and not any(x.startswith("LOCK_0.3R") for x in d.actions)  # trail, no floor
    assert not _run(105.0, 5.0, split=True, taken=True).partial_close_pct


def test_lock_never_loosens_and_skips_time_stop():
    assert _run(108.0, 10.0, sl=107.0).new_sl == 107.0
    assert _lk().time_stop_minutes == 0.0


def test_plain_institutional_trail_unchanged_without_lock_fields():
    p = _EP(digits=2, pip_size=0.01, trail_mode="institutional")
    assert p.lock_floor_r is None and p.trail_r is None and p.lock_partial_pct == 0.0
