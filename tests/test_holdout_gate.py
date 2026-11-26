"""Walk-forward holdout feedback: stamp -> profile -> deployment_refusal (audit 2026-11-24)."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.backtesting import exit_geometry
from jarvis.intelligence import winrate_targeting as wt
from jarvis.intelligence.winrate_targeting import WRProfileStore, WRTargetProfile

REPO = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.calibrated_exits


def _live(monkeypatch, profs):
    from jarvis.config import runtime
    from jarvis.config.settings import SETTINGS
    monkeypatch.setattr(runtime, "is_offline", lambda: False)
    monkeypatch.setattr(SETTINGS.trading, "use_calibrated_entry_policy", True, raising=False)
    monkeypatch.setattr(exit_geometry, "_stamped_profile", lambda s: profs.get(s))


def _p(he=None, hn=0):
    return SimpleNamespace(oos_trades=150, oos_expectancy_r=0.10, holdout_trades=hn,
                           holdout_expectancy_r=he, holdout_window="2026-05-19..2026-11-18")


def _profile(sym="AAA"):
    return WRTargetProfile.from_dict({"symbol": sym, "target_wr": 0.75, "geometry": {"tp_r": 1.0}})


def test_holdout_gate(monkeypatch):
    _live(monkeypatch, {"NEVER": _p(), "LOSS": _p(-0.05, 40), "THIN": _p(-0.5, 5),
                        "WIN": _p(0.08, 40), "FLAT": _p(0.0, 40)})
    assert exit_geometry.deployment_refusal("NEVER") is None  # never holdout-tested: unchanged
    assert exit_geometry.deployment_refusal("LOSS").startswith("HOLDOUT_GATE")
    assert exit_geometry.deployment_refusal("THIN") is None  # too few trades to judge
    assert exit_geometry.deployment_refusal("WIN") is None
    assert exit_geometry.deployment_refusal("FLAT").startswith("HOLDOUT_GATE")


def test_holdout_fields_round_trip_and_old_profiles_load():
    p = _profile()
    assert p.holdout_expectancy_r is None and p.holdout_trades == 0
    p.holdout_trades, p.holdout_expectancy_r = 30, -0.1
    q = WRTargetProfile.from_dict(json.loads(json.dumps(p.to_dict(), default=str)))
    assert (q.holdout_trades, q.holdout_expectancy_r) == (30, -0.1)


def _runner():
    spec = importlib.util.spec_from_file_location("rb", REPO / "tools" / "backtests" / "run_3month_backtest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stamp_keeps_meta_and_skips_unknown(tmp_path):
    path = tmp_path / "p.json"
    WRProfileStore(path).save({"AAA": _profile()}, meta={"days": 730})
    rb = _runner()
    done = rb.stamp_holdout(path, {"AAA": {"trades": 12, "expectancy_r": -0.2, "profit_factor": 0.7},
                                   "ZZZ": {"trades": 9, "expectancy_r": 0.5, "profit_factor": 2.0}}, "w")
    raw = json.loads(path.read_text())
    assert done == ["AAA"] and raw["meta"] == {"days": 730} and "ZZZ" not in raw["profiles"]
    assert raw["profiles"]["AAA"]["holdout_expectancy_r"] == -0.2
    assert rb.max_drawdown_r([1, -1, -2, 3, -1]) == 3.0


def test_merge_realised_keeps_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(wt, "isotonic_calibrate", lambda s, w: None)
    monkeypatch.setattr(wt, "regime_edge_table", lambda o: {})
    path = tmp_path / "p.json"
    store = WRProfileStore(path)
    store.save({"AAA": _profile()}, meta={"days": 730})
    store.merge_realised("AAA", [SimpleNamespace(ai_score=0.5, is_win=True)] * 25)
    assert json.loads(path.read_text())["meta"] == {"days": 730}


def test_gate_applies_with_calibrated_entry_policy_off(monkeypatch):
    """Commit 4fd416a turned use_calibrated_entry_policy off, which silently switched the
    holdout/expectancy gate off for every symbol. The gate must not depend on that flag."""
    from jarvis.config import runtime
    from jarvis.config.settings import SETTINGS
    monkeypatch.setattr(runtime, "is_offline", lambda: False)
    monkeypatch.setattr(SETTINGS.trading, "use_calibrated_entry_policy", False, raising=False)
    profs = {"LOSS": _p(-0.05, 40), "WIN": _p(0.08, 40)}
    monkeypatch.setattr(exit_geometry, "_stamped_profile", lambda s: profs.get(s))
    assert exit_geometry.deployment_refusal("LOSS").startswith("HOLDOUT_GATE")
    assert exit_geometry.deployment_refusal("WIN") is None
    assert exit_geometry.deployment_refusal("NOPROFILE").startswith("NO_VALIDATED_PROFILE")
    assert exit_geometry.live_profile("WIN") is None  # geometry still follows the flag
