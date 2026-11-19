"""Calibrated profiles reload on file change, and inconsistent OOS stats are restated."""
import json
import os

from jarvis.intelligence.winrate_targeting import load_profiles

REAL = "config/winrate_profiles.json"


def _write(path, profiles, mtime):
    path.write_text(json.dumps({"profiles": profiles}), encoding="utf-8")
    os.utime(path, ns=(mtime, mtime))


def _one(symbol):
    raw = json.load(open(REAL, encoding="utf-8"))
    return dict(raw.get("profiles", raw)[symbol])


def test_rewritten_profile_file_is_picked_up(tmp_path):
    f = tmp_path / "p.json"
    a = _one("XAUUSD")
    _write(f, {"XAUUSD": a}, 1_000_000_000)
    assert load_profiles(f)["XAUUSD"].oos_trades == a["oos_trades"]
    b = dict(a, oos_trades=a["oos_trades"] + 1, oos_total_r=a["oos_expectancy_r"] * (a["oos_trades"] + 1))
    _write(f, {"XAUUSD": b}, 2_000_000_000)
    assert load_profiles(f)["XAUUSD"].oos_trades == a["oos_trades"] + 1


def test_expectancy_that_disagrees_with_total_is_restated(tmp_path):
    # USDJPY as committed in c3ac298: +0.032R x 36 trades but -11.121R total.
    f = tmp_path / "p.json"
    bad = dict(_one("XAUUSD"), oos_trades=36, oos_expectancy_r=0.032, oos_total_r=-11.121)
    _write(f, {"USDJPY": bad}, 3_000_000_000)
    prof = load_profiles(f)["USDJPY"]
    assert abs(prof.oos_expectancy_r - (-11.121 / 36)) < 1e-9


def test_consistent_profile_is_untouched(tmp_path):
    f = tmp_path / "p.json"
    good = dict(_one("XAUUSD"), oos_trades=100, oos_expectancy_r=0.05, oos_total_r=5.02)
    _write(f, {"XAUUSD": good}, 4_000_000_000)
    assert load_profiles(f)["XAUUSD"].oos_expectancy_r == 0.05
