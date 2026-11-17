"""Root causes of trade starvation (2026-11-17), one regression test each."""
from datetime import datetime, timedelta, timezone

import pandas as pd

from jarvis.market.market_context import _decision_time


def test_live_forming_d1_bar_uses_wall_clock_not_sunday_open():
    # EET broker D1 bar opened Sunday 22:00 UTC; it is now Monday 10:00 UTC and the bar is forming.
    opens = pd.date_range("2026-11-09 22:00", periods=6, freq="D")
    now = datetime.now(timezone.utc)
    df = pd.DataFrame({"time": opens.append(pd.DatetimeIndex([now.replace(tzinfo=None) - timedelta(hours=12)]))})
    last = df.time.iloc[-1].to_pydatetime().replace(tzinfo=timezone.utc)
    got = _decision_time(df, "time", last)
    assert abs((got - now).total_seconds()) < 5          # forming bar -> now, not the bar open


def test_completed_backtest_bar_decides_at_its_close():
    opens = pd.date_range("2026-06-01 06:00", periods=6, freq="h")
    df = pd.DataFrame({"time": opens})
    last = opens[-1].to_pydatetime().replace(tzinfo=timezone.utc)
    assert _decision_time(df, "time", last) == last + timedelta(hours=1)


def test_pending_order_age_does_not_jump_by_broker_offset_after_30_min():
    from jarvis.execution.position_monitor import _pending_order_age
    now, server_now = 1_800_000_000.0, 1_800_000_000.0 + 7200      # broker clock 2h ahead
    assert _pending_order_age(now - 31 * 60, now, server_now) == 31 * 60     # UTC stamp, 31 min old
    assert _pending_order_age(server_now - 35 * 60, now, server_now) == 35 * 60  # broker-clock stamp
    assert _pending_order_age(0, now, server_now) == 0.0
