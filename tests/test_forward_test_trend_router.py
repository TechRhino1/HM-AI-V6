"""Demo-only trend router (jarvis/forward_tests/trend_router.py): research rules, unchanged, and
every router decision path."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools"))

from jarvis.forward_tests import trend_router as tr


def _bars(n=900, seed=3, freq="D"):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    return pd.DataFrame({"time": pd.date_range("2023-01-01", periods=n, freq=freq), "open": c,
                         "high": c * 1.01, "low": c * 0.99, "close": c, "spread": np.full(n, 10)})


def test_signals_match_research_bar_for_bar():
    import strategy_research as sr
    df = _bars()
    A = {"c": df.close.to_numpy(float), "h": df.high.to_numpy(float), "l": df.low.to_numpy(float),
         "atr": np.ones(len(df))}
    bpm = tr.bars_per_month(df["time"])
    for i in range(400, len(df)):
        live_d = tr.donchian_signals(df.iloc[:i + 1])
        live_t = tr.tsmom_signals(df.iloc[:i + 1])
        assert tr.bars_per_month(df["time"].iloc[:i + 1]) == bpm      # regular calendar: constant
        for n_in, n_out in tr.DONCHIAN:
            sig, ex = sr.donchian(A, n_in, n_out)
            side = {k: s for k, s, _ in sig}.get(i, 0)
            d = live_d[f"D{n_in}"]
            assert d["entry"] == side and d["exit_long"] == bool(ex["exit_long"][i]) \
                and d["exit_short"] == bool(ex["exit_short"][i])
        for k in tr.TSMOM_MONTHS:
            sig, ex = sr.tsmom(A, k * bpm)
            side = {j: s for j, s, _ in sig}.get(i, 0)
            t = live_t[f"T{k}"]
            assert t["entry"] == side and t["exit_long"] == bool(ex["exit_long"][i])


def _router(positions=(), news=False, halted=False, enter_res=None):
    o = SimpleNamespace(mode="demo", mt5_client=MagicMock(), data_feed=MagicMock(),
                        circuit_breaker=MagicMock(), drawdown_guard=MagicMock())
    o._is_news_blackout = MagicMock(return_value=news)
    o.mt5_client.get_open_positions.return_value = list(positions)
    o.circuit_breaker.check_status.return_value = {"active": halted}
    o.drawdown_guard.check_limits.return_value = {"passed": True}
    r = tr.TrendRouter(o)
    r._enter = MagicMock(return_value=enter_res if enter_res is not None else {"status": "FILLED"})
    r._close = MagicMock()
    return r, o


SIG_BUY = {"entry": 1, "exit_long": False, "exit_short": True}
SIG_FLAT = {"entry": 0, "exit_long": False, "exit_short": False}


def _pos(comment, side="BUY", sl=95.0):
    return SimpleNamespace(comment=comment, type=side, sl=sl, ticket=1)


def test_enters_on_signal_with_the_component_comment():
    r, _ = _router()
    a, _ = r._decide("FT_TR_EURUSD_D1_D20", "donchian", "EURUSD", "D1", SIG_BUY, 100.0, 1.0, np.array([0.01]), False)
    assert a == "ENTER"
    args, kw = r._enter.call_args
    assert args[:2] == ("EURUSD", 1) and args[3] == 3.0 and kw["comment"] == "FT_TR_EURUSD_D1_D20"
    assert r.STRATEGY == "TREND_DONCHIAN_EURUSD_D1"


def test_news_halt_and_slot_limits_block_new_entries():
    assert _router(news=True)[0]._decide("FT_TR_EURUSD_D1_D20", "donchian", "EURUSD", "D1", SIG_BUY,
                                          100.0, 1.0, np.array([0.0]), True)[0] == "SKIP"
    assert _router(halted=True)[0]._decide("FT_TR_EURUSD_D1_D20", "donchian", "EURUSD", "D1", SIG_BUY,
                                            100.0, 1.0, np.array([0.0]), False)[1].startswith("circuit")
    full = [_pos(f"FT_TR_BTCUSD_H4_T{k}") for k in (1, 3, 6)]
    a, why = _router(full)[0]._decide("FT_TR_EURUSD_D1_D20", "donchian", "EURUSD", "D1", SIG_BUY,
                                      100.0, 1.0, np.array([0.0]), False)
    assert a == "SKIP" and "3 open" in why
    two = [_pos("FT_TR_EURUSD_H4_T1"), _pos("FT_TR_EURUSD_D1_T3")]
    a, why = _router(two)[0]._decide("FT_TR_EURUSD_D1_D20", "donchian", "EURUSD", "D1", SIG_BUY,
                                     100.0, 1.0, np.array([0.0]), False)
    assert a == "SKIP" and "EURUSD" in why


def test_unaffordable_min_lot_is_journalled_as_skip_not_enter():
    r, _ = _router()
    r._enter = MagicMock(return_value=None)
    assert r._decide("FT_TR_BTCUSD_D1_T1", "tsmom", "BTCUSD", "D1", SIG_BUY, 100.0, 1.0,
                     np.array([0.0]), False) == ("SKIP", "minimum lot exceeds the risk policy")


def test_exit_closes_and_does_not_reenter_on_the_same_bar():
    pos = _pos("FT_TR_EURUSD_D1_T1", side="BUY")
    r, _ = _router([pos])
    sig = {"entry": -1, "exit_long": True, "exit_short": False}
    assert r._decide("FT_TR_EURUSD_D1_T1", "tsmom", "EURUSD", "D1", sig, 100.0, 1.0, np.array([0.0]), False)[0] == "EXIT"
    r._close.assert_called_once()
    r._enter.assert_not_called()


def test_donchian_trails_3atr_and_never_loosens_tsmom_keeps_fixed_stop():
    r, o = _router([_pos("FT_TR_EURUSD_D1_D20", sl=95.0)])
    assert r._decide("FT_TR_EURUSD_D1_D20", "donchian", "EURUSD", "D1", SIG_FLAT, 100.0, 1.0,
                     np.array([0.0]), False)[0] == "TRAIL"
    o.mt5_client.modify_position.assert_called_once_with(1, sl=97.0, tp=0.0)
    r2, o2 = _router([_pos("FT_TR_EURUSD_D1_D20", sl=99.0)])
    assert r2._decide("FT_TR_EURUSD_D1_D20", "donchian", "EURUSD", "D1", SIG_FLAT, 100.0, 1.0,
                      np.array([0.0]), False)[0] == "HOLD"     # 97 would loosen a 99 stop
    r3, o3 = _router([_pos("FT_TR_EURUSD_D1_T1", sl=95.0)])
    assert r3._decide("FT_TR_EURUSD_D1_T1", "tsmom", "EURUSD", "D1", SIG_FLAT, 100.0, 1.0,
                      np.array([0.0]), False)[0] == "HOLD"
    o3.mt5_client.modify_position.assert_not_called()


def test_live_mode_never_runs_and_regime_label_is_known():
    r, o = _router()
    o.mode = "live"
    r.step()
    o.data_feed.fetch_rates.assert_not_called()
    assert tr.regime_label(_bars()) in ("TREND", "RANGE", "HIGH_VOL_SHOCK", "DEAD")
