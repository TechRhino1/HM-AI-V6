"""PR B health upgrade (2026-11-27): windowed checks, new checks, alert transitions, maintenance,
supervisor hang rule, alert persistence/ack, thread self-heal, per-symbol feed health."""
import gzip
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from jarvis.config.settings import MonitorSettings
from jarvis.observability import maintenance
from jarvis.observability import system_monitor as sm

NOW = 1_800_000_000.0
CFG = MonitorSettings()


# ── windowed rates ───────────────────────────────────────────────────────────
def test_window_forgets_events_older_than_the_span():
    w = sm.Window()
    assert w.delta("k", NOW, 100.0, 600) == 0.0
    assert w.delta("k", NOW + 300, 130.0, 600) == 30.0
    assert w.delta("k", NOW + 1300, 130.0, 600) == 0.0      # the old burst left the window


def test_share_needs_enough_events_and_judges_the_window():
    sm.WINDOW._pts.clear()
    sm.check_share("t", NOW, 0, 0, 0.1, 1800)
    out = sm.check_share("t", NOW + 60, 30, 100, 0.1, 1800)
    assert out["status"] == sm.WARN and out["value"] == 0.3
    sm.WINDOW._pts.clear()
    sm.check_share("u", NOW, 0, 0, 0.1, 1800)
    assert sm.check_share("u", NOW + 60, 5, 10, 0.1, 1800)["status"] == sm.OK  # under min_events


# ── new checks ───────────────────────────────────────────────────────────────
def test_state_sync_feeds_timeouts_guards_overrides_resources():
    assert sm.check_state_sync(NOW, None, CFG)["status"] == sm.WARN
    assert sm.check_state_sync(NOW, NOW - 5, CFG)["status"] == sm.OK
    assert sm.check_state_sync(NOW, NOW - 120, CFG)["status"] == sm.CRITICAL

    feeds = {"XAUUSD": {"status": "STREAMING"}, "US30": {"status": "STALE"}, "EURUSD": {"status": "CLOSED"}}
    out = sm.check_symbol_feeds(feeds, CFG)
    assert out["status"] == sm.WARN and "US30 STALE" in out["detail"] and "EURUSD" not in out["detail"]

    assert sm.check_timeouts({"stuck_workers": 0, "wedged": False})["status"] == sm.OK
    assert sm.check_timeouts({"stuck_workers": 2, "wedged": False})["status"] == sm.WARN
    assert sm.check_timeouts({"stuck_workers": 8, "wedged": True})["status"] == sm.CRITICAL

    assert sm.check_risk_guards(None, None, -5.0, 500.0)["status"] == sm.OK          # 1% of a 4% lockout
    assert sm.check_risk_guards(None, None, -16.0, 500.0)["status"] == sm.WARN       # 3.2% = 80% of it
    assert sm.check_risk_guards(None, "LOSS_STREAK", 0.0, 500.0)["status"] == sm.WARN

    ok = {"symbol": "XAUUSD", "style": "SCALP", "n": 4, "r": 0.2, "stop_after": 30, "stop_below": -0.1}
    assert sm.check_overrides([ok])["status"] == sm.OK
    assert sm.check_overrides([dict(ok, n=20, r=-0.3)])["status"] == sm.WARN          # half-way and losing
    assert sm.check_overrides([dict(ok, n=31, r=-0.3, stopped=True)])["detail"].endswith("STOPPED")

    assert sm.check_resources(20, 40, 100, 1, CFG)["status"] == sm.OK
    assert sm.check_resources(99, 40, 100, 1, CFG)["status"] == sm.WARN
    assert sm.check_resources(20, 40, 0.5, 1, CFG)["status"] == sm.CRITICAL


# ── alert transitions ────────────────────────────────────────────────────────
@pytest.fixture
def sent(monkeypatch):
    import jarvis.observability.alerting as al
    out = []
    monkeypatch.setattr(al, "dispatch_alert", lambda **k: out.append((k["title"], k["severity"].value)) or True)
    sm._ALERT_STATE.clear()
    yield out
    sm._ALERT_STATE.clear()


def test_alerts_fire_on_change_and_recovery_not_every_pass(sent):
    cfg = SimpleNamespace(escalate_after_passes=30, repeat_alert_s=21600.0)
    sm._alert_transitions(NOW, {"x": {"status": sm.WARN, "detail": "d"}}, cfg)
    sm._alert_transitions(NOW + 60, {"x": {"status": sm.WARN, "detail": "d"}}, cfg)
    assert sent == [("Monitor: x WARN", "WARNING")]                       # not re-sent every minute
    sm._alert_transitions(NOW + 120, {"x": {"status": sm.OK, "detail": "d"}}, cfg)
    assert sent[-1] == ("Monitor: x recovered", "INFO")
    sm._alert_transitions(NOW + 180, {"x": {"status": sm.OK, "detail": "d"}}, cfg)
    assert len(sent) == 2                                                  # recovery sent once


