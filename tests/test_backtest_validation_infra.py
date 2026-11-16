"""Backtest validation infrastructure (2026-11-16): real MTF slicing, no live-calendar leakage."""
import numpy as np
import pandas as pd

from jarvis.backtesting.engine import BacktestEngine, MTF_TAIL_BARS


def _bars(n, minutes, start="2026-01-01"):
    t = pd.date_range(start, periods=n, freq=f"{minutes}min")
    c = np.linspace(100, 110, n)
    return pd.DataFrame({"time": t, "open": c, "high": c + 0.1, "low": c - 0.1, "close": c, "volume": 1.0})


def test_slices_are_completed_bars_only_and_bounded():
    eng = object.__new__(BacktestEngine)
    m5 = _bars(5000, 5)
    prepared = BacktestEngine._prepare_mtf({"M5": m5}, {"timing": "M5"})
    cutoff = m5["time"].iloc[3000]
    out = eng._slice_mtf(prepared, {"timing": "M5"}, cutoff)["timing"]
    # The bar that OPENED at the cutoff closes 5 minutes later: not visible yet.
    assert out["time"].iloc[-1] == m5["time"].iloc[2999]
    assert len(out) == MTF_TAIL_BARS


def test_nothing_is_visible_before_the_first_bar_closes():
    eng = object.__new__(BacktestEngine)
    m5 = _bars(10, 5)
    prepared = BacktestEngine._prepare_mtf({"M5": m5}, {"timing": "M5"})
    assert eng._slice_mtf(prepared, {"timing": "M5"}, m5["time"].iloc[0]) == {}


def test_the_backtest_macro_analyst_never_sees_the_live_calendar():
    assert BacktestEngine().analyst_cluster.macro_analyst.news_calendar == []
