"""PR A live-safety fixes (2026-11-27): a restart keeps a tripped daily-loss lockout; MT5 reconnects
after a drop without sleeping the caller; XAGUSD resolves its broker name and a failed spec lookup is
not retried under the lock on every call."""
import sqlite3
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from jarvis.execution import mt5_client as mc
from jarvis.risk import loss_cooldown as lc


def _history(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE executed_trades (symbol TEXT, realized_pnl REAL, closed_at TEXT, execution_mode TEXT)")
    con.executemany("INSERT INTO executed_trades VALUES (?,?,?,?)", rows)
    con.commit()
    con.close()


@pytest.fixture
def live_history(monkeypatch, tmp_path):
    from jarvis.config import paths, runtime
    monkeypatch.setattr(runtime, "is_offline", lambda: False)
    db = tmp_path / "jarvis_history.db"
    monkeypatch.setattr(paths, "resolve_db_path", lambda name: str(db))
    today = datetime.now(timezone.utc).date().isoformat()
    return db, today


def test_restart_keeps_a_tripped_daily_loss_lockout(live_history):
    db, today = live_history
    _history(str(db), [("XAUUSD", -12.0, f"{today}T02:00:00+00:00", "demo"),
                       ("GBPUSD", -9.5, f"{today}T03:00:00+00:00", "demo"),
                       ("EURUSD", -50.0, f"{today}T03:30:00+00:00", "paper"),      # paper: not counted
                       ("US30", -40.0, "2020-01-01T03:00:00+00:00", "demo")])      # another day
    fresh = lc.LossCooldownManager()          # a restarted process
    fresh.peak_equity = 483.0
    skip, why = fresh.should_skip_trade("ETHUSD")
    assert skip and "daily drawdown" in why
    assert fresh.daily_pnl == pytest.approx(-21.5) and fresh.trades_today == 2
    assert fresh.trades_today_by_symbol == {"XAUUSD": 1, "GBPUSD": 1}


def test_a_close_event_first_also_rebuilds_the_day(live_history):
    db, today = live_history
    _history(str(db), [("XAUUSD", -20.0, f"{today}T02:00:00+00:00", "demo")])
    m = lc.LossCooldownManager()
    m.record_trade_result(pnl=-1.0, is_win=False, symbol="GBPUSD", current_date=today)
    assert m.daily_pnl == pytest.approx(-21.0)


def test_no_rebuild_offline_or_on_a_running_rollover(live_history, monkeypatch):
    db, today = live_history
    _history(str(db), [("XAUUSD", -20.0, f"{today}T02:00:00+00:00", "demo")])
    m = lc.LossCooldownManager()
    m.current_date = "2000-01-01"            # a running process crossing midnight
    m.should_skip_trade("ETHUSD")
    assert m.daily_pnl == 0.0
    from jarvis.config import runtime
    monkeypatch.setattr(runtime, "is_offline", lambda: True)
    bt = lc.LossCooldownManager()
    bt.record_trade_result(pnl=-1.0, is_win=False, symbol="X", current_date=today)
    assert bt.daily_pnl == pytest.approx(-1.0)  # backtests never read the live history


def test_unreadable_history_keeps_zero(live_history, monkeypatch):
    from jarvis.config import paths
    monkeypatch.setattr(paths, "resolve_db_path", lambda name: "Z:/no/such/jarvis_history.db")
    m = lc.LossCooldownManager()
    assert m.should_skip_trade("ETHUSD") == (False, "")


def test_reconnect_never_sleeps_the_caller_and_backs_off(monkeypatch):
    c = mc.MT5Client(mode="demo", auto_init=False)
    calls = []
    monkeypatch.setattr(c, "init_connection", lambda retries=True: calls.append(retries) or False)
    t0 = time.monotonic()
    for _ in range(5):
        c._reconnect_if_needed()
    assert time.monotonic() - t0 < 1.0
    assert calls == [False]                     # one attempt, no startup retry loop
    assert c._reconnect_backoff == 2.0
    c._next_reconnect_at = 0.0
    c._reconnect_if_needed()
    assert calls == [False, False] and c._reconnect_backoff == 4.0


def test_a_dropped_link_resets_the_terminal_latch(monkeypatch):
    c = mc.MT5Client(mode="demo", auto_init=False)
    c.is_connected = True
    reset = []
    import jarvis.data.broker_symbols as bs
    monkeypatch.setattr(bs, "reset_cache", lambda: reset.append(1))
    c.mark_disconnected("test")
    assert c.is_connected is False and reset == [1]
    paper = mc.MT5Client(mode="paper", auto_init=False)
    paper.is_connected = True
    paper.mark_disconnected("test")
    assert paper.is_connected is True           # paper has no broker link to lose


def test_silver_resolves_through_the_broker_alias_table(monkeypatch):
    c = mc.MT5Client(mode="demo", auto_init=False)
    c.is_connected = True
    monkeypatch.setattr(mc, "MT5_AVAILABLE", True)
    import jarvis.data.broker_symbols as bs
    monkeypatch.setattr(bs, "resolve_broker_symbol", lambda s, **k: "SILVER.i#" if s == "XAGUSD" else None)
    assert c.resolve_symbol_name("XAGUSD") == "SILVER.i#"


def test_failed_spec_lookup_is_cached_for_a_minute(monkeypatch):
    c = mc.MT5Client(mode="demo", auto_init=False)
    c.is_connected = True
    c.symbol_alias_cache["XAGUSD"] = "SILVER.i#"
    asked = []
    fake = SimpleNamespace(symbol_info=lambda name: asked.append(name) or None)
    monkeypatch.setattr(mc, "MT5_AVAILABLE", True)
    monkeypatch.setattr(mc, "mt5", fake)
    spec = c.get_symbol_trading_spec("XAGUSD")
    assert spec["trade_contract_size"] == 5000.0  # registry fallback
    c.get_symbol_trading_spec("XAGUSD")
    assert asked == ["SILVER.i#"]                 # second call served from the 60 s negative cache
    c._symbol_spec_cache["SILVER.i#"] = (time.time() - 3601.0, {})
    c.get_symbol_trading_spec("XAGUSD")
    assert asked == ["SILVER.i#", "SILVER.i#"]    # retried once it expires
