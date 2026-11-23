"""One exec-ready rule for live dispatch (orchestrator) and the live-takeable calibration (signal_scan)."""
from types import SimpleNamespace

import pytest

from jarvis.intelligence.opportunity_arbiter import is_exec_ready, unsoftened_failure_count


def _cand(grade="GRADE A", ev=0.6, rr=2.0, actionable=True, order_type="MARKET"):
    d = SimpleNamespace(bias="BUY", order_type=order_type)
    return SimpleNamespace(is_actionable=actionable, setup_grade=grade, decision_obj=d, bias="BUY",
                           expected_value=ev, risk_reward_ratio=rr)


@pytest.mark.parametrize("grade,action,fails,ev,rr,expected", [
    ("GRADE A", "EXECUTE", 5, 0.0, 0.5, True),     # EXECUTE needs only actionable + grade
    ("GRADE A+", "WAIT", 1, 0.6, 2.0, True),
    ("GRADE A", "WAIT", 2, 0.6, 2.0, False),      # too many unsoftened failures
    ("GRADE A", "WAIT", 0, 0.39, 2.0, False),     # EV below 0.40
    ("GRADE A", "WAIT", 0, 0.6, 1.39, False),     # RR below 1.4
    ("GRADE B", "WAIT", 0, 0.6, 2.0, True),
    ("GRADE B", "WAIT", 1, 0.6, 2.0, False),      # grade B needs zero failures
    ("GRADE C", "EXECUTE", 0, 0.6, 2.0, False),
    ("GRADE A", "NO_TRADE", 0, 0.6, 2.0, False),
])
def test_truth_table(grade, action, fails, ev, rr, expected):
    assert is_exec_ready(_cand(grade, ev, rr), action, fails) is expected


def test_not_actionable_or_stop_order_is_not_ready():
    assert is_exec_ready(_cand(actionable=False), "EXECUTE", 0) is False
    assert is_exec_ready(_cand(order_type="STOP"), "EXECUTE", 0) is False


def test_failure_count_ignores_softened_gates():
    qg = SimpleNamespace(failing_reasons=["Premium/Discount Alignment", "Macro MTF Alignment"],
                         softened_gates=["Premium/Discount Alignment"])
    assert unsoftened_failure_count(SimpleNamespace(quality_gate=qg)) == 1
    assert unsoftened_failure_count(SimpleNamespace(quality_gate=None)) == 99
