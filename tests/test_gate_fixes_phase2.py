"""Regressions for the Phase 2 gate fixes (2026-11-25 gate audit)."""
from types import SimpleNamespace
from unittest.mock import patch

from jarvis.application import orchestrator as orch_mod
from jarvis.config.settings import SETTINGS
from jarvis.execution.strategy_quarantine import ledger_modes
from jarvis.risk.trade_guard import TradeGuard


def test_quarantine_reads_the_account_ledger_and_never_less_than_demo():
    assert ledger_modes("demo") == ("demo",)
    assert ledger_modes("live") == ("live", "demo")
    assert ledger_modes(None) == ("demo",)


def test_decision_engine_quarantine_consults_every_ledger_for_its_mode():
    from jarvis.intelligence.decision_engine import DecisionEngine
    de = object.__new__(DecisionEngine)
    de._quarantine_offline = False
    de.execution_mode = "live"
    seen = []

    def fake(sym, strat, **kw):
        seen.append(kw["execution_mode"])
        return kw["execution_mode"] == "demo"  # condemned only in the demo ledger

    with patch("jarvis.execution.strategy_quarantine.is_quarantined", side_effect=fake):
        assert de._strategy_quarantined("EURUSD", "TREND_PULLBACK") is True
    assert seen == ["live", "demo"]


def test_promotion_hole_flags_hard_waits_only():
    friction = SimpleNamespace(waiting_reasons=["Awaiting spread tightening (current friction 68% > 25%)"],
                               model_confidence=0.6)
    lowconf = SimpleNamespace(waiting_reasons=[], model_confidence=0.30)
    benign = SimpleNamespace(waiting_reasons=["Awaiting optimal price fill."], model_confidence=0.6)
    assert "friction" in orch_mod._promotion_hole(friction, "WAIT")
    assert orch_mod._promotion_hole(lowconf, "WAIT").startswith("CONFIDENCE_GATE")
    assert orch_mod._promotion_hole(benign, "WAIT") == ""
    assert orch_mod._promotion_hole(friction, "EXECUTE") == ""  # only promotions are checked


def test_elite_bypass_is_off_by_default_and_never_beats_a_learned_regime_ban():
    entry = SimpleNamespace(reason="regime LIQUIDITY_SWEEP disabled by learned policy")
    assert SETTINGS.gates.elite_bypass_enabled is False
    assert orch_mod._elite_bypass_allowed("EURUSD", SimpleNamespace(reason="score low")) is False
    with patch.object(SETTINGS.gates, "elite_bypass_enabled", True), \
         patch("jarvis.backtesting.exit_geometry.deployment_refusal", return_value=None):
        assert orch_mod._elite_bypass_allowed("EURUSD", SimpleNamespace(reason="score low")) is True
        assert orch_mod._elite_bypass_allowed("EURUSD", entry) is False
    with patch.object(SETTINGS.gates, "elite_bypass_enabled", True), \
         patch("jarvis.backtesting.exit_geometry.deployment_refusal", return_value="HOLDOUT_GATE: x"):
        assert orch_mod._elite_bypass_allowed("XAUUSD", SimpleNamespace(reason="score low")) is False


def _dec(**kw):
    base = dict(symbol="EURUSD", entry_price=1.1000, stop_loss=1.0980, take_profit=1.1030,
                trade_style="SWING", min_allowed_rr=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_rr_assessment_is_the_single_floor():
    with patch("jarvis.backtesting.exit_geometry.live_target_r", return_value=None):
        a = TradeGuard.rr_assessment(_dec())  # 1.5R vs 1.50 floor
        assert a["ok"] and round(a["rr"], 2) == 1.5 and a["floor"] == 1.5
        assert not TradeGuard.rr_assessment(_dec(take_profit=1.1024))["ok"]  # 1.2R
        assert TradeGuard.rr_assessment(_dec(take_profit=1.1026, trade_style="SCALP"))["ok"]  # 1.3R scalp
    with patch("jarvis.backtesting.exit_geometry.live_target_r", return_value=2.5), \
         patch("jarvis.backtesting.exit_geometry.deployment_refusal", return_value=None):
        a = TradeGuard.rr_assessment(_dec(take_profit=1.1001))
        assert a["ok"] and a["skip_floor"] and a["rr"] == 2.5  # judged on the TP actually sent

