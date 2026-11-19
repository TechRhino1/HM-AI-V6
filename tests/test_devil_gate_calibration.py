"""Devil's Advocate gate calibration: the math on fixed data, and the gate wiring."""
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from jarvis.analysts import devil_calibration as dc
from jarvis.analysts.devil_advocate import DevilAdvocateAnalyst
from jarvis.data.schemas import (
    DevilAdvocateReport, LiquidityContext, MarketContext, MarketRegime, MomentumContext, RegimeOutput,
    SessionContext, StructureContext, VolatilityContext,
)
from tools import calibrate_devil_gate as cdg


@pytest.fixture(autouse=True)
def calib_path(monkeypatch, tmp_path):
    p = tmp_path / "devil_gate_calibration.json"
    monkeypatch.setattr(dc, "PATH", p)
    dc._cache.update(mtime=None, doc=None, path=None)
    return p


def frame(rows):
    """rows: (flags, r) in time order."""
    t0 = pd.Timestamp("2025-01-01", tz="UTC")
    return pd.DataFrame({
        "symbol": "EURUSD", "bar_idx": np.arange(len(rows)) * 100, "exit_idx": np.arange(len(rows)) * 100 + 5,
        "time": [t0 + pd.Timedelta(hours=100 * i) for i in range(len(rows))],
        "devil_flags": [f for f, _ in rows], "r": [float(r) for _, r in rows],
        "win": [r > 0 for _, r in rows], "current_pass": True, "group": "forex",
    })


# ---------------------------------------------------------------- calibration math

def test_flag_stats_on_fixed_data():
    f = frame([("rsi_overextended", -1), ("rsi_overextended", -1), ("rsi_overextended", 2), ("", 2), ("", 2), ("", -1)])
    s = {x["flag"]: x for x in cdg.flag_stats(f)}["rsi_overextended"]
    assert s["n"] == 3 and s["n_without"] == 3
    assert s["win_rate"] == pytest.approx(1 / 3, abs=1e-4) and s["win_rate_without"] == pytest.approx(2 / 3, abs=1e-4)
    assert s["mean_r_delta"] == pytest.approx(0.0 - 1.0)
    # Welch t: both groups var = 3.0 (ddof 1), n=3 -> se = sqrt(2) -> t = -1/sqrt(2)
    assert s["t_stat"] == pytest.approx(-0.71, abs=0.01)


def test_logistic_recovers_empirical_rates_when_unregularised():
    X = np.array([[1], [1], [1], [1], [0], [0], [0], [0]], float)
    y = np.array([1, 1, 1, 0, 1, 0, 0, 0], float)
    beta = cdg.fit_logistic(X, y, l2=1e-9)
    assert cdg.predict(beta, np.array([[1.0]]))[0] == pytest.approx(0.75, abs=1e-4)
    assert cdg.predict(beta, np.array([[0.0]]))[0] == pytest.approx(0.25, abs=1e-4)
    assert beta[1] == pytest.approx(np.log(3) - np.log(1 / 3), abs=1e-3)


def test_threshold_maximises_kept_expectancy():
    p = np.array([0.1, 0.2, 0.3, 0.8, 0.9])
    r = np.array([1.0, 1.0, 0.5, -1.0, -1.0])
    t = cdg.choose_threshold(p, r)
    assert t < 0.8 and r[p <= t].mean() == 1.0


def test_walk_forward_is_time_ordered_and_scores_current_on_same_folds():
    rows = [("trend_broken" if i % 3 == 0 else "", -1 if i % 3 == 0 else (2 if i % 3 == 1 else -1)) for i in range(600)]
    f = frame(rows)
    f["current_pass"] = f["devil_flags"] == ""
    wf = cdg.walk_forward(f, folds=4, embargo=0)
    starts = [pd.Timestamp(x["test_from"]) for x in wf["folds"]]
    assert starts == sorted(starts) and starts[0] > f["time"].iloc[0]
    # the calibrated gate learns trend_broken -> loss and therefore removes exactly those trades
    assert wf["calibrated"]["n"] == wf["current"]["n"]
    assert wf["calibrated"]["expectancy_r"] == pytest.approx(wf["current"]["expectancy_r"])
    assert sum(x["all"]["n"] for x in wf["folds"]) == wf["all_test"]["n"]


def test_embargo_drops_overlapping_training_trades():
    f = frame([("", 1)] * 300)
    f["exit_idx"] = f["bar_idx"] + 1_000_000  # every trade overlaps every later one
    assert cdg.walk_forward(f, folds=3, embargo=48)["folds"] == []


def test_publish_rule():
    cur = {"n": 100, "expectancy_r": 0.02}
    assert cdg.beats({"calibrated": {"n": 95, "expectancy_r": 0.05}, "current": cur})[0]
    assert not cdg.beats({"calibrated": {"n": 95, "expectancy_r": 0.01}, "current": cur})[0]   # worse
    assert not cdg.beats({"calibrated": {"n": 40, "expectancy_r": 0.09}, "current": cur})[0]   # n too small vs current
    assert not cdg.beats({"calibrated": {"n": 10, "expectancy_r": 0.50}, "current": {"n": 5, "expectancy_r": 0.0}})[0]
    assert not cdg.beats({"calibrated": {"n": 95, "expectancy_r": -0.01}, "current": {"n": 100, "expectancy_r": -0.05}})[0]
    fold = lambda c, k: {"calibrated": {"expectancy_r": c}, "current": {"expectancy_r": k}}
    noisy = {"calibrated": {"n": 95, "expectancy_r": 0.05}, "current": cur, "folds": [fold(.2, .1), fold(.0, .1), fold(.0, .1)]}
    assert not cdg.beats(noisy)[0]                                                                # wins 1/3 folds


