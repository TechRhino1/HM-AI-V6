"""Unit and Contract Tests for Bugatti Cockpit UI & Extended Intelligence Endpoints."""
import unittest
import os
import json
from jarvis.api.intelligence_api import INTELLIGENCE
from jarvis.risk.risk_engine import RiskEngine
from jarvis.data.schemas import AccountSnapshot


class TestBugattiEndpoints(unittest.TestCase):
    def setUp(self):
        self.risk_engine = RiskEngine()

    def test_risk_status_includes_portfolio_heat_and_hrp(self):
        """Verify get_risk_status returns full cockpit heat instrument telemetry."""
        acc = AccountSnapshot(
            login=101059540,
            server="XMGlobal-MT5",
            balance=10000.0,
            equity=10000.0,
            margin=500.0,
            free_margin=9500.0,
            margin_level=2000.0,
            leverage=100
        )
        status = self.risk_engine.get_risk_status(10000.0, 10000.0, account=acc, positions=[])
        self.assertIn("portfolio_heat_score", status)
        self.assertIn("portfolio_heat_zone", status)
        self.assertIn("heat_risk_multiplier", status)
        self.assertIn("margin_utilization_pct", status)
        self.assertIn("hrp_weights", status)
        self.assertEqual(status["portfolio_heat_zone"], "NORMAL")
        self.assertGreaterEqual(status["portfolio_heat_score"], 0.0)
        self.assertLessEqual(status["portfolio_heat_score"], 100.0)
        self.assertIn("XAUUSD", status["hrp_weights"])

    def test_intelligence_missed_trades_endpoint(self):
        """Verify /api/intelligence/missed-trades returns structured vetoed opportunities."""
        class MockHandler:
            def __init__(self): self.data = None
        import jarvis.api.intelligence_api as mod
        from unittest.mock import patch
        from jarvis.application.state_manager import GLOBAL_STATE
        refused = [
            # SELL refused, price then fell: the refusal cost a winner.
            {"symbol": "XAUUSD", "bias": "SELL", "trade_style": "SCALP", "decision": "WAIT",
             "entry_price": 3821.0, "current_price": 3792.0, "failing_reasons": ["Devil Adversarial Guard"]},
            # BUY refused, price then fell: the refusal protected capital.
            {"symbol": "EURUSD", "bias": "BUY", "trade_style": "SWING", "decision": "WAIT",
             "entry_price": 1.10, "current_price": 1.09, "failing_reasons": ["Forex Prime Session"]},
        ]
        old_json = mod._json
        try:
            mod._json = lambda h, p, c=200: setattr(h, 'data', p)
            handler = MockHandler()
            with patch.object(GLOBAL_STATE, "get_state_snapshot", return_value={"radar_opportunities": refused}):
                handled = INTELLIGENCE.handle_get('/api/intelligence/missed-trades', {}, handler)
            self.assertTrue(handled)
            self.assertEqual(handler.data["status"], "OK")
            by_sym = {t["symbol"]: t for t in handler.data["missed_trades"]}
            self.assertFalse(by_sym["XAUUSD"]["protected_capital"])
            self.assertTrue(by_sym["EURUSD"]["protected_capital"])
            self.assertEqual(by_sym["XAUUSD"]["style"], "SCALP")
            self.assertIn("gate", by_sym["XAUUSD"])

            # No refused setups: an empty list, never invented examples.
            with patch.object(GLOBAL_STATE, "get_state_snapshot", return_value={"radar_opportunities": []}):
                INTELLIGENCE.handle_get('/api/intelligence/missed-trades', {}, handler)
            self.assertEqual(handler.data["count"], 0)
        finally:
            mod._json = old_json

    def test_intelligence_calibration_endpoint(self):
        """Verify /api/intelligence/calibration returns Brier score, ECE, and honest base rates."""
        class MockHandler:
            def __init__(self): self.data = None
        import jarvis.api.intelligence_api as mod
        old_json = mod._json
        try:
            mod._json = lambda h, p, c=200: setattr(h, 'data', p)
            handler = MockHandler()
            handled = INTELLIGENCE.handle_get('/api/intelligence/calibration', {}, handler)
            self.assertTrue(handled)
            self.assertIsNotNone(handler.data)
            self.assertEqual(handler.data["status"], "OK")
            self.assertIn("brier_score", handler.data)
            self.assertIn("ece", handler.data)
            self.assertIn("calibration_bins", handler.data)
            self.assertIn("honest_base_rates", handler.data)
            self.assertIn("XAUUSD", handler.data["honest_base_rates"])
        finally:
            mod._json = old_json

    def test_intelligence_symbol_profiles_endpoint(self):
        """Verify /api/intelligence/symbol-profiles returns all 20 symbol configs."""
        class MockHandler:
            def __init__(self): self.data = None
        import jarvis.api.intelligence_api as mod
        old_json = mod._json
        try:
            mod._json = lambda h, p, c=200: setattr(h, 'data', p)
            handler = MockHandler()
            handled = INTELLIGENCE.handle_get('/api/intelligence/symbol-profiles', {}, handler)
            self.assertTrue(handled)
            self.assertIsNotNone(handler.data)
            self.assertEqual(handler.data["status"], "OK")
            self.assertEqual(handler.data["count"], 21)
            profiles = handler.data["profiles"]
            self.assertIn("XAUUSD", profiles)
            self.assertIn("EURUSD", profiles)
            self.assertIn("BTCUSD", profiles)
            # Gold must have its calibrated BE trigger
            self.assertIn(profiles["XAUUSD"]["be_trigger_r"], (1.20, 1.80))
            self.assertIn(profiles["XAUUSD"]["fast_cash_r"], (1.10, 1.50))
        finally:
            mod._json = old_json


if __name__ == "__main__":
    unittest.main()
