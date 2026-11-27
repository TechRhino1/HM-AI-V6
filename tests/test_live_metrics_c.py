"""PR C (2026-11-27): one net R for every live reader, execution quality per trade, drift per
symbol x style against engine evidence, and reduce-only unvalidated adjusters."""
import sqlite3
from types import SimpleNamespace

import pytest

from jarvis.analytics.performance import net_r_multiple, performance_report


# ── one net R ────────────────────────────────────────────────────────────────
def test_net_r_counts_every_deal_of_a_partially_closed_position():
    # Gold 0.02 lot, $10 stop -> $20 risk. Half closed at +1R (+$10), rest trailed out at +0.3R
    # (+$3), $0.40 commission: the close P&L is the sum over the deals, +$12.60.
    assert net_r_multiple("XAUUSD", 4150.0, 4140.0, 0.02, 12.60) == pytest.approx(0.63)
    # The price R from the final exit alone (+0.3R) is what the old readers used.
    assert net_r_multiple("XAUUSD", 4150.0, 4140.0, 0.02, None) is None
    assert net_r_multiple("XAUUSD", 4150.0, 0.0, 0.02, 5.0) is None        # no stop, no R
    assert net_r_multiple("XAUUSD", 4150.0, 4140.0, 0.0, 5.0) is None      # no size, no R