# ---------------------------------------------------------------- wiring

def _ctx(symbol="EURUSD"):
    return MarketContext(
        symbol=symbol, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), current_price=1.1, bid=1.0999, ask=1.1001,
        structure=StructureContext(bias="NEUTRAL", lower_highs=True, lower_lows=True), liquidity=LiquidityContext(),
        volatility=VolatilityContext(), momentum=MomentumContext(rsi=80.0),
        session=SessionContext(current_session="LONDON", is_prime_session=True), mtf_alignment={}, order_flow={},
        context_quality=100.0)


class _Corr:
    def get_correlation(self, a, b):
        return 0.0


def critique(symbol="EURUSD"):
    reg = RegimeOutput(primary_regime=MarketRegime.TREND_BULL, probabilities={"TREND_BULL": 1.0}, confidence=0.9, regime_transition=False)
    return DevilAdvocateAnalyst(correlation_engine=_Corr()).critique_opportunity(_ctx(symbol), reg, "BUY")


def original_rule(rep, ai, maxp):
    return rep.penalty_score <= (maxp + (10.0 if ai >= 75.0 else 0.0)) and len(rep.threats_detected) <= 3


def write(path, published, threshold=0.5, weights=None):
    path.write_text(json.dumps({"published": published, "groups": {
        "forex": {"published": published, "intercept": -1.0, "threshold": threshold,
                  "weights": weights or {"trend_broken": 2.0, "rsi_overextended": 0.5},
                  "flag_stats": [{"flag": "rsi_overextended", "n": 1240, "win_rate_delta": -0.06, "mean_r_delta": -0.08, "t_stat": -2.1}]},
        "pooled": {"published": False, "flag_stats": []}}}), encoding="utf-8")
    # Two writes can land in one mtime tick and the loader caches on mtime; make each one distinct.
    write.n = getattr(write, "n", 0) + 1
    os.utime(path, (1_000_000_000 + write.n, 1_000_000_000 + write.n))


def test_flags_recorded():
    rep = critique()
    assert rep.threat_flags == ["rsi_overextended", "trend_broken"] and set(rep.threat_flags) <= set(dc.FLAG_IDS)


@pytest.mark.parametrize("published_file", ["missing", "unpublished"])
def test_gate_identical_when_unpublished(calib_path, published_file):
    if published_file == "unpublished":
        write(calib_path, published=False, threshold=0.0)
    rep = critique()
    assert rep.calibrated_loss_prob is None
    for pen in (0.0, 30.0, 43.0, 50.0, 53.0, 100.0):
        for n in range(6):
            for ai in (50.0, 75.0):
                r = DevilAdvocateReport(symbol="EURUSD", counter_bias="BEARISH", penalty_score=pen,
                                        invalidation_risk_coefficient=1.0, threats_detected=["t"] * n)
                for maxp in (43.0, 50.0):
                    assert dc.gate_passes(r, "EURUSD", ai, maxp) == original_rule(r, ai, maxp)


def test_calibrated_path_when_published(calib_path):
    write(calib_path, published=True, threshold=0.5)
    rep = critique()  # flags rsi_overextended + trend_broken -> z = -1 + 2 + 0.5
    assert rep.calibration_group == "forex"
    assert rep.calibrated_loss_prob == pytest.approx(1 / (1 + np.exp(-1.5)), abs=1e-4)
    assert not dc.gate_passes(rep, "EURUSD", 50.0, 43.0)        # 0.82 > 0.5
    assert original_rule(rep, 50.0, 43.0)                      # the old rule would have passed it
    write(calib_path, published=True, threshold=0.9)
    rep = critique()
    assert dc.gate_passes(rep, "EURUSD", 50.0, 43.0)
    gold = critique("XAUUSD")                                  # no gold entry -> original rule
    assert gold.calibrated_loss_prob is None and dc.gate_passes(gold, "XAUUSD", 50.0, 43.0) == original_rule(gold, 50.0, 43.0)


def test_fail_closed_fallback_still_fails_when_published(calib_path):
    write(calib_path, published=True, threshold=1.0)
    fallback = DevilAdvocateReport(symbol="EURUSD", counter_bias="NEUTRAL", penalty_score=100.0, invalidation_risk_coefficient=1.0)
    assert not dc.gate_passes(fallback, "EURUSD", 90.0, 43.0)


def test_threat_stats_attached_for_ui(calib_path):
    write(calib_path, published=False)
    rep = critique()
    assert rep.threat_stats == [{"flag": "rsi_overextended", "n": 1240, "win_rate_delta": -0.06, "mean_r_delta": -0.08, "t_stat": -2.1}]


def test_decision_engine_uses_the_shared_gate():
    import inspect
    from jarvis.intelligence import decision_engine
    src = inspect.getsource(decision_engine)
    assert '"Devil Adversarial Guard": devil_gate_passes(devil_report, context.symbol, ai_score, self.max_devil_penalty)' in src


def test_groups():
    assert dc.group_for("EURUSD") == "forex" and dc.group_for("XAUUSD") == "gold" and dc.group_for("BTCUSD") == "crypto"
