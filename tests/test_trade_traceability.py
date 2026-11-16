"""Phase 5 (2026-11-16): account-tagged journal, exit reasons, SL history, excursions,
decision journal and server-side analytics."""
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from jarvis.data.database import SQLiteTradeDB


@pytest.fixture
def db(tmp_path):
    d = SQLiteTradeDB(db_path=str(tmp_path / "j.db"))
    yield d
    d.close()


def _row(db, ticket):
    cur = db._get_conn().execute("SELECT * FROM executed_trades WHERE ticket = ?", (ticket,))
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, cur.fetchone()))


def test_entry_context_is_recorded_and_junk_becomes_null(db):
    db.log_trade(ticket=1, position_id=1, symbol="EURUSD", action="BUY", entry=1.1, sl=1.098, tp=1.104,
                 volume=0.01, score=80, regime="TREND_BULL", ev=1.0, origin="broker", execution_mode="demo",
                 account_login=101059540, server="XMGlobal-MT5 5", strategy="TREND_PULLBACK",
                 trade_style="DAY_TRADING", planned_rr=2.0)
    r = _row(db, 1)
    assert (r["account_login"], r["server"], r["strategy"], r["trade_style"], r["planned_rr"]) == (
        101059540, "XMGlobal-MT5 5", "TREND_PULLBACK", "DAY_TRADING", 2.0)
    # A mock or enum where a value belongs must not lose the whole row.
    db.log_trade(ticket=2, symbol="EURUSD", action="BUY", entry=1.1, sl=1.098, tp=1.104, volume=0.01,
                 score=80, regime="X", ev=1.0, account_login=MagicMock(), trade_style=MagicMock())
    assert _row(db, 2)["account_login"] is None


def test_engine_exit_reason_wins_over_the_broker_label_and_excursions_persist(db):
    db.log_trade(ticket=7, position_id=7, symbol="EURUSD", action="BUY", entry=1.1, sl=1.098, tp=1.104,
                 volume=0.01, score=80, regime="X", ev=1.0, origin="broker")
    db.set_exit_reason(7, "TIME_STOP")
    db.set_exit_reason(7, "ENGINE")          # first writer wins
    db.record_excursions(7, 0.0012, 0.0004)
    r = _row(db, 7)
    assert r["exit_reason"] == "TIME_STOP" and (r["mfe"], r["mae"]) == (0.0012, 0.0004)


def test_sl_history_is_kept(db):
    db.log_sl_event(9, 1.098, 1.0995, 1.104, 1.104, "BE_LOCK")
    db.log_sl_event(9, 1.0995, 1.1010, 1.104, 1.104, "TRAIL")
    rows = db._get_conn().execute("SELECT old_sl, new_sl, reason FROM sl_events WHERE ticket=9 ORDER BY id").fetchall()
    assert rows == [(1.098, 1.0995, "BE_LOCK"), (1.0995, 1.1010, "TRAIL")]


def test_sync_tags_the_account_costs_and_broker_exit_reason(db):
    db.log_trade(ticket=555, position_id=555, symbol="EURUSD", action="BUY", entry=1.1, sl=1.098, tp=1.104,
                 volume=0.10, score=80, regime="X", ev=1.0, origin="broker")
    entry = SimpleNamespace(symbol="EURUSD", position_id=555, entry=0, type=0, price=1.1, volume=0.1, profit=0.0,
                            swap=0.0, commission=-0.35, time=1792501000, magic=888999, comment="", reason=3)
    exit_ = SimpleNamespace(symbol="EURUSD", position_id=555, entry=1, type=1, price=1.104, volume=0.1, profit=40.0,
                            swap=-0.10, commission=-0.35, time=1792505000, magic=888999, comment="[tp 1.104]", reason=5)
    fake = SimpleNamespace(history_deals_get=lambda *a, **k: [entry, exit_], history_orders_get=lambda *a, **k: [],
                           account_info=lambda: SimpleNamespace(login=101059540, server="XMGlobal-MT5 5"))
    with patch("jarvis.data.database.broker_utc_offset", return_value=0):
        db._last_mt5_sync = 0.0
        db.sync_mt5_history(days=1, mt5_module=fake)
    r = _row(db, 555)
    assert r["account_login"] == 101059540 and r["exit_reason"] == "TAKE_PROFIT"
    assert r["commission"] == pytest.approx(-0.70) and r["swap"] == pytest.approx(-0.10)


def test_decision_journal_writes_changes_only():
    from tests.conftest import _DECISION_JOURNAL_DIR
    from jarvis.observability import decision_journal
    d = SimpleNamespace(decision="WAIT", bias="SELL", strategy="TREND_PULLBACK", ai_score=60.0,
                        model_confidence=0.55, risk_reward_ratio=2.5, expected_value=0.3, entry_price=1.0,
                        stop_loss=1.01, take_profit=0.975, waiting_reasons=["RISK: cap"],
                        quality_gate=SimpleNamespace(failing_reasons=["Trend Not Exhausted"]))
    res = {"symbol": "JTEST", "trade_style": "DAY_TRADING", "decision": d, "authorized": False,
           "auth_reason": "cap", "execution": None}
    for _ in range(3):
        decision_journal.record(res)
    d.decision = "EXECUTE"
    decision_journal.record(res)
    lines = []
    for f in os.listdir(_DECISION_JOURNAL_DIR):
        lines += [json.loads(x) for x in open(os.path.join(_DECISION_JOURNAL_DIR, f)) if '"JTEST"' in x]
    assert [x["decision"] for x in lines] == ["WAIT", "EXECUTE"]
    assert lines[0]["failing"] == ["Trend Not Exhausted"] and lines[0]["waiting"] == ["RISK: cap"]


def test_analytics_groups_closed_broker_rows_with_r(db):
    from jarvis.analytics.performance import performance_report
    for t, pnl, strat in ((1, 4.0, "A"), (2, -2.0, "A"), (3, -2.0, "B")):
        db.log_trade(ticket=t, position_id=t, symbol="EURUSD", action="BUY", entry=1.1, sl=1.098, tp=1.104,
                     volume=0.01, score=80, regime="X", ev=1.0, origin="broker", strategy=strat)
        db.record_trade_exit(position_id=t, exit_price=1.1, realized_pnl=pnl, closed_at="2026-11-16T00:00:00+00:00")
    rep = performance_report(db, group_by="strategy")
    assert rep["closed_trades"] == 3
    a = rep["groups"]["A"]
    assert a["total_trades"] == 2 and a["avg_r"] == pytest.approx(0.5)   # $2 risk: +2R and -1R
    assert rep["groups"]["B"]["max_consecutive_losses"] == 1
