"""Equities: pure maths on formula-built bars, a recorded real Yahoo spark payload, and the provenance guard."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from jarvis.markets.api import ProvenanceMissing, require_provenance
from jarvis.markets.equities import calc, service

FX = Path(__file__).parent / "fixtures"
DAY = 86400
T0 = 1704067200  # 2024-01-01 UTC


def _bars(n, f=lambda i: 100 + i, rng=2.0):
    """Deterministic test bars by formula: close f(i), high/low ±rng/2."""
    return [{"time": T0 + i * DAY, "open": f(i), "high": f(i) + rng / 2, "low": f(i) - rng / 2, "close": f(i), "volume": 1000}
            for i in range(n)]


def test_sma_and_rsi_extremes():
    up = [b["close"] for b in _bars(60)]
    assert calc.sma(up, 20) == pytest.approx(sum(up[-20:]) / 20)
    assert calc.sma(up[:5], 20) is None
    assert calc.rsi(up) == 100.0                       # only gains
    assert calc.rsi(list(reversed(up))) == pytest.approx(0.0)
    zig = [100 + (1 if i % 2 else -1) for i in range(60)]  # equal gains and losses
    assert calc.rsi(zig) == pytest.approx(50, abs=3)


def test_atr_constant_range_and_vol():
    flat = _bars(40, f=lambda i: 100.0, rng=2.0)
    assert calc.atr(flat) == pytest.approx(2.0)
    assert calc.realised_vol([b["close"] for b in flat]) == 0.0
    g = [100 * math.exp(0.01 * i) for i in range(30)]   # constant log return → zero vol
    assert calc.realised_vol(g) == pytest.approx(0.0, abs=1e-9)


def test_technicals_52w_and_distances():
    b = _bars(300)
    t = calc.technicals(b, price=400.0)
    assert t["high_52w"] == max(x["high"] for x in b[-252:]) and t["low_52w"] == min(x["low"] for x in b[-252:])
    assert t["vs_sma20_pct"] == pytest.approx((400 - t["sma20"]) / t["sma20"] * 100, abs=0.01)
    assert t["bars_used"] == 300


def test_pivots_classic():
    p = calc.pivots({"high": 110.0, "low": 90.0, "close": 100.0})
    assert p == {"P": 100.0, "R1": 110.0, "S1": 90.0, "R2": 120.0, "S2": 80.0, "R3": 130.0, "S3": 70.0}


def test_risk_sizing_calculator():
    r = calc.risk_sizing(equity=100000, risk_pct=1, atr_value=10, atr_mult=2, price=500)
    assert r["shares"] == 50 and r["stop_distance"] == 20 and r["kind"] == "calculator"


def test_month_end_closes_excludes_current_month():
    b = _bars(70)  # 2024-01-01 .. 2024-03-10
    m = calc.month_end_closes(b, "2024-03")
    assert list(m) == ["2024-01", "2024-02"]
    assert m["2024-01"] == b[30]["close"]  # Jan 31


def test_momentum_score_skips_last_month_and_ranks():
    s = [100.0] * 12 + [150.0]
    assert calc.momentum_12_1(s) == 0.0                 # the jump in the skipped month is ignored
    assert calc.momentum_12_1([100.0] + [110.0] * 11 + [999.0]) == pytest.approx(0.10)
    r = calc.rank({"A": 0.3, "B": -0.1, "C": 0.1, "D": 0.0, "E": 0.2})
    assert r["A"]["rank"] == 1 and r["A"]["percentile"] == 100.0 and r["B"]["percentile"] == 0.0
    assert [s for s, v in r.items() if v["top_quintile"]] == ["A"]


def test_momentum_backtest_detects_persistent_winner():
    months = [f"{2015 + i // 12}-{i % 12 + 1:02d}" for i in range(40)]
    monthly = {f"S{k}": {m: 100 * (1 + 0.001 * k) ** i for i, m in enumerate(months)} for k in range(10)}
    rows = calc.momentum_backtest(monthly)
    assert len(rows) == 40 - 13
    assert all(ex > 0 for _, ex, n in rows) and all(n == 10 for *_, n in rows)
    st = calc.excess_stats(rows)
    assert st["pct_months_positive"] == 100.0 and st["max_drawdown_excess_pct"] == 0.0


def test_spark_parse_on_recorded_payload():
    raw = json.loads((FX / "yahoo_spark_in.json").read_text(encoding="utf-8"))
    out = calc.parse_spark(raw, {"RELIANCE.NS": "RELIANCE", "TCS.NS": "TCS", "INFY.NS": "INFY"}, session_open=False)
    assert set(out) == {"RELIANCE", "TCS", "INFY"}
    d = raw["TCS.NS"]
    last = [c for c in d["close"] if c is not None][-1]
    assert out["TCS"]["price"] == last
    assert out["TCS"]["change_pct"] == pytest.approx((last - d["previousClose"]) / d["previousClose"] * 100, abs=1e-3)
    assert out["TCS"]["prov"]["kind"] == "close" and out["TCS"]["prov"]["source"] == "yahoo:spark/TCS.NS"


def test_rss_parse():
    xml = (b'<?xml version="1.0" encoding="UTF-8"?><rss><channel><item><title>Headline</title>'
           b'<link>https://www.example.com/a?x=1</link><pubDate>Wed, 18 Nov 2026 03:04:29 +0000</pubDate></item></channel></rss>')
    [it] = service.parse_rss(xml)
    assert it == {"title": "Headline", "link": "https://www.example.com/a?x=1", "source": "example.com",
                  "published": "2026-11-18T03:04:29+00:00"}


def test_route_payload_shapes_pass_provenance_guard(monkeypatch):
    prov = {"source": "t", "kind": "close"}
    monkeypatch.setattr(service, "_cached", lambda k, ttl, fn: fn())
    monkeypatch.setattr(service.feeds, "session", lambda m: {"open": False})
    monkeypatch.setattr(service, "spark", lambda s, m, o: {"TCS": {"price": 1.0, "change_pct": 0.5, "prov": prov}})
    monkeypatch.setattr(service, "_tv", lambda s, m: {})
    monkeypatch.setattr(service, "momentum_now", lambda m: {"formed_at": "2026-10", "scores": {"TCS": 0.1},
                                                            "ranks": calc.rank({"TCS": 0.1}), "prov": prov})
    out = service._scan("IN")
    require_provenance(out)
    tcs = next(r for r in out["rows"] if r["symbol"] == "TCS")
    assert tcs["price_prov"] == prov and tcs["momentum_rank"] == 1
    other = next(r for r in out["rows"] if r["symbol"] == "INFY")
    assert other["price"] is None and other["price_prov"]["kind"] == "unavailable"
    with pytest.raises(ProvenanceMissing):
        require_provenance({"rows": [{"price": 1.0}]})
