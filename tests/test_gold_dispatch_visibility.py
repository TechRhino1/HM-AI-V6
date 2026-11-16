"""Gold dispatch defects found 2026-11-16: hidden risk refusals and a forced 120-min time stop."""
from types import SimpleNamespace

import pytest

from jarvis.application.orchestrator import JarvisOrchestrator
from jarvis.execution import exit_policy
from jarvis.execution.exit_policy import ExitPolicy


def _decision():
    return SimpleNamespace(decision="EXECUTE", execution_authorized=True, waiting_reasons=[])


def test_risk_refusal_is_visible_on_the_decision():
    d = _decision()
    JarvisOrchestrator._mark_risk_refusal(d, {
        "authorized": False,
        "reasons": ["Risk Ceiling Exceeded: Minimum tradeable lot size exceeds safe account risk limits."],
    })
    assert d.decision == "WAIT" and d.execution_authorized is False
    assert d.waiting_reasons == [
        "RISK: Risk Ceiling Exceeded: Minimum tradeable lot size exceeds safe account risk limits."
    ]


def test_refusal_marking_is_idempotent_and_ignores_non_execute():
    d = _decision()
    for _ in range(2):
        d.decision = "EXECUTE"
        JarvisOrchestrator._mark_risk_refusal(d, {"authorized": False, "reason": "CIRCUIT_BREAKER"})
    assert d.waiting_reasons == ["RISK: CIRCUIT_BREAKER"]

    wait = SimpleNamespace(decision="WAIT", execution_authorized=False, waiting_reasons=[])
    JarvisOrchestrator._mark_risk_refusal(wait, {"authorized": False, "reason": "x"})
    assert wait.waiting_reasons == []


@pytest.mark.parametrize("style,minutes", [
    ("SCALP", 90.0), ("DAY_TRADING", 240.0), ("SWING", 720.0), ("D1_SWING", 720.0),
])
def test_gold_fixed_target_keeps_each_styles_time_stop(style, minutes):
    exit_policy._RESOLVED_POLICY_CACHE.clear()
    pol = ExitPolicy.for_symbol("XAUUSD", None, trade_style=style)
    assert pol.profit_locks is False  # still the fixed 2.5R exit
    assert pol.time_stop_minutes == minutes
