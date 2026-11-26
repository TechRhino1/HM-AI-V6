"""Shared test configuration.

WHY THIS FILE EXISTS
--------------------
There was no conftest, so every test that built a ``RiskEngine`` or a
``JarvisOrchestrator`` also built a ``DrawdownGuard`` on its DEFAULT database
path, which ``jarvis.config.paths`` anchors under ``<repo>/data`` — the same file
the live engine reads. Risk state was therefore shared by the whole suite *and*
with the running account:

* Tests inherited whatever the live account last wrote, so results depended on
  the operator's equity rather than on the code.
* Tests wrote back into live risk state. ``data/jarvis_drawdown_state.db`` was
  found holding ``daily_start_equity = 487.36`` beside ``peak_equity = 10150.0``
  — the signature of a test running a small mock account. The old re-anchor rule
  (``baseline > current * 1.5``) took a $500 test balance for a withdrawal and
  wrote it into the live daily-loss baseline, against which the 4% cap would
  then be measured.
* And within a single session the baseline was process-wide, so test A's equity
  set the baseline that test B was judged against. Once the re-anchor was removed
  (see jarvis/risk/drawdown.py) the baseline stopped following large jumps and
  simply stuck to whichever test ran first, which is how
  ``test_d1_online_ml_and_trade_memory_learning_loop`` came to be judged against
  a stranger's equity and blocked.

Redirecting ``JARVIS_DATA_DIR`` is NOT a usable fix: 12 tests in
test_backtest_optimizer.py and test_regime_optimizer.py read real parquet data
out of ``data/`` and break when it is moved. So instead every test gets an
IN-MEMORY drawdown guard (``db_path=""``, the same sentinel ``is_offline()``
uses), which needs no files and cannot leak between tests.

Tests that exercise persistence itself opt out with
``@pytest.mark.drawdown_persistence``.
"""
import pytest

from jarvis.risk.drawdown import DrawdownGuard


@pytest.fixture(autouse=True)
def _hermetic_drawdown_guard(monkeypatch, request):
    """Give every test its own drawdown state instead of the shared on-disk one."""
    if request.node.get_closest_marker("drawdown_persistence"):
        return
    original = DrawdownGuard.__init__

    def in_memory_init(self, *args, **kwargs):
        kwargs["db_path"] = ""
        return original(self, *args, **kwargs)

    monkeypatch.setattr(DrawdownGuard, "__init__", in_memory_init)


@pytest.fixture(autouse=True)
def _hermetic_news_disk_cache(tmp_path):
    """Give every test its own news calendar cache.

    `LiveNewsEngine` writes `data/news_calendar_cache.json` after a successful
    fetch. A test that fetched real feeds (the unified-state contract test)
    left that file behind, and later calendar tests inherited it as a fresh
    cache -- so they never called their mocked fetch and failed for reasons
    unrelated to the code under test. The live operator's calendar is also not
    a test fixture.
    """
    from jarvis.market.news import LiveNewsEngine

    original = LiveNewsEngine.DISK_CACHE_PATH
    LiveNewsEngine.DISK_CACHE_PATH = str(tmp_path / "news_calendar_cache.json")
    try:
        yield
    finally:
        LiveNewsEngine.DISK_CACHE_PATH = original


@pytest.fixture(autouse=True)
def _hermetic_trade_journal(monkeypatch):
    """Keep tests out of the real trade journal.

    `jarvis.data.database.TRADE_DB` is a module-level singleton pointed at
    `data/jarvis_history.db`, and `ExecutionEngine.execute_decision` imports it
    at CALL time, so any test that drives a real execution path writes into the
    live journal. Measured: `data/jarvis_history.db` gained exactly one EURUSD
    BUY row per suite run (rows 264-268, timestamps matching five consecutive
    runs) — fake trades in the same table every realised-P&L statistic is read
    from, indistinguishable from real ones.

    Redirecting `JARVIS_DATA_DIR` is not an option (see the note above: 12
    parquet-reading tests break), so the singleton itself is swapped for one
    backed by a per-test temp file. Tests that need to inspect the journal get
    the replacement and can write freely.
    """
    import os
    import tempfile

    import jarvis.data.database as database

    # Deliberately NOT `tmp_path`: tests such as
    # `test_drawdown_guard.py::TestPersistence::test_an_empty_db_path_writes_nothing`
    # assert that their own tmp_path stays empty, and dropping a journal file in
    # there turns "nothing was written" into three extra entries.
    fd, path = tempfile.mkstemp(suffix=".db", prefix="jarvis_test_journal_")
    os.close(fd)
    temp_db = database.SQLiteTradeDB(db_path=path)
    monkeypatch.setattr(database, "TRADE_DB", temp_db)
    try:
        yield temp_db
    finally:
        try:
            temp_db.close()
        except Exception:
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass


# Keep tests out of data/models: building an orchestrator freezes the live learned
# state into the model registry on first use. Redirected at conftest IMPORT time,
# not in a fixture: importing jarvis.api.intelligence_api during collection starts
# a pre-warm thread that builds a fallback orchestrator before any fixture runs.
import tempfile as _tempfile  # noqa: E402

import jarvis.learning.model_registry as _model_registry  # noqa: E402

_MODEL_REGISTRY_ROOT = _tempfile.mkdtemp(prefix="jarvis_test_models_")
_model_registry._root = lambda: _MODEL_REGISTRY_ROOT

# Same for the decision journal (data/decisions): orchestrator cycles write it.
import jarvis.observability.decision_journal as _decision_journal  # noqa: E402

