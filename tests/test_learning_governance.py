"""Learning governance (2026-11-16): frozen live models, validated promotion, no live loosening."""
import json
import os

import pytest

import jarvis.learning.model_registry as reg
from jarvis.intelligence.gate_policy import AdaptiveGatePolicy
from jarvis.intelligence.gate_registry import HARD_GATES, GATE_NAMES


def _state(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return str(p)


def test_first_use_freezes_the_live_state_as_v1(tmp_path):
    seed = _state(tmp_path, "w.json", {"weights": [1, 2]})
    path = reg.active_path("m1", seed)
    assert reg.active_info("m1")["version"] == "v1"
    assert json.loads(open(path).read()) == {"weights": [1, 2]}
    # The frozen snapshot is read-only: nothing can rewrite it in place.
    with pytest.raises(PermissionError):
        open(path, "w").write("x")


def test_register_activate_rollback_and_audit(tmp_path, _hermetic_model_registry):
    reg.register("m2", _state(tmp_path, "a.json", {"v": 1}), reason="first", activate=True)
    reg.register("m2", _state(tmp_path, "b.json", {"v": 2}), reason="better", activate=True,
                 validation={"passed": True})
    assert reg.active_info("m2")["version"] == "v2"
    assert reg.active_info("m2")["parent"] == "v1"
    reg.activate("m2", "v1", reason="rollback test")
    assert reg.active_info("m2")["version"] == "v1"
    records = [json.loads(line) for line in open(os.path.join(_hermetic_model_registry, "audit.jsonl"))]
    assert [r["event"] for r in records if r.get("model") == "m2"] == ["register", "register", "activate"]


def test_prequential_promotion_scores_before_learning_and_never_touches_the_active(tmp_path):
    from jarvis.learning.online_ml_predictor import OnlineMLPredictor
    from tools.promote_model import evaluate_online_ml

    active_file = str(tmp_path / "active.json")
    OnlineMLPredictor(model_file=active_file)._save_model()
    before = open(active_file, "rb").read()
    n_feat = len(OnlineMLPredictor.FEATURE_NAMES)
    # A learnable signal: feature 0 decides the outcome.
    trades = [("t", [1.0 if i % 2 else -1.0] + [0.0] * (n_feat - 1), i % 2) for i in range(80)]
    m = evaluate_online_ml(active_file, trades)
    assert m["n"] == 80
    assert m["brier_candidate"] < m["brier_active"]   # it learned, measured out-of-sample
    assert open(active_file, "rb").read() == before    # the live model was not modified


def test_gate_softening_respects_the_configured_floor():
    policy = AdaptiveGatePolicy(max_soft_fail=3, min_recent_win_rate=0.45)
    soft = ["Trend Not Exhausted: stretched"]
    assert policy.decide(soft, recent_win_rate=0.30)[0] == "BLOCK"   # was SOFTEN via min(0.30, ...)
    assert policy.decide(soft, recent_win_rate=0.50)[0] == "SOFTEN"


def test_previously_unregistered_gates_are_registered():
    assert "Honest Base Rate + 5%" in HARD_GATES
    assert "ML Meta-Label Confirmation" in GATE_NAMES


def test_realtime_optimizer_never_loosens(tmp_path, monkeypatch):
    import sqlite3
    from jarvis.intelligence.realtime_optimizer import RealtimeOptimizer
    import jarvis.config.runtime as runtime

    db = str(tmp_path / "h.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE executed_trades (id INTEGER PRIMARY KEY, symbol TEXT, regime TEXT, realized_pnl REAL)")
    con.executemany("INSERT INTO executed_trades (symbol, regime, realized_pnl) VALUES ('EURUSD','TREND_BULL',?)",
                    [(5.0,)] * 25 + [(-1.0,)] * 5)   # 83% win rate: used to relax thresholds
    con.commit(); con.close()
    monkeypatch.setattr(runtime, "is_offline", lambda: False)
    adj = RealtimeOptimizer(db_path=db).get_adjustments("EURUSD", "TREND_BULL")
    assert all(v >= 0 for v in adj.values())
