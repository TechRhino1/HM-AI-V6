"""
Integration tests for the TradingView live data provider.
"""
import unittest
import pytest

pytestmark = pytest.mark.network

from jarvis.data.tradingview_provider import TradingViewDataProvider, TRADINGVIEW_PROVIDER
from jarvis.data.market_data_provider import fetch_real_candles


class TestTradingViewDataProvider(unittest.TestCase):
    def setUp(self):
        self.provider = TradingViewDataProvider(request_timeout=10)

    def test_fetch_quotes_us_equities(self):
        symbols = ["AAPL", "NVDA", "TSLA", "MSFT"]
        quotes = self.provider.fetch_quotes(symbols)
        self.assertIsInstance(quotes, dict)

        for sym in symbols:
            self.assertIn(sym, quotes, f"Expected {sym} in quotes")
            q = quotes[sym]
            self.assertEqual(q["source"], "tradingview")
            self.assertGreater(q["price"], 0.0)
            self.assertGreater(q["open"], 0.0)
            self.assertGreater(q["high"], 0.0)
            self.assertGreater(q["low"], 0.0)
            self.assertGreater(q["close"], 0.0)
            self.assertIn("change_val", q)
            self.assertIn("change_pct", q)
            self.assertIn("volume", q)
            self.assertIn("rsi", q)

    def test_fetch_quotes_forex_and_crypto(self):
        quotes = self.provider.fetch_quotes(["EURUSD", "BTCUSD"])
        self.assertIsInstance(quotes, dict)
        if "EURUSD" in quotes:
            self.assertGreater(quotes["EURUSD"]["price"], 0.5)
        if "BTCUSD" in quotes:
            self.assertGreater(quotes["BTCUSD"]["price"], 1000.0)

    def test_fetch_candles_format(self):
        candles = self.provider.fetch_candles("AAPL", timeframe="1D", num_bars=10)
        self.assertIsNotNone(candles)
        self.assertEqual(len(candles), 10)

        for bar in candles:
            self.assertIn("time", bar)
            self.assertIn("open", bar)
            self.assertIn("high", bar)
            self.assertIn("low", bar)
            self.assertIn("close", bar)
            self.assertIn("volume", bar)
            self.assertIsInstance(bar["time"], int)
            self.assertIsInstance(bar["open"], float)
            self.assertIsInstance(bar["high"], float)
            self.assertIsInstance(bar["low"], float)
            self.assertIsInstance(bar["close"], float)
            self.assertIsInstance(bar["volume"], int)

        # Chronological order check
        self.assertLess(candles[0]["time"], candles[-1]["time"])

    def test_market_data_provider_hierarchy(self):
        candles = fetch_real_candles("AAPL", timeframe="1D", num_bars=5)
        self.assertIsNotNone(candles)
        self.assertGreaterEqual(len(candles), 5)


if __name__ == "__main__":
    unittest.main()
