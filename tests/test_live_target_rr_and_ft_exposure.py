"""Risk checks judge the take-profit the order actually carries, and FT_ research positions
are not engine currency exposure (2026-11-23 journal: 844 "Sub-minimum Risk:Reward" refusals on
ETH/SOL whose TP is rewritten to the calibrated 2.0-2.5R at dispatch; ADAPTIVE_GATE_12 tripped
by open FT_ EURUSD sells)."""
from types import SimpleNamespace

import pytest

from jarvis.backtesting import exit_geometry as eg
from jarvis.risk.exposure import ExposureManager
from jarvis.risk.trade_guard import TradeGuard


def _decision(tp, symbol="ETHUSD"):
    # entry 2000, stop 1900 (1R = 100), stale scan TP gives 1.2R when tp=2120
    return SimpleNamespace(symbol=symbol, bias="BUY", decision="EXECUTE", execution_authorized=True,
                           entry_price=2000.0, stop_loss=1900.0, take_profit=tp, trade_style="SWING",
                           min_allowed_rr=None, risk_reward_ratio=(tp - 2000.0) / 100.0)


def _rr_refusals(decision):
    acct = SimpleNamespace(equity=538.0, balance=538.0, margin_level=0.0, free_margin=538.0, login=1, trade_allowed=True)
    res = TradeGuard.validate_pre_execution(decision, acct, [], entry_authorized_override=True)
    return [r for r in res["reasons"] if "Risk:Reward" in r]


def test_stale_tp_is_judged_on_the_calibrated_live_target(monkeypatch):
    monkeypatch.setattr(eg, "live_target_r", lambda s: 2.5)
    monkeypatch.setattr(eg, "deployment_refusal", lambda s: None)
    assert _rr_refusals(_decision(2120.0)) == []


def test_deployable_calibrated_target_below_floor_is_not_refused(monkeypatch):
    monkeypatch.setattr(eg, "live_target_r", lambda s: 0.75)
    monkeypatch.setattr(eg, "deployment_refusal", lambda s: None)
    assert _rr_refusals(_decision(2120.0, "USDCHF")) == []


def test_refused_profile_is_still_held_to_the_floor(monkeypatch):
    monkeypatch.setattr(eg, "live_target_r", lambda s: 0.4)
    monkeypatch.setattr(eg, "deployment_refusal", lambda s: "EXPECTANCY_GATE")
    assert _rr_refusals(_decision(2120.0, "USDCAD"))


def test_no_live_target_keeps_the_old_rule(monkeypatch):
    monkeypatch.setattr(eg, "live_target_r", lambda s: None)
    assert _rr_refusals(_decision(2120.0))          # 1.2R < 1.45
    assert _rr_refusals(_decision(2200.0)) == []    # 2.0R


def _pos(sym, side, comment=""):
    return SimpleNamespace(symbol=sym, side=side, type=side, comment=comment)


def test_forward_test_positions_do_not_count_toward_currency_concentration():
    em = ExposureManager()
    ft = [_pos("EURUSD", "SELL", "FT_TR_EURUSD_H4_T1"), _pos("EURUSD", "SELL", "FT_ESW_EURUSD"),
          _pos("EURUSD", "SELL", "FT_TR_EURUSD_H4_T3")]
    ok_with_ft = em.check_currency_directional_exposure("EURUSD", "SELL", ft + [_pos("EURUSD", "SELL")])
    real = [_pos("EURUSD", "SELL")] * 4
    ok_real = em.check_currency_directional_exposure("EURUSD", "SELL", real)
    assert ok_with_ft["passed"] is True
    assert ok_real["passed"] is False