def test_persistent_warn_escalates_and_repeats_after_the_quiet_period(sent):
    cfg = SimpleNamespace(escalate_after_passes=3, repeat_alert_s=600.0)
    for i in range(3):
        c = {"x": {"status": sm.WARN, "detail": "d"}}
        sm._alert_transitions(NOW + 60 * i, c, cfg)
    assert c["x"].get("escalated") and sent[-1] == ("Monitor: x CRITICAL (escalated: persistent)", "CRITICAL")
    n = len(sent)
    sm._alert_transitions(NOW + 240, {"x": {"status": sm.WARN, "detail": "d"}}, cfg)
    assert len(sent) == n                                                   # inside the quiet period
    sm._alert_transitions(NOW + 900, {"x": {"status": sm.WARN, "detail": "d"}}, cfg)
    assert len(sent) == n + 1                                               # reminder after repeat_alert_s


def test_run_checks_merges_extra_checks_and_reports_the_worst():
    out = sm.run_checks(now=NOW, heartbeat=NOW - 5, rows=[], last_send=NOW - 60, verifications=[], positions=[],
                        equity=500.0, max_portfolio_risk_pct=2.0, fallbacks=0, evaluations=0, cfg=CFG, alert=False,
                        position_monitor={"running": True, "thread_alive": True, "last_tick_at": NOW - 1},
                        extra_checks={"timeouts": {"status": sm.CRITICAL, "detail": "wedged"}})
    assert out["checks"]["timeouts"]["status"] == sm.CRITICAL and out["status"] == sm.CRITICAL


# ── maintenance ──────────────────────────────────────────────────────────────
def test_rotate_journals_keeps_recent_files(tmp_path):
    today = datetime(2026, 11, 27, tzinfo=timezone.utc)
    d = tmp_path / "decisions"
    d.mkdir()
    for days in (0, 1, 20):
        (d / f"decisions_{today - timedelta(days=days):%Y%m%d}.jsonl").write_text('{"a": 1}\n' * 100)
    (d / f"decisions_{today - timedelta(days=200):%Y%m%d}.jsonl.gz").write_bytes(gzip.compress(b"x"))
    (d / "notes.txt").write_text("no date, never touched")
    out = maintenance.rotate_journals(str(d), today, retention_days=14, delete_after_days=90)
    names = sorted(os.listdir(d))
    assert out["compressed"] == 1 and out["deleted"] == 1
    assert f"decisions_{today:%Y%m%d}.jsonl" in names and f"decisions_{today - timedelta(days=1):%Y%m%d}.jsonl" in names
    assert f"decisions_{today - timedelta(days=20):%Y%m%d}.jsonl.gz" in names and "notes.txt" in names
    with gzip.open(d / f"decisions_{today - timedelta(days=20):%Y%m%d}.jsonl.gz") as fh:
        assert fh.read().count(b"\n") == 100


def test_backup_database_is_consistent_and_pruned(tmp_path):
    db = tmp_path / "jarvis_history.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    bdir = tmp_path / "backups"
    for i in range(4):
        out = maintenance.backup_database(str(db), str(bdir), datetime(2026, 11, 20 + i, tzinfo=timezone.utc), keep=2)
    assert out["quick_check"] == "ok"
    kept = sorted(os.listdir(bdir))
    assert kept == ["jarvis_history_20261122.db", "jarvis_history_20261123.db"]
    con = sqlite3.connect(bdir / kept[-1])
    try:
        assert con.execute("SELECT x FROM t").fetchone() == (1,)
    finally:
        con.close()


def test_run_daily_never_raises_and_reports(tmp_path):
    rep = maintenance.run_daily(str(tmp_path), CFG, NOW)
    assert rep["errors"] == [] and rep["backups"] == [] and rep["corrupt"] == []


# ── supervisor hang rule ─────────────────────────────────────────────────────
def test_supervisor_restarts_only_on_a_real_hang():
    from tools.hm_supervisor import STALLED_S, UNREACHABLE_S, hang_verdict
    st = {}
    assert hang_verdict(None, st, 0.0) is None
    assert hang_verdict(None, st, UNREACHABLE_S - 1) is None
    assert "unreachable" in hang_verdict(None, st, UNREACHABLE_S + 1)
    st = {}
    assert hang_verdict(None, st, 0.0) is None
    assert hang_verdict({"status": "degraded"}, st, 100.0) is None and "unreachable" not in st   # answered again
    st = {}
    stalled = {"loop": {"status": "CRITICAL"}}
    assert hang_verdict(stalled, st, 0.0) is None
    assert hang_verdict(stalled, st, STALLED_S + 1).startswith("orchestration loop stalled")
    st = {}
    hang_verdict({"monitor_stale": True}, st, 0.0)
    assert hang_verdict({"status": "degraded", "workers": {"symbol_feeds": "WARN"}}, st, STALLED_S + 1) is None


