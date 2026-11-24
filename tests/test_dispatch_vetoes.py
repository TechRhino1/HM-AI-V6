"""Arbiter dispatch must honour the hard vetoes the dry-run scan computed (audit 2026-11-18)."""
from types import SimpleNamespace
from unittest.mock import patch

from jarvis.application.orchestrator import JarvisOrchestrator


def _orch():
    o = object.__new__(JarvisOrchestrator)  # helper needs only .mode
    o.mode = "demo"
    return o


def _vetoes(o, **kw):
    args = dict(symbol="EURUSD", prof=None, profile_lookup_failed=False, is_session_blackout=False,
                premium_offwindow_elite=False, gov_sym_dir=None, tf_conflict="", is_exec_style_match=True,
                strategy=None)
    args.update(kw)
    return o._dispatch_vetoes(**args)


@patch.object(JarvisOrchestrator, "_count_entries_today", return_value=0)
def test_clean_candidate_has_no_vetoes(_):
    assert _vetoes(_orch()) == []


@patch.object(JarvisOrchestrator, "_count_entries_today", return_value=0)
def test_each_hard_gate_vetoes(_):
    o = _orch()
    assert _vetoes(o, is_session_blackout=True) == ["SESSION_BLACKOUT"]
    assert _vetoes(o, is_session_blackout=True, premium_offwindow_elite=True) == []
    assert _vetoes(o, gov_sym_dir=SimpleNamespace(status="PAUSED", reason="x"))[0].startswith("LLM_GOVERNOR_PAUSED")
    assert _vetoes(o, tf_conflict="M5 BUY")[0].startswith("TIMEFRAME_CONFLICT")
    assert _vetoes(o, profile_lookup_failed=True) == ["PROFILE_LOOKUP_FAILED"]
    assert _vetoes(o, is_exec_style_match=False) == ["STYLE_FILTER"]
    closed = SimpleNamespace(allowed_utc_hours=(25, 26), session_restriction=True, premium_window_exception=False)
    assert _vetoes(o, prof=closed) == ["PROFILE_SESSION_WINDOW"]


@patch.object(JarvisOrchestrator, "_count_entries_today", return_value=99)
def test_daily_cap_vetoes_even_on_dry_run(_):
    assert _vetoes(_orch()) == ["DAILY_ENTRY_CAP"]


def test_entry_count_fails_closed():
    with patch("jarvis.data.database.TRADE_DB", SimpleNamespace(db_path="Z:/does/not/exist.db")):
        assert JarvisOrchestrator._count_entries_today("EURUSD", mode="demo") >= 10**6


def test_never_filled_orders_do_not_use_the_daily_cap(tmp_path):
    # 2026-11-23: three EURUSD limits cancelled unfilled still counted as entries, so the
    # 4/day cap was spent by one fill and vetoed EURUSD 788 times.
    import sqlite3
    from datetime import datetime, timezone
    db = tmp_path / "h.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE executed_trades (ticket, symbol, timestamp, execution_mode, regime, "
              "closed_at, exit_price, realized_pnl)")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    rows = [(1, "EURUSD", ts, "demo", "TREND", ts, None, None),        # cancelled, never filled
            (2, "EURUSD", ts, "demo", "TREND", ts, None, None),        # cancelled, never filled
            (3, "EURUSD", ts, "demo", "TREND", None, None, None),      # resting / open
            (4, "EURUSD", ts, "demo", "TREND", ts, 1.1, 2.5),          # filled and closed
            (5, "EURUSD", ts, "demo", "FORWARD_TEST", None, None, None)]
    c.executemany("INSERT INTO executed_trades VALUES (?,?,?,?,?,?,?,?)", rows)
    c.commit(); c.close()
    with patch("jarvis.data.database.TRADE_DB", SimpleNamespace(db_path=str(db))):
        assert JarvisOrchestrator._count_entries_today("EURUSD", mode="demo") == 2
        assert JarvisOrchestrator._count_entries_today("EURUSD") == 2


_CONDEMNED = {"quarantined": True, "n": 30, "expectancy_r": -0.41}


@patch.object(JarvisOrchestrator, "_count_entries_today", return_value=0)
def test_quarantined_pair_is_vetoed_in_the_orchestrator_mode(_):
    o = _orch()
    o.mode = "live"
    with patch("jarvis.execution.strategy_quarantine.expectancy_state", return_value=_CONDEMNED) as st:
        assert _vetoes(o, symbol="XAUUSD", strategy="StrategyType.TREND_PULLBACK") == [
            "STRATEGY_QUARANTINE: TREND_PULLBACK n=30 exp=-0.41R"]
    st.assert_called_once_with("XAUUSD", "TREND_PULLBACK", execution_mode="live")
    with patch("jarvis.execution.strategy_quarantine.expectancy_state",
               return_value={"quarantined": False, "n": 30, "expectancy_r": 0.2}):
        assert _vetoes(o, strategy="TREND_PULLBACK") == []
    with patch("jarvis.execution.strategy_quarantine.expectancy_state", side_effect=RuntimeError("db")):
        assert _vetoes(o, strategy="TREND_PULLBACK") == []  # fails open; other governors still apply


def test_calibrated_route_candidate_still_honours_the_quarantine_veto():
    """CALIBRATED_ROUTE promotes a legacy-WAIT candidate to MARKET; the quarantine veto
    computed by the scan must still stop it before any order path is touched."""
    from unittest.mock import MagicMock
    from jarvis.application import orchestrator as orch_mod

    o = _orch()
    o.trade_style = "SWING"
    o.order_manager = MagicMock()
    o.order_manager.cleanup_stale_pending_orders.return_value = []
    o.state_manager = MagicMock()
    o.mt5_client = MagicMock()
    with patch.object(JarvisOrchestrator, "_count_entries_today", return_value=0),          patch("jarvis.execution.strategy_quarantine.expectancy_state", return_value=_CONDEMNED):
        vetoes = _vetoes(o, symbol="XAUUSD", strategy="TREND_PULLBACK")
    decision = SimpleNamespace(decision="WAIT", order_type="LIMIT", dispatch_vetoes=vetoes)
    cand = SimpleNamespace(symbol="XAUUSD", trade_style="SWING", bias="BUY", decision_obj=decision,
                           setup_grade="GRADE A", is_actionable=True, expected_value=1.0,
                           risk_reward_ratio=2.0, to_radar_item=lambda: {})
    with patch.object(JarvisOrchestrator, "scan_all_modes", return_value=(None, [cand], [])),          patch.object(JarvisOrchestrator, "_calibrated_route_allows", return_value=True),          patch.object(orch_mod, "_is_exec_ready", return_value=False),          patch("jarvis.observability.decision_journal.record_dispatch") as rec:
        o._orchestration_loop_single_pass()
    assert decision.order_type == "MARKET"  # the calibrated route was taken ...
    rec.assert_called_once()
    assert rec.call_args[0][0]["status"] == "VETOED"  # ... and the veto still won
    assert rec.call_args[0][0]["vetoes"][0].startswith("STRATEGY_QUARANTINE: TREND_PULLBACK")
    o.mt5_client.get_account_snapshot.assert_not_called()