def _ledger(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE executed_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket INTEGER, symbol TEXT, "
                "action TEXT, entry_price REAL, exit_price REAL, sl REAL, tp REAL, volume REAL, realized_pnl REAL, "
                "features_json TEXT, closed_at TEXT, execution_mode TEXT, regime TEXT, trade_style TEXT, "
                "origin TEXT, strategy TEXT, exit_reason TEXT, account_login INTEGER)")
    con.executemany("INSERT INTO executed_trades (ticket, symbol, action, entry_price, exit_price, sl, tp, volume, "
                    "realized_pnl, features_json, closed_at, execution_mode, regime, trade_style, origin) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def test_quarantine_ledger_reads_net_r_not_the_final_exit(tmp_path):
    from jarvis.execution import strategy_quarantine as sq
    db = str(tmp_path / "h.db")
    # Final exit at entry (price R 0) but the position banked +$10 on a partial: net +0.5R.
    rows = [(i, "XAUUSD", "BUY", 4150.0, 4150.0, 4140.0, 4170.0, 0.02, 10.0, '{"strategy": "TREND_PULLBACK"}',
             f"2026-11-2{i % 10}T10:00:00+00:00", "demo", "TREND_BULL", "DAY_TRADING", "broker") for i in range(25)]
    _ledger(db, rows)
    sq.clear_cache()
    stats, _ = sq._load_full(db, "demo")
    n, exp_r = stats[("XAUUSD", "TREND_PULLBACK")]
    assert n == 25 and exp_r == pytest.approx(0.5)


def test_auto_counts_only_trades_from_this_engines_mode(tmp_path, monkeypatch):
    from jarvis.config import paths
    from jarvis.intelligence.auto_style import AutoStyleSelector
    db = str(tmp_path / "jarvis_history.db")
    _ledger(db, [(1, "XAUUSD", "BUY", 4150.0, 4160.0, 4140.0, 4170.0, 0.01, 10.0, "{}", "2026-11-26T10:00:00Z", "demo", "X", "SCALP", "broker"),
                 (2, "XAUUSD", "BUY", 4150.0, 4140.0, 4140.0, 4170.0, 0.01, -10.0, "{}", "2026-11-26T11:00:00Z", "paper", "X", "SCALP", "paper")])
    monkeypatch.setattr(paths, "resolve_db_path", lambda name: db)
    mem = SimpleNamespace(fetch_all_trades=lambda: [
        {"ticket": 1, "symbol": "XAUUSD", "entry_price": 4150.0, "exit_price": 4160.0, "sl": 4140.0, "lots": 0.01,
         "pnl": 10.0, "trade_type": "BUY", "reasoning": '{"trade_style": "SCALP"}', "strategy": "X"},
        {"ticket": 2, "symbol": "XAUUSD", "entry_price": 4150.0, "exit_price": 4140.0, "sl": 4140.0, "lots": 0.01,
         "pnl": -10.0, "trade_type": "BUY", "reasoning": '{"trade_style": "SCALP"}', "strategy": "X"},
        {"ticket": 3, "symbol": "XAUUSD", "entry_price": 4150.0, "exit_price": 4140.0, "sl": 4140.0, "lots": 0.01,
         "pnl": -10.0, "trade_type": "BUY", "reasoning": '{"trade_style": "SCALP"}', "strategy": "X"}])
    rows = AutoStyleSelector(mem, prior=object(), execution_mode="demo")._load()
    assert [r["ticket"] for r in rows] == [1]          # paper and unjournalled trades left out
    assert len(AutoStyleSelector(mem, prior=object())._load()) == 3   # no mode given: unchanged behaviour


# ── drift per symbol x style ─────────────────────────────────────────────────
def test_drift_judges_each_cell_against_its_engine_evidence():
    from jarvis.observability import system_monitor as sm
    live = {"XAUUSD|SCALP": [-0.3] * 25, "ETHUSD|DAY_TRADING": [0.25, 0.2] * 13}
    bench = {"XAUUSD|SCALP": {"expectancy_r": 0.01, "source": "engine_holdout"},
             "ETHUSD|DAY_TRADING": {"expectancy_r": 0.232, "source": "engine_holdout"}}
    out = sm.check_live_drift(live, bench, -0.15)
    cells = out["symbols"]
    assert cells["XAUUSD|SCALP"]["status"] == sm.CRITICAL and cells["XAUUSD|SCALP"]["benchmark"] == "engine_holdout"
    assert cells["ETHUSD|DAY_TRADING"]["status"] == sm.OK
    few = sm.check_live_drift({"XAUUSD|SCALP": [-1.0] * 5}, bench, -0.15)
    assert few["status"] == sm.OK and "under 20 live closes" in few["detail"]


# ── execution quality ────────────────────────────────────────────────────────
def test_execution_quality_is_journalled_and_reported(tmp_path):
    from jarvis.data.database import SQLiteTradeDB
    db = SQLiteTradeDB(db_path=str(tmp_path / "h.db"))
    cols = {r[1] for r in db._get_conn().execute("PRAGMA table_info(executed_trades)")}
    assert {"requested_price", "fill_price", "spread_at_fill", "fill_latency_ms"} <= cols
    db.log_trade(ticket=1, symbol="XAUUSD", action="BUY", entry=4150.4, sl=4140.0, tp=4170.0, volume=0.01,
                 score=70, regime="X", ev=0.1, origin="broker", execution_mode="demo", trade_style="SCALP",
                 requested_price=4150.0, fill_price=4150.4, spread_at_fill=2.0, fill_latency_ms=180.0)
    db.record_trade_exit(ticket=1, exit_price=4160.0, realized_pnl=9.6, closed_at="2026-11-27T10:00:00+00:00")
    g = performance_report(db, group_by="symbol_style")["groups"]["XAUUSD|SCALP"]
    assert g["execution"]["measured_fills"] == 1
    assert g["execution"]["avg_slippage_r"] == pytest.approx(0.4 / 10.4, rel=1e-3)   # 0.40 worse over a 10.40 stop
    assert g["execution"]["avg_fill_latency_ms"] == 180.0 and g["avg_r"] == pytest.approx(9.6 / 10.4, rel=1e-3)


def test_execution_quality_asks_the_right_price():
    from jarvis.execution.execution_engine import ExecutionEngine
    eng = object.__new__(ExecutionEngine)
    eng.mt5_client = SimpleNamespace(get_tick=lambda s: {"bid": 4150.0, "ask": 4150.2, "age_s": 0.1})
    buy = SimpleNamespace(bias="BUY", entry_price=4148.0, symbol="XAUUSD")
    timer = SimpleNamespace(elapsed_ms=210.0)
    q = eng._execution_quality(buy, {"price": 4150.3}, False, 4150.0, 4150.2, timer)
    assert q["requested_price"] == 4150.2 and q["fill_price"] == 4150.3 and q["fill_latency_ms"] == 210.0
    assert q["spread_at_fill"] == pytest.approx(2.0)                     # 0.20 / 0.1 gold pip (registry units, like spread_pips)
    assert eng._execution_quality(buy, {"price": 4148.0}, True, 4150.0, 4150.2, timer)["requested_price"] == 4148.0
    sell = SimpleNamespace(bias="SELL", entry_price=4148.0, symbol="XAUUSD")
    assert eng._execution_quality(sell, {}, False, 4150.0, 4150.2, timer)["requested_price"] == 4150.0
    eng.mt5_client = SimpleNamespace()                                    # no broker: nothing raised
    assert eng._execution_quality(buy, None, False, 4150.0, 4150.2, timer)["spread_at_fill"] is None


# ── reduce-only adjusters ────────────────────────────────────────────────────
def test_self_learning_can_cut_but_not_raise(tmp_path, monkeypatch):
    from jarvis.config import runtime
    from jarvis.intelligence.self_learning import SelfLearningEngine
    monkeypatch.setattr(runtime, "is_offline", lambda: False)
    db = str(tmp_path / "h.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE executed_trades (id INTEGER PRIMARY KEY, symbol TEXT, regime TEXT, expected_value REAL, "
                "realized_pnl REAL, closed_at TEXT)")
    con.executemany("INSERT INTO executed_trades (symbol, regime, expected_value, realized_pnl, closed_at) VALUES (?,?,?,?,?)",
                    [("XAUUSD", "TREND_BULL", 2.0, 5.0, "2026-11-27")] * 30)   # a great record
    con.commit()
    con.close()
    sl = SelfLearningEngine(db_path=db)
    assert sl.get_regime_multiplier("TREND_BULL") <= 1.0
    pat = sl.get_pattern_win_rate_and_ev("XAUUSD", "TREND_BULL")
    assert pat["conviction_multiplier"] <= 1.0 and pat["empirical_edge"] is False


def test_soft_gates_block_by_default_and_sizing_never_boosts():
    from jarvis.execution import strategy_quarantine as sq
    from jarvis.intelligence.gate_policy import AdaptiveGatePolicy
    assert AdaptiveGatePolicy(max_soft_fail=3, min_recent_win_rate=0.45).decide(
        ["Trend Not Exhausted: stretched"], recent_win_rate=0.9)[0] == "BLOCK"
    assert sq.SIZING_REDUCE_ONLY is True and min(1.0, sq.SIZE_MULT_FOR_POSITIVE) == 1.0
