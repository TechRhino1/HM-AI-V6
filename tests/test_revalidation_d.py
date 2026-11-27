"""PR D (2026-11-27): governed deployment evidence - promote (tighten now, loosen PENDING),
integrity (stale / other exit policy), drift refusal with rollback, runtime override reload,
and the weekly revalidation runner."""
import datetime as dt
import json
import os

import pytest

from jarvis.backtesting import exit_geometry as eg
from jarvis.learning import evidence
from jarvis.learning import model_registry as reg

END = dt.date(2026, 11, 26)
pytestmark = pytest.mark.calibrated_exits   # the real deployment gate, not the conftest stub


def _report(rows, exit_mode="institutional_lock", hold=("BTCUSD", "ETHUSD", "SOLUSD"), window="2026-05-24..2026-11-26"):
    modes = {}
    for r in rows:
        modes.setdefault(r.pop("style"), []).append(r)
    out = {"holdout_window": window, "exit_mode": exit_mode,
           "modes": [{"style": st, "pooled": {}, "per_symbol": rs} for st, rs in modes.items()]}
    if hold is not None:
        out["exit_hold_symbols"] = sorted(hold)
    return out


def _row(sym, e, n=60, style="DAY_TRADING", **kw):
    return {"symbol": sym, "style": style, "trades": n, "expectancy_r": e, **kw}


@pytest.fixture
def ev_env(tmp_path, monkeypatch):
    """A private registry and live report path; live exit policy pinned; gate enabled."""
    from jarvis.config import runtime
    from jarvis.config.settings import SETTINGS
    monkeypatch.setattr(reg, "_root", lambda: str(tmp_path / "models"))
    live = tmp_path / "mode_backtest_report.json"
    monkeypatch.setattr(evidence, "live_path", lambda: str(live))
    monkeypatch.setattr(evidence, "_ACTIVE", {"mt": None, "path": None})
    monkeypatch.setattr(eg, "_ENGINE_EVIDENCE", {"key": None, "rows": None, "payload": None})
    monkeypatch.setattr(SETTINGS.trading, "exit_mode", "institutional_lock")
    monkeypatch.setattr(SETTINGS.trading, "exit_hold_symbols", ["BTCUSD", "ETHUSD", "SOLUSD"])
    monkeypatch.setattr(SETTINGS.trading, "use_calibrated_entry_policy", False)
    monkeypatch.setattr(SETTINGS.gates, "deployment_overrides", [])
    monkeypatch.setattr(SETTINGS.gates, "evidence_max_age_days", 10000.0)
    monkeypatch.setattr(runtime, "is_offline", lambda: False)

    def write(payload, path=live):
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write, tmp_path


def _verdicts():
    return {f"{k[0]}|{k[1]}": evidence._gate(k, r) for k, r in evidence.cells(evidence.load(evidence.active_file())).items()}


def test_tightening_applies_and_loosening_waits_for_approval(ev_env):
    write, tmp = ev_env
    write(_report([_row("EURUSD", 0.10), _row("GBPUSD", -0.10), _row("USDJPY", -0.05)]))
    assert eg.deployment_refusal("EURUSD", "DAY_TRADING") is None           # v1 frozen from today's report
    cand = write(_report([_row("EURUSD", -0.05),                            # stops passing: tighten
                          _row("GBPUSD", 0.20, lcb80_r=0.05, train_expectancy_r=0.1),   # would start: loosen
                          _row("USDJPY", 0.08, lcb80_r=-0.10, dsr=0.0)]),  # passes the gate, not the rule
                 tmp / "cand.json")
    out = evidence.promote(cand, reason="test")
    assert out["tightened"]["status"] == "ACTIVE" and out["result"]["status"] == "PENDING"
    assert [c.split(" ")[0] for c in out["changes"]["loosen"]] == ["GBPUSD"]
    v = _verdicts()
    assert v["EURUSD|DAY_TRADING"].startswith("REVALIDATION")                 # refused at once
    assert v["GBPUSD|DAY_TRADING"].startswith("STYLE_HOLDOUT_GATE")           # still refused: not approved
    assert eg.deployment_refusal("EURUSD", "DAY_TRADING").startswith("REVALIDATION")
    reg.deploy_version(evidence.NAME, out["result"]["version"], evidence.live_path(), reason="operator ok")
    v = _verdicts()
    assert v["GBPUSD|DAY_TRADING"] is None
    assert v["USDJPY|DAY_TRADING"].startswith("PROMOTION_RULE")              # held back by the stricter bar
    assert v["EURUSD|DAY_TRADING"].startswith("STYLE_HOLDOUT_GATE")


