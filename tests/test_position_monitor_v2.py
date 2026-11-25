"""Position monitor v2 (2026-11-25 plan): true peak, loosen-proof writes, backoff, layer
registry (shadow), margin cooldown, portfolio protections incl. forward tests."""
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from jarvis.execution.position_monitor import PositionMonitorEngine
from jarvis.observability import decision_journal as dj
from jarvis.observability import system_monitor as sm


def _pos(**kw):
    base = dict(ticket=1, symbol="EURUSD", type="BUY", volume=0.01, open_price=1.1000, current_price=1.1010,
                sl=1.0980, tp=1.1060, profit=1.0, comment="HMA2_SWNG_TREN_DEMO", magic=888999,
                open_time="2026-11-25 10:00:00")
    base.update(kw)
    return SimpleNamespace(**base)


def _pm():
    pm = object.__new__(PositionMonitorEngine)
    pm.mt5_client = MagicMock()
    pm.mt5_client.magic_number = 888999
    pm.mt5_client.get_symbol_trading_spec.return_value = {"point": 0.00001, "digits": 5}
    pm.data_feed = MagicMock()
    pm._bar_peak_at, pm._modify_backoff, pm._modify_times = {}, {}, {}
    pm._highest_favorable_price, pm._lowest_adverse_price = {}, {}
    pm._layer_last, pm._margin_ladder_at = {}, 0.0
    pm._manual_trade_modes = {}
    pm.manual_mode = "PROTECT_ONLY"
    return pm


def _bars(rows):
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "spread"])


def test_peak_folds_m1_extremes_after_entry_only():
    pm = _pm()
    pm.data_feed.fetch_rates.return_value = _bars([
        ("2026-11-25 09:59:00", 1.1, 1.1200, 1.0900, 1.1, 0),   # before entry: ignored
        ("2026-11-25 10:01:00", 1.1, 1.1035, 1.0995, 1.1, 0),
        ("2026-11-25 10:02:00", 1.1, 1.1050, 1.0990, 1.1, 0),
    ])
    p = _pos()
    pm._fold_bar_extremes(p, "EURUSD")
    assert pm._highest_favorable_price[1] == 1.1050 and pm._lowest_adverse_price[1] == 1.0990
    pm.data_feed.fetch_rates.reset_mock()
    pm._fold_bar_extremes(p, "EURUSD")  # rate-limited (once per 60 s)
    pm.data_feed.fetch_rates.assert_not_called()


def test_sell_peak_is_measured_on_the_closing_side():
    pm = _pm()
    pm.data_feed.fetch_rates.return_value = _bars([("2026-11-25 10:01:00", 1.1, 1.1005, 1.0950, 1.1, 20)])
    pm._fold_bar_extremes(_pos(type="SELL"), "EURUSD")
    assert pm._highest_favorable_price[1] == pytest.approx(1.0950 + 20 * 0.00001)  # bid low + spread


@pytest.mark.parametrize("side,broker_sl,candidate,expected", [
    ("BUY", 1.0995, 1.0990, 1.0995),   # candidate looser than broker -> clamped up
    ("BUY", 1.0995, 1.1000, 1.1000),   # tighter -> kept
    ("SELL", 1.1005, 1.1010, 1.1005),  # looser SELL stop clamped down
    ("SELL", 1.1005, 1.1000, 1.1000),
])
def test_never_sends_a_looser_stop_than_the_broker_has(side, broker_sl, candidate, expected):
    pm = _pm()
    p = _pos(type=side, sl=broker_sl - (0.0010 if side == "BUY" else -0.0010))  # stale snapshot is looser
    pm.mt5_client.get_open_positions.return_value = [SimpleNamespace(ticket=1, sl=broker_sl)]
    assert pm._one_way_vs_broker(p, candidate, 5) == pytest.approx(expected)


def test_failed_modify_backs_off_and_rate_cap_holds():
    pm = _pm()
    assert pm._modify_allowed(1)
    pm._note_modify_result(1, {"status": "FAILED", "reason": "Invalid stops"})
    assert not pm._modify_allowed(1)            # backing off
    pm._modify_backoff[1] = (time.time() - 1, 1)
    assert pm._modify_allowed(1)
    pm._note_modify_result(1, {"status": "FAILED", "reason": "No changes"})  # 10025 == success
    assert 1 not in pm._modify_backoff
    for _ in range(pm.MODIFY_MAX_PER_MIN):
        pm._note_modify_result(1, {"status": "MODIFIED"})
    assert not pm._modify_allowed(1)            # per-ticket rate cap


def test_registry_layers_default_to_shadow_and_never_act():
    pm = _pm()
    dj.MONITOR_ACTIONS.clear()
    p = _pos()
    assert pm._execute_exit(p, "TP_ZONE_HARVEST") is False
    pm.mt5_client.close_position.assert_not_called()
    row = dj.MONITOR_ACTIONS[-1]
    assert row["rule"] == "tp_zone_harvest" and row["status"] == "SHADOW"
    assert pm._layer_gate(p, "news_floor", "SL", "1.0990") is False


