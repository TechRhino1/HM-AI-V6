"""KN-Adaptive signal layers (jarvis/forward_tests/kn_adaptive.py) and the ladder walker (tools/kn_research.py).

Bars here are hand-built fixtures for the logic only; they never reach a trade or a report."""
import numpy as np
import pandas as pd

from jarvis.forward_tests import kn_adaptive as kn
from tools.kn_research import walk_ladder


def _bars(close, wick=0.2):
    c = np.asarray(close, float)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + wick, "low": np.minimum(o, c) - wick, "close": c})


def _v_shape():
    return np.r_[np.linspace(110, 100, 60), np.linspace(100, 115, 60), np.linspace(115, 105, 60)]


def test_one_cross_up_then_one_cross_down():
    F = kn.features(_bars(_v_shape()))
    sig = kn.signals(F, kn.VARIANTS["V0_raw"], start=5)   # past the EMA seed bar
    assert [s for _, s, _ in sig] == [1, -1]
    up, dn = sig[0][0], sig[1][0]
    assert 60 <= up < 70 and 120 <= dn < 130          # just after each turn
    assert all(abs(sd - 1.5 * F["atr"][i]) < 1e-12 for i, _, sd in sig)


def test_signal_uses_only_past_bars():
    c = _v_shape()
    c2 = c.copy(); c2[100:] = c2[99]                     # change the future after bar 99
    s1 = [x for x in kn.signals(kn.features(_bars(c)), kn.VARIANTS["V0_raw"], start=1) if x[0] < 99]
    s2 = [x for x in kn.signals(kn.features(_bars(c2)), kn.VARIANTS["V0_raw"], start=1) if x[0] < 99]
    assert s1 == s2


def test_regime_gate_blocks_chop():
    rng = np.random.default_rng(0)
    chop = 100 + np.cumsum(rng.choice([-1.0, 1.0], 400)) * 0.05 + np.sin(np.arange(400)) * 0.5
    F = kn.features(_bars(chop))
    raw = kn.signals(F, kn.VARIANTS["V0_raw"], start=50)
    gated = kn.signals(F, kn.KNConfig(regime=True, er_min=0.35), start=50)
    assert len(raw) > 20 and len(gated) < len(raw) / 2


def test_htf_bias_filters_direction():
    F = kn.features(_bars(_v_shape()))
    sig = kn.signals(F, kn.KNConfig(htf=True), bias=np.ones(180, int), start=5)
    assert [s for _, s, _ in sig] == [1]


def test_adaptive_stop_stays_in_band():
    F = kn.features(_bars(_v_shape() + np.sin(np.arange(180)) * 2))
    cfg = kn.VARIANTS["V3_stop"]
    for i in range(30, 180):
        for side in (1, -1):
            k = kn.stop_distance(F, i, side, cfg) / F["atr"][i]
            assert kn.K_MIN - 1e-9 <= k <= kn.K_MAX + 1e-9


def test_ladder_levels():
    assert kn.ladder_levels([5.0] * 29) == (1.0, 2.0)  # too few samples
    tp1, tp2 = kn.ladder_levels(np.linspace(0, 3, 101))
    assert abs(tp1 - 1.2) < 1e-9 and abs(tp2 - 1.95) < 1e-9
    tp1, tp2 = kn.ladder_levels([0.0] * 40)
    assert tp1 == kn.TP_MIN and tp2 == kn.TP_MIN + 0.5


def _A(o, h, l):
    n = len(o)
    info = {"price_now": 100.0, "point": 0.01, "trade_tick_value": 1.0, "trade_tick_size": 0.01,
            "swap_long": 0.0, "swap_short": 0.0, "swap_mode": 0, "swap_rollover3days": 3}
    return {"o": np.asarray(o, float), "h": np.asarray(h, float), "l": np.asarray(l, float),
            "spr": np.zeros(n), "atr": np.ones(n), "slip": 0.0, "info": info,
            "day": np.full(n, 20_000), "d0": 20_000, "W": np.zeros(3)}


def test_walk_ladder_books_each_target_then_stops_at_entry():
    # entry 100 at bar 1, sd 1: TP1 101 and TP2 102 fill, then price falls back through entry
    A = _A([100, 100, 101, 102, 100], [100, 100.5, 101.2, 102.3, 100.5], [100, 99.5, 100.5, 101.5, 99.0])
    legs, be, trail = kn.exit_plan(kn.KNConfig(dyn_ladder=True), (1.0, 2.0))
    r, j, sw = walk_ladder(A, 0, 1, 1.0, legs, be, False, np.zeros(5, bool))
    assert j == 4 and abs(r - (1.0 + 2.0 + 0.0) / 3) < 1e-9


