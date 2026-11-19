"""Alert rules: each type fires on injected real-shaped inputs, once per crossing, re-arming on recross."""
import json
import time
from datetime import datetime

import pytest

from jarvis.markets import alerts
from jarvis.markets.data import store
from jarvis.markets.data.nse import IST

PROV = {"source": "test-fixture", "kind": "live", "as_of": 1.0}


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "_path", lambda: str(tmp_path / "m.db"))
    alerts._RECENT.clear()


class Inputs:
    """Injected inputs with the same shapes LiveInputs returns."""

    def __init__(self, **kw):
        self.q = kw.get("quote")
        self.an = kw.get("an")
        self.iv = kw.get("iv", [])
        self.fii = kw.get("fii")
        self.spurts = kw.get("spurts")
        self.ledger = kw.get("ledger", [])
        self.inst_data = kw.get("inst", {})

    def quote(self, s, m):
        return self.q

    def analytics(self, s):
        return self.an

    def iv_points(self, s, since):
        return self.iv

    def fii_rows(self):
        return self.fii

    def oi_spurts(self):
        return self.spurts

    def ledger_rows(self):
        return self.ledger

    def inst(self, slug, query=None):
        return self.inst_data.get(slug)


def an(spot, **kw):
    d = {"symbol": "NIFTY", "spot": spot, "forward": spot, "expiry": "27-Nov-2026", "days_to_expiry": 5.0, "max_pain": 24000.0,
         "atm_iv": 12.0, "pcr": {"oi": 1.0}, "walls": {"resistance": [{"strike": 24500.0, "oi": 9}], "support": [{"strike": 23500.0, "oi": 8}]},
         "prov": PROV}
    d.update(kw)
    return d


def run(inp):
    return alerts.evaluate_all(inp)


def test_level_cross_fires_once_and_rearms():
    alerts.create({"type": "level_cross", "symbol": "nifty", "level": 24000, "direction": "above"})
    q = lambda p: {"price": p, "prov": PROV}
    assert run(Inputs(quote=q(23900))) == []          # first observation only sets the side
    fired = run(Inputs(quote=q(24010)))
    assert len(fired) == 1 and fired[0]["value"]["price"] == 24010 and fired[0]["prov"] == PROV
    assert run(Inputs(quote=q(24050))) == []          # still above: no duplicate
    assert run(Inputs(quote=q(23950))) == []          # recross down re-arms
    assert len(run(Inputs(quote=q(24020)))) == 1      # fires again
    assert len(alerts.fired()) == 2


def test_unavailable_data_never_fires():
    alerts.create({"type": "level_cross", "symbol": "NIFTY", "level": 1, "direction": "above"})
    assert run(Inputs(quote=None)) == [] and run(Inputs(quote=None)) == []


def test_oi_wall_cross():
    alerts.create({"type": "oi_wall_cross", "symbol": "NIFTY", "side": "call", "nth": 1})
    assert run(Inputs(an=an(24400))) == []
    f = run(Inputs(an=an(24510)))
    assert f and f[0]["value"]["wall_strike"] == 24500.0


def test_max_pain_distance_edge():
    alerts.create({"type": "max_pain_distance", "symbol": "NIFTY", "pct": 0.5})
    assert len(run(Inputs(an=an(24050)))) == 1        # 0.21% away → fires
    assert run(Inputs(an=an(24060))) == []            # still inside → no repeat
    assert run(Inputs(an=an(24500))) == []            # outside → re-arm
    assert len(run(Inputs(an=an(24010)))) == 1


def test_expiry_pin_only_on_expiry_day():
    alerts.create({"type": "expiry_pin", "symbol": "NIFTY", "pct": 0.5})
    assert run(Inputs(an=an(24010))) == []            # 5 days to expiry
    today = datetime.now(IST).strftime("%d-%b-%Y")
    assert len(run(Inputs(an=an(24010, expiry=today, days_to_expiry=0.2)))) == 1


def test_iv_change_uses_recorded_history():
    alerts.create({"type": "iv_change", "symbol": "NIFTY", "points": 2, "window_min": 30})
    assert run(Inputs(an=an(24000, atm_iv=13.0), iv=[])) == []              # no history yet: skip
    f = run(Inputs(an=an(24000, atm_iv=14.5), iv=[(time.time() - 1500, 12.0)]))
    assert f and f[0]["value"]["change_pts"] == 2.5


def test_pcr_cross():
    alerts.create({"type": "pcr_cross", "symbol": "NIFTY", "threshold": 1.2, "direction": "above"})
    assert run(Inputs(an=an(24000, pcr={"oi": 1.1}))) == []
    assert len(run(Inputs(an=an(24000, pcr={"oi": 1.25})))) == 1


