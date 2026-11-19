"""Overview attention rules: ranking, thresholds, and AI-only-words-the-headline fallback."""
from jarvis.ai import insights, tools
from jarvis.ai.providers.base import ChatResult, ProviderError

ACC = {"equity": 10000.0, "margin": 1000.0}
RISK = {"daily_loss_pct": 0.5, "max_daily_loss_pct": 3, "total_dd_pct": 1, "max_drawdown_pct": 10, "portfolio_heat_score": 20,
        "allow_new_risk": True, "consecutive_losses": 0, "paused_symbols": []}


def ids(items):
    return [i["id"] for i in items]


def test_calm_account_has_no_items():
    assert insights.rules(ACC, [{"symbol": "EURUSD", "volume": 0.1}, {"symbol": "GBPUSD", "volume": 0.1}], RISK) == []


def test_limits_rank_danger_first():
    r = dict(RISK, daily_loss_pct=2.7, total_dd_pct=6, consecutive_losses=4, paused_symbols=["XAUUSD"])
    items = insights.rules(ACC, [], r)
    assert ids(items) == ["daily_loss", "drawdown", "loss_streak", "paused"]
    assert [i["level"] for i in items] == ["danger", "warn", "warn", "info"]
    assert items[0]["title"] == "Daily loss at 90% of its limit"


def test_circuit_breaker_and_concentration_and_margin():
    pos = [{"symbol": "XAUUSD#", "volume": 1.0}, {"symbol": "XAUUSD.i", "volume": 0.5}, {"symbol": "EURUSD", "volume": 0.5}]
    items = insights.rules({"equity": 1000, "margin": 900}, pos, dict(RISK, circuit_breaker_active=True, allow_new_risk=False))
    assert ids(items) == ["circuit_breaker", "margin", "concentration"]
    assert items[2]["symbol"] == "XAUUSD" and "75%" in items[2]["title"]


def test_missing_risk_does_not_crash():
    assert insights.rules(None, None, None) == []


class Fake:
    name = "fake"

    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, 0

    def user(self, t):
        return {"role": "user", "content": t}

    def chat(self, *a, **k):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result


def _live(monkeypatch, risk):
    insights._cache.clear()
    monkeypatch.setattr(tools, "_forex_account", lambda _a: {"account": ACC, "positions": []})
    monkeypatch.setattr(tools, "_forex_risk", lambda _a: dict(risk, prov={"source": "risk engine over MT5 account"}))


def test_ai_words_headline_and_is_cached(monkeypatch):
    _live(monkeypatch, dict(RISK, daily_loss_pct=2.9))
    p = Fake(ChatResult(text="Daily loss is close to the limit."))
    a = insights.overview(provider=p)
    b = insights.overview(provider=p)
    assert a["headline"] == "Daily loss is close to the limit." and a["provider"] == "fake"
    assert b["headline"] == a["headline"] and p.calls == 1
    assert ids(a["items"]) == ["daily_loss"] and a["prov"]["kind"] == "live"


def test_template_when_ai_fails_or_refuses(monkeypatch):
    _live(monkeypatch, dict(RISK, daily_loss_pct=2.9, consecutive_losses=3))
    out = insights.overview(provider=Fake(exc=ProviderError("down")))
    assert out["provider"] == "template" and out["headline"] == "Daily loss at 97% of its limit, plus 1 more item."
    out = insights.overview(provider=Fake(ChatResult(text="no", stop_reason="refusal")))
    assert out["provider"] == "template"


def test_calm_and_unavailable(monkeypatch):
    _live(monkeypatch, RISK)
    p = Fake(ChatResult(text="x"))
    out = insights.overview(provider=p)
    assert out["items"] == [] and p.calls == 0 and out["provider"] == "template"
    monkeypatch.setattr(tools, "_forex_risk", lambda _a: {"status": "UNAVAILABLE"})
    monkeypatch.setattr(tools, "_forex_account", lambda _a: {"account": None, "positions": []})
    out = insights.overview(use_provider=False)
    assert not out["risk_available"] and out["prov"]["kind"] == "unavailable" and "No broker account" in out["headline"]