def test_enforced_layer_acts_and_hold_list_is_exempt():
    from jarvis.config.settings import SETTINGS
    pm = _pm()
    dj.MONITOR_ACTIONS.clear()
    with patch.object(SETTINGS.monitor_layers, "news_bank", "enforce"):
        assert pm._layer_gate(_pos(), "news_bank", "CLOSE") is True
        with patch.object(SETTINGS.trading, "exit_hold_symbols", ["BTCUSD"]):
            assert pm._layer_gate(_pos(symbol="BTCUSD"), "news_bank", "CLOSE") is False
    with patch.object(SETTINGS.monitor_layers, "weekend_floor", "enforce"):
        assert pm._layer_gate(_pos(symbol="ETHUSD"), "weekend_floor", "SL") is False  # crypto trades weekends
    assert [r["symbol"] for r in dj.MONITOR_ACTIONS] == ["EURUSD"]  # exemptions record nothing


def test_margin_ladder_closes_at_most_one_position_per_minute():
    pm = _pm()
    pm._is_manual_trade = lambda p: False
    pm.mt5_client.close_position.return_value = {"status": "CLOSED"}
    losers = [_pos(ticket=1, profit=-5.0), _pos(ticket=2, profit=-3.0)]
    with patch("jarvis.data.database.TRADE_DB"):
        pm._apply_margin_ladder(losers, 120.0)
        pm._apply_margin_ladder(losers, 120.0)
    assert pm.mt5_client.close_position.call_count == 1


def test_missing_broker_stop_gets_an_emergency_stop_for_forward_tests_too():
    pm = _pm()
    pm._is_manual_trade = lambda p: False
    pm._get_context = lambda sym, style: SimpleNamespace(volatility=SimpleNamespace(atr=0.0010))
    pm._extract_position_trade_style = lambda pos, atr=0.0: "SWING"
    pm.mt5_client.modify_position.return_value = {"status": "MODIFIED"}
    pm._apply_portfolio_protections([_pos(sl=0.0, comment="FT_TR_EURUSD_H4_T1", type="SELL",
                                          open_price=1.0947, current_price=1.0950)], emergency_brake=False)
    sl = pm.mt5_client.modify_position.call_args.kwargs["sl"]
    assert sl == pytest.approx(1.0947 + 1.8 * 0.0010)


def test_emergency_brake_protects_profitable_forward_tests_only():
    pm = _pm()
    pm._is_manual_trade = lambda p: False
    pm._get_context = lambda sym, style: SimpleNamespace(volatility=SimpleNamespace(atr=0.0010))
    pm._extract_position_trade_style = lambda pos, atr=0.0: "SWING"
    pm.mt5_client.get_open_positions.return_value = []
    pm.mt5_client.modify_position.return_value = {"status": "MODIFIED"}
    winner = _pos(ticket=5, type="SELL", open_price=1.1000, current_price=1.0950, sl=1.1050, comment="FT_ESW_EURUSD")
    loser = _pos(ticket=6, type="SELL", open_price=1.1000, current_price=1.1030, sl=1.1050, comment="FT_ESW_EURUSD")
    pm._apply_portfolio_protections([winner, loser], emergency_brake=True)
    assert pm.mt5_client.modify_position.call_count == 1
    assert pm.mt5_client.modify_position.call_args.args[0] == 5
    assert pm.mt5_client.modify_position.call_args.kwargs["sl"] < 1.1000  # breakeven-side floor
    pm.mt5_client.modify_position.reset_mock()
    pm._apply_portfolio_protections([winner], emergency_brake=False)  # no brake: FT left alone
    pm.mt5_client.modify_position.assert_not_called()


def test_four_eurusd_shorts_show_as_one_concentrated_currency_risk():
    shorts = [SimpleNamespace(symbol="EURUSD", type="SELL", volume=0.01, open_price=1.0947, sl=1.1015,
                              comment="FT_X")] * 4
    exp = sm.currency_exposure(shorts)
    assert exp["EUR"]["short"] == pytest.approx(exp["USD"]["long"]) and exp["EUR"]["short"] > 25
    chk = sm.check_currency_exposure(shorts, equity=480.0, cap_pct=2.5)
    assert chk["status"] == sm.WARN and ("EUR" in chk["detail"] or "USD" in chk["detail"])


def test_stops_watchdog_flags_naked_positions_and_weekend_gap_multiplier():
    fri_night = pd.Timestamp("2026-11-27 21:00:00", tz="UTC").timestamp()
    ok = [SimpleNamespace(ticket=1, symbol="EURUSD", type="BUY", volume=0.01, open_price=1.1, sl=1.099)]
    naked = ok + [SimpleNamespace(ticket=2, symbol="EURUSD", type="BUY", volume=0.01, open_price=1.1, sl=0.0)]
    assert sm.check_stops_and_gap(naked, 500.0, fri_night)["status"] == sm.CRITICAL
    weekday = pd.Timestamp("2026-11-25 12:00:00", tz="UTC").timestamp()
    assert sm.check_stops_and_gap(ok, 500.0, fri_night)["value"] == pytest.approx(
        3 * sm.check_stops_and_gap(ok, 500.0, weekday)["value"])
