"""Arbiter dispatch must honour the hard vetoes the dry-run scan computed (audit 2026-11-18)."""
from types import SimpleNamespace
from unittest.mock import patch

from jarvis.application.orchestrator import JarvisOrchestrator


def _orch():
    o = object.__new__(JarvisOrchestrator)  # helper needs only .mode
    o.mode = "demo"
    return o


def _vetoes(o, **kw):
    args = dict(symbol="EURUSD", prof=None, profile_lookup_failed=False, is_session_blackout=False,
                premium_offwindow_elite=False, gov_sym_dir=None, tf_conflict="", is_exec_style_match=True)
    args.update(kw)
    return o._dispatch_vetoes(**args)


@patch.object(JarvisOrchestrator, "_count_entries_today", return_value=0)
def test_clean_candidate_has_no_vetoes(_):
    assert _vetoes(_orch()) == []


@patch.object(JarvisOrchestrator, "_count_entries_today", return_value=0)
def test_each_hard_gate_vetoes(_):
    o = _orch()
    assert _vetoes(o, is_session_blackout=True) == ["SESSION_BLACKOUT"]
    assert _vetoes(o, is_session_blackout=True, premium_offwindow_elite=True) == []
    assert _vetoes(o, gov_sym_dir=SimpleNamespace(status="PAUSED", reason="x"))[0].startswith("LLM_GOVERNOR_PAUSED")
    assert _vetoes(o, tf_conflict="M5 BUY")[0].startswith("TIMEFRAME_CONFLICT")
    assert _vetoes(o, profile_lookup_failed=True) == ["PROFILE_LOOKUP_FAILED"]
    assert _vetoes(o, is_exec_style_match=False) == ["STYLE_FILTER"]
    closed = SimpleNamespace(allowed_utc_hours=(25, 26), session_restriction=True, premium_window_exception=False)
    assert _vetoes(o, prof=closed) == ["PROFILE_SESSION_WINDOW"]


@patch.object(JarvisOrchestrator, "_count_entries_today", return_value=99)
def test_daily_cap_vetoes_even_on_dry_run(_):
    assert _vetoes(_orch()) == ["DAILY_ENTRY_CAP"]


def test_entry_count_fails_closed():
    with patch("jarvis.data.database.TRADE_DB", SimpleNamespace(db_path="Z:/does/not/exist.db")):
        assert JarvisOrchestrator._count_entries_today("EURUSD", mode="demo") >= 10**6