def test_health_url_follows_the_port_argument():
    from tools.hm_supervisor import health_url
    assert health_url(["demo", "8502"]).endswith(":8502/health")
    assert health_url(["--port=9000"]).endswith(":9000/health")


# ── alert persistence and acknowledgement ────────────────────────────────────
def test_alerts_persist_and_acks_survive_a_reload(tmp_path):
    from jarvis.observability.alerting import ALERT_MANAGER, AlertSeverity
    ALERT_MANAGER.clear()
    try:
        ALERT_MANAGER.enable_persistence(str(tmp_path))
        ALERT_MANAGER.dispatch("Monitor: x WARN", "detail", AlertSeverity.WARNING, event_key="t1", debounce_seconds=0)
        aid = ALERT_MANAGER.get_recent_alerts(1)[0]["id"]
        assert ALERT_MANAGER.acknowledge([aid]) == 1 and ALERT_MANAGER.acknowledge([aid]) == 0
        ALERT_MANAGER.clear()
        ALERT_MANAGER.enable_persistence(str(tmp_path))                      # a restart
        row = ALERT_MANAGER.get_recent_alerts(5)[0]
        assert row["id"] == aid and row["acknowledged"] is True and row["title"] == "Monitor: x WARN"
    finally:
        ALERT_MANAGER._persist_dir = None
        ALERT_MANAGER.clear()


# ── watchdog scheduling and self-heal ────────────────────────────────────────
def test_due_is_monotonic_not_a_modulo_window():
    from jarvis.application.orchestrator import JarvisOrchestrator
    o = SimpleNamespace()
    due = JarvisOrchestrator._due
    assert due(o, "j", 60.0, 1000.0) is True
    assert due(o, "j", 60.0, 1059.0) is False
    assert due(o, "j", 60.0, 1061.0) is True     # a long pass no longer skips the job


class _Worker:
    def __init__(self):
        self._running, self.starts = True, 0
        self._thread = threading.Thread(target=lambda: None)
        self._thread.start()
        self._thread.join()                        # dead

    def start(self):
        if not self._running:
            self._running = True
            self.starts += 1
            self._thread = threading.Thread(target=lambda: time.sleep(0.2), daemon=True)
            self._thread.start()


def test_dead_worker_threads_are_restarted_up_to_the_cap(monkeypatch):
    import jarvis.observability.alerting as al
    from jarvis.application.orchestrator import JarvisOrchestrator
    from jarvis.config.settings import SETTINGS
    alerts = []
    monkeypatch.setattr(al, "dispatch_alert", lambda **k: alerts.append(k["title"]) or True)
    monkeypatch.setattr(SETTINGS.monitor, "thread_restarts_per_hour", 2)
    pm, sync = _Worker(), _Worker()
    alive = threading.Thread(target=lambda: time.sleep(0.5), daemon=True)
    alive.start()
    o = SimpleNamespace(_running=True, position_monitor=pm, state_synchronizer=sync, _main_thread=alive)
    assert sorted(JarvisOrchestrator._heal_threads(o, NOW)) == ["position_monitor", "state_synchronizer"]
    assert pm.starts == 1 and pm._thread.is_alive()
    for k in (1, 2):                                # kill it again twice: the second exceeds the cap
        pm._thread.join()
        JarvisOrchestrator._heal_threads(o, NOW + k)
    assert pm.starts == 2 and any("restart cap reached" in a for a in alerts)
    o._running = False                               # a stopping engine is never resurrected
    assert JarvisOrchestrator._heal_threads(o, NOW + 10) == []


# ── per-symbol feed health ───────────────────────────────────────────────────
def test_symbol_health_keeps_each_symbol_and_classifies_it():
    import pandas as pd
    from jarvis.market.data_feed import FRESH, MARKET_CLOSED, STALE, DataFeedEngine
    feed = SimpleNamespace(_health_lock=threading.Lock(), _health={})
    for sym, src, fr in (("XAUUSD", "LIVE_MT5", FRESH), ("US30", "LIVE_MT5", STALE),
                         ("EURUSD", "LIVE_MT5", MARKET_CLOSED), ("GBPUSD", "SYNTHETIC_FALLBACK", None)):
        df = pd.DataFrame({"close": [1.0]})
        df.attrs.update(data_source=src, freshness=fr)
        DataFeedEngine._note_health(feed, df, sym, "H1")
    h = DataFeedEngine.symbol_health(feed)
    assert {s: v["status"] for s, v in h.items()} == {"XAUUSD": "STREAMING", "US30": "STALE",
                                                      "EURUSD": "CLOSED", "GBPUSD": "SYNTHETIC"}