def test_walk_ladder_stop_first_and_signal_exit():
    A = _A([100, 100, 100, 100], [100, 103.5, 100.2, 100], [100, 98.5, 99.8, 100])
    legs, be, trail = kn.exit_plan(kn.VARIANTS["V0_raw"])
    r, j, _ = walk_ladder(A, 0, 1, 1.0, legs, be, trail, np.zeros(4, bool))
    assert j == 1 and abs(r + 1.0) < 1e-9                 # stop and targets in one bar: stop wins
    A = _A([100, 100, 100.5, 100.4], [100, 100.6, 100.6, 100.4], [100, 99.7, 100.3, 100.4])
    xr = np.array([False, False, True, False])
    r, j, _ = walk_ladder(A, 0, 1, 1.0, legs, be, trail, xr)
    assert j == 3 and abs(r - 0.4) < 1e-9                 # opposite cross closes all legs at the next open


# ── demo forward test (KNForwardTest) ───────────────────────────────────────

def _synth(seed, n=900):
    rng = np.random.default_rng(seed)
    c = 1.25 * np.exp(np.cumsum(rng.standard_t(3, n) * 0.004 + 0.0004 * np.sin(np.arange(n) / 40)))
    o = np.r_[c[0], c[:-1]]
    w = np.abs(rng.normal(0, 0.002, (2, n))) * c
    return pd.DataFrame({"time": pd.date_range("2025-01-06", periods=n, freq="4h"), "open": o,
                         "high": np.maximum(o, c) + w[0], "low": np.minimum(o, c) - w[1], "close": c,
                         "spread": np.full(n, 15)})


def _lead(positions=()):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    o = SimpleNamespace(mode="demo", mt5_client=MagicMock(), data_feed=MagicMock(),
                        circuit_breaker=MagicMock(), drawdown_guard=MagicMock())
    o.mt5_client.get_open_positions.return_value = list(positions)
    o.mt5_client.get_symbol_trading_spec.return_value = {"point": 0.00001}
    o.circuit_breaker.check_status.return_value = {"active": False}
    o.drawdown_guard.check_limits.return_value = {"passed": True}
    o._is_news_blackout = lambda *a: False
    lead = kn.build(o)[0]
    lead.entries = []
    lead._enter = lambda sym, side, ref, sd, tp_r: lead.entries.append((side, sd, tp_r))
    return lead, o


def _research_signals(df):
    return kn.signals(kn.features(df), kn.KNForwardTest.CFG, kn.htf_bias(df), np.full(len(df), 15 * 0.00001))


def test_forward_test_matches_research_bar_for_bar():
    df = _synth(3)
    research = {i: (s, sd) for i, s, sd in _research_signals(df) if i >= 300}
    assert research, "fixture produced no signals; test is vacuous"
    live = {}
    for i in range(300, len(df)):
        lead, _ = _lead()
        lead._on_bar("GBPUSD", df.iloc[:i + 1].reset_index(drop=True))
        if lead.entries:
            live[i] = lead.entries[0][:2]
            assert lead.entries[0][2] == 2.0
    assert set(live) == set(research)
    assert all(live[i][0] == research[i][0] and abs(live[i][1] - research[i][1]) < 1e-12 for i in live)


def test_forward_test_closes_on_opposite_cross_without_reentry():
    from types import SimpleNamespace
    df = _synth(3)
    F = kn.features(df)
    i = int(np.flatnonzero(F["cross_dn"][300:])[0]) + 300
    pos = SimpleNamespace(ticket=9, type="BUY", comment="FT_KN_GBPUSD")
    lead, o = _lead([pos])
    o.mt5_client.close_position.return_value = {"status": "OPEN"}
    lead._on_bar("GBPUSD", df.iloc[:i + 1].reset_index(drop=True))
    o.mt5_client.close_position.assert_called_once_with(9)
    assert lead.entries == []
    lead, o = _lead([pos])
    lead._on_bar("GBPUSD", df.iloc[:i].reset_index(drop=True))   # bar before: no opposite cross yet
    o.mt5_client.close_position.assert_not_called()


def test_forward_test_never_trades_outside_demo(monkeypatch):
    from jarvis.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS.trading, "forward_test_modes", ["paper", "demo", "live"])
    for mode in ("live", "paper"):
        lead, o = _lead()
        o.mode = mode
        lead.step()
        o.data_feed.fetch_rates.assert_not_called()