_DECISION_JOURNAL_DIR = _tempfile.mkdtemp(prefix="jarvis_test_decisions_")
_decision_journal._dir = lambda: _DECISION_JOURNAL_DIR

# Tests that drive hm_start()/main() must not attach a file handler to the real
# data/logs (it would also capture every later test's log lines).
import jarvis.observability.logging_setup as _logging_setup  # noqa: E402

_logging_setup.add_file_logging = lambda *a, **k: None


@pytest.fixture(autouse=True)
def _hermetic_trade_memory(monkeypatch):
    """TradeMemory() defaults to data/jarvis_trade_memory.db - the live learning memory. Any test
    that builds an orchestrator wrote fake trades into it (ticket 999333, pnl 50.0, seen in the
    production file). Point the default at a per-test temp file."""
    import os
    import tempfile

    from jarvis.learning.trade_memory import TradeMemory

    fd, path = tempfile.mkstemp(suffix=".db", prefix="jarvis_test_trade_memory_")
    os.close(fd)
    monkeypatch.setattr(TradeMemory.__init__, "__defaults__", (path,))
    yield path
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def _legacy_exits_unless_marked(monkeypatch, request):
    """Live exits follow the calibrated profile geometry when config/settings.json enables the
    calibrated policy. Most exit tests pin the style-profile machinery that non-calibrated symbols
    still use, so they run on it unless marked `calibrated_exits`."""
    if request.node.get_closest_marker("calibrated_exits"):
        return
    from jarvis.backtesting import exit_geometry

    monkeypatch.setattr(exit_geometry, "live_exit_geometry", lambda symbol: None)
    # Same for the live deployment bar (expectancy gate): unit tests use synthetic symbols/setups.
    monkeypatch.setattr(exit_geometry, "deployment_refusal", lambda symbol, style=None: None)


@pytest.fixture(autouse=True)
def _no_live_news_outside_news_tests(monkeypatch, request):
    """Orchestrator paths consult the live economic calendar on the WALL CLOCK; inside +-30 min of
    a real HIGH-impact release (or a scheduled one, via the fail-closed fallback) entries are
    correctly blocked, so unrelated tests failed at certain times of day. Outside the news test
    files: no network fetch and no scheduled-release fallback. News tests exercise both for real."""
    if "news" in request.node.nodeid.lower():
        yield
        return
    from jarvis.market import news

    monkeypatch.setattr(news.GLOBAL_NEWS_ENGINE, "_fetch_all_live_sources", lambda *a, **k: [])
    monkeypatch.setattr(news, "us_release_slot_active", lambda *a, **k: False)
    yield


@pytest.fixture(autouse=True)
def _isolated_process_globals(monkeypatch):
    """Process-wide state that individual tests mutated and never restored:
    * SETTINGS.trading.symbols (symbol-toggle tests wrote it even with persist=False);
    * MT5Client's class-level paper book (a leaked EURUSD pending order / 3+ paper positions changed
      the session-window short-circuit and tripped 'max open positions' in unrelated tests)."""
    from jarvis.config.settings import SETTINGS
    from jarvis.execution.mt5_client import MT5Client

    monkeypatch.setattr(SETTINGS.trading, "symbols", list(SETTINGS.trading.symbols))
    MT5Client._shared_paper_positions.clear()
    MT5Client._shared_paper_pending_orders.clear()
    yield
    MT5Client._shared_paper_positions.clear()
    MT5Client._shared_paper_pending_orders.clear()
    # Any test that started the web telemetry syncer leaves a thread sweeping every 3s; stop it so
    # it cannot interleave log lines or state with later tests.
    import sys as _sys
    _srv = _sys.modules.get("jarvis.api.server")
    if _srv is not None and getattr(_srv.JarvisRequestHandler, "_bg_thread_started", False):
        _srv.JarvisRequestHandler.stop_background_syncer()


@pytest.fixture(autouse=True)
def _isolated_global_state():
    """GLOBAL_STATE is a process-wide singleton; positions left by one test changed what later
    tests saw (e.g. an EURUSD position disabled the session-window short-circuit)."""
    from jarvis.application.state_manager import GLOBAL_STATE
    saved = list(GLOBAL_STATE.positions)
    saved_account = GLOBAL_STATE.account   # tests set it to a MagicMock and never restored it
    GLOBAL_STATE.positions = []
    yield
    GLOBAL_STATE.positions = saved
    GLOBAL_STATE.account = saved_account


@pytest.fixture
def _hermetic_model_registry():
    """The test-run model registry root (see the import-time redirect above)."""
    return _MODEL_REGISTRY_ROOT


@pytest.fixture
def managed_gold_exit(monkeypatch):
    """Gold with the managed exit (BE / partial / milestones / locks) it had before
    the 2026-11-14 fixed-target switch. Tests that use gold as the sample symbol for
    those mechanics opt in; every other symbol still runs them in production."""
    from jarvis.execution import exit_policy
    from jarvis.intelligence.symbol_profile_config import SYMBOL_PROFILES

    monkeypatch.setattr(SYMBOL_PROFILES["XAUUSD"], "fixed_target_r", None)
    exit_policy._RESOLVED_POLICY_CACHE.clear()
    yield
    exit_policy._RESOLVED_POLICY_CACHE.clear()




@pytest.fixture(autouse=True)
def _legacy_exit_mode_unless_asked(monkeypatch):
    """config/settings.json runs live on the institutional lock; tests assert the code default (legacy)
    unless they select the lock themselves (exit_policy.institutional_lock)."""
    from jarvis.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS.trading, "exit_mode", "legacy")
