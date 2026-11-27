"""
Tests for Institutional Profit Asymmetry, Small-Account Risk Cap, and Exit Logic Audit.
Verifies:
1. Gold stop loss distance is strictly capped at <= 12.50 points for micro-account protection.
2. Small-account position sizer strictly rejects setups requiring > $12.00 risk on accounts < $500.
3. Crypto stop loss distances are tightened to local execution structure (ETH <= 32 pts, BTC <= 750 pts).
4. Crypto position sizing yields normalized, meaningful lot sizes without forcing min_lot artificially.
5. ExecutionEngine blocks setups where broker stops_level > 2x planned stop or where micro risk > $12.00.
6. Position monitor provides full breathing room below +1.0R without choking trades at +0.50R.
"""
from datetime import datetime, timezone
import pytest

from jarvis.risk.position_sizing import PositionSizer
from jarvis.intelligence.symbol_profile_config import get_symbol_profile_config
from jarvis.intelligence.dynamic_levels import DynamicRiskAndLevelsEngine
from jarvis.data.schemas import (
    MarketContext,
    StructureContext,
    LiquidityContext,
    VolatilityContext,
    MomentumContext,
    SessionContext,
    RegimeOutput,
    MarketRegime,
    PositionSnapshot,
    DecisionObject,
)
from jarvis.execution.position_monitor import PositionMonitorEngine
from jarvis.execution.exit_policy import ExitPolicy, evaluate_exit
from jarvis.execution.execution_engine import ExecutionEngine


def test_gold_sl_distance_cap():
    """Gold's $12+spread stop cap applies to SCALP/DAY only (user decision 2026-11-27). On SWING
    a $12 stop is ~0.7x H1 ATR - inside one normal H1 bar - so SWING keeps its ATR ceiling and
    sizing refuses a stop the minimum lot cannot afford (it never squeezes the stop)."""
    engine = DynamicRiskAndLevelsEngine()
    
    ctx = MarketContext(
        symbol="XAUUSD",
        timestamp=datetime.now(timezone.utc),
        ask=4150.00,
        bid=4149.80,
        current_price=4149.90,
        structure=StructureContext(
            bias="BULLISH",
            demand_zone=(4110.00, 4120.00),  # 30-40 points away!
            supply_zone=(4180.00, 4190.00),
            order_blocks=[{"type": "BULLISH_ORDER_BLOCK", "low": 4110.00}],  # 40 points away!
        ),
        liquidity=LiquidityContext(buy_side_liquidity=4190.00, sell_side_liquidity=4100.00),
        volatility=VolatilityContext(atr=18.00, current_spread_pips=2.0),
        momentum=MomentumContext(trend_score=35.0, adx=28.0),
        session=SessionContext(is_prime_session=True),
        trade_style="SWING",
    )
    regime = RegimeOutput(
        primary_regime=MarketRegime.TREND_BULL,
        probabilities={"TREND_BULL": 0.85},
        confidence=0.85,
    )

    swing = engine.calculate_levels(ctx, regime, tentative_bias="BUY", trade_style="SWING")
    assert swing["risk_dist"] > 12.50, f"Gold swing SL ({swing['risk_dist']}) is still squeezed to the scalp cap"
    assert swing["rr_ratio"] >= 1.8, f"Gold R:R ({swing['rr_ratio']}) is below institutional minimum 1.8:1"
    for style in ("SCALP", "DAY_TRADING"):
        lv = engine.calculate_levels(ctx, regime, tentative_bias="BUY", trade_style=style)
        assert lv["risk_dist"] <= 12.50, f"Gold {style} SL distance ({lv['risk_dist']}) exceeds 12.50 points!"


