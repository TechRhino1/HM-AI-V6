"""Phase-0 regression tests for scalp defects (plan v3, Part A1 #17-#19)."""
from types import SimpleNamespace as NS

from jarvis.scalping.scalp_execution_engine import _scalp_sweep_side


def test_bearish_context_sweep_does_not_fund_a_buy():
    micro = NS(sweep_detected=False, sweep_side="NONE")
    liq = NS(sweep_detected=True, sweep_type="BEARISH_SWEEP")
    assert _scalp_sweep_side(micro, liq) == "BUY_SIDE"      # only a SELL may use it


def test_no_sweep_is_none_and_micro_wins():
    assert _scalp_sweep_side(NS(sweep_detected=False, sweep_side="NONE"),
                             NS(sweep_detected=False, sweep_type="NONE")) == "NONE"
    assert _scalp_sweep_side(NS(sweep_detected=True, sweep_side="SELL_SIDE"),
                             NS(sweep_detected=True, sweep_type="BEARISH_SWEEP")) == "SELL_SIDE"


def test_scalp_targets_keep_r_multiples_when_stop_is_widened():
    from jarvis.intelligence.decision_engine import _rescale_scalp_targets
    sc = NS(entry_price=100.0, stop_loss=99.0, tp1=101.0, tp2=101.8, tp3=102.8)  # 1/1.8/2.8R on risk 1
    tp1, tp2, tp3 = _rescale_scalp_targets(sc, 100.0, 2.0, "BUY")                 # engine widened risk to 2
    assert (round(tp1, 6), round(tp2, 6), round(tp3, 6)) == (102.0, 103.6, 105.6)
    sc = NS(entry_price=100.0, stop_loss=101.0, tp1=99.0, tp2=98.2, tp3=97.2)
    assert round(_rescale_scalp_targets(sc, 100.0, 2.0, "SELL")[1], 6) == 96.4
