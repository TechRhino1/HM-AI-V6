"""Regression tests for the 2026-11-27 loss root-cause audit (reports/LOSS_ROOT_CAUSE_AUDIT_2026-11-27.md)."""
import inspect

import pytest

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


def test_signal_frames_read_closed_bars_only(monkeypatch):
    """R5: the primary (and intraday setup) frame used to include the forming bar, so live
    signals repainted mid-bar while the backtest read closed bars. Price rides in attrs."""
    import pandas as pd
    from jarvis.market.data_feed import DataFeedEngine

    def fake_rates(self, symbol, timeframe="H1", num_bars=300, include_current_bar=False):
        n = num_bars
        df = pd.DataFrame({"time": pd.date_range("2026-11-01", periods=n, freq="5min"),
                           "open": range(n), "high": range(n), "low": range(n),
                           "close": [float(i) for i in range(n)], "volume": [1] * n})
        df.attrs = {"data_source": "LIVE_MT5"}
        return df

    monkeypatch.setattr(DataFeedEngine, "fetch_rates", fake_rates)
    feed = DataFeedEngine.__new__(DataFeedEngine)
    for style in ("SCALP", "DAY_TRADING", "SWING"):
        mtf = feed.fetch_multi_timeframe("XAUUSD", trade_style=style, num_bars=50)
        for role, frame in mtf.items():
            assert len(frame) == 50 and float(frame["close"].iloc[-1]) == 49.0, (style, role)  # forming bar 50 dropped
            assert frame.attrs["last_price"] == 50.0  # the live price is still available
            assert frame.attrs["data_source"] == "LIVE_MT5"  # freshness/provenance stamps survive


def test_promoted_wait_with_cost_or_quality_hole_is_enforced():
    """R9: a scalp WAIT whose costs eat >35% of gross profit (or whose quality score is short)
    was promoted to EXECUTE by the arbiter; the refusal ran in shadow, and 9 of 29 orders sent
    2026-11-24..26 carried 41-157% friction. The hole is enforced by config."""
    import json
    from types import SimpleNamespace
    from jarvis.application.orchestrator import _promotion_hole
    gates = json.load(open("config/settings.json", encoding="utf-8")).get("gates", {})
    assert gates.get("promotion_hole_mode") == "enforce"
    d = SimpleNamespace(waiting_reasons=["Awaiting spread tightening (current friction 150.4% > 35%)"],
                        model_confidence=0.6)
    assert _promotion_hole(d, "WAIT").startswith("Awaiting spread tightening")
    assert _promotion_hole(d, "EXECUTE") == ""  # only promotions are judged


def test_correlated_group_is_one_bet():
    """R8: BTC+ETH+SOL (and gold+silver, the cash indices) used to pass as separate bets."""
    from types import SimpleNamespace
    from jarvis.risk.exposure import ExposureManager
    em = ExposureManager()
    btc_long = SimpleNamespace(symbol="BTCUSD", side="BUY", type="BUY", sl=60000.0, open_price=61000.0, comment="")
    res = em.check_currency_directional_exposure("ETHUSD", "BUY", [btc_long])
    assert not res["passed"] and any("CRYPTO" in b for b in res["breaches"])
    assert em.check_currency_directional_exposure("ETHUSD", "SELL", [btc_long])["passed"]  # opposite way is a hedge
    assert em.check_currency_directional_exposure("EURUSD", "BUY", [btc_long])["passed"]  # other group
    runner = SimpleNamespace(symbol="BTCUSD", side="BUY", type="BUY", sl=61500.0, open_price=61000.0, comment="")
    assert em.check_currency_directional_exposure("ETHUSD", "BUY", [runner])["passed"]  # risk-free runner


def test_drift_check_uses_holdout_and_writes_one_advisory(tmp_path):
    """Monitoring: live R is judged against the stamped holdout, and a drift writes ONE read-only
    recommendation per day (no settings are touched)."""
    from types import SimpleNamespace
    from jarvis.observability import system_monitor as sm
    prof = SimpleNamespace(oos_expectancy_r=0.30, holdout_trades=40, holdout_expectancy_r=0.05)
    live = {"XAUUSD": [-1.0, 0.5] * 15}  # mean -0.25R over 30 closes
    c = sm.check_live_drift(live, {"XAUUSD": prof}, quarantine_r=-0.15)
    s = c["symbols"]["XAUUSD"]
    assert s["benchmark"] == "holdout" and s["oos_r"] == 0.05 and s["status"] == sm.CRITICAL
    sm._LAST_DRIFT_ADVISORY.clear()
    state = {"checks": {"live_vs_calibrated": c}}
    assert sm.record_drift_advisory(state, str(tmp_path))["source"] == "MONITOR_DRIFT"
    assert sm.record_drift_advisory(state, str(tmp_path)) is None  # debounced
    lines = list(tmp_path.glob("advisories_*.jsonl"))[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and "promote_model.py" in lines[0]


@pytest.mark.calibrated_exits  # conftest otherwise stubs deployment_refusal to None
def test_gate_judges_engine_holdout_per_style_when_calibrated_policy_off(monkeypatch):
    """Part B: with the calibrated policy off, the gate reads the engine-in-the-loop holdout of the
    policy that actually trades, per symbol x style; with no such evidence it falls back to the stamps."""
    from jarvis.config import runtime
    from jarvis.config.settings import SETTINGS
    monkeypatch.setattr(runtime, "is_offline", lambda: False)
    monkeypatch.setattr(SETTINGS.trading, "use_calibrated_entry_policy", False, raising=False)
    monkeypatch.setattr(SETTINGS.gates, "deployment_overrides", [], raising=False)  # evidence alone
    ev = {"DAY_TRADING": {"trades": 120, "expectancy_r": 0.08}, "SCALP": {"trades": 300, "expectancy_r": -0.05}}
    monkeypatch.setattr(exit_geometry, "_engine_evidence", lambda s: ev if s == "XAUUSD" else ({} if s == "NZDUSD" else None))
    assert exit_geometry.deployment_refusal("XAUUSD", "DAY_TRADING") is None
    assert exit_geometry.deployment_refusal("XAUUSD", "DAY") is None  # alias
    assert exit_geometry.deployment_refusal("XAUUSD", "SCALP").startswith("STYLE_HOLDOUT_GATE")
    assert exit_geometry.deployment_refusal("XAUUSD", "SWING").startswith("STYLE_HOLDOUT_GATE")  # no evidence
    assert exit_geometry.deployment_refusal("XAUUSD") is None  # some cell passes
    assert exit_geometry.deployment_refusal("NZDUSD").startswith("STYLE_HOLDOUT_GATE")  # evidence: none for it
    monkeypatch.setattr(exit_geometry, "_stamped_profile", lambda s: None)
    assert exit_geometry.deployment_refusal("EURUSD").startswith("NO_VALIDATED_PROFILE")  # no report -> stamps
    # A cell that lost on train is refused despite its holdout; too few train trades or none -> holdout alone.
    ev["DAY_TRADING"].update(train_trades=60, train_expectancy_r=-0.10)
    assert exit_geometry.deployment_refusal("XAUUSD", "DAY_TRADING").startswith("STYLE_TRAIN_GATE")
    ev["DAY_TRADING"].update(train_trades=5)
    assert exit_geometry.deployment_refusal("XAUUSD", "DAY_TRADING") is None
