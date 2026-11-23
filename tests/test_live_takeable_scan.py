"""Live-takeable calibration: the scan records what live dispatch would do with each read, and
LIMIT candidates are filled the way live fills them (real MT5 EURUSD H1 bars; skipped if absent)."""
import os

import pandas as pd
import pytest

from jarvis.backtesting.signal_scan import (CANDIDATE_COLUMNS, SignalScanner, apply_limit_fills,
                                            live_hour_vetoes)
from jarvis.data.symbol_registry import resolve

REAL = os.path.join("data", "market", "real", "EURUSD", "EURUSD_H1_730d.parquet")


@pytest.fixture(scope="module")
def bars():
    if not os.path.exists(REAL):
        pytest.skip("no real EURUSD bars")
    return pd.read_parquet(REAL).reset_index(drop=True).iloc[-400:].reset_index(drop=True)


def _row(bars, i, side, entry, order_type="LIMIT", regime="RANGE", strategy="TREND_PULLBACK"):
    spec = resolve("EURUSD")
    o = float(bars["open"].iloc[i + 1])
    fill = o + (2.0 * spec.pip_size if side == "BUY" else 0.0)
    sd = 0.0020
    sl = fill - sd if side == "BUY" else fill + sd
    tp = fill + 2 * sd if side == "BUY" else fill - 2 * sd
    return {c: None for c in CANDIDATE_COLUMNS} | {
        "symbol": "EURUSD", "bar_idx": i, "side": side, "entry": entry, "fill": fill, "sl": sl, "tp": tp,
        "atr": 0.0015, "spread_pips": 2.0, "order_type": order_type, "regime": regime, "strategy": strategy}


def _find(bars, pred):
    for i in range(20, len(bars) - 2):
        if pred(i):
            return i
    pytest.skip("no bar with the needed shape in this slice")


def test_buy_limit_touched_fills_at_the_limit_with_its_risk_kept(bars):
    o, lo = bars["open"].to_numpy(), bars["low"].to_numpy()
    # needs room: limit beyond the capture band (0.09 ATR) yet touched by the next bar's ask
    i = _find(bars, lambda i: o[i + 1] - lo[i + 1] > 0.0008)
    lim = lo[i + 1] + 0.0003                       # ask (low + 2 pip spread) trades through it
    out = apply_limit_fills(pd.DataFrame([_row(bars, i, "BUY", lim)]), bars, resolve("EURUSD"))
    assert len(out) == 1
    r = out.iloc[0]
    assert r["fill"] == pytest.approx(lim)
    assert r["fill"] - r["sl"] == pytest.approx(0.0020)


def test_buy_limit_never_touched_is_dropped(bars):
    o, lo = bars["open"].to_numpy(), bars["low"].to_numpy()
    i = _find(bars, lambda i: o[i + 1] - lo[i + 1] > 0.0004)
    lim = lo[i + 1] - 0.0005                       # below the bar: the ask never got there
    assert apply_limit_fills(pd.DataFrame([_row(bars, i, "BUY", lim)]), bars, resolve("EURUSD")).empty


def test_sell_limit_never_touched_is_dropped(bars):
    o, hi = bars["open"].to_numpy(), bars["high"].to_numpy()
    i = _find(bars, lambda i: hi[i + 1] - o[i + 1] > 0.0004)
    assert apply_limit_fills(pd.DataFrame([_row(bars, i, "SELL", hi[i + 1] + 0.0005)]), bars,
                             resolve("EURUSD")).empty


def test_market_breakout_and_capture_band_rows_are_unchanged(bars):
    i = 50
    o = float(bars["open"].iloc[i + 1])
    rows = [_row(bars, i, "BUY", o - 0.0050, order_type="MARKET"),
            _row(bars, i, "BUY", o - 0.0050, regime="BREAKOUT"),
            _row(bars, i, "BUY", o - 0.000001)]     # ask - limit = 0.0002 < band 0.15 ATR = 0.000225
    out = apply_limit_fills(pd.DataFrame(rows), bars, resolve("EURUSD"))
    assert len(out) == 3
    assert list(out["fill"]) == [r["fill"] for r in rows]


def test_hour_vetoes_match_live_windows():
    assert live_hour_vetoes("EURUSD", 10) == []
    assert "SESSION_BLACKOUT" in live_hour_vetoes("EURUSD", 22)
    assert live_hour_vetoes("USDJPY", 3) == []                     # Asian pair: no Asian blackout
    assert "PROFILE_SESSION_WINDOW" in live_hour_vetoes("USDJPY", 18)
    assert live_hour_vetoes("BTCUSD", 22) == []                    # crypto trades round the clock


def test_scan_records_the_live_verdict(bars):
    res = SignalScanner().scan(bars.iloc[-90:].reset_index(drop=True), "EURUSD")
    c = res.candidates
    for col in ("setup_grade", "is_actionable", "n_unsoftened_failed", "session_blackout", "live_takeable"):
        assert col in c.columns
    if len(c):
        assert not (c["live_takeable"].astype(bool) & c["session_blackout"].astype(bool)).any()
        assert not (c["live_takeable"].astype(bool) & (c["decision"] == "NO_TRADE")).any()
