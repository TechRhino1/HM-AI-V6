"""Gold was not trading (2026-11-24 live journal):
1. UNSPLIT_RR_GATE logged "RR=4.99 < 2.00" while comparing gold's calibrated 1.5R target with the
   2R floor, so every gold arbiter dispatch was skipped (all styles, 344 calibrated-route approvals).
2. Below $250 no gold setup fits a minimum lot: user decision, scalp setups may risk up to 5%."""
import pytest

from jarvis.application import orchestrator as orch
from jarvis.backtesting import exit_geometry as eg
from jarvis.risk import account_tier
from jarvis.risk.account_tier import min_lot_risk_cap
from jarvis.risk.position_sizing import PositionSizer


def test_deployable_calibrated_target_is_not_held_to_the_2r_floor(monkeypatch):
    monkeypatch.setattr(eg, "live_target_r", lambda s: 1.5)
    monkeypatch.setattr(eg, "deployment_refusal", lambda s, style=None: None)
    assert orch.unsplit_rr_block("XAUUSD", 4.99) is None


def test_refused_profile_is_judged_on_the_target_it_carries(monkeypatch):
    monkeypatch.setattr(eg, "live_target_r", lambda s: 1.5)
    monkeypatch.setattr(eg, "deployment_refusal", lambda s, style=None: "EXPECTANCY_GATE")
    assert orch.unsplit_rr_block("USDCAD", 4.99) == 1.5     # the R it is judged on, not 4.99


def test_no_target_keeps_the_decision_rr_rule(monkeypatch):
    monkeypatch.setattr(eg, "live_target_r", lambda s: None)
    assert orch.unsplit_rr_block("EURUSD", 1.8) == 1.8
    assert orch.unsplit_rr_block("EURUSD", 2.4) is None


@pytest.fixture
def policy_2_5(monkeypatch):
    monkeypatch.setattr(account_tier._risk_policy(), "min_lot_max_risk_pct", 2.5)


def test_micro_account_gold_scalp_may_risk_5pct(policy_2_5):
    assert min_lot_risk_cap(100.0, "XAUUSD", "SCALP") == pytest.approx((5.0, 5.0))
    assert min_lot_risk_cap(100.0, "GOLD.i#", "scalp") == pytest.approx((5.0, 5.0))


def test_micro_account_gold_other_styles_keep_the_policy_cap(policy_2_5):
    for style in ("SWING", "H4_SWING", "D1_SWING", "DAY_TRADING", ""):
        assert min_lot_risk_cap(100.0, "XAUUSD", style) == pytest.approx((2.5, 2.5))


def test_250_plus_gold_and_other_symbols_unchanged(policy_2_5):
    assert min_lot_risk_cap(538.0, "XAUUSD", "SWING")[1] == 3.5
    assert min_lot_risk_cap(538.0, "XAUUSD", "SCALP")[1] == 3.5
    assert min_lot_risk_cap(100.0, "EURUSD", "SCALP")[1] == 2.5


def test_sizer_takes_a_micro_gold_scalp_that_fits_5pct(policy_2_5):
    info = {"name": "XAUUSD", "trade_contract_size": 100.0, "trade_tick_value": 1.0, "trade_tick_size": 0.01,
            "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01}
    # $100 equity, 4.5-point stop: the 0.01-lot minimum risks $4.50 = 4.5%
    kw = dict(account_balance=100.0, entry_price=4100.0, sl_price=4095.5, risk_pct=1.0, symbol_info=info)
    assert PositionSizer.calculate_lot_size(**kw, trade_style="SCALP") == pytest.approx(0.01)
    assert PositionSizer.calculate_lot_size(**kw, trade_style="SWING") == 0.0
