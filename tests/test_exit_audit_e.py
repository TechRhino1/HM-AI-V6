"""Exit audit (2026-11-27, PR E): excursions survive broker-side closes, the scalp stall keeps
stop dispatch when refused, pre-registered exit variants, per-cell live exit modes, the shadow
forward test, approval gating, and the exit-quality check."""
import pytest

from jarvis.execution.exit_policy import (EXIT_VARIANTS, ExitPolicy, apply_exit_mode, evaluate_exit,
                                          live_exit_mode)

GOLD_ENTRY, GOLD_SL = 3670.24, 3658.42          # live #2607: 1R = 11.82


def _lock_pol(mode=None):
    base = ExitPolicy(symbol="XAUUSD", trade_style="SCALP", digits=2, pip_size=0.1)
    return apply_exit_mode(base, mode or "institutional_lock")


def _walk(path, pol):
    """Replay a BUY price path through evaluate_exit like the monitor: (exit price, final stop)."""
    sl, peak = GOLD_SL, 0.0
    for px in path:
        if px <= sl:
            return sl, sl
        peak = max(peak, px - GOLD_ENTRY)
        d = evaluate_exit(side="BUY", entry=GOLD_ENTRY, initial_sl=GOLD_SL, current_sl=sl, tp=0.0, price=px,
                          favorable_dist=px - GOLD_ENTRY, atr=5.0, policy=pol, partial_already_taken=True,
                          be_already_locked=sl >= GOLD_ENTRY, partial_executable=False,
                          peak_favorable_dist=peak)
        if d.new_sl:
            sl = max(sl, d.new_sl)
    return path[-1], sl


def _r(px):
    return (px - GOLD_ENTRY) / (GOLD_ENTRY - GOLD_SL)


# ── the live trade, replayed ─────────────────────────────────────────────────
GOLD_PATH = [3672.0, 3675.0, 3680.0, 3682.4, 3684.0, 3685.0, 3683.0, 3680.0, 3678.0, 3677.0, 3676.5]


def test_gold_trade_replay_baseline_matches_live():
    px, sl = _walk(GOLD_PATH, _lock_pol())
    assert sl == pytest.approx(3676.73, abs=0.15)      # live: last stop 3676.86 (peak ~3685.0 - 0.7R)
    assert _r(px) == pytest.approx(0.55, abs=0.02)     # live: +0.54R


def test_variants_on_the_gold_trade():
    base = _r(_walk(GOLD_PATH, _lock_pol())[0])
    assert _r(_walk(GOLD_PATH, _lock_pol("ratchet"))[0]) == pytest.approx(base)   # peak 1.25R < 1.5R rung: same
    assert _r(_walk(GOLD_PATH, _lock_pol("early_protect"))[0]) == pytest.approx(base)


def test_early_protect_turns_a_07r_reversal_into_breakeven():
    path = [3674.0, 3678.5, 3675.0, 3668.0, 3660.0, 3658.0]          # peak +0.70R, then the full stop
    assert _r(_walk(path, _lock_pol())[0]) == pytest.approx(-1.0)
    px, _ = _walk(path, _lock_pol("early_protect"))
    assert 0.0 <= _r(px) < 0.1                                        # breakeven + buffer


def test_ratchet_narrows_the_trail_on_bigger_peaks():
    path = [GOLD_ENTRY + k * 11.82 for k in (0.5, 1.0, 1.6, 2.0, 2.6, 3.0)] + [GOLD_ENTRY + 1.0 * 11.82]
    assert _r(_walk(path, _lock_pol())[0]) == pytest.approx(2.3, abs=0.02)        # 3.0R peak - 0.7R
    assert _r(_walk(path, _lock_pol("ratchet"))[0]) == pytest.approx(2.6, abs=0.02)  # 3.0R peak - 0.4R


