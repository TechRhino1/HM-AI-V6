"""GateTrace: every order attempt records which gate decided it (plan Phase 1)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jarvis.application import orchestrator as orch_mod
from jarvis.application.orchestrator import JarvisOrchestrator
from jarvis.observability import decision_journal as dj
from jarvis.risk.risk_engine import gate_for_reason


def test_trace_reports_the_first_rejecting_gate():
    t = dj.GateTrace("EURUSD", "SWING", "BUY")
    t.add("EXEC_READY", "PASS").add("SIZE_HEAT", "SCALE", value=0.5)
    assert t.blocked_by() is None and t.final() == "SENT"
    t.reject("HARD_SYMBOL_LIMIT", "2 pos", value=2, threshold=2).reject("NEWS_BLACKOUT", "x")
    assert t.blocked_by() == "HARD_SYMBOL_LIMIT"


def test_trace_of_ignores_decisions_without_a_trace():
    assert dj.trace_of(SimpleNamespace()) is None
    assert dj.trace_of(SimpleNamespace(gate_trace="junk")) is None


def test_repeated_identical_rejection_is_journaled_once_but_sends_always():
    dj._LAST.clear()
    with patch.object(dj, "record_dispatch") as rec:
        for _ in range(3):
            dj.record_attempt(dj.GateTrace("XAUUSD", "SCALP", "SELL").reject("COOLDOWN_GUARD", "cd"))
        assert rec.call_count == 1
        for _ in range(2):
            dj.record_attempt(dj.GateTrace("XAUUSD", "SCALP", "SELL"), status="FILLED", ticket=1)
        assert rec.call_count == 3
    row = rec.call_args_list[0][0][0]
    assert row["blocked_by"] == "COOLDOWN_GUARD" and row["gates"][0]["reason"] == "cd"


def test_gate_verdicts_metric_counts_every_attempt():
    from jarvis.observability.instruments import GATE_VERDICTS
    want = {"gate": "UNSPLIT_RR_GATE", "verdict": "REJECT", "origin": "arbiter"}

    def count():
        return sum(s["value"] for s in GATE_VERDICTS.samples() if s["labels"] == want)

    dj._LAST.clear()
    before = count()
    with patch.object(dj, "record_dispatch"):
        for _ in range(3):
            dj.record_attempt(dj.GateTrace("GBPUSD", "SWING").reject("UNSPLIT_RR_GATE", "rr"))
    assert count() == before + 3


def test_risk_reasons_map_to_stable_gate_names():
    assert gate_for_reason("Max Weekly Loss breached (10.49% >= 10.00%).") == "DRAWDOWN_GUARD"
    assert gate_for_reason("HOLDOUT_GATE: XAUUSD walk-forward holdout -0.1R") == "HOLDOUT_GATE"
    assert gate_for_reason("Portfolio Risk Budget exceeded (3%)") == "PORTFOLIO_RISK_BUDGET"
    assert gate_for_reason("something new") == "RISK_OTHER"


def _loop_orch():
    o = object.__new__(JarvisOrchestrator)
    o.mode = "demo"
    o.trade_style = "SWING"
    o.order_manager = MagicMock()
    o.order_manager.cleanup_stale_pending_orders.return_value = []
    o.state_manager = MagicMock()
    o.mt5_client = MagicMock()
    return o


def test_arbiter_records_a_not_exec_ready_candidate_with_its_gate():
    dj._LAST.clear()
    o = _loop_orch()
    decision = SimpleNamespace(decision="WAIT", dispatch_vetoes=[])
    cand = SimpleNamespace(symbol="USDCHF", trade_style="SWING", bias="BUY", decision_obj=decision,
                           setup_grade="GRADE C", is_actionable=False, expected_value=0.1,
                           risk_reward_ratio=1.0, to_radar_item=lambda: {})
    with patch.object(JarvisOrchestrator, "scan_all_modes", return_value=(None, [cand], [])), \
         patch.object(JarvisOrchestrator, "_calibrated_route_allows", return_value=False), \
         patch.object(orch_mod, "_is_exec_ready", return_value=False), \
         patch("jarvis.observability.decision_journal.record_dispatch") as rec:
        o._orchestration_loop_single_pass()
    rec.assert_called_once()
    row = rec.call_args[0][0]
    assert row["blocked_by"] == "EXEC_READY" and row["origin"] == "arbiter"
    assert isinstance(decision.gate_trace, dj.GateTrace)


def test_arbiter_vetoed_candidate_keeps_the_legacy_row_fields():
    dj._LAST.clear()
    o = _loop_orch()
    decision = SimpleNamespace(decision="EXECUTE", order_type="MARKET", dispatch_vetoes=["SESSION_BLACKOUT"])
    cand = SimpleNamespace(symbol="EURUSD", trade_style="SWING", bias="SELL", decision_obj=decision,
                           setup_grade="GRADE A", is_actionable=True, expected_value=1.0,
                           risk_reward_ratio=2.0, to_radar_item=lambda: {})
    with patch.object(JarvisOrchestrator, "scan_all_modes", return_value=(None, [cand], [])), \
         patch.object(orch_mod, "_is_exec_ready", return_value=True), \
         patch("jarvis.observability.decision_journal.record_dispatch") as rec:
        o._orchestration_loop_single_pass()
    row = rec.call_args[0][0]
    assert row["status"] == "VETOED" and row["vetoes"] == ["SESSION_BLACKOUT"]
    assert row["blocked_by"] == "DISPATCH_VETOES"
    assert [g["gate"] for g in row["gates"]] == ["EXEC_READY", "DISPATCH_VETOES"]
