"""System monitor checks + async advisory (plan Phase 5)."""
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jarvis.config.settings import MonitorSettings
from jarvis.observability import system_monitor as sm

NOW = 1_800_000_000.0
CFG = MonitorSettings()


def _row(age_s, blocked_by=None, status=None):
    ts = datetime.fromtimestamp(NOW - age_s, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"ts": ts, "blocked_by": blocked_by, "status": status}


def test_stalled_loop_is_critical():
    assert sm.check_loop(NOW, NOW - 30, CFG)["status"] == sm.OK
    assert sm.check_loop(NOW, NOW - 3600, CFG)["status"] == sm.CRITICAL


def test_no_trade_names_the_top_blocking_gates():
    rows = [_row(60, "DRAWDOWN_GUARD")] * 5 + [_row(120, "HOLDOUT_GATE")] * 2
    out = sm.check_no_trade(NOW, rows, last_send=NOW - 20 * 3600, cfg=CFG)
    assert out["status"] == sm.WARN and "DRAWDOWN_GUARD x5" in out["detail"]
    assert sm.check_no_trade(NOW, rows, last_send=NOW - 600, cfg=CFG)["status"] == sm.OK


def test_rejection_spike_against_the_daily_average():
    steady = [_row(3600 * h, "COOLDOWN_GUARD") for h in range(2, 24)] * 3   # ~66/day
    assert sm.check_reject_spike(NOW, steady, CFG)["status"] == sm.OK
    burst = steady + [_row(60, "COOLDOWN_GUARD")] * 40
    assert sm.check_reject_spike(NOW, burst, CFG)["status"] == sm.WARN


def test_analyst_fallback_rate():
    assert sm.check_rate("x", 1, 100, 0.25)["status"] == sm.OK
    assert sm.check_rate("x", 60, 100, 0.25)["status"] == sm.WARN
    assert sm.check_rate("x", 0, 0, 0.25)["status"] == sm.OK


def test_verifier_errors_are_critical_because_the_verifier_fails_closed():
    good = {"reasons": [{"rule": "sizing_budget", "ok": True}]}
    bad = {"reasons": [{"rule": "verifier_error", "ok": False}]}
    assert sm.check_verifier([good] * 50, CFG)["status"] == sm.OK
    assert sm.check_verifier([good] * 40 + [bad] * 10, CFG)["status"] == sm.CRITICAL


def test_forward_test_exposure_share_of_budget():
    pos = [SimpleNamespace(symbol="EURUSD", type="SELL", volume=0.01, open_price=1.0947, sl=1.1015,
                           comment="FT_TR_EURUSD_H4_T1")] * 4
    out = sm.check_forward_exposure(pos, equity=480.0, max_portfolio_risk_pct=2.5, cfg=CFG)
    assert out["status"] == sm.WARN and out["value"] > 100  # ~$27 vs a $12 budget


def test_run_checks_rolls_up_and_alerts_once_per_problem():
    with patch("jarvis.observability.alerting.dispatch_alert") as alert:
        out = sm.run_checks(now=NOW, heartbeat=NOW - 3600, rows=[], last_send=NOW - 60,
                            verifications=[], positions=[], equity=1000.0, max_portfolio_risk_pct=2.5,
                            fallbacks=0, evaluations=10, cfg=CFG)
    assert out["status"] == sm.CRITICAL and out["checks"]["loop_heartbeat"]["status"] == sm.CRITICAL
    assert alert.call_count == 1


def test_advisory_needs_a_provider_and_respects_backoff_and_interval():
    from jarvis.intelligence.llm_controller import AutonomousLLMSystemController
    ctl = AutonomousLLMSystemController(provider=None)
    assert ctl.review_operations({}, {}) is False  # no provider -> no invented advice
    ctl.provider = MagicMock()
    ctl._ai_backoff_until = time.time() + 600
    assert ctl.review_operations({}, {}) is False
    ctl._ai_backoff_until = 0.0
    with patch("threading.Thread") as th:
        assert ctl.review_operations({"checks": {}}, {"X": 1}) is True
        assert ctl.review_operations({"checks": {}}, {"X": 1}) is False  # hourly at most
    th.return_value.start.assert_called_once()


def _pm(**kw):
    base = {"running": True, "thread_alive": True, "last_tick_at": NOW - 2, "tick_errors": 0, "last_tick_error": ""}
    base.update(kw)
    return base


def test_position_monitor_heartbeat_states():
    assert sm.check_position_monitor(NOW, _pm(), 6, CFG)["status"] == sm.OK
    assert sm.check_position_monitor(NOW, _pm(last_tick_at=NOW - 300), 6, CFG)["status"] == sm.CRITICAL
    assert sm.check_position_monitor(NOW, _pm(thread_alive=False), 6, CFG)["status"] == sm.CRITICAL
    assert sm.check_position_monitor(NOW, _pm(last_tick_at=0.0), 6, CFG)["status"] == sm.CRITICAL
    # Judged on the current error streak, not the lifetime count (one old error used to mean WARN forever).
    out = sm.check_position_monitor(NOW, _pm(tick_errors=3, consecutive_tick_errors=3, last_tick_error="KeyError: x"), 6, CFG)
    assert out["status"] == sm.WARN and "KeyError" in out["detail"]
    assert sm.check_position_monitor(NOW, _pm(tick_errors=3, consecutive_tick_errors=0), 6, CFG)["status"] == sm.OK
    # Every tick failing for longer than the stall window is CRITICAL even though ticks "complete".
    failing = _pm(consecutive_tick_errors=20, last_ok_at=NOW - 300, last_tick_error="KeyError: x")
    assert sm.check_position_monitor(NOW, failing, 6, CFG)["status"] == sm.CRITICAL
    assert sm.check_position_monitor(NOW, None, 6, CFG)["status"] == sm.WARN   # open trades, no monitor
    assert sm.check_position_monitor(NOW, None, 0, CFG)["status"] == sm.OK


def test_monitor_loop_records_a_heartbeat_even_when_a_tick_raises():
    from jarvis.execution.position_monitor import PositionMonitorEngine
    pm = object.__new__(PositionMonitorEngine)
    pm.last_tick_at, pm.tick_errors, pm.last_tick_error = 0.0, 0, ""
    pm._running = True

    def boom():
        pm._running = False  # one iteration
        raise RuntimeError("broker hiccup")

    pm._run_monitor_tick = boom
    with patch("time.sleep"):
        pm._monitor_loop()
    assert pm.last_tick_at > 0 and pm.tick_errors == 1 and "broker hiccup" in pm.last_tick_error


def test_run_checks_includes_the_position_monitor():
    out = sm.run_checks(now=NOW, heartbeat=NOW - 5, rows=[], last_send=NOW - 60, verifications=[],
                        positions=[SimpleNamespace(symbol="EURUSD", type="SELL", volume=0.01, open_price=1.1,
                                                   sl=1.11, comment="")],
                        equity=1000.0, max_portfolio_risk_pct=2.5, fallbacks=0, evaluations=10, cfg=CFG,
                        alert=False, position_monitor=_pm(thread_alive=False))
    assert out["checks"]["position_monitor"]["status"] == sm.CRITICAL and out["status"] == sm.CRITICAL


def test_first_watchdog_monitor_pass_waits_one_interval_after_start():
    """At t=0 the position monitor has not ticked yet; checking then raised a false CRITICAL."""
    import inspect
    from jarvis.application.orchestrator import JarvisOrchestrator
    src = inspect.getsource(JarvisOrchestrator.__init__)
    assert "self._last_monitor_at: float = self._started_at" in src
