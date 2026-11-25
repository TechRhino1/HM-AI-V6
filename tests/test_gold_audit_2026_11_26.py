"""Regressions for defects confirmed in the 2026-11-26 Gold (XAUUSD) audit."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _gold_decision(order_type="MARKET"):
    from jarvis.data.schemas import DecisionObject, TradeQualityGateResult, RegimeOutput, MarketRegime

    regime = RegimeOutput(primary_regime=MarketRegime.TREND_BEAR, probabilities={"TREND_BEAR": 0.9}, confidence=0.9)
    # Planned 18.0 stop and a ~5R target: the calibrated rewrite must make it 1.5R.
    return DecisionObject(
        symbol="XAUUSD", timestamp=datetime.now(timezone.utc), regime=regime, bias="SELL",
        probabilities={"SELL": 0.8}, strategy="TREND_PULLBACK", entry_price=3622.88,
        stop_loss=3640.88, take_profit=3533.08, risk_reward_ratio=4.99, calculated_risk_percent=0.5,
        expected_value=1.0, model_confidence=0.6, adversarial_penalty=0.0, invalidation_levels=[],
        bull_case=[], bear_case=[], risk_factors=[], quality_gate=TradeQualityGateResult(passed=True, checks={}),
        decision="EXECUTE", execution_authorized=True, order_type=order_type, ai_score=90.0,
    )


def test_slipped_gold_fill_keeps_the_calibrated_target_after_reanchor():
    """11-24 ledger: planned_rr 1.5 but broker TP ~5R -- the re-anchor restored the old distance."""
    from jarvis.execution.execution_engine import ExecutionEngine

    mt5 = MagicMock()
    mt5.is_connected = True
    mt5.get_pending_orders.return_value = []
    mt5.send_market_order.return_value = {"status": "FILLED", "ticket": 7, "position_id": 7, "price": 3621.88}
    mt5.modify_position.return_value = {"status": "MODIFIED"}
    state = MagicMock(is_safe_mode=False, is_circuit_broken=False, is_drawdown_limit_reached=False)
    state.account.equity = 10000.0
    state.get_market_context.return_value = None
    decision = _gold_decision()
    with patch("jarvis.backtesting.exit_geometry.live_target_r", return_value=1.5), \
         patch("jarvis.data.database.TRADE_DB.log_trade"):
        ExecutionEngine(mt5_client=mt5, state_manager=state).execute_decision(decision, lots=0.01)
    assert mt5.modify_position.called, "slipped fill must be re-anchored"
    kw = mt5.modify_position.call_args.kwargs
    fill = 3621.88
    risk, reward = kw["sl"] - fill, fill - kw["tp"]
    assert abs(reward / risk - 1.5) < 0.02


@pytest.mark.calibrated_exits
def test_deployment_gate_fails_closed_when_settings_cannot_load(monkeypatch):
    import jarvis.config.runtime as runtime
    from jarvis.backtesting import exit_geometry

    def boom():
        raise RuntimeError("settings unreadable")

    monkeypatch.setattr(runtime, "is_offline", boom)
    reason = exit_geometry.deployment_refusal("XAUUSD")
    assert reason and reason.startswith("DEPLOYMENT_GATE_UNVERIFIED")


def test_calibrated_route_refuses_what_the_risk_engine_refuses():
    """The calibrated route used to say PASS for a symbol HOLDOUT_GATE then refused."""
    from jarvis.application.orchestrator import JarvisOrchestrator

    orch = JarvisOrchestrator.__new__(JarvisOrchestrator)
    profile = SimpleNamespace(score_col="score", oos_expectancy_r=0.04, oos_trades=959, expectancy_r=0.04,
                              geometry=SimpleNamespace(min_score=0.0), regime_geometry={}, regime_edge={})
    orch._calibrated_profile = lambda symbol: profile
    decision = SimpleNamespace(model_confidence=0.9, quality_gate=SimpleNamespace(passed=True, checks={}))
    regime = SimpleNamespace(primary_regime="TREND_BEAR")
    with patch("jarvis.backtesting.exit_geometry.deployment_refusal",
               return_value="HOLDOUT_GATE: XAUUSD walk-forward holdout -0.106R over 347 trades"):
        dec = orch._calibrated_entry_decision("XAUUSD", decision, regime)
    assert dec.allowed is False and dec.reason.startswith("HOLDOUT_GATE")
    with patch("jarvis.backtesting.exit_geometry.deployment_refusal", return_value=None):
        assert orch._calibrated_entry_decision("XAUUSD", decision, regime).allowed is True


def test_live_drift_check_flags_gold_running_below_its_calibration():
    from jarvis.observability.system_monitor import CRITICAL, OK, WARN, check_live_drift

    prof = {"XAUUSD": SimpleNamespace(oos_expectancy_r=0.041), "EURUSD": SimpleNamespace(oos_expectancy_r=0.05)}
    gold = [-1.0] * 30 + [1.5] * 10          # mean -0.375R, like the demo ledger
    eur = [1.0, -1.0] * 15                    # mean 0: inside 2 SE of +0.05
    res = check_live_drift({"XAUUSD": gold, "EURUSD": eur}, prof, quarantine_r=-0.15)
    assert res["status"] == CRITICAL
    assert res["symbols"]["XAUUSD"]["status"] == CRITICAL and res["symbols"]["EURUSD"]["status"] == OK
    mild = check_live_drift({"XAUUSD": [-1.0] * 12 + [1.5] * 9}, prof, quarantine_r=-0.15)  # +0.07R: in band
    assert mild["status"] == OK
    warn = check_live_drift({"XAUUSD": [-1.0] * 140 + [1.5] * 60}, prof, quarantine_r=-0.5)  # -0.25R, n=200
    assert warn["status"] == WARN
    assert check_live_drift({"XAUUSD": gold[:5]}, prof)["status"] == OK  # too few closes to judge
