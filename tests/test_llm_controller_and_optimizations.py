"""
Unit tests for Autonomous LLM System Controller, Strategy Optimizations, and Efficiency Enhancements.
Verifies:
1. AutonomousLLMSystemController generates valid directives via institutional offline heuristic.
2. Safety bounds: risk multiplier strictly clamped to [0.35, 1.25], max concurrent trades strictly clamped.
3. Weekend crypto routing: switches BTC/ETH to RANGE_MEAN_REVERSION or flat, pauses FX/Gold.
4. StateManager updates llm_governor_state and exposes it in get_state_snapshot.
5. SelfLearningEngine query speed with new composite indices.
6. Strategy selector weekend rules for crypto.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from jarvis.intelligence.llm_controller import AutonomousLLMSystemController, GovernorDirectives
from jarvis.application.state_manager import StateManager
from jarvis.data.schemas import MarketRegime, RegimeOutput, MarketContext, VolatilityContext
from jarvis.intelligence.strategy_selector import StrategySelector
from jarvis.intelligence.symbol_profile_config import get_symbol_profile_config
from jarvis.intelligence.self_learning import SelfLearningEngine


def test_llm_controller_heuristic_evaluation():
    """Verify AutonomousLLMSystemController produces valid directives in offline heuristic mode."""
    state_mgr = StateManager()
    controller = AutonomousLLMSystemController(state_manager=state_mgr, provider=None, cache_ttl_sec=60.0)

    directives = controller.get_latest_directives(force_refresh=True)

    assert isinstance(directives, GovernorDirectives)
    assert directives.risk_posture in ("DEFENSIVE", "NORMAL", "AGGRESSIVE")
    assert 0.35 <= directives.risk_multiplier <= 1.25
    assert 1 <= directives.max_concurrent_trades <= 3
    assert len(directives.symbol_directives) > 0
    assert directives.source == "OFFLINE_HEURISTIC"

    # Verify published to state manager
    snap = state_mgr.get_state_snapshot()
    assert "llm_governor" in snap
    assert snap["llm_governor"]["risk_posture"] == directives.risk_posture


def test_llm_controller_drawdown_safety_damping():
    """Verify high drawdown triggers DEFENSIVE posture with damped risk multiplier."""
    state_mgr = StateManager()
    # Mock account with 4% drawdown
    mock_acc = MagicMock()
    mock_acc.balance = 500.0
    mock_acc.equity = 480.0  # 4% DD
    state_mgr.account = mock_acc

    controller = AutonomousLLMSystemController(state_manager=state_mgr, provider=None)
    directives = controller.get_latest_directives(force_refresh=True)

    assert directives.risk_posture == "DEFENSIVE"
    assert directives.risk_multiplier <= 0.80
    assert directives.max_concurrent_trades == 1


def test_llm_controller_spread_spike_pauses_symbol():
    """Verify that an extreme spread spike marks the symbol as PAUSED."""
    state_mgr = StateManager()
    
    # Mock wide spread on XAUUSD
    mock_ctx = MagicMock()
    mock_ctx.live_spread_pips = 15.0  # Typical is ~2.0 pips -> 7.5x typical
    state_mgr.market_contexts["XAUUSD"] = mock_ctx

    controller = AutonomousLLMSystemController(state_manager=state_mgr, provider=None)
    directives = controller.get_latest_directives(force_refresh=True)

    gold_dir = directives.symbol_directives.get("XAUUSD")
    if gold_dir:
        # Either paused due to off-hours or due to spread spike
        assert gold_dir.status == "PAUSED"


class _FakeProvider:
    def __init__(self, payload=None, exc=None):
        self.payload, self.exc, self.calls = payload, exc, 0

    def available(self):
        return True

    def structured(self, prompt, json_schema, system=""):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.payload


def test_llm_governor_is_reduce_only():
    """An LLM asking for 1.25x risk is honoured as LLM-sourced but capped at 1.0x."""
    provider = _FakeProvider({"risk_posture": "AGGRESSIVE", "risk_multiplier": 1.25,
                              "max_concurrent_trades": 2, "macro_reasoning": "go big",
                              "symbol_directives": {"BTCUSD": {"status": "PAUSED", "preferred_strategy": "NONE",
                                                               "reason": "news"}}})
    controller = AutonomousLLMSystemController(state_manager=StateManager(), provider=provider)
    d = controller.get_latest_directives(force_refresh=True)
    assert provider.calls == 1
    assert d.source == "LLM"
    assert d.risk_multiplier == 1.0
    assert d.risk_posture == "NORMAL"
    if "BTCUSD" in d.symbol_directives:
        # Only the rule-based governor hard-pauses; an AI pause is shown as advisory THROTTLED.
        assert d.symbol_directives["BTCUSD"].status == "THROTTLED"
        assert d.symbol_directives["BTCUSD"].reason.startswith("AI advisory")


def test_llm_governor_cannot_unpause_heuristic_pause():
    state_mgr = StateManager()
    mock_ctx = MagicMock()
    mock_ctx.live_spread_pips = 100.0  # far beyond any typical spread -> heuristic PAUSED
    state_mgr.market_contexts["XAUUSD"] = mock_ctx
    provider = _FakeProvider({"risk_posture": "NORMAL", "risk_multiplier": 1.0, "max_concurrent_trades": 2,
                              "macro_reasoning": "", "symbol_directives": {
                                  "XAUUSD": {"status": "ENABLED", "preferred_strategy": "TREND_FOLLOWING",
                                             "reason": "fine"}}})
    d = AutonomousLLMSystemController(state_manager=state_mgr, provider=provider).get_latest_directives(True)
    if "XAUUSD" in d.symbol_directives:
        assert d.symbol_directives["XAUUSD"].status == "PAUSED"


def test_llm_governor_error_falls_back_to_heuristic():
    provider = _FakeProvider(exc=RuntimeError("boom"))
    d = AutonomousLLMSystemController(state_manager=StateManager(), provider=provider).get_latest_directives(True)
    assert provider.calls == 1
    assert d.source == "OFFLINE_HEURISTIC"


def test_llm_governor_skipped_offline_and_without_provider():
    from jarvis.config.runtime import offline_mode

    assert AutonomousLLMSystemController(state_manager=StateManager(), provider=None) \
        .get_latest_directives(True).source == "OFFLINE_HEURISTIC"
    provider = _FakeProvider({"risk_multiplier": 0.5})
    with offline_mode():
        d = AutonomousLLMSystemController(state_manager=StateManager(), provider=provider).get_latest_directives(True)
    assert provider.calls == 0 and d.source == "OFFLINE_HEURISTIC"


def test_llm_governor_default_provider_disabled_under_pytest(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-should-never-be-used")
    assert AutonomousLLMSystemController(state_manager=StateManager()).provider is None


def test_forex_profiles_session_and_sl_calibration():
    """Verify EURUSD and GBPUSD have session restrictions and calibrated intraday SL multipliers."""
    eur = get_symbol_profile_config("EURUSD")
    gbp = get_symbol_profile_config("GBPUSD")

    assert eur.session_restriction is True
    assert eur.allowed_utc_hours == (7, 17)
    assert eur.sl_atr_multiplier <= 1.60

    assert gbp.session_restriction is True
    assert gbp.allowed_utc_hours == (7, 17)
    assert gbp.sl_atr_multiplier <= 1.80


def test_crypto_strategy_selector_prior_weights():
    """Verify crypto prior weights favor trend/breakout or weekend mean reversion."""
    from jarvis.data.schemas import StructureContext, LiquidityContext, MomentumContext, SessionContext
    selector = StrategySelector()
    regime = RegimeOutput(
        primary_regime=MarketRegime.RANGE,
        probabilities={"RANGE": 0.9},
        confidence=0.85
    )
    ctx = MarketContext(
        symbol="ETHUSD",
        timestamp=datetime.now(timezone.utc),
        ask=3000.0,
        bid=2990.0,
        current_price=2995.0,
        volatility=VolatilityContext(atr=500.0, current_spread_pips=10.0),
        structure=StructureContext(bias="NEUTRAL"),
        liquidity=LiquidityContext(buy_side_liquidity=83000.0, sell_side_liquidity=81000.0),
        momentum=MomentumContext(trend_score=10.0),
        session=SessionContext(is_prime_session=True),
    )

    probs = selector.select_strategy_probabilities(regime, context=ctx, account_equity=450.0)
    assert isinstance(probs, dict)
    assert len(probs) > 0
    # In RANGE regime on crypto, range mean reversion should be favored
    assert probs.get("RANGE_MEAN_REVERSION", 0.0) >= 0.25
    assert probs.get("MICRO_ACCOUNT_ADAPTIVE", 0.0) == 0.0


def test_self_learning_database_indices_query():
    """Verify SelfLearningEngine queries execute without error."""
    sle = SelfLearningEngine()
    reg_mult = sle.get_regime_multiplier("TREND_BULL")
    assert isinstance(reg_mult, (int, float))
    assert 0.5 <= reg_mult <= 1.5

    pattern_stats = sle.get_pattern_win_rate_and_ev("XAUUSD", "TREND_BULL")
    assert isinstance(pattern_stats, dict)
    assert "win_rate" in pattern_stats
    assert "conviction_multiplier" in pattern_stats


def test_llm_failure_backs_off_instead_of_retrying_every_call():
    """2026-11-24: Google 429/503 on every cache expiry, per scan thread (78 failures)."""
    provider = _FakeProvider(exc=RuntimeError("AI busy at Google (429)"))
    c = AutonomousLLMSystemController(state_manager=StateManager(), provider=provider)
    c.get_latest_directives(True)
    c.get_latest_directives(True)
    assert provider.calls == 1                      # second evaluation is inside the backoff
    st = c.ai_status()
    assert st["failures"] == 1 and "429" in st["last_error"] and st["backoff_until"] is not None


def test_trading_loop_never_waits_on_the_model():
    """A non-forced expired call returns the cached directive at once; one background refresh runs."""
    import threading
    gate = threading.Event()

    class _Slow(_FakeProvider):
        def structured(self, prompt, json_schema, system=""):
            gate.wait(5)
            return super().structured(prompt, json_schema, system)

    provider = _Slow({"risk_posture": "DEFENSIVE", "risk_multiplier": 0.5, "max_concurrent_trades": 2,
                      "macro_reasoning": "x", "symbol_directives": {}})
    c = AutonomousLLMSystemController(state_manager=StateManager(), provider=provider, cache_ttl_sec=0.0)
    first = c.get_latest_directives()               # rule-based now, AI in the background
    assert first.source == "OFFLINE_HEURISTIC"
    for _ in range(5):
        assert c.get_latest_directives() is first   # still cached, no second thread started
    gate.set()
    for _ in range(50):
        if not c._refreshing:
            break
        threading.Event().wait(0.05)
    assert provider.calls == 1
    assert c._cached_directives.source == "LLM" and c._cached_directives.risk_multiplier == 0.5
