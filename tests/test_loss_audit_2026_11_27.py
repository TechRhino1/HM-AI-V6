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


def test_backtest_replays_the_live_exit_when_asked(monkeypatch):
    """R3: offline runs used to ignore trading.exit_mode, so no backtest ever measured the live exit."""
    from jarvis.config import runtime
    from jarvis.execution.exit_policy import ExitPolicy
    monkeypatch.setattr(runtime, "is_offline", lambda: True)
    monkeypatch.delenv("JARVIS_BACKTEST_EXIT_MODE", raising=False)
    base = ExitPolicy.for_symbol("EURUSD", trade_style="DAY_TRADING")
    assert base.lock_floor_r is None  # default offline: the calibrated/legacy policy, unchanged
    monkeypatch.setenv("JARVIS_BACKTEST_EXIT_MODE", "institutional_lock")
    lock = ExitPolicy.for_symbol("EURUSD", trade_style="DAY_TRADING")
    assert (lock.lock_floor_r, lock.trail_r, lock.be_at_r) == (0.3, 0.7, 1.0)
    monkeypatch.setenv("JARVIS_BACKTEST_EXIT_MODE", "hold")
    assert ExitPolicy.for_symbol("EURUSD", trade_style="DAY_TRADING").be_at_r == float("inf")
    monkeypatch.setenv("JARVIS_BACKTEST_EXIT_MODE", "chandelier")
    ch = ExitPolicy.for_symbol("EURUSD", trade_style="DAY_TRADING")
    assert ch.trail_mode == "institutional" and ch.lock_floor_r is None


def test_live_ignores_the_backtest_exit_override(monkeypatch):
    """R3: JARVIS_BACKTEST_EXIT_MODE must never change a live position's exits."""
    from jarvis.config import runtime
    from jarvis.config.settings import SETTINGS
    from jarvis.execution.exit_policy import ExitPolicy
    monkeypatch.setattr(runtime, "is_offline", lambda: False)
    monkeypatch.setattr(SETTINGS.trading, "exit_mode", "legacy", raising=False)
    monkeypatch.setenv("JARVIS_BACKTEST_EXIT_MODE", "institutional_lock")
    assert ExitPolicy.for_symbol("EURUSD", trade_style="DAY_TRADING").lock_floor_r is None