def test_fii_cash_flip_and_participant_flip():
    alerts.create({"type": "fii_flip", "category": "FII"})
    alerts.create({"type": "fii_flip", "category": "FII", "participant": True})
    fii = lambda n: {"rows": [{"category": "FII/FPI", "date": "17-Nov-2026", "net_cr": n}], "prov": PROV}
    # Shape of the real /api/markets/inst/participants payload.
    part = lambda l, s: {"participants": {"latest": {"participants": {"FII": {"net_idx_fut": l - s}}}, "prov": PROV}}
    assert run(Inputs(fii=fii(-500), inst=part(10, 20))) == []
    f = run(Inputs(fii=fii(800), inst=part(30, 20)))
    assert {a["type"] for a in f} == {"fii_flip"} and len(f) == 2
    assert run(Inputs(fii=fii(900), inst=part(40, 20))) == []


def test_futures_buildup_change():
    alerts.create({"type": "futures_buildup_change", "symbol": "RELIANCE"})
    sp = lambda oi: {"rows": [{"symbol": "RELIANCE", "changeInOI": oi}], "prov": PROV}
    q = lambda c: {"price": 1300.0, "change_pct": c, "prov": PROV}
    assert run(Inputs(spurts=sp(100), quote=q(1.0))) == []          # long_buildup recorded
    f = run(Inputs(spurts=sp(100), quote=q(-1.0)))
    assert f and f[0]["value"]["class"] == "short_buildup" and f[0]["value"]["previous"] == "long_buildup"


def test_ledger_event_and_new_recommendation():
    alerts.create({"type": "ledger_event"})
    alerts.create({"type": "new_recommendation", "symbol": "ANY"})
    row = lambda i, st: {"id": i, "ts": 1, "symbol": "NIFTY", "strategy": "bull_call", "expiry": "27-Nov-2026", "status": st,
                         "exit_reason": "target" if st == "CLOSED" else None, "pnl_per_lot": 500.0 if st == "CLOSED" else None, "closed_ts": None}
    assert run(Inputs(ledger=[row("a", "OPEN")])) == []              # baseline
    f = run(Inputs(ledger=[row("a", "CLOSED"), row("b", "OPEN")]))
    assert sorted(a["type"] for a in f) == ["ledger_event", "new_recommendation"]
    assert run(Inputs(ledger=[row("a", "CLOSED"), row("b", "OPEN")])) == []


def test_event_upcoming():
    alerts.create({"type": "event_upcoming", "symbol": "INFY", "days": 3})
    d = datetime.now(IST).strftime("%d-%b-%Y")
    ev = {"events": {"rows": [{"symbol": "INFY", "date": d, "purpose": "Financial Results"}], "prov": PROV}}
    assert len(run(Inputs(inst=ev))) == 1
    assert run(Inputs(inst=ev)) == []
    assert run(Inputs(inst={})) == []                                # data absent: state unchanged, no fire


def test_validation_and_crud():
    with pytest.raises(ValueError):
        alerts.validate_rule({"type": "level_cross", "symbol": "NIFTY"})
    with pytest.raises(ValueError):
        alerts.validate_rule({"type": "nope"})
    r = alerts.create({"type": "pcr_cross", "symbol": "NIFTY", "threshold": "1.3", "direction": "BELOW"})
    assert r["threshold"] == 1.3 and r["direction"] == "below"
    assert [x["id"] for x in alerts.list_rules()] == [r["id"]]
    assert alerts.delete(r["id"]) and alerts.list_rules() == []


def test_ack_and_sse_event_format():
    alerts.create({"type": "pcr_cross", "symbol": "NIFTY", "threshold": 1.2, "direction": "above"})
    run(Inputs(an=an(24000, pcr={"oi": 1.0})))
    a = run(Inputs(an=an(24000, pcr={"oi": 1.3})))[0]
    assert alerts.ack([a["id"]]) == 1 and alerts.fired()[0]["acked"]
    ev = alerts.sse_event(a)
    assert ev.startswith(f"event: alert\nid: alert-{a['id']}\ndata: ") and ev.endswith("\n\n")
    body = json.loads(ev.split("data: ", 1)[1])
    assert body["value"]["pcr_oi"] == 1.3 and body["prov"]["source"] == "test-fixture"
    assert alerts.recent_since(0)[-1]["id"] == a["id"] and alerts.recent_since(a["id"]) == []


def test_last_event_id_resume():
    from jarvis.api.server import _last_alert_id
    assert _last_alert_id("alert-7", alerts) == 7
    assert _last_alert_id("", alerts) == 0
