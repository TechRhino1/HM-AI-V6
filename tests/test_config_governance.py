"""Governed config writes: versioned, bounded, approval-gated, byte-exact rollback (plan Phase 6)."""
import json

import pytest

from jarvis.learning import model_registry as reg

BOUNDS = {"settings": {"risk.max_risk_per_trade_pct": [0.05, 2.0]}}


@pytest.fixture
def live(tmp_path, monkeypatch, _hermetic_model_registry):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"risk": {"max_risk_per_trade_pct": 1.0}}), encoding="utf-8")
    monkeypatch.setattr(reg, "load_param_bounds", lambda path=None: BOUNDS)
    return p


def _doc(pct):
    return json.dumps({"risk": {"max_risk_per_trade_pct": pct}}, indent=2)


def test_small_change_installs_and_freezes_the_previous_file_as_v1(live):
    original = live.read_bytes()
    res = reg.governed_write("settings", str(live), _doc(1.1), reason="tweak", approve=False)
    assert res == {"version": "v2", "status": "ACTIVE", "high_impact": []}
    assert json.loads(live.read_text())["risk"]["max_risk_per_trade_pct"] == 1.1
    v1 = reg.versions("settings")["versions"]["v1"]
    assert v1["reason"].startswith("bootstrap")
    reg.deploy_version("settings", "v1", str(live), reason="rollback test")
    assert live.read_bytes() == original  # byte-exact rollback
    assert reg.active_info("settings")["version"] == "v1"


def test_high_impact_change_waits_for_approval(live):
    res = reg.governed_write("settings", str(live), _doc(1.8), reason="big jump")
    assert res["status"] == "PENDING" and res["high_impact"]
    assert json.loads(live.read_text())["risk"]["max_risk_per_trade_pct"] == 1.0  # live untouched
    reg.deploy_version("settings", res["version"], str(live), reason="approved by operator")
    assert json.loads(live.read_text())["risk"]["max_risk_per_trade_pct"] == 1.8
    assert reg.versions("settings")["versions"][res["version"]]["status"] == "ACTIVE"


def test_out_of_bounds_value_is_refused_and_audited(live):
    with pytest.raises(ValueError):
        reg.governed_write("settings", str(live), _doc(5.0), reason="reckless", approve=True)
    assert json.loads(live.read_text())["risk"]["max_risk_per_trade_pct"] == 1.0


def test_bounds_check_reports_violations_and_large_moves():
    out = reg.check_param_bounds("settings", {"risk": {"max_risk_per_trade_pct": 1.0}},
                                 {"risk": {"max_risk_per_trade_pct": 3.0}}, bounds=BOUNDS, max_delta_pct=20)
    assert out["violations"] and out["high_impact"]


def test_repo_bounds_file_accepts_the_shipped_settings():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "config", "settings.json"), encoding="utf-8") as f:
        shipped = json.load(f)
    assert reg.check_param_bounds("settings", shipped, shipped,
                                  bounds=reg.load_param_bounds())["violations"] == []
