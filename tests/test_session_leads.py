"""Pre-registered session leads: causal signals on real bars, and the promotion rule."""
import os

import pandas as pd
import pytest

from jarvis.forward_tests import session_leads as sl

REAL = os.path.join("data", "market", "real", "EURUSD", "EURUSD_H1_730d.parquet")


@pytest.fixture(scope="module")
def bars():
    if not os.path.exists(REAL):
        pytest.skip("no real EURUSD bars")
    return pd.read_parquet(REAL).reset_index(drop=True).iloc[-3000:].reset_index(drop=True)


@pytest.mark.parametrize("kind", list(sl.SIGNALS))
def test_signals_are_causal(bars, kind):
    # What the live router sees on a truncated history must equal the full-history signal there.
    fn = sl.SIGNALS[kind][0]
    full = {s["i"]: s for s in fn(bars)}
    assert full, f"{kind} produced no signals on 3000 real bars"
    for k in list(full)[:: max(1, len(full) // 15)]:
        last = fn(bars.iloc[: k + 1].reset_index(drop=True))
        assert last and last[-1]["i"] == k and last[-1]["side"] == full[k]["side"]
        assert abs(last[-1]["stop"] - full[k]["stop"]) < 1e-9


def test_stops_sit_on_the_losing_side(bars):
    c = bars["close"].to_numpy(float)
    for kind in sl.SIGNALS:
        for s in sl.SIGNALS[kind][0](bars):
            assert (c[s["i"]] - s["stop"]) * s["side"] > 0


def test_orb_trades_once_per_session_inside_its_window(bars):
    t = pd.to_datetime(bars["time"], utc=True)
    seen = set()
    for s in sl.orb_signals(bars):
        h = t.iloc[s["i"]].hour
        assert 9 <= h <= 11 or 15 <= h <= 17
        key = (t.iloc[s["i"]].date(), h < 13)
        assert key not in seen
        seen.add(key)


def test_promotion_needs_live_sample_backtest_hurdle_and_dsr():
    hurdle = {"min_trades": 25.0, "min_expectancy_r": 0.015}
    good_bt = {"trades": 300, "expectancy_r": 0.08, "dsr": 0.95}
    assert sl.promotion_verdict([0.2] * 30, good_bt, hurdle) is None
    assert "closed demo trades" in sl.promotion_verdict([0.2] * 29, good_bt, hurdle)
    assert "not positive" in sl.promotion_verdict([-0.1] * 30, good_bt, hurdle)
    assert "hurdle" in sl.promotion_verdict([0.2] * 30, {**good_bt, "expectancy_r": 0.0}, hurdle)
    assert "deflated" in sl.promotion_verdict([0.2] * 30, {**good_bt, "dsr": 0.5}, hurdle)


def test_nothing_is_shadow_traded_without_evidence():
    # 2026-11-19 research: no symbol cleared the shadow bar, so the router builds no leads.
    assert sl.build(object()) == []
