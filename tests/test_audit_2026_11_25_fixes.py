"""Regressions for defects confirmed in the 2026-11-25 institutional audit."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jarvis.data.symbol_registry import volume_decimals
from jarvis.data.schemas import PositionSnapshot
from jarvis.execution.state_synchronizer import MT5StateSynchronizer
from jarvis.risk.circuit_breaker import CircuitBreaker
import tests.test_adaptive_same_symbol_risk as _adaptive  # module import: a bare class import gets re-collected
from tests.test_live_readiness_fixes import _demo_client, _order_mt5


def _rc(code, volume=0.10):
    return SimpleNamespace(retcode=code, deal=1, order=555, price=1.0852, volume=volume, comment=str(code))


def _send(side_effect, volume=0.10):
    fake = _order_mt5(10009, volume)
    fake.TRADE_RETCODE_DONE_PARTIAL = 10010
    fake.order_send.side_effect = side_effect
    with patch("jarvis.execution.mt5_client.mt5", fake), \
         patch("jarvis.execution.mt5_client.MT5_AVAILABLE", True):
        res = _demo_client().send_market_order("EURUSD", "BUY", volume, sl_price=1.0800, tp_price=1.0900)
    return fake, res


def test_partial_fill_is_never_resent_as_a_duplicate_order():
    fake, res = _send([_rc(10010, 0.06), _rc(10009), _rc(10009)])
    assert fake.order_send.call_count == 1
    assert res["status"] == "PARTIAL"


def test_terminal_reject_is_not_retried():
    fake, res = _send([_rc(10019), _rc(10009), _rc(10009)])  # no money
    assert fake.order_send.call_count == 1
    assert res["status"] == "FAILED"


def test_price_changed_is_retried_with_a_fresh_price():
    fake, res = _send([_rc(10020), _rc(10009)])
    assert fake.order_send.call_count == 2
    assert res["status"] == "FILLED"


def test_connection_error_does_not_trigger_the_filling_fallback():
    fake, _ = _send([_rc(10031), _rc(10009)])
    assert fake.order_send.call_count == 1


def test_volume_decimals_follow_the_step():
    assert [volume_decimals(s) for s in (0.01, 0.5, 0.05, 0.001, 1.0, 0.1)] == [2, 1, 2, 3, 0, 1]


def test_live_spec_failure_falls_back_to_the_symbol_registry_not_eurusd_defaults():
    fake = MagicMock()
    fake.symbol_info.return_value = None
    client = _demo_client()
    # The spec cache is class-level (shared across clients): isolate it.
    with patch.dict(type(client)._symbol_spec_cache, clear=True), \
         patch("jarvis.execution.mt5_client.mt5", fake), \
         patch("jarvis.execution.mt5_client.MT5_AVAILABLE", True):
        spec = client.get_symbol_trading_spec("XAUUSD")
        assert "XAUUSD" not in client._symbol_spec_cache  # retried next call, not cached
    # The EURUSD-shaped default valued gold at 1.0 / 0.0001 per price unit.
    assert (spec["trade_tick_value"], spec["trade_tick_size"]) != (1.0, 0.0001)


def test_failed_position_read_does_not_empty_the_book():
    client = MagicMock()
    client.get_open_positions.return_value = []
    client.last_positions_ok = False
    state = MagicMock()
    sync = MT5StateSynchronizer.__new__(MT5StateSynchronizer)
    sync.mt5_client, sync.state_manager, sync.event_bus = client, state, MagicMock()
    sync._last_position_tickets = {101, 102}
    sync._last_position_volumes = {101: 0.1, 102: 0.1}
    res = sync.sync_once()
    assert res["status"] == "SKIPPED"
    state.update_positions.assert_not_called()
    sync.event_bus.publish_sync.assert_not_called()


def test_served_cooldown_keeps_the_loss_streak_as_a_reduced_size_probe():
    now = {"t": 1_000_000.0}
    cb = CircuitBreaker(db_path="", clock=lambda: now["t"], consecutive_loss_limit=5)
    for _ in range(3):  # three fast losses -> velocity trip
        cb.record_trade_result(is_win=False, symbol="EURUSD")
        now["t"] += 60
    assert cb.is_tripped
    now["t"] += 10 * 3600
    assert not cb.check_status()["active"]
    assert cb.consecutive_losses == 3
    assert cb.get_streak_risk_multiplier() < 1.0


def test_served_cooldown_after_hard_limit_does_not_deadlock():
    now = {"t": 1_000_000.0}
    cb = CircuitBreaker(db_path="", clock=lambda: now["t"], consecutive_loss_limit=5)
    for k in range(5):
        cb.record_trade_result(is_win=False, symbol=f"S{k}")
        now["t"] += 3600  # slow losses: no velocity trip, hard limit instead
    assert cb.is_tripped
    now["t"] += 24 * 3600
    cb.check_status()
    assert cb.consecutive_losses == 4
    assert cb.get_streak_risk_multiplier() > 0.0


def test_portfolio_budget_counts_the_new_trade():
    # $240 open risk on $10k = 2.4%: passes the pre-sizing check (open risk only).
    # The new gold trade adds its own risk and must take the book past the 2.5% cap.
    fx = _adaptive.TestAdaptiveSameSymbolRisk("test_01_first_trade_authorization")
    fx.setUp()
    open_eur = PositionSnapshot(
        ticket=7, symbol="EURUSD", type="BUY", volume=0.10, open_price=1.1000,
        current_price=1.1000, sl=1.0760, tp=1.1300, profit=0.0, swap=0.0,
        commission=0.0, open_time="2026-11-25 00:00:00", magic=888999, comment="",
    )
    with patch("jarvis.backtesting.exit_geometry.deployment_refusal", lambda s, style=None: None):
        flat = fx.risk_engine.authorize_execution(
            fx.decision, fx.account, [], fx.sym_info,
            current_spread_pips=1.5, max_allowed_spread_pips=35.0, context=fx.context,
        )
        res = fx.risk_engine.authorize_execution(
            fx.decision, fx.account, [open_eur], fx.sym_info,
            current_spread_pips=1.5, max_allowed_spread_pips=35.0, context=fx.context,
        )
    assert flat["authorized"], flat["reasons"]
    assert not res["authorized"]
    assert any("Portfolio Risk Budget" in r for r in res["reasons"]), res["reasons"]


def test_backtest_engine_no_longer_drops_h4_d1_context():
    """A stray `else` nulled the resampled frames whenever the column was 'time' (always)."""
    import inspect
    from jarvis.backtesting import engine
    assert "full_df_h4 = None\n            full_df_d1 = None" not in inspect.getsource(engine)


def test_auto_tune_never_activates_a_symbol_the_deployment_gate_refuses():
    """Auto-tune picked 8 symbols the execution gate refused while EURUSD (allowed) sat idle."""
    from jarvis.intelligence.auto_tune_engine import AutoTuneEngine
    def gate(sym):  # only EURUSD passes, as on 2026-11-25
        return None if sym == "EURUSD" else "HOLDOUT_GATE: test"
    state = MagicMock()
    state.allowed_symbols = ["XAUUSD", "GBPUSD", "EURUSD"]
    state.radar_opportunities = [
        {"symbol": s, "setup_grade": "GRADE A", "confluence_score": 70.0, "win_prob": 62.0,
         "expected_value": 1.2, "regime": "TRENDING"} for s in state.allowed_symbols
    ]
    mt5 = MagicMock()
    mt5.get_symbol_trading_spec.return_value = {"spread": 10, "digits": 5, "point": 0.00001}
    with patch("jarvis.intelligence.auto_tune_engine._deployment_refusal", gate), \
         patch("jarvis.intelligence.auto_tune_engine._is_weekend_gap", return_value=False), \
         patch("jarvis.intelligence.auto_tune_engine.SessionEngine.get_market_trading_status",
               return_value={"is_open": True, "current_session": "LONDON"}):
        res = AutoTuneEngine.tune_universe(orchestrator=MagicMock(), state_manager=state,
                                           mt5_client=mt5, mode="BALANCED")
    assert res["active_symbols"] == ["EURUSD"]
    why = {d["symbol"]: d for d in res["details"]}
    assert why["XAUUSD"]["status"] == "DEACTIVATED" and "HOLDOUT_GATE" in why["XAUUSD"]["reason"]


def test_auto_tune_universe_is_never_empty_when_the_gate_refuses_everything():
    from jarvis.intelligence.auto_tune_engine import AutoTuneEngine
    state = MagicMock()
    state.allowed_symbols = ["XAUUSD"]
    state.radar_opportunities = [{"symbol": "XAUUSD", "setup_grade": "GRADE A", "confluence_score": 70.0,
                                  "win_prob": 62.0, "expected_value": 1.2, "regime": "TRENDING"}]
    mt5 = MagicMock()
    mt5.get_symbol_trading_spec.return_value = {"spread": 10, "digits": 5, "point": 0.00001}
    def gate(sym):
        return "HOLDOUT_GATE: test"
    with patch("jarvis.intelligence.auto_tune_engine._deployment_refusal", gate), \
         patch("jarvis.intelligence.auto_tune_engine._is_weekend_gap", return_value=False), \
         patch("jarvis.intelligence.auto_tune_engine.SessionEngine.get_market_trading_status",
               return_value={"is_open": True, "current_session": "LONDON"}):
        res = AutoTuneEngine.tune_universe(orchestrator=MagicMock(), state_manager=state,
                                           mt5_client=mt5, mode="BALANCED")
    assert res["active_symbols"] == ["BTCUSD", "EURUSD", "XAUUSD"]  # old anchors; orders still gated
