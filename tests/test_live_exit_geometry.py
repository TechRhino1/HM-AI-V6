"""Live exits must run the geometry the calibration measured (audit 2026-11-18)."""
from types import SimpleNamespace

import pytest

from jarvis.backtesting import exit_geometry
from jarvis.backtesting.exit_geometry import geometry_from_profile
from jarvis.execution import exit_policy

pytestmark = pytest.mark.calibrated_exits


def _profile(tp_r, trail_atr=None, mode="A_fixed_tp", max_bars=24):
    geom = SimpleNamespace(tp_r=tp_r, trail_atr=trail_atr, be_trigger_r=None, trail_activation_r=2.0, max_bars=max_bars)
    return SimpleNamespace(geometry=geom, geometry_mode=mode)


def test_policy_uses_calibrated_geometry(monkeypatch):
    geom = geometry_from_profile(_profile(1.5))
    monkeypatch.setattr(exit_geometry, "live_exit_geometry", lambda s: geom)
    exit_policy._RESOLVED_POLICY_CACHE.clear()
    spec = SimpleNamespace(digits=5, pip_size=0.0001)
    pol = exit_policy.ExitPolicy.for_symbol("ZZZUSD", spec, trade_style="SWING")
    assert pol.time_stop_minutes == 24 * 60
    assert pol.trail_activation_r >= 1e9  # trail_atr None = no runner trail, as calibrated
    assert pol.milestones == []
    exit_policy._RESOLVED_POLICY_CACHE.clear()


def test_none_trail_is_not_defaulted():
    assert geometry_from_profile(_profile(None, mode="A_fixed_tp")).trail_atr is None


def test_expectancy_gate(monkeypatch):
    from jarvis.config import runtime
    from jarvis.config.settings import SETTINGS
    monkeypatch.setattr(runtime, "is_offline", lambda: False)
    monkeypatch.setattr(SETTINGS.trading, "use_calibrated_entry_policy", True, raising=False)
    profs = {"AAA": SimpleNamespace(oos_trades=150, oos_expectancy_r=0.10),
             "BBB": SimpleNamespace(oos_trades=150, oos_expectancy_r=0.01),
             "CCC": SimpleNamespace(oos_trades=20, oos_expectancy_r=0.50)}
    monkeypatch.setattr(exit_geometry, "_stamped_profile", lambda s: profs.get(s))
    assert exit_geometry.deployment_refusal("AAA") is None
    assert exit_geometry.deployment_refusal("BBB").startswith("EXPECTANCY_GATE")
    assert exit_geometry.deployment_refusal("CCC").startswith("EXPECTANCY_GATE")
    assert exit_geometry.deployment_refusal("ZZZ").startswith("NO_VALIDATED_PROFILE")
    monkeypatch.setattr(runtime, "is_offline", lambda: True)  # backtests are never gated
    assert exit_geometry.deployment_refusal("BBB") is None
