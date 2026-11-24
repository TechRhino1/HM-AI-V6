"""DYNAMIC auto-tune: live-edge scoring, hysteresis, the 30-minute schedule and its API."""
import io
import json
import sqlite3

import pytest

from jarvis.intelligence import auto_tune_engine as ate
from jarvis.intelligence.auto_tune_engine import AutoTuneEngine, dynamic_edge, dynamic_on, dynamic_score


def _cand(sym, n=30, live=0.0, prior=0.0, **kw):
    c = dict(symbol=sym, confluence=50.0, ev=0.0, is_open=True, is_spread_spiked=False,
             spread_pips=1.0, max_spread=3.0)
    c.update(dynamic_score(n, live, prior))
    c.update(kw)
    return c


def test_edge_shrinks_live_toward_the_prior():
    assert dynamic_edge(0, 0.5, 0.1) == pytest.approx(0.1)
    assert dynamic_edge(30, 0.5, 0.1) == pytest.approx(0.3)


def test_hysteresis_needs_more_to_switch_on_than_to_stay_on():
    assert dynamic_on(-0.10, was_on=True) and not dynamic_on(-0.10, was_on=False)
    assert not dynamic_on(-0.20, was_on=True)


def test_select_excludes_closed_spiked_and_weak_and_keeps_no_evidence_as_it_was():
    cands = [_cand("ETHUSD", live=0.3), _cand("XAUUSD", is_open=False, live=0.5),
             _cand("SOLUSD", is_spread_spiked=True, live=0.5), _cand("GBPUSD", live=-0.6),
             _cand("WTI", n=0, prior=None), _cand("US500", n=0, prior=None)]
    on, det = AutoTuneEngine.dynamic_select(cands, incumbents={"WTI"})
    assert on == {"ETHUSD", "WTI"}
    assert {d["symbol"] for d in det} == {c["symbol"] for c in cands}


def test_select_caps_usd_pairs_and_universe_and_ranks_by_edge_then_radar():
    usd = [_cand(s, live=0.2) for s in ("EURUSD", "GBPUSD", "USDJPY", "USDCAD")]
    on, _ = AutoTuneEngine.dynamic_select(usd, incumbents=set())
    assert len(on) == ate.DYN_MAX_USD
    many = [_cand(f"S{i}", live=0.1 + i / 100) for i in range(12)]
    on, _ = AutoTuneEngine.dynamic_select(many, incumbents=set())
    assert on == {f"S{i}" for i in range(4, 12)}
    tie = [_cand("A1", live=0.2, confluence=40.0), _cand("A2", live=0.2, confluence=80.0)]
    _, det = AutoTuneEngine.dynamic_select(tie, incumbents=set())
    assert det[0]["symbol"] == "A2"


def _ledger(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE executed_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, action TEXT,"
                 " entry_price REAL, sl REAL, tp REAL, exit_price REAL, realized_pnl REAL, features_json TEXT,"
                 " closed_at TEXT, execution_mode TEXT, regime TEXT)")
    for sym, strat, r, tp in rows:
        conn.execute("INSERT INTO executed_trades (symbol, action, entry_price, sl, tp, exit_price, realized_pnl,"
                     " features_json, closed_at, execution_mode, regime) VALUES (?, 'BUY', 100, 90, ?, ?, ?, ?, 'x',"
                     " 'demo', '')", (sym, tp, 100 + 10 * r, r, json.dumps({"strategy": strat})))
    conn.commit()
    conn.close()


def test_symbol_expectancy_pools_strategies_and_skips_misrecorded_stops(tmp_path, monkeypatch):
    from jarvis.execution import strategy_quarantine as q
    monkeypatch.setattr("jarvis.config.runtime.is_offline", lambda: False)
    db = str(tmp_path / "ledger.db")
    _ledger(db, [("XAUUSD", "TREND_PULLBACK", 1.0, 120), ("XAUUSD", "TREND_FOLLOWING", -1.0, 120),
                 ("XAUUSD", "TREND_FOLLOWING", 1.0, 120), ("XAUUSD", "TREND_FOLLOWING", 50.0, 1100)])
    q.clear_cache()
    try:
        assert q.load_symbol_expectancy(db_path=db)["XAUUSD"] == (3, pytest.approx(1 / 3))
        stats = q.load_live_expectancy(db_path=db)
        assert ("XAUUSD", q.SYMBOL_POOL) not in stats  # never a quarantine pair
        assert stats[("XAUUSD", "TREND_FOLLOWING")][0] == 2
    finally:
        q.clear_cache()


