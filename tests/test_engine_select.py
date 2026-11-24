"""engine_select: candidate generation, train ranking and holdout pass rule."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools" / "backtests")]

import engine_select as es  # noqa: E402
from jarvis.backtesting.trade_simulator import Geometry  # noqa: E402
from jarvis.intelligence.winrate_targeting import WRTargetProfile  # noqa: E402


def _r(n, exp, pf, t):
    return {"trades": n, "expectancy_r": exp, "profit_factor": pf, "t_stat": t}


def test_pick_ranks_by_t_stat_among_eligible_only():
    res = {
        "thin": _r(10, 0.9, 3.0, 9.0),      # too few trades
        "losing_pf": _r(100, 0.05, 0.9, 5.0),  # PF below floor
        "ok_low": _r(80, 0.10, 1.2, 1.5),
        "ok_high": _r(120, 0.08, 1.3, 2.4),
    }
    assert es.pick(res) == "ok_high"
    assert es.pick({"x": _r(100, -0.1, 0.8, -1.0)}) is None


def test_holdout_needs_positive_r_pf_and_min_trades():
    assert es.passes_holdout(_r(50, 0.05, 1.1, 0))
    assert not es.passes_holdout(_r(50, 0.05, 0.95, 0))
    assert not es.passes_holdout(_r(50, -0.01, 1.1, 0))
    assert not es.passes_holdout(_r(3, 0.5, 2.0, 0))


def test_variants_override_geometry_and_clear_regime_geometry():
    g = Geometry(tp_r=0.5, be_trigger_r=None, fast_cash_r=None, fast_cash_pct=0.5,
                 trail_atr=None, max_bars=24, min_score=0.4)
    p = WRTargetProfile(symbol="EURUSD", target_wr=0.75, geometry=g, regime_geometry={"TREND_BULL": g})
    c = dict(es.candidates(p))
    assert c["calibrated"] is p and len(c) == len(es.VARIANTS) + 1
    v = c["tp2.5_be1.0_mb48"]
    assert (v.geometry.tp_r, v.geometry.be_trigger_r, v.geometry.max_bars, v.geometry.min_score) == (2.5, 1.0, 48, 0.4)
    assert v.regime_geometry == {} and p.regime_geometry  # original untouched