def test_cells_already_trading_keep_the_gate_rule(ev_env):
    write, tmp = ev_env
    write(_report([_row("EURUSD", 0.10)]))
    evidence.active_file()
    out = evidence.promote(write(_report([_row("EURUSD", 0.06, lcb80_r=-0.2)]), tmp / "c.json"), reason="t")
    assert out["result"]["status"] == "ACTIVE" and not any(out["changes"].values())
    assert _verdicts()["EURUSD|DAY_TRADING"] is None


def test_a_changed_exit_policy_waits_for_approval(ev_env):
    write, tmp = ev_env
    write(_report([_row("EURUSD", 0.10)]))
    evidence.active_file()
    out = evidence.promote(write(_report([_row("EURUSD", 0.10)], exit_mode="default"), tmp / "c.json"), reason="t")
    assert out["result"]["status"] == "PENDING" and out["changes"]["exit_policy"]


def test_gate_refuses_mismatched_or_stale_evidence_even_with_an_override(ev_env, monkeypatch):
    from jarvis.config.settings import SETTINGS
    write, _ = ev_env
    write(_report([_row("EURUSD", 0.10)], exit_mode="default"))   # measured on the legacy exit
    monkeypatch.setattr(SETTINGS.gates, "deployment_overrides",
                        [{"symbol": "EURUSD", "style": "DAY_TRADING", "since": "2026-11-27"}])
    assert eg.deployment_refusal("EURUSD", "DAY_TRADING").startswith("EVIDENCE_MISMATCH")
    assert eg.deployment_refusal("EURUSD").startswith("EVIDENCE_MISMATCH")
    p = _report([_row("EURUSD", 0.10)])
    monkeypatch.setattr(SETTINGS.gates, "evidence_max_age_days", 35.0)
    assert evidence.integrity_refusal(p, today=END + dt.timedelta(days=10)) is None
    assert evidence.integrity_refusal(p, today=END + dt.timedelta(days=36)).startswith("EVIDENCE_STALE")
    assert evidence.integrity_refusal(_report([_row("EURUSD", 0.1)], hold=("BTCUSD",)), today=END).startswith("EVIDENCE_MISMATCH")
    assert evidence.integrity_refusal(_report([_row("EURUSD", 0.1)], hold=None), today=END) is None  # older reports


def test_drift_refuses_the_cell_and_rollback_restores_it(ev_env):
    write, _ = ev_env
    write(_report([_row("XAUUSD", 0.05, n=230, style="SCALP")]))
    assert eg.deployment_refusal("XAUUSD", "SCALP") is None
    state = {"checks": {"live_vs_calibrated": {"symbols": {
        "XAUUSD|SCALP": {"status": "CRITICAL", "benchmark": "engine_holdout", "n": 25, "live_r": -0.3, "oos_r": 0.05},
        "ETHUSD|DAY_TRADING": {"status": "WARN", "benchmark": "engine_holdout", "n": 25, "live_r": 0.0, "oos_r": 0.2}}}}}
    assert evidence.refuse_drifting_cells(state) == ["XAUUSD|SCALP"]
    assert evidence.refuse_drifting_cells(state) == []                      # already refused: no new version
    assert eg.deployment_refusal("XAUUSD", "SCALP").startswith("LIVE_DRIFT")
    reg.deploy_version(evidence.NAME, "v1", evidence.live_path(), reason="rollback")
    assert eg.deployment_refusal("XAUUSD", "SCALP") is None


def test_monitor_evidence_check():
    from jarvis.observability import system_monitor as sm
    assert sm.check_evidence({"version": "v2", "age_days": 3, "pending": []})["status"] == sm.OK
    assert sm.check_evidence({"version": "v2", "age_days": 20, "pending": []})["status"] == sm.WARN
    assert sm.check_evidence({"version": "v2", "age_days": 3, "pending": ["v3"]})["status"] == sm.WARN
    assert sm.check_evidence({"version": "v2", "age_days": 40, "integrity": "EVIDENCE_STALE: x"})["status"] == sm.CRITICAL


def test_overrides_reload_without_restart(tmp_path, monkeypatch):
    from jarvis.config import settings as st
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"gates": {"deployment_overrides": []}}), encoding="utf-8")
    monkeypatch.setattr(st, "_LIVE_SETTINGS_PATH", str(f))
    monkeypatch.setattr(st, "_OVERRIDES_SEEN", {"mtime": None})
    monkeypatch.setattr(st.SETTINGS.gates, "deployment_overrides", [])
    assert st.reload_deployment_overrides() is False                         # first look: baseline only
    new = [{"symbol": "XAUUSD", "style": "SCALP", "since": "2026-11-27"}]
    f.write_text(json.dumps({"gates": {"deployment_overrides": new}}), encoding="utf-8")
    os.utime(f, (os.path.getmtime(f) + 5, os.path.getmtime(f) + 5))
    assert st.reload_deployment_overrides() is True and st.SETTINGS.gates.deployment_overrides == new
    f.write_text("{ half written", encoding="utf-8")
    os.utime(f, (os.path.getmtime(f) + 10, os.path.getmtime(f) + 10))
    assert st.reload_deployment_overrides() is False and st.SETTINGS.gates.deployment_overrides == new


