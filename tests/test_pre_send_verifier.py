"""Pre-send Verification Agent (TradeGuard.verify_pre_send) — plan Phase 3."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from jarvis.config.settings import VerifierSettings
from jarvis.risk import trade_guard as tg

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


def _decision(**kw):
    base = dict(symbol="EURUSD", bias="BUY", entry_price=1.1000, stop_loss=1.0980, take_profit=1.1040,
                trade_style="SWING", order_type="MARKET", timestamp=NOW - timedelta(seconds=30),
                context=SimpleNamespace(volatility=SimpleNamespace(atr=0.0020)), dispatch_vetoes=[])
    base.update(kw)
    return SimpleNamespace(**base)


def _ctx(**kw):
    base = dict(decision=_decision(), lots=0.01, spec={"point": 0.00001, "trade_stops_level": 10,
                                                       "volume_min": 0.01},
                tick={"bid": 1.10000, "ask": 1.10002, "age_s": 1.0}, positions=[], equity=10_000.0,
                origin="arbiter", now=NOW, check_news=False)
    base.update(kw)
    return tg.PreSendContext(**base)


@pytest.fixture(autouse=True)
def _no_calibrated_target():
    tg._RECENT_SENDS.clear()
    with patch("jarvis.backtesting.exit_geometry.live_target_r", return_value=None):
        yield


def _failed(res):
    return {r["rule"] for r in res["reasons"] if not r["ok"]}


def test_clean_order_is_approved():
    res = tg.verify_pre_send(_ctx(), VerifierSettings())
    assert res["outcome"] == tg.APPROVED and not _failed(res)


@pytest.mark.parametrize("ctx_kw,rule,outcome", [
    (dict(tick={"bid": 1.1, "ask": 1.1, "age_s": 999}), "stale_data", tg.BLOCKED_RISK),
    (dict(decision=_decision(stop_loss=1.1010)), "sl_tp_geometry", tg.BLOCKED_RISK),
    (dict(decision=_decision(stop_loss=1.09999)), "sl_tp_geometry", tg.BLOCKED_RISK),  # inside stops_level
    (dict(lots=50.0), "sizing_budget", tg.BLOCKED_RISK),
    (dict(equity=0.0), "sizing_budget", tg.BLOCKED_RISK),
    (dict(positions=[SimpleNamespace(symbol="EURUSD", type="BUY", comment="FT_TR_X")] * 2), "exposure", tg.BLOCKED_RISK),
    (dict(decision=_decision(timestamp=NOW - timedelta(hours=2))), "signal_age", tg.REJECTED),
    (dict(tick={"bid": 1.1030, "ask": 1.1031, "age_s": 1.0},
          decision=_decision(take_profit=1.1080)), "price_drift", tg.REJECTED),
    (dict(decision=_decision(take_profit=1.1010)), "rr_floor", tg.REJECTED),
    (dict(decision=_decision(dispatch_vetoes=["TIMEFRAME_CONFLICT: H4 SELL"])), "mtf_alignment", tg.REJECTED),
    (dict(positions=[SimpleNamespace(symbol="EURUSD", type="SELL", comment="")]), "conflict", tg.REJECTED),
])
def test_each_rule_fails_with_its_outcome(ctx_kw, rule, outcome):
    res = tg.verify_pre_send(_ctx(**ctx_kw), VerifierSettings())
    assert rule in _failed(res)
    assert res["outcome"] == outcome


def test_forward_test_positions_count_toward_the_symbol_cap():
    # The 2026-11-25 stack: forward-test EURUSD shorts must fill the per-symbol cap.
    ft = [SimpleNamespace(symbol="EURUSD#", type="SELL", comment="FT_TR_EURUSD_H4_T1")] * 2
    res = tg.verify_pre_send(_ctx(decision=_decision(bias="SELL", stop_loss=1.1020, take_profit=1.0960),
                                  positions=ft), VerifierSettings())
    assert "exposure" in _failed(res) and res["outcome"] == tg.BLOCKED_RISK


def test_duplicate_same_side_send_is_rejected_inside_the_window():
    tg.note_sent("EURUSD", "BUY", "arbiter")
    assert "duplicate" in _failed(tg.verify_pre_send(_ctx(), VerifierSettings()))
    assert "duplicate" not in _failed(tg.verify_pre_send(_ctx(origin="forward_test:FT_X"), VerifierSettings()))


def test_news_window_rule_uses_the_shared_blackout():
    with patch("jarvis.market.news.is_entry_blackout", return_value=True):
        res = tg.verify_pre_send(_ctx(check_news=True), VerifierSettings())
    assert "news_window" in _failed(res) and res["outcome"] == tg.REJECTED


def test_runner_without_target_is_not_held_to_the_rr_floor():
    assert "rr_floor" not in _failed(tg.verify_pre_send(_ctx(decision=_decision(take_profit=0.0)), VerifierSettings()))


def test_rule_exception_fails_closed():
    with patch.object(tg, "RULES", (("boom", lambda c, cfg: 1 / 0),)):
        res = tg.verify_pre_send(_ctx(), VerifierSettings())
    assert res["outcome"] == tg.BLOCKED_RISK and "verifier_error" in _failed(res)


def test_blown_time_budget_fails_closed():
    def slow(c, cfg):
        import time
        time.sleep(0.05)
        return True, "signal", None, None, "slow"
    with patch.object(tg, "RULES", (("slow", slow), ("never_reached", slow))):
        res = tg.verify_pre_send(_ctx(), VerifierSettings(budget_ms=20.0))
    assert res["outcome"] == tg.BLOCKED_RISK and "time_budget" in _failed(res)
    assert "never_reached" not in {r["rule"] for r in res["reasons"]}


def _engine():
    from jarvis.execution.execution_engine import ExecutionEngine
    eng = object.__new__(ExecutionEngine)
    eng.mt5_client = MagicMock()
    eng.mt5_client.get_tick.return_value = {"bid": 1.1, "ask": 1.1, "age_s": 999}  # stale -> BLOCKED_RISK
    eng.state_manager = SimpleNamespace(positions=[], account=SimpleNamespace(equity=10_000.0))
    eng._execution_mode = lambda: "demo"
    return eng


def test_enforce_mode_blocks_before_any_broker_call():
    from jarvis.config.settings import SETTINGS
    eng = _engine()
    d = _decision(execution_authorized=True)
    with patch.object(SETTINGS.verifier, "mode", "enforce"), \
         patch.object(type(eng), "_execute_decision_impl") as impl:
        res = eng.execute_decision(d, 0.01, sym_spec={"point": 0.00001, "volume_min": 0.01})
    assert res["status"] == "BLOCKED" and res["reason"].startswith("VERIFIER_BLOCKED_RISK")
    impl.assert_not_called()
    assert d.verification["outcome"] == tg.BLOCKED_RISK


def test_shadow_mode_records_but_still_dispatches():
    from jarvis.config.settings import SETTINGS
    from jarvis.observability.decision_journal import GateTrace
    eng = _engine()
    d = _decision(execution_authorized=True)
    d.gate_trace = GateTrace("EURUSD", "SWING", "BUY")
    with patch.object(SETTINGS.verifier, "mode", "shadow"), \
         patch.object(type(eng), "_execute_decision_impl", return_value={"status": "FILLED", "ticket": 7}) as impl:
        res = eng.execute_decision(d, 0.01, sym_spec={"point": 0.00001, "volume_min": 0.01})
    assert res["status"] == "FILLED"
    impl.assert_called_once()
    assert d.gate_trace.gates[-1]["verdict"] == "SHADOW_REJECT"
    assert tg.VERIFICATIONS[-1]["symbol"] == "EURUSD"