def test_variants_are_the_lock_plus_one_change_and_never_looser():
    lock = _lock_pol()
    for mode, fields in EXIT_VARIANTS.items():
        v = _lock_pol(mode)
        assert (v.be_at_r, v.lock_floor_r, v.trail_r, v.time_stop_minutes) == (1.0, 0.3, 0.7, 0.0)
        assert all(getattr(v, k) == val for k, val in fields.items())
        for path in (GOLD_PATH, [3674.0, 3678.5, 3660.0], [GOLD_ENTRY + 11.82 * k for k in (1, 2, 3, 1)]):
            assert _walk(path, v)[1] >= _walk(path, lock)[1] - 1e-9


def test_live_exit_mode_per_cell(monkeypatch):
    from jarvis.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS.trading, "exit_mode", "institutional_lock")
    monkeypatch.setattr(SETTINGS.trading, "exit_hold_symbols", ["BTCUSD"])
    monkeypatch.setattr(SETTINGS.trading, "exit_cells", {})
    assert live_exit_mode("XAUUSD", "SCALP") == "institutional_lock"
    assert live_exit_mode("BTCUSD", "DAY") == "hold"
    monkeypatch.setattr(SETTINGS.trading, "exit_cells", {"COMMODITY|SCALP": "early_protect", "XAUUSD|SCALP": "ratchet",
                                                          "CRYPTO|DAY_TRADING": "early_ratchet"})
    assert live_exit_mode("XAUUSD", "SCALP") == "ratchet"            # symbol beats class
    assert live_exit_mode("XAGUSD", "SCALP") == "early_protect"
    assert live_exit_mode("BTCUSD", "DAY") == "early_ratchet"        # a cell beats the hold list
    assert live_exit_mode("XAUUSD", "SWING") == "institutional_lock"
    pol = ExitPolicy.for_symbol("XAUUSD", trade_style="SCALP")
    assert pol.trail_ladder == EXIT_VARIANTS["ratchet"]["trail_ladder"]


def test_unknown_exit_cell_mode_is_dropped():
    from jarvis.config.settings import _valid_exit_cells
    assert _valid_exit_cells({"XAUUSD|SCALP": "ratchet", "EURUSD|SWING": "yolo", "bad": "hold"}) == {"XAUUSD|SCALP": "ratchet"}


# ── excursions ───────────────────────────────────────────────────────────────
def test_excursions_survive_a_broker_side_close():
    from jarvis.execution.position_monitor import PositionMonitorEngine
    pm = object.__new__(PositionMonitorEngine)
    pm._peak_mfe, pm._peak_mae, pm._closed_excursions, pm._closed_excursions_order = {7: 14.9}, {7: 2.1}, {}, []
    pm._closed_excursions_cap = 512
    assert pm.pop_excursions(7) == (14.9, 2.1)          # read before the monitor's next tick retired it
    assert pm.pop_excursions(7) is None                 # never credited twice
    pm._peak_mfe, pm._peak_mae = {8: 1.0}, {8: 0.5}
    pm._remember_closed_excursions(8)
    assert pm.pop_excursions(8) == (1.0, 0.5)


def test_generic_prune_no_longer_drops_excursions():
    import inspect
    from jarvis.execution import position_monitor as m
    src = inspect.getsource(m.PositionMonitorEngine)
    prune = src[src.index('for _name in ("_initial_tp"'):src.index("_d = getattr(self, _name, None)")]
    assert '"_peak_mfe"' not in prune and '"_peak_mae"' not in prune


