"""Duplicate-order and shutdown safety defects found 2026-11-16."""
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jarvis.application.orchestrator import JarvisOrchestrator, UNKNOWN_ORDER_HOLD_SEC
from jarvis.common.single_instance import acquire_engine_lock

REPO = str(Path(__file__).resolve().parents[1])


def _locks():
    o = object.__new__(JarvisOrchestrator)
    o._execution_lock = threading.Lock()
    o._execution_in_progress = set()
    o._execution_claimed_at = {}
    o._last_execution_time = {}
    return o


def test_watchdog_never_frees_a_fresh_claim_even_after_an_old_execution():
    o = _locks()
    now = time.time()
    o._last_execution_time["XAUUSD"] = now - 3600   # previous trade an hour ago
    o._execution_in_progress.add("XAUUSD")
    o._execution_claimed_at["XAUUSD"] = now - 2     # this dispatch started 2 s ago
    assert o._release_stale_execution_locks(now) == []
    assert "XAUUSD" in o._execution_in_progress


def test_watchdog_frees_a_hung_claim():
    o = _locks()
    now = time.time()
    o._execution_in_progress.add("EURUSD")
    o._execution_claimed_at["EURUSD"] = now - 61
    assert o._release_stale_execution_locks(now) == ["EURUSD"]
    assert not o._execution_in_progress


def test_unknown_outcome_reservation_outlives_the_default_ttl():
    from jarvis.risk.risk_engine import RiskEngine
    clock = [1000.0]
    re = RiskEngine()
    re.set_clock(lambda: clock[0])
    re.reserve_risk("EURUSD", 25.0, ttl_sec=UNKNOWN_ORDER_HOLD_SEC)
    clock[0] += 120  # long after the old 15 s TTL
    assert re.get_total_reserved_risk_usd() == pytest.approx(25.0)


def test_second_engine_in_the_same_mode_refuses_to_start(tmp_path):
    acquire_engine_lock("unit_test_mode", lock_dir=str(tmp_path))
    child = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {REPO!r})
        from jarvis.common.single_instance import acquire_engine_lock, AlreadyRunningError
        try:
            acquire_engine_lock("unit_test_mode", lock_dir={str(tmp_path)!r})
            print("ACQUIRED")
        except AlreadyRunningError:
            print("REFUSED")
    """)
    out = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True, timeout=60).stdout
    assert "REFUSED" in out
    # A different mode may run alongside.
    acquire_engine_lock("other_mode", lock_dir=str(tmp_path))


def test_cancel_pending_order_cannot_hang_the_caller():
    from tests.test_live_readiness_fixes import _demo_client
    fake = MagicMock()
    fake.TRADE_ACTION_REMOVE = 8
    release = threading.Event()
    # The hung call holds the shared broker lock: free it as soon as the test has
    # its answer, or every later broker test in the run waits on it.
    fake.order_send.side_effect = lambda req: release.wait(30)
    try:
        with patch("jarvis.execution.mt5_client.mt5", fake), \
             patch("jarvis.execution.mt5_client.MT5_AVAILABLE", True):
            t0 = time.time()
            res = _demo_client().cancel_pending_order(123)
        assert time.time() - t0 < 15
        assert res["status"] == "UNKNOWN"
    finally:
        release.set()
        time.sleep(0.2)
