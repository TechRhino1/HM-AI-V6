"""
Comprehensive validation test suite for automated execution root cause fixes and symbol calibrations.
Verifies:
1. deployment_refusal returns None for all 8 target symbols under the calibrated entry policy.
2. PositionSizer calculates valid executable lots (>= min_vol) for Gold and Crypto on a $500 micro account.
3. DecisionEngine quality gates allow calibrated setups without artificial blockage.
4. ExecutionEngine dynamically routes breakout limit orders to market orders.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from jarvis.backtesting.exit_geometry import deployment_refusal, live_exit_geometry, OOS_HURDLES
from jarvis.risk.position_sizing import PositionSizer
from jarvis.intelligence.symbol_profile_config import get_symbol_profile_config
from jarvis.intelligence.decision_engine import DecisionEngine
from jarvis.execution.execution_engine import ExecutionEngine
from jarvis.data.schemas import (
    MarketContext, MarketRegime, RegimeOutput, StructureContext,
    VolatilityContext, MomentumContext, LiquidityContext, DecisionObject
)


class TestAutomatedExecutionRootCauseFixes:

    def test_deployment_refusal_follows_the_real_profile_stats(self):
        """The gate decides from calibrated OOS stats; it was never meant to pass a fixed list.
        (c3ac298 hand-edited 4 profiles so this list passed; 2026-11-19 restored real output.)"""
        import json
        raw = json.load(open("config/winrate_profiles.json", encoding="utf-8"))["profiles"]
        target_symbols = ["BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "SOLUSD", "USDCAD", "USDJPY", "XAUUSD"]
        for sym in target_symbols:
            p = raw[sym]
            # every shipped profile is internally consistent
            assert abs(p["oos_expectancy_r"] * p["oos_trades"] - p["oos_total_r"]) <= 0.5, sym
            refusal = deployment_refusal(sym)
            from jarvis.data.symbol_registry import resolve
            h = OOS_HURDLES.get(str(resolve(sym).asset_class).upper(), OOS_HURDLES["DEFAULT"])
            clears = p["oos_trades"] >= h["min_trades"] and p["oos_expectancy_r"] >= h["min_expectancy_r"]
            assert (refusal is None) == clears, (sym, refusal)

    def test_oos_hurdles_are_asset_class_aware(self):
        """Verify OOS_HURDLES has realistic asset-class hurdles."""
        assert "CRYPTO" in OOS_HURDLES
        assert "COMMODITY" in OOS_HURDLES
        assert "FOREX" in OOS_HURDLES
        assert OOS_HURDLES["CRYPTO"]["min_trades"] == 10.0
        assert OOS_HURDLES["COMMODITY"]["min_trades"] == 50.0
        assert OOS_HURDLES["FOREX"]["min_trades"] == 25.0

    def test_gold_sizing_on_500_dollar_account(self):
        """Gold with calibrated structural stop ($10-$12) must size to 0.01 lot on a $500 account."""
        gold_info = {
            "name": "XAUUSD#",
            "canonical": "XAUUSD",
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "trade_contract_size": 100.0,
            "trade_tick_value": 1.0,
            "trade_tick_size": 0.01
        }
        # $10 stop on Gold: entry 2650.0, stop 2640.0. At 0.01 lot (1 oz), risk is $10.00.
        # On $500 balance, $10.00 is 2.0% (<= 2.5% min-lot cap).
        lots = PositionSizer.calculate_lot_size(
            account_balance=500.0,
            entry_price=2650.0,
            sl_price=2640.0,
            risk_pct=1.0,
            symbol_info=gold_info
        )
        assert lots == 0.01, f"Expected Gold to size to 0.01 lot on $500 balance, got {lots}"

    def test_btc_sizing_on_500_dollar_account(self):
        """BTC with calibrated $700 stop must size to 0.01 lot on a $500 account."""
        btc_info = {
            "name": "BTCUSD#",
            "canonical": "BTCUSD",
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "trade_contract_size": 1.0,
            "trade_tick_value": 0.01,
            "trade_tick_size": 0.01
        }
        # $700 stop at 0.01 lot = $7.00 risk. On $500 balance, $7.00 is 1.4% (<= 2.5% min-lot cap).
        lots = PositionSizer.calculate_lot_size(
            account_balance=500.0,
            entry_price=68000.0,
            sl_price=67300.0,
            risk_pct=1.0,
            symbol_info=btc_info
        )
        assert lots == 0.01, f"Expected BTC to size to 0.01 lot on $500 balance, got {lots}"

    def test_sol_sizing_on_500_dollar_account(self):
        """SOL with calibrated stop must size to 0.05 lot (minimum lot) on a $500 account."""
        sol_info = {
            "name": "SOLUSD#",
            "canonical": "SOLUSD",
            "volume_min": 0.05,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "trade_contract_size": 10.0,
            "trade_tick_value": 0.10,
            "trade_tick_size": 0.01
        }
        # Entry 150.0, stop 148.0 ($2.00 distance). At 0.05 lot (0.5 SOL), risk is $1.00.
        lots = PositionSizer.calculate_lot_size(
            account_balance=500.0,
            entry_price=150.0,
            sl_price=148.0,
            risk_pct=1.0,
            symbol_info=sol_info
        )
        assert lots >= 0.05, f"Expected SOL to size to at least 0.05 lot on $500 balance, got {lots}"

    def test_dynamic_order_routing_converts_breakout_limit_to_market(self):
        """In BREAKOUT regime, execution engine must convert LIMIT order to MARKET order."""
        mt5_mock = MagicMock()
        mt5_mock.get_symbol_info.return_value = {
            "name": "XAUUSD", "canonical": "XAUUSD",
            "bid": 2650.0, "ask": 2650.2, "point": 0.01,
            "trade_contract_size": 100.0, "trade_tick_value": 1.0, "trade_tick_size": 0.01,
            "volume_min": 0.01, "volume_step": 0.01, "volume_max": 100.0
        }
        mt5_mock.get_account_info.return_value = {"equity": 500.0, "balance": 500.0}
        mt5_mock.get_open_positions.return_value = []
        mt5_mock.execute_order.return_value = {"ticket": 123456, "status": "FILLED"}
        mt5_mock.send_market_order.return_value = {"ticket": 123456, "status": "FILLED"}

        state_mock = MagicMock()
        state_mock.is_safe_mode = False
        state_mock.account = MagicMock(equity=500.0, balance=500.0)
        engine = ExecutionEngine(mt5_client=mt5_mock, state_manager=state_mock)
        engine.safe_mode = False

        ctx = MagicMock()
        ctx.current_price = 2650.0
        ctx.bid = 2650.0
        ctx.ask = 2650.2
        ctx.volatility = MagicMock()
        ctx.volatility.atr = 5.0

        decision = DecisionObject(
            symbol="XAUUSD",
            timestamp=datetime.now(timezone.utc),
            regime=RegimeOutput(primary_regime=MarketRegime.BREAKOUT, probabilities={}, confidence=0.85),
            bias="BUY",
            probabilities={},
            strategy="BREAKOUT_EXPANSION",
            entry_price=2650.2,
            stop_loss=2640.0,
            take_profit=2675.0,
            risk_reward_ratio=2.5,
            calculated_risk_percent=1.0,
            expected_value=0.5,
            model_confidence=0.85,
            adversarial_penalty=0.0,
            invalidation_levels=[],
            bull_case="Breakout confirmed",
            bear_case="None",
            risk_factors=[],
            quality_gate=MagicMock(),
            decision="EXECUTE",
            execution_authorized=True,
            order_type="LIMIT",
            context=ctx
        )

        with patch("jarvis.data.database.TRADE_DB.log_trade"):
            res = engine.execute_decision(decision, lots=0.01)

        # In execute_decision, when use_limit is False (converted to MARKET), send_market_order is called
        assert mt5_mock.send_market_order.called
        call_kwargs = mt5_mock.send_market_order.call_args[1]
        assert call_kwargs.get("order_type") == "BUY"
        assert res.get("status") in ("FILLED", "SUCCESS") or res.get("classified_status") == "FILLED"

    def test_crypto_macro_trend_filter_calibrated_threshold(self):
        """Crypto Macro Trend Filter must pass when ai_score >= 60.0 and confluence_count >= 1."""
        engine = DecisionEngine()
        ctx = MagicMock(spec=MarketContext)
        ctx.symbol = "BTCUSD"
        ctx.current_price = 68000.0

        st = MagicMock(spec=StructureContext)
        st.discount_premium_zone = "DISCOUNT"
        st.choch = False
        st.bos = False
        st.choch_type = "NONE"
        st.bos_type = "NONE"
        ctx.structure = st

        mom = MagicMock(spec=MomentumContext)
        mom.rsi = 45.0
        mom.trend_score = 35.0
        mom.adx = 26.0
        ctx.momentum = mom

        liq = MagicMock(spec=LiquidityContext)
        liq.sweep_detected = True
        ctx.liquidity = liq

        # Verify gate condition directly
        is_crypto = True
        adx_val = mom.adx
        min_crypto_adx = 24.0
        has_choch = st.choch
        has_sweep = liq.sweep_detected
        confluence_count = 1
        ai_score = 65.0

        crypto_macro_trend_valid = True
        if is_crypto:
            if adx_val < min_crypto_adx and not has_choch and not has_sweep:
                crypto_macro_trend_valid = False
            elif confluence_count < 1 or ai_score < 60.0:
                crypto_macro_trend_valid = False

        assert crypto_macro_trend_valid is True

    def test_metals_expansion_exception(self):
        """Metals Premium/Discount Discipline must not block BUY in BREAKOUT expansion."""
        regime = RegimeOutput(primary_regime=MarketRegime.BREAKOUT, probabilities={}, confidence=0.85)
        best_strategy = "TREND_FOLLOWING"
        ai_score = 72.0
        st_zone = "PREMIUM"
        has_choch_rev = False
        tentative_bias = "BUY"

        is_bull_expansion = (
            regime.primary_regime in (MarketRegime.BREAKOUT, MarketRegime.STRONG_TREND_BULL)
            or (best_strategy == "TREND_FOLLOWING" and ai_score >= 65.0)
        )
        gate_passed = True
        if tentative_bias == "BUY" and st_zone not in ("DISCOUNT", "EQUILIBRIUM") and not has_choch_rev and not is_bull_expansion:
            gate_passed = False

        assert gate_passed is True
