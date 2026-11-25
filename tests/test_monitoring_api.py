"""Monitoring API read models + routes (plan Phase 7)."""
import json
import time
from types import SimpleNamespace

from jarvis.api.server import JarvisRequestHandler
from jarvis.observability import system_monitor as sm


def _row(age_s, **kw):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_s))
    return {"kind": "dispatch", "ts": ts, "symbol": "EURUSD", "origin": "arbiter", **kw}


def _journal(tmp_path, rows):
    (tmp_path / "decisions_20261125.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(tmp_path)


def test_read_decisions_filters_newest_first_and_skips_scan_rows(tmp_path):
    d = _journal(tmp_path, [
        _row(300, blocked_by="HOLDOUT_GATE", symbol="XAUUSD"),
        {"symbol": "EURUSD", "decision": "WAIT", "ts": "2026-11-25T10:00:00Z"},  # scan row, not dispatch
        _row(200, blocked_by="DRAWDOWN_GUARD"),
        _row(100, status="FILLED", origin="forward_test:FT_TR_EURUSD_H4_T1"),
    ])
    rows = sm.read_decisions(d, symbol="EURUSD")
    assert [r.get("status") or r.get("blocked_by") for r in rows] == ["FILLED", "DRAWDOWN_GUARD"]
    assert len(sm.read_decisions(d, origin="forward_test")) == 1
    assert len(sm.read_decisions(d, blocked_by="HOLDOUT_GATE")) == 1
    assert sm.read_decisions(d, since=time.time() - 150)[0]["status"] == "FILLED"


def test_gate_stats_counts_blockers_sends_and_shadow_rejects():
    rows = [_row(60, blocked_by="DRAWDOWN_GUARD")] * 3 + [
        _row(30, status="FILLED", gates=[{"gate": "PRE_SEND_VERIFIER", "verdict": "SHADOW_REJECT"}])]
    out = sm.gate_stats(rows, hours=1, now=time.time())
    assert out["attempts"] == 4 and out["sent"] == 1
    assert out["blocked_by"] == {"DRAWDOWN_GUARD": 3}
    assert out["shadow_rejects"] == {"PRE_SEND_VERIFIER": 1}


def _call(path, query=None, orch=None):
    sent = {}
    fake = SimpleNamespace(orchestrator=orch, _send_json=lambda data, status_code=200: sent.update(data=data))
    JarvisRequestHandler._send_monitoring(fake, path, query or {})
    return sent["data"]


def test_monitor_route_serves_state_and_rollout_config():
    orch = SimpleNamespace(monitor_state={"status": "WARN", "checks": {}},
                           llm_controller=SimpleNamespace(last_advisory=None))
    out = _call("/api/monitor", orch=orch)
    assert out["monitor"]["status"] == "WARN"
    assert out["config"]["verifier"]["mode"] in ("off", "shadow", "enforce")


def test_verifier_recent_route_is_newest_first():
    from jarvis.risk import trade_guard as tg
    tg.VERIFICATIONS.clear()
    tg.VERIFICATIONS.extend([{"symbol": "A"}, {"symbol": "B"}])
    out = _call("/api/verifier/recent", {"limit": ["5"]})
    assert [r["symbol"] for r in out["rows"]] == ["B", "A"]


def test_gate_stats_and_decisions_routes_answer(tmp_path, monkeypatch):
    import jarvis.config.paths as paths
    (tmp_path / "decisions").mkdir()
    _journal(tmp_path / "decisions", [_row(60, blocked_by="NEWS_BLACKOUT")])
    monkeypatch.setattr(paths, "DATA_DIR", str(tmp_path))
    assert _call("/api/gates/stats", {"hours": ["2"]})["blocked_by"].get("NEWS_BLACKOUT") == 1
    assert _call("/api/decisions", {"blocked_by": ["NEWS_BLACKOUT"]})["count"] == 1
