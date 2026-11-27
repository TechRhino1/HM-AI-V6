"""HM Algo 2.0 Settings Engine."""
import os
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger("JARVIS_Config")

AUTO_TUNE_MODES = ("off", "dynamic")

def verify_execution_mode(mode: str) -> str:
    """
    Verifies execution mode.
    Defaults to 'demo' for broker-connected paper testing (safe default).
    'live' requires the explicit JARVIS_CONFIRM_LIVE=1 acknowledgement and
    otherwise falls back to 'paper' with a loud warning, matching README §7.
    Returns 'paper' for offline / backtest simulation.
    """
    norm_mode = str(mode or "demo").lower().strip()
    if norm_mode == "live":
        confirmed = str(os.environ.get("JARVIS_CONFIRM_LIVE", "")).strip().lower()
        if confirmed in {"1", "true", "yes", "on"}:
            return "live"
        logger.critical(
            "LIVE EXECUTION BLOCKED: mode='live' was requested without "
            "JARVIS_CONFIRM_LIVE=1. Falling back to 'paper'. Set the variable "
            "explicitly only after verifying the account, symbols, and risk limits."
        )
        return "paper"
    if norm_mode in {"paper", "backtest", "simulated", "offline"}:
        return "paper"
    return "demo"


@dataclass
class RiskSettings:
    # Unified risk policy (approved 2026-11-16): one source of truth for every
    # account size. Sizing targets max_risk_per_trade_pct; a broker-minimum lot
    # may risk up to min_lot_max_risk_pct, otherwise the trade is skipped.
    max_risk_per_trade_pct: float = 1.0
    min_lot_max_risk_pct: float = 2.5
    max_portfolio_risk_pct: float = 2.5
    max_daily_loss_pct: float = 5.0
    max_weekly_loss_pct: float = 10.0
    max_drawdown_pct: float = 20.0
    max_open_positions: int = 3
    max_symbol_positions: int = 2
    partial_tp_r_multiple: float = 1.5
    # Approved 2026-10-23: a capped recovery channel for perfect A+ setups after
    # the daily halt. Disabled until out-of-sample validation proves the edge;
    # when enabled it is one attempt per day at 0.5% risk, and never past 6.5%.
    recovery_channel_enabled: bool = False
    recovery_risk_pct: float = 0.5
    recovery_max_daily_loss_pct: float = 6.5
    recovery_max_attempts_per_day: int = 1
    # NOTE: `breakeven_atr_multiple` was REMOVED here. It was declared but never
    # read anywhere, and its value (1.0) directly contradicted the canonical exit
    # policy, which defers breakeven to +2R. Leaving a dead field named this
    # invites someone to "fix" it and reintroduce the premature-breakeven defect
    # that was responsible for the negative net profit. Breakeven is now owned
    # solely by jarvis.execution.exit_policy.
    max_sector_exposure_count: int = 2
    correlation_scaling_enabled: bool = True
    correlation_scaling_floor: float = 0.40
    breakeven_clears_correlation: bool = True

