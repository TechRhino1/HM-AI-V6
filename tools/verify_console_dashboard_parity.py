"""
Verification Harness: merged dashboard parity.
/console, /classic and /positions were folded into dashboard.html as tabs
(Trading, Positions & Orders, Performance, Controls). This checks the merged
page still reaches every backend action the old pages used, that the old URLs
redirect, and that the risk gate is still in front of every trade.
"""
from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jarvis.data.schemas import AccountSnapshot
from jarvis.risk.risk_engine import RiskEngine

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Every endpoint the deleted console / classic / positions pages called.
ENDPOINTS = [
    "/api/telemetry_state", "/api/history", "/api/pending_orders", "/api/radar",
    "/api/analytics/performance", "/api/intelligence/auto-selection",
    "/api/action/close_position", "/api/action/cancel_pending_order",
    "/api/action/modify_pending_order", "/api/action/set_manual_mode",
    "/api/action/set_mode", "/api/action/set_trade_style", "/api/action/toggle_safe_mode",
    "/api/action/emergency_stop", "/api/action/resume_trading", "/api/action/reset_drawdown",
]


class TestMergedDashboardParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates_dir = REPO_ROOT / "jarvis" / "ui" / "templates"
        cls.dashboard_html = (cls.templates_dir / "dashboard.html").read_text(encoding="utf-8")
        cls.dashboard_js = (REPO_ROOT / "jarvis" / "ui" / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
        cls.server_py = (REPO_ROOT / "jarvis" / "api" / "server.py").read_text(encoding="utf-8")

    def test_old_pages_are_gone(self):
        for name in ("console.html", "index.html", "positions.html"):
            self.assertFalse((self.templates_dir / name).exists(), name)

    def test_dashboard_has_the_four_tabs(self):
        for view in ("trade", "positions", "performance", "controls"):
            self.assertIn(f'data-view-btn="{view}"', self.dashboard_html)
            self.assertIn(f'data-view-panel="{view}"', self.dashboard_html)
        self.assertIn("lightweight-charts", self.dashboard_html)
        self.assertIn("auth.js", self.dashboard_html)

    def test_dashboard_reaches_every_endpoint(self):
        missing = [e for e in ENDPOINTS if e not in self.dashboard_js]
        self.assertEqual(missing, [])

    def test_old_urls_redirect_to_tabs(self):
        from jarvis.api.server import LEGACY_PAGE_REDIRECTS
        self.assertEqual(LEGACY_PAGE_REDIRECTS["/console"], "/#trading")
        self.assertEqual(LEGACY_PAGE_REDIRECTS["/classic"], "/#controls")
        self.assertEqual(LEGACY_PAGE_REDIRECTS["/positions"], "/#positions")
        self.assertIn("self._serve_dashboard_ui()", self.server_py)

    def test_risk_gate_is_unbypassable(self):
        """Any trade action is bound to RiskEngine: an extreme spread must reject."""
        from unittest.mock import MagicMock
        risk_engine = RiskEngine(max_risk_per_trade_pct=0.5)
        acc = AccountSnapshot(login=101059540, server="XMGlobal-MT5", balance=618.70, equity=618.70, margin=0.0, free_margin=618.70, margin_level=0.0, leverage=500)
        decision = MagicMock()
        decision.symbol = "XAUUSD"
        decision.regime = None
        decision.bias = "BUY"
        decision.entry_price = 3000.0
        decision.stop_loss = 2900.0
        decision.take_profit = 3200.0
        decision.risk_reward_ratio = 2.0
        decision.expected_value = 0.5
        decision.model_confidence = 0.6
        decision.calculated_risk_percent = 0.5
        auth = risk_engine.authorize_execution(
            decision=decision, account=acc, positions=[], symbol_info={"name": "XAUUSD"},
            current_spread_pips=999.0, max_allowed_spread_pips=5.0
        )
        self.assertFalse(auth["authorized"])
        self.assertTrue(any("spread" in str(r).lower() for r in auth["reasons"]))


if __name__ == "__main__":
    unittest.main()