# ── shadow forward test ──────────────────────────────────────────────────────
def test_shadow_records_each_variant_against_the_real_exit():
    from jarvis.execution.exit_shadow import SHADOW_MODES, ExitShadow
    sh = ExitShadow()
    pol = _lock_pol()
    peak = 0.0
    for i, px in enumerate([3674.0, 3678.5, 3675.0, 3668.0]):          # peak +0.70R
        peak = max(peak, px - GOLD_ENTRY)
        sh.update(ticket=1, symbol="XAUUSD", style="SCALP", side="BUY", entry=GOLD_ENTRY, initial_sl=GOLD_SL,
                  price=px, favorable_dist=px - GOLD_ENTRY, atr=5.0, policy=pol, struct_level=None, regime=None,
                  partial_executable=False, open_dur_sec=10.0 * (i + 1), peak_favorable_dist=peak)
    rows = {r["mode"]: r for r in sh.pop(1, actual_exit=GOLD_SL)}  # the real trade hit its full stop
    assert set(rows) == set(SHADOW_MODES)
    assert rows["early_protect"]["shadow_hit"] and 0.0 <= rows["early_protect"]["shadow_r"] < 0.1
    assert rows["ratchet"]["shadow_r"] == pytest.approx(-1.0) and rows["ratchet"]["actual_r"] == pytest.approx(-1.0)
    assert all(r["complete"] for r in rows.values())
    sh.update(ticket=2, symbol="XAUUSD", style="SCALP", side="BUY", entry=GOLD_ENTRY, initial_sl=GOLD_SL, price=3672.0,
              favorable_dist=1.8, atr=5.0, policy=ExitPolicy(), struct_level=None, regime=None,
              partial_executable=False, open_dur_sec=5.0, peak_favorable_dist=1.8)
    assert sh.pop(2, 3672.0) == []                        # not on the lock: nothing shadowed


def _shadow_db(path, rows):
    from jarvis.data.database import SQLiteTradeDB
    db = SQLiteTradeDB(db_path=str(path))
    db.record_shadow_exits(rows, execution_mode="demo")
    return str(path)


def _row(i, mode="early_protect", shadow=0.05, actual=-1.0, sym="XAUUSD", complete=True):
    return {"ticket": i, "symbol": sym, "trade_style": "SCALP", "mode": mode, "entry": 1.0, "initial_sl": 0.9,
            "shadow_exit": 1.0, "shadow_r": shadow, "actual_exit": 0.9, "actual_r": actual, "shadow_hit": True,
            "complete": complete}


def test_approval_needs_twenty_complete_shadow_closes_not_worse(tmp_path):
    from jarvis.learning.evidence import shadow_failures
    db = _shadow_db(tmp_path / "h.db", [_row(i) for i in range(19)] + [_row(99, complete=False)])
    assert "19 shadow closes" in shadow_failures({"XAUUSD|SCALP": "early_protect"}, db_path=db)[0]
    db = _shadow_db(tmp_path / "h2.db", [_row(i, sym="XAGUSD") for i in range(20)])
    assert shadow_failures({"COMMODITY|SCALP": "early_protect"}, db_path=db) == []     # class key
    assert shadow_failures({"XAUUSD|SCALP": "early_protect"}, db_path=db)              # silver is not gold
    db = _shadow_db(tmp_path / "h3.db", [_row(i, shadow=-0.5, actual=0.2) for i in range(25)])
    assert "shadow -0.500R vs real +0.200R" in shadow_failures({"XAUUSD|SCALP": "early_protect"}, db_path=db)[0]
    assert "no live shadow" in shadow_failures({"XAUUSD|SCALP": "chandelier"}, db_path=db)[0]
    assert shadow_failures({"XAUUSD|SCALP": "institutional_lock"}, db_path=db) == []   # back to the measured lock


