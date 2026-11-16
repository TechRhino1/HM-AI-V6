"""
Unit and integration test suite for:
- Small Account ($100) Invariant Dollar Risk Sizing
- Forex 0.02 lot promotion on tight stops
- Gold (XAUUSD) 0.01 lot strict floor on sub-$150 accounts
- Gold 0.02 lot unlock at $150+ milestone tier
- Milestone Compounding & Risk Budgets
- Gold profile strategy weights & killzone windows
- Orchestrator splittable book protocol
"""
import unittest
from jarvis.risk.account_tier import (
    get_max_lot_cap,
    get_nano_risk_cap,
    get_milestone_risk_budget,
    AccountTier,
    get_account_tier,
)
from jarvis.risk.position_sizing import PositionSizer
from jarvis.intelligence.symbol_profile_config import get_symbol_profile_config


class TestNanoCompoundingAndGoldSniper(unittest.TestCase):

    def test_milestone_risk_budgets_progression(self):
        """Risk policy 2026-11-16: the per-trade budget is 1% of equity and grows with it."""
        for equity in (100.0, 180.0, 300.0, 750.0, 5000.0):
            for sym in ("EURUSD", "XAUUSD"):
                usd, pct = get_milestone_risk_budget(equity, sym)
                self.assertEqual(pct, 1.0)
                self.assertAlmostEqual(usd, equity * 0.01)

    def test_max_lot_caps_by_tier_and_asset(self):
        """Verifies lot caps permit 0.02 on FX on $100 while keeping Gold strictly capped at 0.01."""
        # On $100 account:
        self.assertEqual(get_max_lot_cap(100.0, "EURUSD"), 0.02)
        self.assertEqual(get_max_lot_cap(100.0, "GBPUSD"), 0.02)
        self.assertEqual(get_max_lot_cap(100.0, "XAUUSD"), 0.01)  # Gold strictly capped!

        # On $160 account (Tier 2):
        self.assertEqual(get_max_lot_cap(160.0, "EURUSD"), 0.03)
        self.assertEqual(get_max_lot_cap(160.0, "XAUUSD"), 0.02)  # Gold unlocked for 0.02 split!

        # On $300 account (Tier 3):
        self.assertEqual(get_max_lot_cap(300.0, "EURUSD"), 0.05)
        self.assertEqual(get_max_lot_cap(300.0, "XAUUSD"), 0.05)

    def test_forex_tight_stop_sizes_to_002_lots_on_100_dollar_account(self):
        """Verifies EURUSD with an 8-pip stop sizes to 0.02 lots on $100 equity."""
        symbol_info = {
            "name": "EURUSD",
            "symbol": "EURUSD",
            "canonical": "EURUSD",
            "point": 0.00001,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "trade_contract_size": 100000.0,
            "trade_tick_value": 1.0,
            "trade_tick_size": 0.00001,
        }
        # Entry 1.0850, SL 1.0842 (8 pips distance = 0.0008)
        lots = PositionSizer.calculate_lot_size(
            account_balance=100.0,
            entry_price=1.0850,
            sl_price=1.0842,
            risk_pct=2.0,
            symbol_info=symbol_info,
            model_confidence=0.75,
            target_rr=2.5
        )
        self.assertEqual(lots, 0.02)
        # Dollar risk at 0.02 lots = 0.0008 * 100,000 * 0.02 = $1.60 (<= $2.50 milestone budget)
        dollar_risk = 0.0008 * 100000.0 * lots
        self.assertLessEqual(dollar_risk, 2.50)

    def test_gold_on_100_dollar_account_strictly_capped_at_001_lot(self):
        """Verifies Gold with tight stop is strictly capped at 0.01 lot on a $100 account."""
        symbol_info = {
            "name": "XAUUSD",
            "symbol": "XAUUSD",
            "canonical": "XAUUSD",
            "point": 0.01,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "trade_contract_size": 100.0,
            "trade_tick_value": 1.0,
            "trade_tick_size": 0.01,
        }
        # Entry 2650.00, SL 2648.00 ($2.00 distance)
        lots = PositionSizer.calculate_lot_size(
            account_balance=100.0,
            entry_price=2650.00,
            sl_price=2648.00,
            risk_pct=2.5,
            symbol_info=symbol_info,
            model_confidence=0.80,
            target_rr=3.0
        )
        self.assertEqual(lots, 0.01)
        dollar_risk = 2.00 * 100.0 * lots
        self.assertEqual(dollar_risk, 2.00)

    def test_gold_size_never_rounds_up_past_the_risk_budget(self):
        """Risk policy 2026-11-16 removed the 'milestone' round-up: on $160 with a $2.00
        gold stop the sizer's budget is $3.68 (2.30%), so 0.02 lots ($4.00) would exceed it."""
        symbol_info = {
            "name": "XAUUSD",
            "symbol": "XAUUSD",
            "canonical": "XAUUSD",
            "point": 0.01,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "trade_contract_size": 100.0,
            "trade_tick_value": 1.0,
            "trade_tick_size": 0.01,
        }
        lots = PositionSizer.calculate_lot_size(
            account_balance=160.0,
            entry_price=2650.00,
            sl_price=2648.00,
            risk_pct=2.5,
            symbol_info=symbol_info,
            model_confidence=0.85,
            target_rr=3.0
        )
        self.assertEqual(lots, 0.01)
        self.assertLessEqual(2.00 * 100.0 * lots, 160.0 * 0.025)

    def test_an_exact_budget_is_not_floored_a_step_short(self):
        """$400 at the 1% ceiling = $4.00 = exactly 0.02 lots of a 20-pip EURUSD stop.
        Float arithmetic gives 0.0199999..., which the old 1e-9 tolerance floored to 0.01."""
        info = {"name": "EURUSD", "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01,
                "trade_contract_size": 100000.0, "trade_tick_value": 1.0, "trade_tick_size": 0.00001}
        lots = PositionSizer.calculate_lot_size(400.0, 1.08500, 1.08300, 1.0, info,
                                                model_confidence=0.60, pattern_sample_size=5)
        self.assertEqual(lots, 0.02)

    def test_gold_profile_configuration_and_killzones(self):
        """Verifies Gold profile has institutional settings and London/NY prime hours."""
        gold_prof = get_symbol_profile_config("XAUUSD")
        self.assertIsNotNone(gold_prof)
        self.assertEqual(gold_prof.strategy_weights.get("TREND_PULLBACK"), 4.0)
        self.assertEqual(gold_prof.strategy_weights.get("TREND_FOLLOWING"), 3.5)
        self.assertEqual(gold_prof.allowed_utc_hours, (7, 18))
        self.assertTrue(gold_prof.premium_window_exception)
        self.assertEqual(gold_prof.premium_out_of_window_min_ai_score, 85.0)
        self.assertEqual(gold_prof.fast_cash_r, 1.10)
        self.assertEqual(gold_prof.be_trigger_r, 1.20)

    def test_orchestrator_splittable_book_logic(self):
        """Verifies book splitting logic correctly identifies 0.02 lots as splittable."""
        from jarvis.application.orchestrator import JarvisOrchestrator
        from unittest.mock import MagicMock

        orch = JarvisOrchestrator.__new__(JarvisOrchestrator)
        orch.risk_engine = MagicMock()
        orch.risk_engine.max_risk_per_trade_pct = 0.5

        # EURUSD 8-pip stop on $100 account
        spec = MagicMock()
        spec.pip_size = 0.0001
        spec.pip_value_per_lot = 10.0

        # With 8 pips stop ($80/lot) and 2% risk budget ($2.00), ideal_lots = 2.00 / 80 = 0.025
        # 0.025 >= 2 * 0.01 = 0.02, so it is splittable (returns False for _is_unsplittable_book)
        is_unsplit = orch._is_unsplittable_book(
            entry_price=1.0850,
            stop_loss=1.0842,
            equity=100.0,
            spec=spec,
            volume_min=0.01
        )
        self.assertFalse(is_unsplit, "0.025 ideal lots must be recognized as splittable!")

        # With a 30-pip stop ($300/lot), ideal_lots = 2.00 / 300 = 0.0067 < 0.02 -> unsplittable
        is_unsplit_wide = orch._is_unsplittable_book(
            entry_price=1.0850,
            stop_loss=1.0820,
            equity=100.0,
            spec=spec,
            volume_min=0.01
        )
        self.assertTrue(is_unsplit_wide, "0.0067 ideal lots must be recognized as unsplittable.")


if __name__ == "__main__":
    unittest.main()
