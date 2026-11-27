"""Gold trades SCALP on an operator override with a live probation stop; AUTO picks only styles the
gate allows and the balance can afford (user decisions 2026-11-27)."""
import sqlite3
from types import SimpleNamespace

import pytest

from jarvis.backtesting import exit_geometry
from jarvis.intelligence import auto_style

OVERRIDE = {"symbol": "XAUUSD", "style": "SCALP", "since": "2026-11-27",
            "stop_after_trades": 30, "stop_below_r": -0.10, "reason": "test"}
EVIDENCE = {"SCALP": {"trades": 230, "expectancy_r": 0.010}, "DAY_TRADING": {"trades": 117, "expectancy_r": 0.064,
            "train_trades": 77, "train_expectancy_r": -0.098}}


def _history(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE executed_trades (symbol TEXT, entry_price REAL, sl REAL, volume REAL, "
                "realized_pnl REAL, trade_style TEXT, closed_at TEXT, execution_mode TEXT)")
    con.executemany("INSERT INTO executed_trades VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


@pytest.fixture
def gate(monkeypatch, tmp_path):
    from jarvis.config import paths, runtime
    from jarvis.config.settings import SETTINGS
    monkeypatch.setattr(runtime, "is_offline", lambda: False)
    monkeypatch.setattr(SETTINGS.trading, "use_calibrated_entry_policy", False, raising=False)
    monkeypatch.setattr(SETTINGS.gates, "deployment_overrides", [dict(OVERRIDE)], raising=False)
    monkeypatch.setattr(exit_geometry, "_engine_evidence", lambda s: EVIDENCE if s == "XAUUSD" else None)
    db = tmp_path / "jarvis_history.db"
    monkeypatch.setattr(paths, "resolve_db_path", lambda name: str(db))
    exit_geometry._OVERRIDE_CACHE.clear()

    def with_trades(rows):
        if db.exists():
            db.unlink()
        _history(str(db), rows)
        exit_geometry._OVERRIDE_CACHE.clear()
    with_trades([])
    return with_trades


def _scalp(r, closed="2026-11-28T10:00:00+00:00", mode="demo"):
    # 0.01 lot, $10 stop, 100 oz contract -> $10 risk; pnl = r x $10
    return ("XAUUSD", 4150.0, 4140.0, 0.01, r * 10.0, "SCALP", closed, mode)


@pytest.mark.calibrated_exits
def test_override_lets_gold_scalp_trade_and_nothing_else(gate):
    assert exit_geometry.deployment_refusal("XAUUSD", "SCALP") is None
    assert exit_geometry.deployment_refusal("XAUUSD", "DAY_TRADING").startswith("STYLE_TRAIN_GATE")
    assert exit_geometry.deployment_refusal("XAUUSD") is None  # style-less callers: an open override passes
    assert exit_geometry.deployment_refusal("NZDUSD", "SCALP") is not None  # no override, no evidence


@pytest.mark.calibrated_exits
def test_override_stops_after_30_losing_live_scalps(gate):
    gate([_scalp(-0.2)] * 30)
    why = exit_geometry.deployment_refusal("XAUUSD", "SCALP")
    assert why.startswith("OVERRIDE_STOPPED") and "30 trades" in why
    assert exit_geometry.deployment_refusal("XAUUSD").startswith("STYLE_")  # evidence refusal stands


@pytest.mark.calibrated_exits
def test_probation_counts_only_live_scalps_since_the_override(gate):
    gate([_scalp(-0.2)] * 29)  # one short of the stop
    assert exit_geometry.deployment_refusal("XAUUSD", "SCALP") is None
    gate([_scalp(-0.2, closed="2026-11-20T10:00:00+00:00")] * 40   # before `since`
         + [_scalp(-0.2, mode="paper")] * 40                       # paper fills
         + [("XAUUSD", 4150.0, 4140.0, 0.01, -2.0, "DAY_TRADING", "2026-11-28T10:00:00+00:00", "demo")] * 40)
    assert exit_geometry.deployment_refusal("XAUUSD", "SCALP") is None
    gate([_scalp(0.1)] * 40)  # winning: no stop
    assert exit_geometry.deployment_refusal("XAUUSD", "SCALP") is None


@pytest.mark.calibrated_exits
def test_unreadable_live_record_fails_closed(gate, monkeypatch):
    from jarvis.config import paths
    monkeypatch.setattr(paths, "resolve_db_path", lambda name: "Z:/no/such/dir/jarvis_history.db")
    exit_geometry._OVERRIDE_CACHE.clear()
    assert exit_geometry.deployment_refusal("XAUUSD", "SCALP").startswith("OVERRIDE_UNVERIFIED")


def _cand(style, utility, sl=4140.0):
    d = SimpleNamespace(entry_price=4150.0, stop_loss=sl)
    return SimpleNamespace(symbol="XAUUSD", is_actionable=True, bias="BUY", trade_style=style,
                           strategy="TREND_FOLLOWING", utility_score=utility, regime="TREND_BULL", decision_obj=d)


def test_auto_skips_refused_and_unaffordable_styles(monkeypatch):
    monkeypatch.setattr(exit_geometry, "deployment_refusal",
                        lambda s, st=None: None if st in ("SCALP", "DAY_TRADING") else "STYLE_HOLDOUT_GATE: x")
    swing, day_wide, scalp = _cand("SWING", 0.9), _cand("DAY_TRADING", 0.8, sl=4110.0), _cand("SCALP", 0.5)
    allowed = lambda c: auto_style.live_allowed(c, equity=466.0)
    assert allowed(swing) == "refused_by_gate"
    assert allowed(day_wide) == "unaffordable"  # $40 at 0.01 lot > 3.5% of $466
    assert allowed(scalp) is None               # $10 fits
    sel = auto_style.choose("XAUUSD", [swing, day_wide, scalp], [], None, allowed)
    assert sel["pick"] is scalp
    assert sel["detail"]["skipped"] == {"refused_by_gate": 1, "unaffordable": 1}
    # a bigger account can carry the wide DAY stop, so AUTO may pick it on utility
    sel = auto_style.choose("XAUUSD", [swing, day_wide, scalp], [], None,
                            lambda c: auto_style.live_allowed(c, equity=2000.0))
    assert sel["pick"] is day_wide
    none = auto_style.choose("XAUUSD", [swing], [], None, allowed)
    assert none["pick"] is None and "refused by the gate or unaffordable" in none["detail"]["reason"]


def test_shipped_config_starts_auto_with_the_gold_scalp_override():
    from jarvis.config.settings import JarvisConfig
    cfg = JarvisConfig.load()
    assert cfg.trading.trade_style == "AUTO"
    o = [x for x in cfg.gates.deployment_overrides if x["symbol"] == "XAUUSD"]
    assert o and o[0]["style"] == "SCALP" and o[0]["stop_after_trades"] == 30 and o[0]["stop_below_r"] == -0.10


def test_override_list_section_rejects_a_non_list():
    from jarvis.config.settings import GateSettings, _load_section
    g = GateSettings()
    _load_section(g, "gates", {"deployment_overrides": "XAUUSD"})
    assert g.deployment_overrides == []
    _load_section(g, "gates", {"deployment_overrides": [OVERRIDE, "junk"]})
    assert g.deployment_overrides == [OVERRIDE]