@dataclass
class TradingSettings:
    default_mode: str = "demo"
    magic_number: int = 888999
    primary_timeframe: str = "H1"
    symbols: List[str] = field(default_factory=lambda: ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD"])
    # Entry selection authority. False (the default) keeps the legacy 29-check
    # gate stack, which is what the platform has always traded on. True hands
    # selection to jarvis.execution.entry_policy, using the out-of-sample
    # calibrated profile in config/winrate_profiles.json.
    #
    # This is deliberately opt-in. The profiles on disk currently show a
    # NEGATIVE out-of-sample expectancy for 11 of the 16 calibrated symbols, so
    # enabling this does not "improve" the trade set -- it switches most of the
    # universe off. That is a trading decision, not a bug fix, and it must be
    # taken knowingly rather than shipped as a default.
    use_calibrated_entry_policy: bool = False
    # Live exit management: "legacy" (the layered stack) or "institutional_lock" (one measured rule:
    # lock at +1R, trail 0.7R behind the peak; see exit_policy.institutional_lock).
    exit_mode: str = "legacy"
    # Under institutional_lock, these symbols hold to their original stop/target instead (no lock,
    # no trail): measured better in both halves for crypto on 353 clean live trades, 2026-11-24.
    exit_hold_symbols: List[str] = field(default_factory=list)
    # Startup trade style (the API can change it for the session): ALL = every style competes;
    # AUTO = one style per symbol, from those the gate allows and the balance can afford.
    trade_style: str = "ALL"
    # Symbol-universe auto-tune: "off" (manual button only) or "dynamic" (AutoTuneEngine DYNAMIC
    # every 30 min from the watchdog; see reports/AUTO_TUNE_RESEARCH_2026-11-24.md).
    auto_tune: str = "off"
    # Calibrated policy as its own entry route (2026-11-23): a SWING candidate the calibrated
    # policy allows is dispatched at market even when the legacy gates said WAIT/NO_TRADE, through
    # the full dispatch path (vetoes, slots, cooldowns, RiskEngine sizing/heat/correlation/circuit
    # breaker, news). Off by default for a fresh install; config/settings.json turns it on.
    calibrated_policy_trader: bool = False
    # Modes in which the FT_ forward tests (trend_router, donchian_eth_h4, research_leads) trade.
    # Demo only by default; config/settings.json can extend it to paper/live.
    forward_test_modes: List[str] = field(default_factory=lambda: ["demo"])
    # AdaptiveGatePolicy knobs. The SOFTEN pathway historically never fired
    # because the decision engine always passed recent_win_rate=None; with the
    # pathway now live, these two knobs decide how permissive it is.
    # max_soft_fail: how many failing SOFT gates may be converted into a
    # confidence penalty instead of a block.
    # min_recent_win_rate: the recent closed-trade win rate (last 30) required
    # before any softening is allowed. With fewer than 10 closed trades there is
    # no evidence and the policy blocks regardless.
    gate_policy_max_soft_fail: int = 3
    gate_policy_min_recent_win_rate: float = 0.45
    # 2026-10-20 profitability audit: 83 gold trades taken in days on a micro
    # account all resolved through an all-or-nothing book with -0.44R/trade
    # expectancy; overtrading spread churn was a first-order cost. Cap new
    # entries per symbol per UTC day (position management/trailing unaffected).
    # 0 disables the cap.
    max_daily_entries_per_symbol: int = 4
    # Live-expectancy quarantine (jarvis.execution.strategy_quarantine): a
    # (symbol, strategy) pair whose last ``quarantine_window`` closed trades
    # average <= ``quarantine_expectancy_r`` R is vetoed on every entry route.
    quarantine_expectancy_r: float = -0.15
    quarantine_window: int = 30

@dataclass
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 8501
    cors_origin: str = ""

@dataclass
class MLSettings:
    sgd_learning_rate: float = 0.05
    sgd_l2_regularization: float = 0.01
    brier_score_drift_threshold: float = 0.28

# The one settings file whose writes are governed (computed at import, before anything can patch os.path).
_LIVE_SETTINGS_PATH = os.path.normcase(os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config", "settings.json")))

GATE_MODES = ("off", "shadow", "enforce")
TRADE_STYLES = ("ALL", "AUTO", "SCALP", "DAY_TRADING", "SWING", "H4_SWING", "D1_SWING")


@dataclass
class GateSettings:
    """Rollout switches for the 2026-11-25 gate fixes (off | shadow | enforce).
    shadow records SHADOW_REJECT on the GateTrace without blocking."""
    rr_floor_mode: str = "shadow"
    promotion_hole_mode: str = "shadow"
    # Elite bypass of the calibrated entry policy (ai>=80): kept, but off until validated.
    elite_bypass_enabled: bool = False
    # Operator overrides of the deployment gate, one symbol x style each, with a live probation
    # stop: {"symbol", "style", "since", "stop_after_trades", "stop_below_r", "reason"}.
    # See exit_geometry.deployment_refusal. Empty = evidence decides alone.
    deployment_overrides: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class VerifierSettings:
    """Pre-send verification (TradeGuard.verify_pre_send). Fails closed on error/timeout."""
    mode: str = "shadow"
    budget_ms: float = 250.0
    max_signal_age_s: float = 900.0
    max_drift_atr: float = 0.5
    min_sl_atr: float = 0.15
    # Order-of-magnitude guard, not a band: structural H4/D1 stops measured 8-22x the
    # primary-timeframe ATR on validated trades (2026-11-25 backtest), so 8 blocked 25%.
    max_sl_atr: float = 30.0
    sizing_tolerance: float = 0.10
    conflict_window_s: float = 600.0
    max_tick_age_s: float = 120.0


@dataclass
class MonitorSettings:
    loop_stall_s: float = 180.0
    # Position monitor ticks every 2 s; this long without a tick means management stopped.
    position_monitor_stall_s: float = 30.0
    no_trade_hours: float = 8.0
    reject_spike_factor: float = 3.0
    fallback_rate_warn: float = 0.25
    verifier_fail_rate_warn: float = 0.05
    forward_test_exposure_warn_pct: float = 50.0
    # 2026-11-27 health upgrade (PR B). Windows are seconds; shares are fractions.
    window_s: float = 1800.0              # rate checks look at this trailing window, not lifetime totals
    state_sync_stall_s: float = 30.0      # the broker sync loop runs every second
    synthetic_share_warn: float = 0.10    # share of rate fetches served synthetic bars
    news_synthetic_share_warn: float = 0.50
    stale_symbols_warn: int = 1           # symbols whose newest frame is STALE while quoting
    cpu_warn_pct: float = 90.0
    memory_warn_pct: float = 90.0
    disk_free_warn_gb: float = 5.0
    data_dir_warn_gb: float = 5.0
    escalate_after_passes: int = 30       # a WARN that persists this many passes (~30 min) becomes CRITICAL
    repeat_alert_s: float = 21600.0       # a persistent, unchanged problem is re-alerted at most every 6 h
    thread_restarts_per_hour: int = 5     # self-heal cap per worker thread
    retention_days: int = 14              # journals/advisories/alerts older than this are gzipped
    delete_after_days: int = 90           # gzipped journals older than this are deleted
    backups_keep: int = 7                 # daily SQLite backups kept per database
    threads_warn: int = 400               # process threads above this look like a leak
    handles_warn: int = 20000             # OS handles above this look like a leak
    auto_unaffordable_sweeps: int = 120   # AUTO sweeps in a row with no affordable allowed style
    decision_p95_s: float = 10.0          # p95 latency ceilings over the window
    order_p95_s: float = 5.0
    fetch_p95_s: float = 5.0
    http_p95_s: float = 3.0


@dataclass
class MonitorLayerSettings:
    """Unproven position-monitor exits (off | shadow | enforce). shadow = record the
    "would have" action, do nothing. Re-enable only after the M1 replay proves a layer
    (EXIT_LOCK_RESEARCH 2026-11-24: the extra layers cost ~40R; NEWS N2 rejected
    pre-release de-risking). The crypto hold list is exempt from all of them."""
    news_floor: str = "shadow"
    news_bank: str = "shadow"
    weekend_floor: str = "shadow"
    weekend_bank: str = "shadow"
    tp_zone_harvest: str = "shadow"
    scalp_stagnation: str = "shadow"


@dataclass
class ForwardTestSettings:
    # Forward tests pass the shared hard risk gates and count toward symbol caps.
    gated: bool = True
    count_toward_symbol_caps: bool = True


@dataclass
class GovernanceSettings:
    # A governed config write moving a risk parameter more than this needs --approve.
    max_auto_delta_pct: float = 20.0


# (section, attr) -> (min, max) bounds. Out-of-bounds values keep the default.
_BOUNDS = {
    ("monitor", "window_s"): (300.0, 86400.0),
    ("monitor", "escalate_after_passes"): (3, 1440),
    ("monitor", "thread_restarts_per_hour"): (0, 60),
    ("monitor", "retention_days"): (3, 365),
    ("monitor", "delete_after_days"): (7, 3650),
    ("monitor", "backups_keep"): (1, 60),
    ("verifier", "budget_ms"): (20.0, 2000.0),
    ("verifier", "max_signal_age_s"): (30.0, 7200.0),
    ("verifier", "max_drift_atr"): (0.05, 3.0),
    ("verifier", "min_sl_atr"): (0.0, 2.0),
    ("verifier", "max_sl_atr"): (1.0, 60.0),
    ("verifier", "sizing_tolerance"): (0.0, 0.5),
    ("verifier", "conflict_window_s"): (0.0, 86400.0),
    ("verifier", "max_tick_age_s"): (5.0, 3600.0),
    ("monitor", "loop_stall_s"): (30.0, 3600.0),
    ("monitor", "position_monitor_stall_s"): (6.0, 600.0),
    ("monitor", "no_trade_hours"): (1.0, 168.0),
    ("monitor", "reject_spike_factor"): (1.5, 20.0),
    ("monitor", "fallback_rate_warn"): (0.01, 1.0),
    ("monitor", "verifier_fail_rate_warn"): (0.001, 1.0),
    ("monitor", "forward_test_exposure_warn_pct"): (5.0, 100.0),
    ("governance", "max_auto_delta_pct"): (0.0, 100.0),
}


def _load_section(obj: Any, section: str, data: Dict[str, Any]) -> None:
    """Typed, bounded load of one dataclass section; bad values keep the default."""
    for key, raw in (data or {}).items():
        if not hasattr(obj, key) or raw is None:
            continue
        default = getattr(obj, key)
        try:
            if isinstance(default, bool):
                val: Any = raw if isinstance(raw, bool) else str(raw).strip().lower() in {"1", "true", "yes", "on"}
            elif isinstance(default, list):
                if not isinstance(raw, list):
                    logger.warning(f"Ignoring invalid {section}.{key}={raw!r}: expected a list")
                    continue
                val = [dict(x) for x in raw if isinstance(x, dict)]
            elif isinstance(default, (int, float)):
                val = type(default)(raw)
                lo, hi = _BOUNDS.get((section, key), (float("-inf"), float("inf")))
                if not lo <= float(val) <= hi:
                    logger.warning(f"Ignoring out-of-bounds {section}.{key}={raw!r} (allowed {lo}..{hi})")
                    continue
            else:
                val = str(raw).strip().lower()
                if (key.endswith("mode") or section == "monitor_layers") and val not in GATE_MODES:
                    logger.warning(f"Ignoring invalid {section}.{key}={raw!r} (allowed {GATE_MODES})")
                    continue
            setattr(obj, key, val)
        except (TypeError, ValueError) as exc:
            logger.warning(f"Ignoring invalid {section}.{key}={raw!r}: {exc}")


@dataclass
class JarvisConfig:
    risk: RiskSettings = field(default_factory=RiskSettings)
    trading: TradingSettings = field(default_factory=TradingSettings)
    server: ServerSettings = field(default_factory=ServerSettings)
    ml: MLSettings = field(default_factory=MLSettings)
    gates: GateSettings = field(default_factory=GateSettings)
    verifier: VerifierSettings = field(default_factory=VerifierSettings)
    monitor: MonitorSettings = field(default_factory=MonitorSettings)
    forward_tests: ForwardTestSettings = field(default_factory=ForwardTestSettings)
    governance: GovernanceSettings = field(default_factory=GovernanceSettings)
    monitor_layers: MonitorLayerSettings = field(default_factory=MonitorLayerSettings)

    @classmethod
    def load(cls) -> "JarvisConfig":
        cfg = cls()
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        json_path = os.path.join(base_dir, "config", "settings.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                r_data = data.get("risk", {})
                # (str-key, attr, caster) — previously only three of these were
                # read, so editing settings.json silently had no effect for the
                # rest. Keep the mapping explicit so the contract is obvious.
                risk_keys = (
                    ("max_risk_per_trade_pct", "max_risk_per_trade_pct", float),
                    ("max_portfolio_risk_pct", "max_portfolio_risk_pct", float),
                    ("max_daily_loss_pct", "max_daily_loss_pct", float),
                    ("max_weekly_loss_pct", "max_weekly_loss_pct", float),
                    ("min_lot_max_risk_pct", "min_lot_max_risk_pct", float),
                    ("max_drawdown_pct", "max_drawdown_pct", float),
                    ("max_open_positions", "max_open_positions", int),
                    ("max_symbol_positions", "max_symbol_positions", int),
                    ("recovery_channel_enabled", "recovery_channel_enabled", lambda v: str(v).strip().lower() in {"1", "true", "yes", "on"}),
                    ("recovery_risk_pct", "recovery_risk_pct", float),
                    ("recovery_max_daily_loss_pct", "recovery_max_daily_loss_pct", float),
                    ("recovery_max_attempts_per_day", "recovery_max_attempts_per_day", int),
                    ("max_sector_exposure_count", "max_sector_exposure_count", int),
                    ("correlation_scaling_enabled", "correlation_scaling_enabled", lambda v: str(v).strip().lower() in {"1", "true", "yes", "on"}),
                    ("correlation_scaling_floor", "correlation_scaling_floor", float),
                    ("breakeven_clears_correlation", "breakeven_clears_correlation", lambda v: str(v).strip().lower() in {"1", "true", "yes", "on"}),
                )
                for json_key, attr, caster in risk_keys:
                    if json_key in r_data and r_data[json_key] is not None:
                        try:
                            setattr(cfg.risk, attr, caster(r_data[json_key]))
                        except (TypeError, ValueError) as exc:
                            logger.warning(
                                f"Ignoring invalid risk.{json_key}={r_data[json_key]!r}: {exc}"
                            )
                # `breakeven_atr_trigger` is intentionally NOT loaded: breakeven
                # timing is owned by jarvis.execution.exit_policy. Warn loudly if
                # someone still has it in the file so its presence is not mistaken
                # for an active setting.
                if "breakeven_atr_trigger" in r_data:
                    logger.warning(
                        "config/settings.json contains 'risk.breakeven_atr_trigger' which is "
                        "IGNORED. Breakeven timing is defined in jarvis.execution.exit_policy "
                        "(be_trigger_r, default +2R). Remove the stale key to avoid confusion."
                    )
                t_data = data.get("trading", {})
                if "default_mode" in t_data and str(t_data["default_mode"]).lower() in {"live", "paper", "demo"}:
                    cfg.trading.default_mode = str(t_data["default_mode"]).lower()
                if "allowed_symbols" in t_data:
                    cfg.trading.symbols = list(t_data["allowed_symbols"])
                if "magic_number" in t_data:
                    cfg.trading.magic_number = int(t_data["magic_number"])
                if "primary_timeframe" in t_data:
                    cfg.trading.primary_timeframe = str(t_data["primary_timeframe"])
                if "use_calibrated_entry_policy" in t_data:
                    raw = t_data["use_calibrated_entry_policy"]
                    if isinstance(raw, bool):
                        cfg.trading.use_calibrated_entry_policy = raw
                    else:
                        cfg.trading.use_calibrated_entry_policy = str(raw).strip().lower() in {
                            "1", "true", "yes", "on",
                        }
                if str(t_data.get("exit_mode", "")).lower() in ("legacy", "institutional_lock"):
                    cfg.trading.exit_mode = str(t_data["exit_mode"]).lower()
                if str(t_data.get("auto_tune", "")).lower() in AUTO_TUNE_MODES:
                    cfg.trading.auto_tune = str(t_data["auto_tune"]).lower()
                if str(t_data.get("trade_style", "")).upper() in TRADE_STYLES:
                    cfg.trading.trade_style = str(t_data["trade_style"]).upper()
                if isinstance(t_data.get("exit_hold_symbols"), list):
                    cfg.trading.exit_hold_symbols = [str(s).upper() for s in t_data["exit_hold_symbols"]]
                if "calibrated_policy_trader" in t_data:
                    raw = t_data["calibrated_policy_trader"]
                    cfg.trading.calibrated_policy_trader = (
                        raw if isinstance(raw, bool) else str(raw).strip().lower() in {"1", "true", "yes", "on"}
                    )
                if "forward_test_modes" in t_data and isinstance(t_data["forward_test_modes"], list):
                    cfg.trading.forward_test_modes = [str(m).strip().lower() for m in t_data["forward_test_modes"]]
                if "gate_policy_max_soft_fail" in t_data:
                    try:
                        cfg.trading.gate_policy_max_soft_fail = int(t_data["gate_policy_max_soft_fail"])
                    except (TypeError, ValueError) as exc:
                        logger.warning(f"Ignoring invalid gate_policy_max_soft_fail={t_data['gate_policy_max_soft_fail']!r}: {exc}")
                if "gate_policy_min_recent_win_rate" in t_data:
                    try:
                        cfg.trading.gate_policy_min_recent_win_rate = float(t_data["gate_policy_min_recent_win_rate"])
                    except (TypeError, ValueError) as exc:
                        logger.warning(f"Ignoring invalid gate_policy_min_recent_win_rate={t_data['gate_policy_min_recent_win_rate']!r}: {exc}")
                if "max_daily_entries_per_symbol" in t_data:
                    try:
                        cfg.trading.max_daily_entries_per_symbol = int(t_data["max_daily_entries_per_symbol"])
                    except (TypeError, ValueError) as exc:
                        logger.warning(f"Ignoring invalid max_daily_entries_per_symbol={t_data['max_daily_entries_per_symbol']!r}: {exc}")
                for _qk, _qcast in (("quarantine_expectancy_r", float), ("quarantine_window", int)):
                    if _qk in t_data:
                        try:
                            setattr(cfg.trading, _qk, _qcast(t_data[_qk]))
                        except (TypeError, ValueError) as exc:
                            logger.warning(f"Ignoring invalid {_qk}={t_data[_qk]!r}: {exc}")
                for _section in ("gates", "verifier", "monitor", "forward_tests", "governance", "monitor_layers"):
                    _sec = data.get(_section, {})
                    if isinstance(_sec, dict):
                        _load_section(getattr(cfg, _section), _section, _sec)
                    else:
                        logger.warning(f"Ignoring config section {_section!r}: expected an object")
                m_data = data.get("ml", {})
                ml_keys = (
                    ("sgd_learning_rate", "sgd_learning_rate", float),
                    ("sgd_l2_regularization", "sgd_l2_regularization", float),
                    ("brier_score_drift_threshold", "brier_score_drift_threshold", float),
                )
                for json_key, attr, caster in ml_keys:
                    if json_key in m_data and m_data[json_key] is not None:
                        try:
                            setattr(cfg.ml, attr, caster(m_data[json_key]))
                        except (TypeError, ValueError) as exc:
                            logger.warning(
                                f"Ignoring invalid ml.{json_key}={m_data[json_key]!r}: {exc}"
                            )
            except Exception as e:
                logger.warning(f"Could not load config/settings.json: {e}")

        env_mode = os.environ.get("JARVIS_MODE")
        if env_mode and env_mode.lower() in {"live", "paper", "demo"}:
            cfg.trading.default_mode = env_mode.lower()
        env_port = os.environ.get("JARVIS_PORT")
        if env_port and env_port.isdigit():
            cfg.server.port = int(env_port)
        env_symbols = os.environ.get("JARVIS_SYMBOLS")
        if env_symbols:
            cfg.trading.symbols = [s.strip().upper() for s in env_symbols.split(",") if s.strip()]
        env_calibrated = os.environ.get("JARVIS_CALIBRATED_ENTRY")
        if env_calibrated:
            cfg.trading.use_calibrated_entry_policy = env_calibrated.strip().lower() in {
                "1", "true", "yes", "on",
            }
        env_risk = os.environ.get("JARVIS_MAX_RISK_PCT")
        if env_risk:
            try:
                cfg.risk.max_risk_per_trade_pct = float(env_risk)
            except Exception as e:
                logger.warning(f"Ignoring invalid JARVIS_MAX_RISK_PCT={env_risk!r}: {e}")
        return cfg

SETTINGS = JarvisConfig.load()


def persist_auto_tune(mode: str) -> bool:
    """Set and persist trading.auto_tune ("off" | "dynamic")."""
    mode = str(mode or "").strip().lower()
    if mode not in AUTO_TUNE_MODES:
        return False
    SETTINGS.trading.auto_tune = mode
    return _persist_trading("auto_tune", mode)


def persist_allowed_symbols(symbols: List[str]) -> bool:
    """Atomically write the allowed_symbols list back to config/settings.json."""
    clean = [str(s).strip().upper() for s in symbols if str(s).strip()]
    if not _persist_trading("allowed_symbols", clean):
        return False
    SETTINGS.trading.symbols = list(clean)
    return True


def _persist_trading(key: str, value: object) -> bool:
    """Atomically write one trading.<key> back to config/settings.json."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    json_path = os.path.join(base_dir, "config", "settings.json")
    try:
        data = {}
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if "trading" not in data or not isinstance(data["trading"], dict):
            data["trading"] = {}
        data["trading"][key] = value

        # Versioned + audited + rollback-able (model_registry "settings"); an
        # operator/dashboard action is the approval, parameter bounds still apply.
        if os.path.normcase(os.path.abspath(json_path)) == _LIVE_SETTINGS_PATH:
            from jarvis.learning.model_registry import governed_write
            governed_write("settings", json_path, json.dumps(data, indent=2),
                           reason=f"persist trading.{key}", author="dashboard", approve=True)
        else:  # a non-live path (tests/tools): plain atomic write, nothing registered
            temp_path = json_path + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_path, json_path)
        logger.info(f"💾 SETTINGS: Persisted trading.{key} to {json_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to persist trading.{key} to {json_path}: {e}")
        return False

