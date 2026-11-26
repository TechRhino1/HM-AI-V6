"""Regression tests for the 2026-11-27 loss root-cause audit (reports/LOSS_ROOT_CAUSE_AUDIT_2026-11-27.md)."""
import inspect

from jarvis.backtesting import exit_geometry
from jarvis.intelligence import decision_engine as de


def test_ev_rr_uses_live_target_when_set(monkeypatch):
    """R2: EV is judged on the R:R the order will carry, never an invented per-strategy floor."""
    monkeypatch.setattr(exit_geometry, "live_target_r", lambda s: 2.5)
    assert de._live_rr_for_ev("XAUUSD", 1.3) == 2.5
    monkeypatch.setattr(exit_geometry, "live_target_r", lambda s: None)
    assert de._live_rr_for_ev("EURUSD", 1.3) == 1.3


def test_no_per_strategy_rr_inflation_left():
    """R2: the 2.0-2.5R floors (max(2.2, rr*1.1) etc.) that pushed EV past the arbiter's 0.40 bar are gone."""
    src = inspect.getsource(de)
    for floor in ("max(2.2, strat_rr", "max(2.5, strat_rr", "max(2.0, strat_rr", "max(1.6, strat_rr"):
        assert floor not in src
