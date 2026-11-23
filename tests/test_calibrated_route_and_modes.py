"""Every feature trades in every mode (user, 2026-11-23): the calibrated policy is its own entry
route, forward tests follow trading.forward_test_modes, AUTO enforces its picks by default."""
from types import SimpleNamespace
from unittest import mock

import pytest

from jarvis.application import orchestrator as orch_mod
from jarvis.config.settings import SETTINGS, TradingSettings
from jarvis.forward_tests.research_leads import forward_test_enabled
from jarvis.intelligence.auto_style import auto_style_live


def _profile(oos_exp=0.2, oos_n=60, min_score=0.5):
    return SimpleNamespace(oos_expectancy_r=oos_exp, oos_trades=oos_n,
                           geometry=SimpleNamespace(min_score=min_score), regime_edge={})


def _cand(style="SWING", conf=0.8, bias="BUY"):
    d = SimpleNamespace(bias=bias, model_confidence=conf, quality_gate=SimpleNamespace(checks={}),
                        regime=SimpleNamespace(primary_regime="TREND_BULL"), order_type="LIMIT")
    return SimpleNamespace(symbol="XAUUSD", trade_style=style, bias=bias, decision_obj=d)


@pytest.fixture
def orch(monkeypatch):
    o = orch_mod.JarvisOrchestrator.__new__(orch_mod.JarvisOrchestrator)
    o._wr_profiles = None
    monkeypatch.setattr(SETTINGS.trading, "use_calibrated_entry_policy", True)
    monkeypatch.setattr(SETTINGS.trading, "calibrated_policy_trader", True)
    return o


def test_allowed_swing_candidate_takes_the_calibrated_route(orch):
    with mock.patch.object(orch_mod, "load_profiles", return_value={"XAUUSD": _profile()}):
        assert orch._calibrated_route_allows(_cand()) is True


def test_route_is_refused_when_off_off_style_or_below_threshold(orch, monkeypatch):
    with mock.patch.object(orch_mod, "load_profiles", return_value={"XAUUSD": _profile()}):
        assert orch._calibrated_route_allows(_cand(style="SCALP")) is False   # not what was calibrated
        assert orch._calibrated_route_allows(_cand(conf=0.3)) is False        # below min_score
        assert orch._calibrated_route_allows(_cand(bias="HOLD")) is False
        monkeypatch.setattr(SETTINGS.trading, "calibrated_policy_trader", False)
        assert orch._calibrated_route_allows(_cand()) is False


def test_route_is_refused_for_a_symbol_with_no_edge(orch):
    with mock.patch.object(orch_mod, "load_profiles", return_value={"XAUUSD": _profile(oos_exp=-0.3)}):
        assert orch._calibrated_route_allows(_cand()) is False


def test_fresh_install_defaults_stay_conservative():
    t = TradingSettings()
    assert t.calibrated_policy_trader is False
    assert t.forward_test_modes == ["demo"]


def test_forward_tests_follow_the_configured_modes(monkeypatch):
    monkeypatch.setattr(SETTINGS.trading, "forward_test_modes", ["paper", "demo", "live"])
    assert forward_test_enabled(SimpleNamespace(mode="live"))
    monkeypatch.setattr(SETTINGS.trading, "forward_test_modes", ["demo"])
    assert not forward_test_enabled(SimpleNamespace(mode="live"))
    assert forward_test_enabled(SimpleNamespace(mode="demo"))


def test_auto_style_enforces_by_default_and_can_be_switched_off(monkeypatch):
    monkeypatch.delenv("JARVIS_AUTO_STYLE_LIVE", raising=False)
    assert auto_style_live() is True
    monkeypatch.setenv("JARVIS_AUTO_STYLE_LIVE", "0")
    assert auto_style_live() is False