class _Orch:
    symbols = ["XAUUSD"]
    mode = "demo"
    state_manager = mt5_client = None

    def __init__(self):
        self.applied = []

    def set_active_symbols(self, syms, persist=True):
        self.applied.append(list(syms))
        self.symbols = list(syms)


def test_schedule_runs_only_when_dynamic_and_at_most_every_30_minutes(monkeypatch):
    from jarvis.application.orchestrator import JarvisOrchestrator
    from jarvis.config.settings import SETTINGS
    calls = []
    monkeypatch.setattr(AutoTuneEngine, "tune_universe",
                        classmethod(lambda cls, **kw: calls.append(kw["mode"]) or {"active_symbols": ["ETHUSD"]}))
    orch = _Orch()
    orch.AUTO_TUNE_EVERY_SEC = JarvisOrchestrator.AUTO_TUNE_EVERY_SEC
    tick = lambda now: JarvisOrchestrator._maybe_auto_tune(orch, now)
    monkeypatch.setattr(SETTINGS.trading, "auto_tune", "off")
    assert tick(10_000.0) is None and not calls
    monkeypatch.setattr(SETTINGS.trading, "auto_tune", "dynamic")
    assert tick(10_000.0)["changed"] and orch.applied == [["ETHUSD"]]
    assert tick(10_000.0 + 1799) is None
    assert tick(10_000.0 + 1800)["changed"] is False and orch.applied == [["ETHUSD"]]
    assert calls == ["DYNAMIC", "DYNAMIC"]


from jarvis.api.server import JarvisRequestHandler  # noqa: E402


class _Route(JarvisRequestHandler):
    def __init__(self, body, orch):
        payload = json.dumps(body).encode()
        self.path = "/api/action/batch_symbols"
        self.headers = {"Content-Length": str(len(payload))}
        self.rfile = io.BytesIO(payload)
        self.client_address = ("127.0.0.1", 1)
        self.orchestrator, self.mt5_client, self.sent = orch, None, []
        self.state_manager = type("SM", (), {"_bump_version": lambda self: None})()

    def _send_json(self, data, status_code=200, cookies=None):
        self.sent.append((status_code, data))

    def _require_role(self, *a):
        return True, None

    def _check_auth(self):
        return True


def _post(body, orch):
    h = _Route(body, orch)
    h.do_POST()
    return h.sent[-1]


def test_endpoint_passes_mode_and_records_the_manual_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(AutoTuneEngine, "tune_universe", classmethod(
        lambda cls, **kw: seen.update(kw) or {"active_symbols": ["ETHUSD"], "details": [], "summary": "s"}))
    orch = _Orch()
    orch.get_active_symbols = lambda: list(orch.symbols)
    status, data = _post({"action": "AUTO_TUNE", "mode": "dynamic"}, orch)
    assert status == 200 and seen["mode"] == "DYNAMIC" and data["active_symbols"] == ["ETHUSD"]
    assert orch.last_auto_tune["trigger"] == "manual" and orch.last_auto_tune["changed"] is True


def test_endpoint_switches_auto_tune_and_rejects_bad_values(monkeypatch):
    import jarvis.config.settings as st
    written = []
    monkeypatch.setattr(st, "_persist_trading", lambda k, v: written.append((k, v)) or True)
    monkeypatch.setattr(st.SETTINGS.trading, "auto_tune", "off")
    orch = _Orch()
    status, data = _post({"action": "SET_AUTO_TUNE", "auto_tune": "dynamic"}, orch)
    assert status == 200 and st.SETTINGS.trading.auto_tune == "dynamic" and written == [("auto_tune", "dynamic")]
    assert orch._last_auto_tune_at == 0.0
    status, _ = _post({"action": "SET_AUTO_TUNE", "auto_tune": "always"}, orch)
    assert status == 400 and st.SETTINGS.trading.auto_tune == "dynamic"