def test_micro_account_gold_dollar_risk_cap():
    """Verify that PositionSizer caps micro-account ($444) Gold risk to <= $12.00."""
    account_balance = 444.0
    entry_price = 4150.00
    
    # Case A: Reasonable stop of 8.0 points -> $8.00 risk on 0.01 lot -> APPROVED
    sl_price_8pt = 4142.00
    symbol_info = {
        "name": "XAUUSD",
        "canonical": "XAUUSD",
        "trade_contract_size": 100.0,
        "trade_tick_value": 1.0,
        "trade_tick_size": 0.01,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
    }
    lots = PositionSizer.calculate_lot_size(
        account_balance=account_balance,
        entry_price=entry_price,
        sl_price=sl_price_8pt,
        risk_pct=1.5,
        symbol_info=symbol_info,
    )
    assert lots == 0.01, f"Expected 0.01 lot for 8pt stop on micro account, got {lots}"

    # Case B: Uncontrolled wide stop of 25.0 points -> $25.00 risk on 0.01 lot -> REJECTED (0.0)
    sl_price_25pt = 4125.00
    lots_wide = PositionSizer.calculate_lot_size(
        account_balance=account_balance,
        entry_price=entry_price,
        sl_price=sl_price_25pt,
        risk_pct=1.5,
        symbol_info=symbol_info,
    )
    assert lots_wide == 0.0, f"Wide stop ($25 risk) on micro account must be REJECTED, but got {lots_wide} lots!"


def test_crypto_local_sl_and_normalized_sizing():
    """Verify that ETHUSD SL is bounded to local structure and sizes meaningfully."""
    engine = DynamicRiskAndLevelsEngine()
    
    ctx = MarketContext(
        symbol="ETHUSD",
        timestamp=datetime.now(timezone.utc),
        ask=2430.50,
        bid=2430.00,
        current_price=2430.25,
        structure=StructureContext(
            bias="BULLISH",
            demand_zone=(2300.00, 2320.00),  # 110 points away!
            supply_zone=(2550.00, 2580.00),
            order_blocks=[{"type": "BULLISH_ORDER_BLOCK", "low": 2415.00}],  # 15 points away
        ),
        liquidity=LiquidityContext(buy_side_liquidity=2520.00, sell_side_liquidity=2350.00),
        volatility=VolatilityContext(atr=22.00, current_spread_pips=50.0),
        momentum=MomentumContext(trend_score=25.0, adx=26.0),
        session=SessionContext(is_prime_session=True),
        trade_style="DAY_TRADING",
    )
    regime = RegimeOutput(
        primary_regime=MarketRegime.TREND_BULL,
        probabilities={"TREND_BULL": 0.80},
        confidence=0.80,
    )

    levels = engine.calculate_levels(ctx, regime, tentative_bias="BUY", trade_style="DAY_TRADING")
    
    assert levels["risk_dist"] <= 32.0, f"ETH risk dist ({levels['risk_dist']}) exceeds 32 points!"
    assert levels["rr_ratio"] >= 1.8, f"ETH R:R ({levels['rr_ratio']}) below 1.8:1"

    # Verify position sizer on normalized 20-point stop:
    symbol_info_eth = {
        "name": "ETHUSD",
        "canonical": "ETHUSD",
        "trade_contract_size": 1.0,
        "trade_tick_value": 0.01,
        "trade_tick_size": 0.01,
        "volume_min": 0.02,
        "volume_max": 100.0,
        "volume_step": 0.01,
    }
    lots_eth = PositionSizer.calculate_lot_size(
        account_balance=450.0,
        entry_price=2430.0,
        sl_price=2410.0,  # 20 points risk
        risk_pct=1.5,
        symbol_info=symbol_info_eth,
    )
    # 1.5% of $450 = $6.75. 20 points on contract_size 1.0 = $20/lot.
    # $6.75 / $20 = ~0.33 lots.
    assert lots_eth >= 0.25, f"ETH lot size ({lots_eth}) is too small! Expected >= 0.25 lots."


def _distorted_gold_decision():
    from jarvis.data.schemas import TradeQualityGateResult
    return DecisionObject(
        symbol="GOLD.i#", timestamp=datetime.now(timezone.utc),
        regime=RegimeOutput(primary_regime=MarketRegime.RANGE, probabilities={"RANGE": 0.8}, confidence=0.8),
        bias="SELL", probabilities={"SELL": 0.8}, strategy="SCALP",
        entry_price=4159.31, stop_loss=4160.62, take_profit=4156.95,   # 1.31 / 2.36 pts
        risk_reward_ratio=1.80, calculated_risk_percent=1.0, expected_value=1.5, model_confidence=0.75,
        adversarial_penalty=0.0, invalidation_levels=["4161.00"], bull_case=["bounce"], bear_case=["breakdown"],
        risk_factors=[], quality_gate=TradeQualityGateResult(passed=True, checks={}), decision="EXECUTE",
        execution_authorized=True, order_type="MARKET", sl_distance=1.31, tp_distance=2.36,
    )


