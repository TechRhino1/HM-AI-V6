"""Unit tests for Avellaneda-Stoikov pricing (fallback ladder and calibration engine were removed as dead code, 2026-11-18)."""
import pytest
import math
from jarvis.intelligence.as_pricing import (
    reservation_price,
    half_spread,
    optimal_quote_prices,
    compute_as_limit_entry,
)


def test_avellaneda_stoikov_inventory_skew():
    mid = 2650.0
    # Flat inventory: reservation price == mid
    r_flat = reservation_price(mid=mid, inventory=0.0, gamma=0.1, sigma=0.002, time_left_s=60.0)
    assert r_flat == mid

    # Long inventory (q > 0): reservation price must be below mid to skew towards selling
    r_long = reservation_price(mid=mid, inventory=2.0, gamma=0.1, sigma=0.002, time_left_s=60.0)
    assert r_long < mid

    # Short inventory (q < 0): reservation price must be above mid to skew towards buying
    r_short = reservation_price(mid=mid, inventory=-2.0, gamma=0.1, sigma=0.002, time_left_s=60.0)
    assert r_short > mid


def test_as_limit_entry_pricing():
    entry_buy = compute_as_limit_entry(
        mid=2650.0,
        side="BUY",
        inventory=0.0,
        sigma=0.002,
        spread_pips=2.0,
        pip_size=0.1,
    )
    assert entry_buy["side"] == "BUY"
    assert entry_buy["optimal_limit_price"] <= 2650.0

    entry_sell = compute_as_limit_entry(
        mid=2650.0,
        side="SELL",
        inventory=0.0,
        sigma=0.002,
        spread_pips=2.0,
        pip_size=0.1,
    )
    assert entry_sell["side"] == "SELL"
    assert entry_sell["optimal_limit_price"] >= 2650.0
