"""Demo-only forward tests of the 2026-11-17 research leads: rules must match the research exactly."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools"))

from jarvis.forward_tests import research_leads as rl


def _synth(seed, n=3000):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.standard_t(3, n) * 0.0015))
    o = np.r_[100.0, c[:-1]]
    w = np.abs(rng.normal(0, 0.0006, (2, n))) * c
    return pd.DataFrame({"time": pd.date_range("2026-01-05", periods=n, freq="15min"), "open": o,
                         "high": np.maximum(o, c) + w[0], "low": np.minimum(o, c) - w[1], "close": c})


def test_live_detector_matches_research_setups_bar_for_bar():
    import smc_research as smc
    for seed in (1, 2):
        df = _synth(seed, 1500)
        spr = np.full(len(df), 0.02)
        h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
        atr = rl.atr14(df)
        A = {"o": df.open.to_numpy(float), "h": h, "l": l, "c": c, "atr": atr, "spr": spr}
        S = smc.structure(h, l, c, atr)
        lv = smc.levels(df.rename(columns={"time": "t_open"}))
        sw_lo, sw_hi = np.zeros(len(c), bool), np.zeros(len(c), bool)
        with np.errstate(invalid="ignore"):
            for L in (lv["pdl"], lv["asl"], lv["lnl"], S["eql"]):
                sw_lo |= (l < L) & (c > L)
            for H in (lv["pdh"], lv["ash"], lv["lnh"], S["eqh"]):
                sw_hi |= (h > H) & (c < H)
        research = {s["i"]: s for s in smc.setups(A, S, sw_lo, sw_hi, np.ones(len(c), bool), "forex") if s["i"] >= 300}
        assert research, "synthetic data produced no setups; test is vacuous"
        live = {}
        for i in range(300, len(c)):
            s = rl.detect_last(df.iloc[:i + 1], spr[:i + 1], 0.5)
            if s:
                live[i] = s
        assert set(live) == set(research)
        for i, s in research.items():
            assert live[i]["side"] == s["side"] and abs(live[i]["sd"] - s["sd"]) < 1e-9


def test_chandelier_waits_for_plus_1r_then_trails_and_never_loosens():
    # BUY entry 100, stop 98 (R = 2), ATR 1, trail 3 ATR.
    assert rl.chandelier_stop(1, 100.0, 98.0, 101.9, 1.0) == 98.0       # below +1R: untouched
    assert rl.chandelier_stop(1, 100.0, 98.0, 102.0, 1.0) == 99.0       # +1R reached: best - 3
    assert rl.chandelier_stop(1, 100.0, 99.0, 101.5, 1.0) == 99.0       # never loosens
    assert rl.chandelier_stop(-1, 100.0, 102.0, 98.0, 1.0) == 101.0     # SELL mirror


def _orch(mode="demo"):
    o = SimpleNamespace(mode=mode, mt5_client=MagicMock(), data_feed=MagicMock(),
                        circuit_breaker=MagicMock(), drawdown_guard=MagicMock())
    o.mt5_client.get_open_positions.return_value = []
    o.circuit_breaker.check_status.return_value = {"active": False}
    o.drawdown_guard.check_limits.return_value = {"passed": True}
    return o


def test_live_mode_never_trades():
    o = _orch("live")
    for lead in rl.build_all(o):
        lead.step()
    o.data_feed.fetch_rates.assert_not_called()
    o.mt5_client.send_market_order.assert_not_called()


def test_forex_day_lead_trades_only_in_session():
    lead = rl.build_all(_orch())[0]
    assert lead.TAG == "FT_SMCD" and lead.session_only and lead.exit_mode == "X0"
    assert lead._in_session(pd.Timestamp("2026-11-17 07:45"))       # decision at 08:00
    assert not lead._in_session(pd.Timestamp("2026-11-17 10:00"))   # decision at 10:15
    assert lead._in_session(pd.Timestamp("2026-11-17 14:30"))
    assert not lead._in_session(pd.Timestamp("2026-11-17 18:00"))


def test_engine_swing_lead_closes_after_48h():
    o = _orch()
    lead = rl.EngineSwingForwardTest(o)
    old = SimpleNamespace(ticket=7, type="BUY", comment="FT_ESW_EURUSD", sl=1.08, open_price=1.09,
                          open_time=(pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=49)).isoformat())
    o.mt5_client.get_open_positions.return_value = [old]
    o.mt5_client.close_position.return_value = {"status": "OPEN"}
    lead._on_bar("EURUSD", _synth(1, 400))
    o.mt5_client.close_position.assert_called_once_with(7)
