"""Trade Style AUTO news verdict: calendar rules first, AI may only tighten."""
from datetime import datetime, timedelta, timezone

from jarvis.intelligence import news_risk
from jarvis.intelligence.news_risk import ai_read, verdict

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def _event(mins, pairs=("EURUSD",), impact="HIGH", **kw):
    e = {"event": "CPI", "currency": "USD", "impact": impact, "source": "live_feed", "is_fallback": False,
         "time_quality": "exact", "affected_pairs": list(pairs), "timestamp_iso": (NOW + timedelta(minutes=mins)).isoformat()}
    e.update(kw)
    return e


def _head(title="Fed holds", urgency="ROUTINE", score=0, ccy=("USD",), age=10, hid=None):
    return {"id": hid or title, "title": title, "urgency": urgency, "sentiment_score": score,
            "affected_currencies": list(ccy), "affected_assets": ["FOREX"], "age_minutes": age}


def _v(cal, heads=(), ai=None, sym="EURUSD"):
    return verdict(sym, calendar=cal, headlines=list(heads), ai_result=ai, now=NOW)


def test_event_inside_window_blocks_both_directions():
    v = _v([_event(10)])
    assert v["state"] == "BLOCK" and v["size_mult"] == 0 and v["blocked_directions"] == ["BUY", "SELL"]


def test_event_within_two_hours_is_caution_at_half_size():
    v = _v([_event(60)])
    assert v["state"] == "CAUTION" and v["size_mult"] == 0.5 and v["blocked_directions"] == []
    assert v["event"]["minutes"] == 60


def test_unrelated_or_far_events_are_clear():
    assert _v([_event(10, pairs=("USDJPY",)), _event(300)])["state"] == "CLEAR"


def test_fallback_only_calendar_never_clear():
    v = _v([_event(500, is_fallback=True)])
    assert v["state"] == "CAUTION" and v["size_mult"] == 0.5


def test_ai_vetoes_opposite_direction_only_when_confident():
    ai = {"bias": "BULL", "confidence": 0.8, "risk": "LOW", "reason": "dovish"}
    assert _v([_event(500)], ai=ai)["blocked_directions"] == ["SELL"]
    assert _v([_event(500)], ai=dict(ai, confidence=0.6))["blocked_directions"] == []


def test_ai_never_raises_size():
    ai = {"bias": "BULL", "confidence": 1.0, "risk": "LOW", "reason": "x"}
    assert _v([_event(60)], ai=ai)["size_mult"] == 0.5
    assert _v([_event(500)], ai=ai)["size_mult"] <= 1.0
    assert _v([_event(500)], ai=dict(ai, risk="HIGH"))["size_mult"] == 0.5


def test_offline_ai_uses_keywords_and_breaking_headlines():
    heads = [_head("a", "BREAKING", 40), _head("b", "BREAKING", 30), _head("old", age=900), _head("jpy", ccy=("JPY",))]
    v = _v([_event(500)], heads)
    assert not v["ai_used"] and v["headlines"] == 2 and v["bias"] == "BULL" and v["state"] == "CLEAR"
    heads += [_head("c", "BREAKING", 0, age=20), _head("d", "BREAKING", 0, age=120)]
    v = _v([_event(500)], heads)
    assert v["state"] == "CAUTION" and v["size_mult"] == 0.5   # 3 breaking within the hour; the 2h-old one doesn't count


def test_ai_read_validates_provider_answer():
    class P:
        name = "fake"

        def __init__(self, out):
            self.out = out

        def structured(self, prompt, schema, system=""):
            assert "EURUSD" in prompt and "Fed holds" in prompt
            return self.out

    good = ai_read(P({"bias": "bear", "confidence": 3, "risk": "HIGH", "reason": "r"}), "EURUSD", [_head()])
    assert good == {"bias": "BEAR", "confidence": 1.0, "risk": "HIGH", "reason": "r", "provider": "fake"}
    assert ai_read(P({"bias": "UP", "confidence": 1, "risk": "LOW"}), "EURUSD", [_head()]) is None


def test_cached_ai_read_never_blocks(monkeypatch):
    calls = []
    monkeypatch.setattr(news_risk._pool, "submit", lambda fn: calls.append(fn))
    news_risk._ai_cache.pop("EURUSD", None)
    news_risk._inflight.discard("EURUSD")
    assert news_risk._ai_cached("EURUSD", [_head()]) is None and len(calls) == 1   # scheduled, not awaited
    assert news_risk._ai_cached("EURUSD", [_head()]) is None and len(calls) == 1   # in flight: no second job
    news_risk._inflight.discard("EURUSD")