_DISTORTED_SPEC = {"name": "GOLD.i#", "point": 0.01, "digits": 2, "trade_stops_level": 2400,   # 24.00 points
                   "spread": 25, "volume_min": 0.01, "volume_step": 0.01,
                   "trade_tick_size": 0.01, "trade_tick_value": 1.0}


def _engine(equity):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    client = MagicMock()
    client.send_market_order.return_value = {"status": "FILLED", "ticket": 1, "price": 4159.31}
    return ExecutionEngine(mt5_client=client, state_manager=SimpleNamespace(
        account=SimpleNamespace(equity=equity, balance=equity))), client


def test_distorted_broker_stops_block_when_the_min_lot_breaches_the_risk_cap():
    """0ac7cf2: a broker stops_level wider than the planned stop no longer blocks outright; the stop
    is widened to the broker minimum. It still blocks when even the minimum lot at that wider stop
    breaches the min-lot risk ceiling ($24 at 0.01 gold vs 2.5% of $545)."""
    eng, client = _engine(545.0)
    res = eng.execute_decision(_distorted_gold_decision(), lots=0.01, sym_spec=dict(_DISTORTED_SPEC))
    assert res.get("status") == "BLOCKED" and "min-lot ceiling" in str(res.get("reason")), res
    client.send_market_order.assert_not_called()


def test_distorted_broker_stops_are_widened_with_the_target_on_a_large_account():
    eng, client = _engine(100_000.0)
    d = _distorted_gold_decision()
    eng.execute_decision(d, lots=0.01, sym_spec=dict(_DISTORTED_SPEC))
    assert d.stop_loss - d.entry_price >= 24.0 - 1e-6          # SELL stop moved to the broker minimum
    assert d.risk_reward_ratio >= 2.0 - 1e-6                    # gold target expanded to >= 2R


def test_position_monitor_breathing_room():
    """Verify that PositionMonitorEngine does NOT choke trades to breakeven at +0.50R."""
    monitor = PositionMonitorEngine(mt5_client=None, data_feed=None, context_engine=None)
    
    pos = PositionSnapshot(
        ticket=123456,
        symbol="XAUUSD",
        type="BUY",
        volume=0.01,
        open_price=4150.00,
        sl=4142.00,  # 8.0 points risk
        tp=4168.00,  # 18.0 points reward
        profit=4.00, # +0.50R gain
        current_price=4154.00,
        swap=0.0,
        commission=0.0,
        magic=888999,
        open_time="2026-10-17 12:00:00",
    )
    
    ctx = MarketContext(
        symbol="XAUUSD",
        timestamp=datetime.now(timezone.utc),
        ask=4154.20,
        bid=4154.00,
        current_price=4154.00,
        structure=StructureContext(bias="BULLISH", choch=False, bos=False),
        liquidity=LiquidityContext(buy_side_liquidity=4170.0, sell_side_liquidity=4140.0),
        volatility=VolatilityContext(atr=10.0, current_spread_pips=2.0),
        momentum=MomentumContext(trend_score=-15.0), # minor adverse tick
        session=SessionContext(is_prime_session=True),
    )
    
    new_sl, act, should_close, reason = monitor._check_market_direction_reversal(
        pos=pos,
        ctx=ctx,
        c_price=4154.00,
        atr=10.0,
        risk_dist=8.0,
        current_r=0.50,
        digits=2,
        current_sl=4142.00,
        policy=ExitPolicy.for_symbol("XAUUSD"),
    )
    
    # Must NOT close or move SL to breakeven at +0.50R
    assert not should_close, "Trade was prematurely closed at +0.50R!"
    assert new_sl == 4142.00, f"Trade was prematurely choked to BE (new_sl={new_sl}) at +0.50R!"
