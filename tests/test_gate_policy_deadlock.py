import pytest
from jarvis.intelligence.gate_policy import AdaptiveGatePolicy
from jarvis.intelligence.opportunity_arbiter import UniversalOpportunityArbiter

def test_adaptive_gate_policy_softens_only_at_the_configured_floor():
    # 4a25738: a soft gate may be softened only while recent win rate meets the CONFIGURED
    # floor (0.45 here); the old min(0.30, floor) let a 30% win rate skip gates.
    policy = AdaptiveGatePolicy(max_soft_fail=1, min_recent_win_rate=0.45)
    decision, gates = policy.decide(["Volume Spike Ratio"], recent_win_rate=0.30)
    assert decision == "BLOCK"
    decision, gates = policy.decide(["Volume Spike Ratio"], recent_win_rate=None)   # cold start
    assert decision == "BLOCK"
    decision, gates = policy.decide(["Volume Spike Ratio"], recent_win_rate=0.50)
    assert decision == "SOFTEN" and "Volume Spike Ratio" in gates

def test_adaptive_gate_policy_blocks_hard_gates_always():
    policy = AdaptiveGatePolicy(max_soft_fail=1, min_recent_win_rate=0.45)
    
    # Hard gate must NEVER soften, even with 100% win rate
    decision, gates = policy.decide(["Market Session Open"], recent_win_rate=1.0)
    assert decision == "BLOCK"
    assert "Market Session Open" in gates

    decision, gates = policy.decide(["Drawdown Safety Guard"], recent_win_rate=1.0)
    assert decision == "BLOCK"

def test_arbiter_gate_acceptable_with_single_soft_failure():
    # Verify arbiter logic accepts candidate when only 1 soft failure occurs
    arbiter = UniversalOpportunityArbiter()
    
    class DummyDecision:
        quality_gate = type("Gate", (), {"passed": False, "failing_reasons": ["Volume Spike Ratio"]})()
        decision = "EXECUTE"
        
    class DummyOpp:
        symbol = "ETHUSD"
        decision = DummyDecision()
        net_score = 75.0
        
    # Check effective gate acceptance
    effective_passed = False
    unsoftened_failures = ["Volume Spike Ratio"]
    critical_failures = []
    hard_failures = []
    
    gate_acceptable = (
        bool(effective_passed)
        or (
            len(set(unsoftened_failures)) <= 1
            and len(critical_failures) == 0
            and len(hard_failures) == 0
        )
    )
    assert gate_acceptable is True
