"""Phase-0 regression tests for live exit-path defects (plan v3, Part A1)."""
from types import SimpleNamespace as NS

from jarvis.execution.position_monitor import _decision_first_target


def _dec(bias, style, tp):
    return NS(bias=bias, trade_style=style, first_target_price=tp)


def test_partial_target_ignores_other_side_decision():
    # A later SELL decision's TP1 (below a BUY's entry) must never trigger the BUY's partial.
    assert _decision_first_target(_dec("SELL", "DAY_TRADING", 3990.0), "BUY", "DAY_TRADING", 4000.0) is None


def test_partial_target_ignores_other_style_decision():
    assert _decision_first_target(_dec("BUY", "SWING", 4030.0), "BUY", "SCALP", 4000.0) is None


def test_partial_target_must_be_on_profit_side():
    assert _decision_first_target(_dec("BUY", "SCALP", 3995.0), "BUY", "SCALP", 4000.0) is None
    assert _decision_first_target(_dec("SELL", "SCALP", 4005.0), "SELL", "SCALP", 4000.0) is None


def test_partial_target_used_when_decision_matches():
    assert _decision_first_target(_dec("BUY", "SCALP", 4010.0), "BUY", "SCALP", 4000.0) == 4010.0
    assert _decision_first_target(_dec("SELL", "day_trading", 3990.0), "SELL", "DAY_TRADING", 4000.0) == 3990.0
    assert _decision_first_target(None, "BUY", "SCALP", 4000.0) is None


def test_monitor_context_style_follows_order_comment():
    from jarvis.execution.position_monitor import _style_from_comment
    assert _style_from_comment("HMA2_SCLP_TREN_DEMO") == "SCALP"
    assert _style_from_comment("HMA2_DAY_TREN_DEMO") == "DAY_TRADING"
    assert _style_from_comment("HMA2_SWNG_TREN_DEMO") == "SWING"
    assert _style_from_comment("") == "SWING"   # manual / untagged keeps the legacy context


def test_get_context_fetches_on_position_style_timeframes():
    from jarvis.execution.position_monitor import PositionMonitorEngine as PositionMonitor
    import threading

    calls = []

    class Feed:
        def fetch_multi_timeframe(self, sym, trade_style="SWING"):
            calls.append((sym, trade_style)); return {}

    class Ctx:
        def build_context(self, sym, mtf, current_spread_pips=2.0, trade_style="SWING"):
            return ("ctx", sym, trade_style)

    m = PositionMonitor.__new__(PositionMonitor)
    m._ctx_cache, m._ctx_lock, m.data_feed, m.context_engine = {}, threading.Lock(), Feed(), Ctx()
    assert m._get_context("XAUUSD", "SCALP") == ("ctx", "XAUUSD", "SCALP")
    assert m._get_context("XAUUSD") == ("ctx", "XAUUSD", "SWING")
    assert calls == [("XAUUSD", "SCALP"), ("XAUUSD", "SWING")]
    assert m._get_context("XAUUSD", "SCALP") == ("ctx", "XAUUSD", "SCALP")  # cached per style
    assert len(calls) == 2


def test_tight_real_stop_defines_1r_not_atr():
    from jarvis.execution.position_monitor import PositionMonitorEngine
    m = PositionMonitorEngine.__new__(PositionMonitorEngine)
    m._initial_risk_dist = {}
    pos = NS(ticket=1, open_price=1.10000, sl=1.09940)       # 6-pip scalp stop
    d = m._ensure_valid_initial_sl_dist(pos, 0.0, fallback_atr=0.0015, pip_size=0.0001)
    assert abs(d - 0.0006) < 1e-9                              # was inflated to 1.5 * ATR = 0.00225
    pos0 = NS(ticket=2, open_price=1.10000, sl=0.0)            # no stop -> ATR fallback stays
    assert abs(m._ensure_valid_initial_sl_dist(pos0, 0.0, 0.0015, 0.0001) - 0.00225) < 1e-9


def test_partial_split_uses_broker_min_lot():
    from jarvis.execution.position_monitor import _can_split
    assert _can_split(0.02, 0.5, 0.01, 0.01)
    assert not _can_split(0.10, 0.5, 0.10, 0.01)     # min lot 0.10: cannot split 0.10
    assert _can_split(0.20, 0.5, 0.10, 0.01)
    assert not _can_split(0.01, 0.5, 0.01, 0.01)


def test_unsplittable_position_gets_fallback_lock_not_nothing():
    from jarvis.execution.exit_policy import ExitPolicy, evaluate_exit
    pol = ExitPolicy.for_symbol("EURUSD", None, trade_style="DAY_TRADING")
    entry, sl = 1.1000, 1.0980
    price = entry + (entry - sl) * (pol.fast_cash_r + 0.05)
    d = evaluate_exit(side="BUY", entry=entry, initial_sl=sl, current_sl=sl, tp=0.0, price=price,
                      favorable_dist=price - entry, atr=0.0015, policy=pol,
                      partial_already_taken=False, be_already_locked=False, partial_executable=False)
    assert any("PARTIAL_FALLBACK_LOCK" in a for a in d.actions), d.actions
    assert d.new_sl > sl

