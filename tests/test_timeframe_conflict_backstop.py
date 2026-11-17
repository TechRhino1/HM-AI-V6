"""Timeframe-conflict backstop and the BTCUSD TREND_FOLLOWING ban (2026-11-17)."""
from jarvis.application.orchestrator import STYLE_CONFLICT_WINDOW_SEC, faster_style_conflict
from jarvis.intelligence.symbol_profile_config import get_symbol_profile_config

NOW = 1_000_000.0


def test_day_sell_blocked_when_scalp_just_said_buy():
    # BTCUSD #995648912: DAY_TRADING sold while SCALP had resolved BUY seconds earlier.
    why = faster_style_conflict({"SCALP": ("BUY", NOW - 20)}, "DAY_TRADING", "SELL", NOW)
    assert "SCALP" in why and "blocked" in why


def test_agreement_stale_or_slower_styles_do_not_block():
    assert not faster_style_conflict({"SCALP": ("SELL", NOW - 20)}, "DAY_TRADING", "SELL", NOW)
    assert not faster_style_conflict({"SCALP": ("BUY", NOW - STYLE_CONFLICT_WINDOW_SEC - 1)}, "DAY_TRADING", "SELL", NOW)
    assert not faster_style_conflict({"SWING": ("BUY", NOW)}, "DAY_TRADING", "SELL", NOW)   # slower style
    assert not faster_style_conflict({"DAY_TRADING": ("BUY", NOW)}, "SCALP", "SELL", NOW)  # scalp is fastest
    assert not faster_style_conflict({"SCALP": ("NEUTRAL", NOW)}, "SWING", "SELL", NOW)
    assert not faster_style_conflict({"SCALP": ("BUY", NOW)}, "UNKNOWN_STYLE", "SELL", NOW)


def test_swing_blocked_by_day():
    assert faster_style_conflict({"DAY_TRADING": ("SELL", NOW - 60)}, "SWING", "BUY", NOW)


def test_btcusd_trend_following_banned():
    cfg = get_symbol_profile_config("BTCUSD")
    assert "TREND_FOLLOWING" in cfg.banned_strategies
    assert cfg.strategy_weights["TREND_FOLLOWING"] == 0.0