# ── the weekly runner ────────────────────────────────────────────────────────
def test_fingerprint_changes_with_the_bars(tmp_path):
    import tools.revalidate as rv
    d = tmp_path / "XAUUSD"
    d.mkdir()
    (d / "XAUUSD_M5_365d.parquet").write_bytes(b"a")
    win = rv.windows(END)
    a = rv.fingerprint(["XAUUSD"], {"exit_mode": "x"}, win, data_dir=str(tmp_path))
    assert a == rv.fingerprint(["XAUUSD"], {"exit_mode": "x"}, win, data_dir=str(tmp_path))
    (d / "XAUUSD_M5_365d.parquet").write_bytes(b"b")
    assert rv.fingerprint(["XAUUSD"], {"exit_mode": "x"}, win, data_dir=str(tmp_path))["all"] != a["all"]
    assert rv.fingerprint(["XAUUSD"], {"exit_mode": "y"}, win, data_dir=str(tmp_path))["all"] != a["all"]
    assert win["train_end"] < win["holdout_start"] and (win["holdout_end"] - win["holdout_start"]).days == 183


def test_runner_replays_the_live_exit_reuses_cells_and_promotes(ev_env, monkeypatch):
    import tools.revalidate as rv
    write, tmp = ev_env
    write(_report([_row("EURUSD", 0.10)]))
    monkeypatch.setattr(rv, "STAGING", str(tmp / "staging"))
    monkeypatch.setattr(rv, "data_gaps", lambda s, e: [])
    calls = []

    def fake(cmd, log):
        calls.append(cmd)
        if "run_mode_backtest.py" in cmd[1]:
            out = cmd[cmd.index("--out") + 1]
            os.makedirs(out, exist_ok=True)
            for sym in cmd[cmd.index("--symbols") + 1].split(","):
                for style in cmd[cmd.index("--styles") + 1].split(","):
                    open(os.path.join(out, f"{sym}__{style}.json"), "w").write("{}")
        if "loss_audit_eval.py" in cmd[1]:
            write(_report([_row("EURUSD", -0.05)]), tmp / "staging" / "mode_backtest_report.candidate.json")
        return 0

    argv = ["--symbols", "EURUSD", "--styles", "SCALP,DAY_TRADING", "--end", str(END)]
    assert rv.main(argv, run=fake) == 0
    grids = [c for c in calls if "run_mode_backtest.py" in c[1]]
    assert [c[c.index("--styles") + 1] for c in grids] == ["SCALP,DAY_TRADING", "DAY_TRADING"]   # no SCALP train
    assert all(c[c.index("--exit-mode") + 1] == "institutional_lock" for c in grids)
    assert grids[0][grids[0].index("--end") + 1] == str(END)
    assert _verdicts()["EURUSD|DAY_TRADING"] is not None                     # the tightening went live
    calls.clear()
    assert rv.main(argv + ["--no-fetch", "--no-promote"], run=fake) == 0
    assert not [c for c in calls if "run_mode_backtest.py" in c[1]]          # same fingerprint: cells reused


def test_runner_promotes_nothing_from_an_incomplete_grid(ev_env, monkeypatch):
    import tools.revalidate as rv
    write, tmp = ev_env
    write(_report([_row("EURUSD", 0.10)]))
    monkeypatch.setattr(rv, "STAGING", str(tmp / "staging"))
    monkeypatch.setattr(rv, "data_gaps", lambda s, e: [])
    assert rv.main(["--symbols", "EURUSD", "--styles", "DAY_TRADING", "--end", str(END)], run=lambda c, l: 0) == 2
    summary = json.load(open(next((tmp / "staging").glob("revalidation_*.json"))))
    assert summary["outcome"].startswith("GRID_INCOMPLETE")
    assert reg.versions(evidence.NAME)["active"] in (None, "v1")


def test_evidence_rows_carry_the_lower_bound():
    from tools.loss_audit_eval import lcb80
    assert lcb80([1.0]) is None
    assert lcb80([0.5, -0.5, 0.5, -0.5]) < 0 < lcb80([1.0, 1.1, 0.9, 1.0])
