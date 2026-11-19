"""Selection-bias stats on calibrated profiles and the per-symbol report."""
import numpy as np

from jarvis.intelligence.winrate_targeting import _selection_bias_stats, load_profiles
from tools.calibration_report import build_rows, render


def test_dsr_deflates_a_lucky_pick_but_keeps_a_real_edge():
    rng = np.random.default_rng(7)
    trials = [list(rng.normal(0.0, 1.0, 200)) for _ in range(100)]
    psr, dsr, trl = _selection_bias_stats(list(rng.normal(0.3, 1.0, 200)), trials)
    assert psr > 0.99 and dsr > 0.5 and trl < 200
    psr0, dsr0, _ = _selection_bias_stats(list(rng.normal(0.0, 1.0, 50)), trials)
    assert dsr0 < 0.5 and dsr0 <= psr0
    assert _selection_bias_stats([0.5, -1.0], trials) == (None, None, None)


def test_report_has_one_row_per_profile_with_a_live_verdict():
    profiles = load_profiles()
    rows = build_rows(profiles)
    assert {r["symbol"] for r in rows} == set(profiles)
    md = render(rows, "2026-11-19")
    assert "| Symbol |" in md and all(f"| {s} |" in md for s in profiles)
    assert all(isinstance(r["live"], bool) and r["why"] for r in rows)
