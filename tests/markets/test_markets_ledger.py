"""Ledger P&L sign conventions for debit and credit trades, on a temp database."""
import json

import pytest

from jarvis.markets import ledger
from jarvis.markets.data import store


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_path", lambda: str(tmp_path / "m.db"))


def _advice(name, legs, net, kind, target, stop):
    key = "close_at_net_debit" if kind == "credit" else "close_at_net_credit"
    return {"status": "RECOMMEND", "symbol": "NIFTY",
            "recommendation": {"name": name, "legs": legs, "edge_per_lot": 100},
            "plan": {"entry": {"net": net, "type": kind}, "target": {key: target}, "stop": {key: stop}},
            "analytics": {"expiry": "30-Dec-2099", "lot_size": 65}}


def _chain(mids):
    return {"strikes": [{"strike": k, "call": {"mid": c}, "put": {"mid": p}} for k, (c, p) in mids.items()]}


def test_debit_trade_hits_target(tmp_db, monkeypatch):
    legs = [{"strike": 100.0, "type": "CE", "side": "BUY", "lots": 1, "price": 10.0}]
    rid = ledger.record(_advice("Long call", legs, 10.0, "debit", 16.0, 5.0))
    assert rid and ledger.record(_advice("Long call", legs, 10.0, "debit", 16.0, 5.0)) == rid  # recorded once
    monkeypatch.setattr("jarvis.markets.data.feeds.chain", lambda s, e=None: object())
    monkeypatch.setattr("jarvis.markets.options.chain_analytics.analyse", lambda c: _chain({100.0: (17.0, 1.0)}))
    assert ledger.score_open() == 1
    s = ledger.summary()
    assert s["closed"] == 1 and s["items"][0]["pnl_per_lot"] == pytest.approx((17 - 10) * 65)


def test_credit_trade_hits_stop(tmp_db, monkeypatch):
    legs = [{"strike": 100.0, "type": "PE", "side": "SELL", "lots": 1, "price": 8.0},
            {"strike": 90.0, "type": "PE", "side": "BUY", "lots": 1, "price": 3.0}]
    ledger.record(_advice("Bull put credit spread", legs, 5.0, "credit", 2.5, 10.0))
    monkeypatch.setattr("jarvis.markets.data.feeds.chain", lambda s, e=None: object())
    # Spread now costs 14 - 3 = 11 to buy back (>= stop 10): loss = 5 - 11 = -6 per unit.
    monkeypatch.setattr("jarvis.markets.options.chain_analytics.analyse", lambda c: _chain({100.0: (0, 14.0), 90.0: (0, 3.0)}))
    assert ledger.score_open() == 1
    item = ledger.summary()["items"][0]
    assert item["exit_reason"] == "stop" and item["pnl_per_lot"] == pytest.approx(-6 * 65)