def test_install_writes_exit_cells_with_the_evidence(tmp_path, monkeypatch):
    import json
    from jarvis.config import settings as st
    from jarvis.learning import evidence, model_registry as reg
    monkeypatch.setattr(reg, "_root", lambda: str(tmp_path / "models"))
    live = tmp_path / "report.json"
    monkeypatch.setattr(evidence, "live_path", lambda: str(live))
    monkeypatch.setattr(evidence, "_ACTIVE", {"mt": None, "path": None})
    sfile = tmp_path / "settings.json"
    sfile.write_text(json.dumps({"trading": {"exit_mode": "institutional_lock"}}), encoding="utf-8")
    monkeypatch.setattr(st, "_LIVE_SETTINGS_PATH", str(sfile))
    monkeypatch.setattr(st.SETTINGS.trading, "exit_cells", {})
    live.write_text(json.dumps({"holdout_window": "a..2026-11-26", "modes": []}), encoding="utf-8")
    evidence.active_file()
    cand = tmp_path / "cand.json"
    cand.write_text(json.dumps({"holdout_window": "a..2026-11-26", "modes": [], "exit_cells": {"XAUUSD|SCALP": "ratchet"}}),
                    encoding="utf-8")
    res = evidence.promote(str(cand), reason="t")
    assert res["result"]["status"] == "PENDING" and res["changes"]["exit_policy"]
    with pytest.raises(ValueError, match="shadow forward test"):
        evidence.install(res["result"]["version"], reason="ok")
    monkeypatch.setattr(evidence, "shadow_failures", lambda changed, db_path=None: [])
    evidence.install(res["result"]["version"], reason="ok")
    assert json.loads(sfile.read_text())["trading"]["exit_cells"] == {"XAUUSD|SCALP": "ratchet"}
    assert st.SETTINGS.trading.exit_cells == {"XAUUSD|SCALP": "ratchet"}
    evidence.install("v1", reason="rollback", require_shadow=False)
    assert json.loads(sfile.read_text())["trading"]["exit_cells"] == {}
    assert st.SETTINGS.trading.exit_cells == {}


def test_integrity_refuses_evidence_measured_without_the_live_exit_cells(monkeypatch):
    import datetime as dt
    from jarvis.config.settings import SETTINGS
    from jarvis.learning.evidence import integrity_refusal
    monkeypatch.setattr(SETTINGS.trading, "exit_mode", "institutional_lock")
    monkeypatch.setattr(SETTINGS.trading, "exit_cells", {"XAUUSD|SCALP": "ratchet"})
    p = {"holdout_window": "2026-05-24..2026-11-26", "exit_mode": "institutional_lock"}
    assert integrity_refusal(p, today=dt.date(2026, 11, 27)).startswith("EVIDENCE_MISMATCH")
    p["exit_cells"] = {"XAUUSD|SCALP": "ratchet"}
    assert integrity_refusal(p, today=dt.date(2026, 11, 27)) is None


# ── exit-quality monitoring ──────────────────────────────────────────────────
def test_exit_quality_check():
    from jarvis.observability import system_monitor as sm
    assert sm.check_exit_quality([], {})["status"] == sm.OK
    ok = [{"cell": "XAUUSD|SCALP", "mfe_r": 1.3, "exit_r": 0.7 + 0.01 * i, "stop_slip_r": 0.02} for i in range(6)]
    assert sm.check_exit_quality(ok, {"XAUUSD|SCALP": {"giveback_r": 0.65}})["status"] == sm.OK
    bad = [{"cell": "XAUUSD|SCALP", "mfe_r": 1.3 + 0.01 * i, "exit_r": -0.2, "stop_slip_r": None} for i in range(6)]
    out = sm.check_exit_quality(bad, {"XAUUSD|SCALP": {"giveback_r": 0.65}})
    assert out["status"] == sm.WARN and "missed protection 6" in out["detail"]
    slip = [{"cell": "EURUSD|DAY_TRADING", "mfe_r": 0.2, "exit_r": -1.2, "stop_slip_r": 0.2} for _ in range(5)]
    assert sm.check_exit_quality(slip, {})["status"] == sm.WARN


def test_excursion_stats_match_the_gold_trade():
    from jarvis.analytics.performance import excursion_stats
    s = excursion_stats([(1.26, 0.54), (0.7, -1.0)])
    assert s["reached_1r"] == 1 and s["giveback_r"] == pytest.approx(0.72) and s["capture_pct"] == pytest.approx(42.9)
