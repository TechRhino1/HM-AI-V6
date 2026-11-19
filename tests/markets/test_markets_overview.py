"""Overview feeds (jarvis/markets/overview.py): timeline merge/order, decision-journal reading, the changes
fact sheet, the AI summary's grounding fallback and batched sparklines — all on recorded fixtures."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.ai import tools
from jarvis.ai.providers.base import ProviderError
from jarvis.markets import overview as O
from jarvis.markets.api import _HANDLERS, require_provenance

FX = Path(__file__).parent / "fixtures"
SPARK = json.loads((FX / "yahoo_spark_in.json").read_text(encoding="utf-8"))
T0 = 1794960000.0  # 2026-11-17 18:40 UTC = 2026-11-18 00:10 IST

TRADES = [
    {"symbol": "USDJPY", "action": "BUY", "volume": 0.01, "entry_price": 159.26, "sl": 158.2476, "tp": 0.0,
     "timestamp": "2026-11-18T10:00:17+00:00", "closed_at": None, "realized_pnl": None, "execution_mode": "demo", "strategy": "TREND_TSMOM"},
    {"symbol": "XAUUSD", "action": "SELL", "volume": 0.01, "entry_price": 3771.87, "sl": 3778.11, "tp": 3744.71,
     "timestamp": "2026-11-18T08:01:46+00:00", "closed_at": "2026-11-18T08:47:23+00:00", "realized_pnl": -0.79,
     "exit_price": 3772.66, "exit_reason": "SCALP_STAGNATION", "execution_mode": "demo"},
    {"symbol": "EURUSD", "action": "BUY", "volume": 0.02, "timestamp": "2026-11-16T08:00:00+00:00",
     "closed_at": "2026-11-16T09:00:00+00:00", "realized_pnl": 3.0},
]
FIRED = [{"id": 4, "ts": O.epoch("2026-11-18T09:00:00Z"), "type": "max_pain_distance",
          "message": "MIDCPNIFTY spot is 0.48% from max pain 14000", "prov": {"source": "nse", "kind": "live", "as_of": None}}]
BRIEFS = [{"kind": "pre", "ts": O.epoch("2026-11-18T03:20:00Z"), "provider": "template", "text": "Headline: NIFTY flat\nmore"}]
LEDGER = [{"ts": O.epoch("2026-11-18T07:00:00Z"), "symbol": "FINNIFTY", "strategy": "Long put", "expiry": "25-Nov-2026",
           "edge_per_lot": 412.5, "status": "OPEN", "closed_ts": None, "pnl_per_lot": None, "exit_reason": None}]


def jrow(ts, sym="USDJPY", style="SWING", decision="NO_TRADE", failing=(), **kw):
    return {"symbol": sym, "style": style, "decision": decision, "failing": list(failing), "ts": ts, **kw}


JOURNAL = [
    jrow("2026-11-17T18:00:00Z", failing=["Devil Adversarial Guard"]),                       # baseline before the day
    jrow("2026-11-18T05:00:00Z", decision="WAIT", failing=[]),                                 # change → event
    jrow("2026-11-18T05:05:00Z", decision="NO_TRADE", failing=["AI Multi-Score Gate"]),       # within 30 min → folded
    jrow("2026-11-18T06:00:00Z", decision="WAIT", failing=[]),                                 # event, mentions the fold
    {"kind": "dispatch", "symbol": "EURUSD", "style": "DAY_TRADING", "bias": "SELL", "status": "VETOED",
     "vetoes": ["TIMEFRAME_CONFLICT: SCALP engine resolved BUY 109s ago"], "ts": "2026-11-18T06:10:00Z"},
    {"kind": "dispatch", "symbol": "EURUSD", "style": "DAY_TRADING", "bias": "SELL", "status": "VETOED",
     "vetoes": ["TIMEFRAME_CONFLICT: SCALP engine resolved BUY 400s ago"], "ts": "2026-11-18T07:10:00Z"},
    {"kind": "router", "component": "FT_TR_USDJPY_H4_T3", "action": "ENTER", "reason": "BUY stop 3.0xATR", "ts": "2026-11-18T10:00:17Z"},
    {"kind": "router", "component": "FT_TR_USDJPY_H4_T6", "action": "SKIP", "reason": "at cap", "ts": "2026-11-18T10:00:18Z"},
]


@pytest.fixture
def journal(tmp_path, monkeypatch):
    d = tmp_path / "decisions"
    d.mkdir()
    monkeypatch.setattr(O, "_journal_dir", lambda: str(d))
    O._JCACHE.clear()
    by_day = {}
    for r in JOURNAL:
        by_day.setdefault(r["ts"][:10].replace("-", ""), []).append(r)
    for day, rows in by_day.items():
        (d / f"decisions_{day}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    yield d
    O._JCACHE.clear()


@pytest.fixture
def sources(monkeypatch, journal):
    monkeypatch.setattr(O, "_trades", lambda days=2: TRADES)
    monkeypatch.setattr(O, "_alerts", lambda since: [a for a in FIRED if a["ts"] >= since])
    monkeypatch.setattr(O, "_briefs", lambda since: [b for b in BRIEFS if b["ts"] >= since])
    monkeypatch.setattr(O, "_ledger", lambda since: LEDGER)
    monkeypatch.setattr(O, "day_start", lambda now=None: T0)
    monkeypatch.setattr(O.time, "time", lambda: O.epoch("2026-11-18T12:00:00Z"))


def test_day_start_is_ist_midnight():
    ts = O.epoch("2026-11-18T12:00:00Z")
    assert O.day_start(ts) == O.epoch("2026-11-17T18:30:00Z")
    assert O.epoch(1794960000000) == 1794960000.0 and O.epoch("garbage") is None


def test_journal_reader_is_incremental_and_skips_partial_lines(journal):
    p = journal / "decisions_20261118.jsonl"
    n = len(O._read_journal(str(p)))
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(jrow("2026-11-18T11:00:00Z")) + "\n" + '{"symbol": "half')
    assert len(O._read_journal(str(p))) == n + 1
    with open(p, "a", encoding="utf-8") as f:
        f.write('", "ts": "2026-11-18T11:01:00Z"}\n')
    rows = O._read_journal(str(p))
    assert len(rows) == n + 2 and rows[-1]["symbol"] == "half"


def test_signal_events_throttle_gates_dispatch_router(journal):
    ev = O.signal_events(T0, O.journal_rows(T0, now=O.epoch("2026-11-18T12:00:00Z")))
    titles = [e["title"] for e in ev]
    verdict = [e for e in ev if "SWING" in e["title"]]
    assert [e["title"] for e in verdict] == ["USDJPY SWING: NO_TRADE → WAIT", "USDJPY SWING: NO_TRADE → WAIT"]
    assert "now passing: Devil Adversarial Guard" in verdict[0]["detail"]
    assert "1 more change(s) folded" in verdict[1]["detail"]
    # dispatch: second veto has the same code (only the seconds differ) → no second event
    assert sum(t.startswith("Dispatch VETOED") for t in titles) == 1
    router = [e for e in ev if e["title"].startswith("Trend router")]
    assert len(router) == 1 and router[0]["symbol"] == "USDJPY"
    assert all(e["link"] == "signals" and e["prov"]["kind"] == "live" for e in ev)


def test_gate_changes_compare_before_and_after(journal):
    gc = O.gate_changes(O.epoch("2026-11-18T05:02:00Z"), O.journal_rows(T0, now=O.epoch("2026-11-18T12:00:00Z")))
    assert gc == []  # WAIT with no failing gates both just before and now
    gc = O.gate_changes(T0, O.journal_rows(T0, now=O.epoch("2026-11-18T12:00:00Z")))
    assert gc == [{"symbol": "USDJPY", "style": "SWING", "from": "NO_TRADE", "to": "WAIT", "now_failing": [], "now_passing": ["Devil Adversarial Guard"]}]


def test_timeline_merges_sources_newest_first(sources, monkeypatch):
    out = O.timeline()
    require_provenance(out)
    ts = [e["ts"] for e in out["events"]]
    assert ts == sorted(ts, reverse=True)
    kinds = {e["kind"] for e in out["events"]}
    assert kinds == {"trade", "alert", "brief", "recommendation", "signal"}
    titles = [e["title"] for e in out["events"]]
    assert "Closed SELL 0.01 XAUUSD -0.79" in titles and "Opened BUY 0.01 USDJPY" in titles
    assert not any("EURUSD" in t and "BUY 0.02" in t for t in titles)  # two days old: outside today
    assert {e["link"] for e in out["events"] if e["kind"] == "alert"} == {"alerts"}
    assert out["day_basis"].startswith("IST") and all(s["ok"] for s in out["sources"].values())
    # a failing source is reported, the rest still served
    monkeypatch.setattr(O, "_alerts", lambda since: (_ for _ in ()).throw(RuntimeError("db locked")))
    out = O.timeline(limit=3)
    assert out["sources"]["alerts"]["ok"] is False and "db locked" in out["sources"]["alerts"]["error"]
    assert len(out["events"]) == 3 and out["total"] > 3


def test_changes_fact_sheet(sources, monkeypatch):
    monkeypatch.setattr(O, "_account", lambda: {"account": {"equity": 1012.5, "profit": -3.25, "currency": "USD"}, "positions": [{}, {}], "ts": "2026-11-18T12:00:00"})
    monkeypatch.setattr(O, "market_moves", lambda since: [{"name": "NIFTY 50", "change_pct": 0.42, "basis": "since previous close", "prov": {"source": "yahoo", "kind": "close", "as_of": 1}}])
    out = O.changes(T0, equity_then=1000.0)
    require_provenance(out)
    f = out["facts"]
    assert f["account"]["equity_change"] == 12.5 and f["account"]["open_positions_now"] == 2
    assert f["trades"]["opened_count"] == 2 and f["trades"]["closed_count"] == 1 and f["trades"]["realised_pnl"] == -0.79
    assert f["alerts"]["fired_count"] == 1
    assert f["engine"]["verdict_changes_count"] == 1 and f["engine"]["dispatch_vetoed"] == 2
    assert f["engine"]["router_actions"][0]["action"] == "ENTER"
    assert f["recommendations"]["new"][0]["edge_per_lot"] == 412.5 and f["briefs"]["written"][0]["kind"] == "pre"
    bullets = O.template(f)
    assert 3 <= len(bullets) <= 5 and "+12.50 since your last visit" in bullets[0]
    from jarvis.markets.levels import grounded
    assert grounded(" ".join(bullets), f)


def test_changes_reports_unavailable_sources(sources, monkeypatch):
    monkeypatch.setattr(O, "_account", lambda: {"account": {}, "positions": [], "ts": None})
    monkeypatch.setattr(O, "_trades", lambda days=2: (_ for _ in ()).throw(RuntimeError("locked")))
    monkeypatch.setattr(O, "market_moves", lambda since: [{"name": "NIFTY 50", "change_pct": None, "prov": {"source": "yahoo", "kind": "unavailable", "as_of": None}}])
    f = O.changes(T0)["facts"]
    assert f["account"]["prov"]["kind"] == "unavailable" and "error" in f["trades"]
    b = O.template(f)
    assert b[0].startswith("Account: unavailable") and "trade journal unavailable" in b[1] and "unavailable: NIFTY 50" in b[4]


class FakeProvider:
    name = "fake"

    def __init__(self, text=None, exc=None):
        self.text, self.exc = text, exc

    def user(self, t):
        return t

    def chat(self, msgs, tools_, system, effort="low"):
        if self.exc:
            raise self.exc
        return SimpleNamespace(text=self.text, stop_reason="end_turn")


@pytest.fixture
def quiet_changes(sources, monkeypatch):
    monkeypatch.setattr(O, "_account", lambda: {"account": {"equity": 1012.5, "profit": -3.25, "currency": "USD"}, "positions": [], "ts": None})
    monkeypatch.setattr(O, "market_moves", lambda since: [])


def test_summary_uses_grounded_ai_answer(quiet_changes):
    ok = "- Equity is 1012.5 USD\n- One alert fired on MIDCPNIFTY\n- USDJPY SWING moved from NO_TRADE to WAIT"
    out = O.summary(T0, provider=FakeProvider(ok))
    assert out["source"] == "fake" and len(out["bullets"]) == 3


def test_summary_falls_back_when_ai_invents_a_number(quiet_changes):
    out = O.summary(T0, provider=FakeProvider("- Equity jumped to 2,345.67\n- NIFTY rallied 3.9%\n- Nothing else"))
    assert out["source"] == "template" and "not in the facts" in out["note"]
    assert out["bullets"] == O.template(out["facts"])


def test_summary_falls_back_when_provider_busy_or_absent(quiet_changes):
    out = O.summary(T0, provider=FakeProvider(exc=ProviderError("503 overloaded")))
    assert out["source"] == "template" and "busy" in out["note"]
    out = O.summary(T0, provider=None)
    assert out["source"] == "template" and "no AI provider" in out["note"]


def test_sparklines_batch_yahoo_in_chunks_of_20(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params["symbols"].split(","))
        return SimpleNamespace(json=lambda: {k: v for k, v in SPARK.items() if k in params["symbols"].split(",")})

    import requests
    from jarvis.markets.data import feeds
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(feeds, "session", lambda m: {"open": False})
    syms = ["TCS", "RELIANCE", "INFY"] + [f"X{i}" for i in range(22)]
    out = O.sparklines(syms, "IN")
    require_provenance(out)
    assert sorted(len(c) for c in calls) == [5, 20]
    tcs = out["series"]["TCS"]
    raw = SPARK["TCS.NS"]
    assert tcs["closes"] == [c for c in raw["close"] if c is not None] and tcs["prov"]["kind"] == "close"
    assert tcs["prev_close"] == float(raw["previousClose"])
    assert "X0" in out["unavailable"] and out["series"]["X0"]["prov"]["kind"] == "unavailable" and out["series"]["X0"]["closes"] == []


def test_sparklines_fx_and_route(monkeypatch):
    xau = json.loads((FX / "mt5_xauusd_h1.json").read_text(encoding="utf-8"))["candles"][-10:]
    monkeypatch.setattr(O, "_fx_spark", lambda s: {"times": [c["time"] for c in xau], "closes": [c["close"] for c in xau], "last": xau[-1]["close"],
                                                   "prov": {"source": "mt5", "kind": "live", "as_of": xau[-1]["time"]}} if s == "XAUUSD" else None)
    from jarvis.markets import levels
    levels._cache.clear()
    out = _HANDLERS["/api/markets/overview/sparklines"]({"symbols": ["XAUUSD,NOPE"], "market": ["FX"]})
    require_provenance(out)
    assert len(out["series"]["XAUUSD"]["closes"]) == 10 and out["unavailable"] == ["NOPE"]
    with pytest.raises(ValueError):
        O.sparklines(["A"], "JP")


def test_move_since_uses_last_close_before_since_or_prev_close():
    s = {"times": [100, 200, 300], "closes": [10.0, 11.0, 12.0], "prev_close": 8.0}
    assert O.move_since(s, 250) == {"from": 11.0, "now": 12.0, "change_pct": 9.09, "basis": "since your last visit"}
    assert O.move_since(s, 50)["basis"] == "since previous close" and O.move_since(s, 50)["change_pct"] == 50.0
    assert O.move_since({"closes": []}, 0) is None


def test_ai_tools_expose_chart_and_overview_routes():
    specs = {t["name"]: t for t in tools.specs()}
    for name in ("chart_levels", "chart_patterns", "chart_signal", "chart_read", "overview_timeline", "overview_changes", "sparklines"):
        assert name in specs and tools.MARKET_TOOLS[name][0] in _HANDLERS
    assert specs["chart_read"]["parameters"]["properties"]["market"]["enum"] == ["FX", "IN", "US"]
    assert specs["chart_read"]["parameters"]["required"] == ["symbol", "market"]
    inst = {n: s for n, s in specs.items() if n.startswith("inst_")}
    assert inst and all("date" not in s["parameters"]["properties"] for s in inst.values())
    assert set(specs["inst_announcements"]["parameters"]["properties"]) == {"symbol", "limit"}
