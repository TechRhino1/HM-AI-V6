"""Trade Style AUTO: per-symbol style/strategy ranking and the orchestrator's AUTO pass."""
import json
from types import SimpleNamespace

import pytest

from jarvis.intelligence import auto_style
from jarvis.intelligence.auto_style import choose, rank, r_multiple


def _trade(style, strategy, r, regime="TRENDING", symbol="EURUSD"):
    # BUY from 1.1000 with a 0.0010 stop: exit = entry + r * 0.0010
    return {"symbol": symbol, "trade_type": "BUY", "entry_price": 1.1, "sl": 1.099, "exit_price": 1.1 + r * 0.001,
            "strategy": strategy, "regime": regime, "reasoning": json.dumps({"trade_style": style})}


def _cand(style, strategy, utility, bias="BUY", actionable=True, symbol="EURUSD"):
    return SimpleNamespace(symbol=symbol, trade_style=style, strategy=strategy, utility_score=utility, bias=bias,
                           is_actionable=actionable, regime="TRENDING", decision_obj=SimpleNamespace(governor_risk_mult=1.0))


class Prior:
    def __init__(self, w):
        self.w = w

    def weight(self, style, symbol=None):
        return self.w.get(style, 0.5)


def test_r_multiple_sign_and_missing():
    assert r_multiple(_trade("SWING", "X", 2.0)) == pytest.approx(2.0)
    sell = dict(_trade("SWING", "X", 0), trade_type="SELL", sl=1.101, exit_price=1.099)
    assert r_multiple(sell) == pytest.approx(1.0)
    assert r_multiple({"entry_price": 1, "sl": 1, "exit_price": 2}) is None


def test_backtest_prior_dominates_thin_record():
    out = rank("EURUSD", None, [_trade("SCALP", "MOMENTUM", 2.0)] * 3, Prior({"SCALP": 0.3}))
    assert out[0]["n"] == 3 and out[0]["score"] < 0.4   # 3 great trades barely move a weak backtest prior


def test_negative_record_is_excluded():
    out = rank("EURUSD", None, [_trade("SWING", "BREAKOUT", -0.3)] * 25)
    assert out[0]["excluded"] and out[0]["expectancy_r"] < 0
    assert not rank("EURUSD", None, [_trade("SWING", "BREAKOUT", -0.3)] * 19)[0]["excluded"]


def test_regime_record_used_once_large_enough():
    trades = [_trade("SWING", "TREND", 1.0, "TRENDING")] * 12 + [_trade("SWING", "TREND", -1.0, "RANGING")] * 30
    assert rank("EURUSD", "TRENDING", trades)[0]["source"] == "regime"
    assert rank("EURUSD", "TRENDING", trades)[0]["expectancy_r"] == pytest.approx(1.0)
    assert rank("EURUSD", "VOLATILE", trades)[0]["source"] == "symbol"


def test_choose_weighs_utility_by_earned_score_and_skips_excluded():
    trades = [_trade("SCALP", "MOMENTUM", -0.5)] * 25 + [_trade("SWING", "TREND", 0.8)] * 25
    cands = [_cand("SCALP", "MOMENTUM", 0.9), _cand("SWING", "TREND", 0.6), _cand("DAY_TRADING", "TREND", 0.9, actionable=False)]
    res = choose("EURUSD", cands, rank("EURUSD", None, trades))
    assert res["pick"].trade_style == "SWING" and res["detail"]["considered"] == 2


def test_choose_returns_none_when_everything_excluded():
    trades = [_trade("SCALP", "MOMENTUM", -0.5)] * 25
    res = choose("EURUSD", [_cand("SCALP", "MOMENTUM", 0.9)], rank("EURUSD", None, trades))
    assert res["pick"] is None and "excluded" in res["detail"]["reason"]


def test_strategy_enum_and_str_forms_match():
    class S:
        value = "TREND"
    assert auto_style.strat_name(S()) == auto_style.strat_name("StrategyType.TREND") == "TREND"


# ── orchestrator AUTO pass ──────────────────────────────────────────────────
def _run_pass(monkeypatch, live, news):
    from jarvis.application.orchestrator import JarvisOrchestrator
    from jarvis.intelligence import news_risk
    monkeypatch.setenv("JARVIS_AUTO_STYLE_LIVE", "1" if live else "0")
    monkeypatch.setattr(news_risk, "verdict", lambda sym: news[sym])
    ranked = [_cand("SCALP", "MOMENTUM", 0.9), _cand("SWING", "TREND", 0.5),
              _cand("SWING", "TREND", 0.7, bias="SELL", symbol="XAUUSD")]
    fake = SimpleNamespace(auto_selector=auto_style.AutoStyleSelector(trade_memory=None, prior=Prior({})), _auto_decisions={})
    return ranked, JarvisOrchestrator._apply_auto_style(fake, ranked), fake


def _news(state="CLEAR", size=1.0, blocked=()):
    return {"state": state, "size_mult": size, "blocked_directions": list(blocked), "ai_used": False, "reasons": []}


def test_shadow_dispatches_exactly_like_all(monkeypatch):
    ranked, out, fake = _run_pass(monkeypatch, False, {"EURUSD": _news(), "XAUUSD": _news("BLOCK", 0, ("BUY", "SELL"))})
    assert out is ranked
    assert fake._auto_decisions["XAUUSD"]["action"] == "VETO" and not fake._auto_decisions["XAUUSD"]["live"]
    assert all(c.decision_obj.governor_risk_mult == 1.0 for c in ranked)


def test_live_keeps_pick_drops_veto_and_scales_risk(monkeypatch):
    ranked, out, fake = _run_pass(monkeypatch, True, {"EURUSD": _news("CAUTION", 0.5), "XAUUSD": _news(blocked=("SELL",))})
    assert [(c.symbol, c.trade_style) for c in out] == [("EURUSD", "SCALP")]
    assert out[0].decision_obj.governor_risk_mult == 0.5
    assert fake._auto_decisions["XAUUSD"]["action"] == "VETO"
